from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import re
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

from .kb import KnowledgeBase
from .guard_config import GuardConfig
from .roomcontract_adapter import ANALYZE_STAGE_IDS, COMMIT_STAGE_IDS, RoomContractAdapter, derive_case_id
from .roomcontract_v2_runtime import (
    RoomContractContractError,
    INTERACTION_MODES,
    SPATIAL_CANDIDATE_LIMIT,
    SPATIAL_COORDINATE_LIMIT,
    SPATIAL_DISTANCE_LIMIT_METERS,
    SPATIAL_ID_MAX_LENGTH,
    SPATIAL_REASON_MAX_LENGTH,
    SPATIAL_SELECTION_MODALITIES,
    WIRE_CONTRACT_VERSION,
    load_project_contract,
    load_v2_document,
    runtime_actions_for_kind,
    select_runtime_action,
)
from .openai_client import OpenAIHTTPError, OpenAIResponsesClient, create_transcription, create_tts_audio
from .placement import assign_spawn_points, normalize_placement_preview, summarize_room_objects, rdl_slice_obstacles, _is_rdl
from .projects import ProjectManager
from .runtime_trace import contract_runtime_fingerprint, contract_commit_fingerprint
from .schemas import arrow_project_schema, npc_action_schema


def _now_ms() -> int:
    return int(time.time() * 1000)


def _slugify(s: str) -> str:
    s = s.strip().lower()
    s = re.sub(r"[^a-z0-9äöüß_-]+", "_", s, flags=re.IGNORECASE)
    s = re.sub(r"_+", "_", s).strip("_")
    return s or "agent"


MEMORY_MODE_SHARED = "shared_history"
MEMORY_MODE_AGENT_PRIVATE = "agent_private_history"
VALID_MEMORY_MODES = {MEMORY_MODE_SHARED, MEMORY_MODE_AGENT_PRIVATE}
_MEMORY_MODE_ALIASES = {
    "shared": MEMORY_MODE_SHARED,
    "global": MEMORY_MODE_SHARED,
    "global_history": MEMORY_MODE_SHARED,
    "agent_private": MEMORY_MODE_AGENT_PRIVATE,
    "private": MEMORY_MODE_AGENT_PRIVATE,
    "private_history": MEMORY_MODE_AGENT_PRIVATE,
    "per_agent": MEMORY_MODE_AGENT_PRIVATE,
    "per_agent_history": MEMORY_MODE_AGENT_PRIVATE,
}

GENERATION_MODE_LEGACY = "legacy"
GENERATION_MODE_ROOMCONTRACT = "roomcontract"
VALID_GENERATION_MODES = {GENERATION_MODE_LEGACY, GENERATION_MODE_ROOMCONTRACT}
PLACEMENT_FORWARD_TOLERANCE = 1e-3
PLACEMENT_PLANAR_TOLERANCE = 1e-4
ROOMCONTRACT_PLACEMENT_DEPENDENT_STAGES = (
    "placement_metrics",
    "roomcontract_assembly",
    "handoff_derivation",
    "roomcontract_v2_assembly",
    "roomcontract_invariants",
)
ARROW_AUTHORING_SESSION_FIELDS = (
    "placement_preview",
    "agent_roles",
    "roomcontract_path",
    "trace_map_path",
    "validation_summary",
    "roomcontract_summary",
    "scenario_summary",
    "capability_summary",
    "handoff_summary",
    "room_knowledge_summary",
    "placement_manually_updated",
    "updated_ms",
)
_GENERATION_MODE_ALIASES = {
    "": GENERATION_MODE_LEGACY,
    "arrow": GENERATION_MODE_LEGACY,
    "legacy_interactive_agents": GENERATION_MODE_LEGACY,
    "functional": GENERATION_MODE_ROOMCONTRACT,
    "functional_rdl": GENERATION_MODE_ROOMCONTRACT,
    "functional-rdl": GENERATION_MODE_ROOMCONTRACT,
}


def normalize_memory_mode(value: Any, default: str = MEMORY_MODE_SHARED) -> str:
    raw = str(value or "").strip().lower()
    if not raw:
        raw = default
    raw = _MEMORY_MODE_ALIASES.get(raw, raw)
    if raw not in VALID_MEMORY_MODES:
        valid = ", ".join(sorted(VALID_MEMORY_MODES))
        raise ValueError(f"Unbekannter memory_mode: {raw}. Erlaubt: {valid}.")
    return raw


def normalize_generation_mode(value: Any, default: str = GENERATION_MODE_LEGACY) -> str:
    raw = str(value or "").strip().lower()
    if not raw:
        raw = default
    raw = _GENERATION_MODE_ALIASES.get(raw, raw)
    if raw not in VALID_GENERATION_MODES:
        valid = ", ".join(sorted(VALID_GENERATION_MODES))
        raise ValueError(f"Unbekannter generation_mode: {raw}. Erlaubt: {valid}.")
    return raw


def _parse_bool(value: Any, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    raw = str(value).strip().lower()
    if raw in {"1", "true", "yes", "y", "on"}:
        return True
    if raw in {"0", "false", "no", "n", "off"}:
        return False
    raise ValueError(f"Ungueltiger Boolean-Wert: {value}.")


def _as_str_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    return [str(x).strip() for x in value if str(x).strip()]


def _canonical_runtime_value(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _semantic_tokens(value: Any) -> set[str]:
    text = str(value or "").lower()
    replacements = {
        "ä": "ae",
        "ö": "oe",
        "ü": "ue",
        "ß": "ss",
        "_": " ",
        "-": " ",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return {m.group(0) for m in re.finditer(r"[a-z0-9]+", text)}


_HANDOFF_SEMANTIC_ALIASES = (
    frozenset({"cheese", "kaese", "kase"}),
    frozenset({"welcome", "willkommen", "empfang"}),
    frozenset({"heritage", "geschichte", "historie", "tradition"}),
    frozenset({"tactile", "taktil", "haptisch"}),
    frozenset({"lounge", "entspannung", "relax"}),
    frozenset({"cow", "kuh", "milchkuh"}),
    frozenset({"truck", "lkw", "milchlaster", "lieferwagen"}),
)

_GENERIC_HANDOFF_ROLE_TOKENS = frozenset(
    {
        "agent",
        "assistant",
        "ambassador",
        "caretaker",
        "educator",
        "expert",
        "guide",
        "host",
        "person",
        "specialist",
    }
)


def _handoff_semantic_tokens(value: Any) -> set[str]:
    """Add narrow German/English aliases used in modeled agent identities."""
    tokens = _semantic_tokens(value)
    for aliases in _HANDOFF_SEMANTIC_ALIASES:
        if tokens.intersection(aliases):
            tokens.update(aliases)
    return tokens


@dataclass
class AgentSpec:
    id: str
    display_name: str
    persona: str
    expertise: List[str] = field(default_factory=list)
    knowledge_tags: List[str] = field(default_factory=list)
    responsible_zone_ids: List[str] = field(default_factory=list)
    grounded_object_ids: List[str] = field(default_factory=list)
    handoff_targets: List[str] = field(default_factory=list)
    preferred_zone_ids: List[str] = field(default_factory=list)
    preferred_spawn_tags: List[str] = field(default_factory=list)
    voice: Optional[str] = None
    voice_style: Optional[str] = None
    tts_model: Optional[str] = None
    roomcontract_agent_ref: Optional[str] = None

    @staticmethod
    def from_dict(d: Dict[str, Any], idx: int) -> "AgentSpec":
        display = str(d.get("display_name") or d.get("name") or f"Agent {idx+1}")
        agent_id = str(d.get("id") or _slugify(display) or f"agent_{idx+1}")
        persona = str(d.get("persona") or "").strip()

        voice = str(d.get("voice") or "").strip() or None
        voice_style = str(d.get("voice_style") or "").strip() or None
        tts_model = str(d.get("tts_model") or "").strip() or None
        roomcontract_agent_ref = str(d.get("roomcontract_agent_ref") or "").strip() or None

        return AgentSpec(
            id=agent_id,
            display_name=display,
            persona=persona,
            expertise=_as_str_list(d.get("expertise")),
            knowledge_tags=_as_str_list(d.get("knowledge_tags")),
            responsible_zone_ids=_as_str_list(d.get("responsible_zone_ids")),
            grounded_object_ids=_as_str_list(d.get("grounded_object_ids")),
            handoff_targets=_as_str_list(d.get("handoff_targets")),
            preferred_zone_ids=_as_str_list(d.get("preferred_zone_ids")),
            preferred_spawn_tags=_as_str_list(d.get("preferred_spawn_tags")),
            voice=voice,
            voice_style=voice_style,
            tts_model=tts_model,
            roomcontract_agent_ref=roomcontract_agent_ref,
        )

    def short_profile(self) -> str:
        exp = ", ".join(self.expertise) if self.expertise else "—"
        return f"{self.id} ({self.display_name}): Expertise: {exp}"


@dataclass
class SessionState:
    session_id: str
    agents: Dict[str, AgentSpec]
    placements: Dict[str, Dict[str, Any]]
    kb: KnowledgeBase
    memory_mode: str = MEMORY_MODE_SHARED
    history: List[Dict[str, str]] = field(default_factory=list)  # shared mode: role=user|assistant, content=str
    agent_histories: Dict[str, List[Dict[str, str]]] = field(default_factory=dict)
    created_ms: int = field(default_factory=_now_ms)
    updated_ms: int = field(default_factory=_now_ms)
    project_id: Optional[str] = None
    roomcontract_contract_kind: str = ""
    roomcontract_model_version: str = ""
    roomcontract_model_sha256: str = ""
    roomcontract_profile: str = "none"
    roomcontract_contract_fingerprint: str = ""
    roomcontract_runtime_context: Optional[Dict[str, Any]] = None
    pinned_contract: Optional[Dict[str, Any]] = None
    commit_fingerprint: str = ""
    routing_table: Optional[Dict[str, Any]] = None
    server_active_agent_id: str = ""
    publication_generation: Optional[int] = None
    ignored_handoff_proposals: List[Dict[str, str]] = field(default_factory=list)

    def touch(self) -> None:
        self.updated_ms = _now_ms()


@dataclass
class ArrowProjectDraft:
    session_id: str
    arrow_payload: Dict[str, Any]
    analysis: str
    assistant_message: str
    project: Dict[str, str]
    agents: List[Dict[str, Any]]
    knowledge: List[Dict[str, Any]]
    placement_preview: Dict[str, Any]
    generation_mode: str = GENERATION_MODE_LEGACY
    project_id_hint: str = ""
    run_validation: bool = False
    max_repair_attempts: Optional[int] = None
    case_id: Optional[str] = None
    case_dir: Optional[str] = None
    agent_roles: Dict[str, Any] = field(default_factory=dict)
    roomcontract_path: Optional[str] = None
    trace_map_path: Optional[str] = None
    validation_summary: Dict[str, Any] = field(default_factory=dict)
    roomcontract_summary: Dict[str, Any] = field(default_factory=dict)
    scenario_summary: Dict[str, Any] = field(default_factory=dict)
    capability_summary: Dict[str, Any] = field(default_factory=dict)
    handoff_summary: Dict[str, Any] = field(default_factory=dict)
    room_knowledge_summary: Dict[str, Any] = field(default_factory=dict)
    refinement_requests: List[Dict[str, Any]] = field(default_factory=list)
    validation_stale: bool = False
    history: List[Dict[str, str]] = field(default_factory=list)
    created_ms: int = field(default_factory=_now_ms)
    updated_ms: int = field(default_factory=_now_ms)
    placement_manually_updated: bool = False

    def touch(self) -> None:
        self.updated_ms = _now_ms()

    def request_options(self) -> Dict[str, Any]:
        return {
            "project_id_hint": self.project_id_hint,
            "run_validation": self.run_validation,
            "max_repair_attempts": self.max_repair_attempts,
            "refinement_request_count": len(self.refinement_requests),
        }

    def decorate_draft_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        out = dict(payload)
        out["generation_mode"] = self.generation_mode
        out["request_options"] = self.request_options()
        out["validation_stale"] = self.validation_stale
        out["refinement_status"] = "stale" if self.validation_stale else "validated"
        if self.refinement_requests:
            out["refinement_requests"] = list(self.refinement_requests)
        if self.case_id:
            out["case_id"] = self.case_id
        if self.case_dir:
            out["case_dir"] = self.case_dir
        if self.roomcontract_path:
            out["roomcontract_path"] = self.roomcontract_path
        if self.trace_map_path:
            out["trace_map_path"] = self.trace_map_path
        if self.validation_summary:
            out["validation_summary"] = self.validation_summary
        if self.roomcontract_summary:
            out["roomcontract_summary"] = self.roomcontract_summary
        if self.scenario_summary:
            out["scenario_summary"] = self.scenario_summary
        if self.capability_summary:
            out["capability_summary"] = self.capability_summary
        if self.handoff_summary:
            out["handoff_summary"] = self.handoff_summary
        if self.room_knowledge_summary:
            out["room_knowledge_summary"] = self.room_knowledge_summary
        return out


@dataclass
class ArrowPlacementAuthoringChange:
    """One explicit, reviewable placement change in the Unity authoring loop.

    File and session snapshots intentionally stay server-side.  Only
    ``public_payload`` crosses the HTTP boundary, so local paths and rollback
    bytes never leak into the Unity client or a paper artifact.
    """

    change_id: str
    session_id: str
    case_id: str
    rationale: str
    revision_before: str
    placements: List[Dict[str, Any]]
    updated_preview: Dict[str, Any]
    diffs: List[Dict[str, Any]]
    validation: Dict[str, Any]
    affected_artifacts: List[str]
    lifecycle: str = "previewed"
    revision_after: str = ""
    analysis_validation_summary: Dict[str, Any] = field(default_factory=dict)
    files_before: Dict[Path, Optional[bytes]] = field(default_factory=dict, repr=False)
    files_after: Dict[Path, Optional[bytes]] = field(default_factory=dict, repr=False)
    session_before: Dict[str, Any] = field(default_factory=dict, repr=False)
    session_after: Dict[str, Any] = field(default_factory=dict, repr=False)
    created_ms: int = field(default_factory=_now_ms)
    applied_ms: Optional[int] = None
    accepted_ms: Optional[int] = None

    def public_payload(self) -> Dict[str, Any]:
        target_ids = [str(item.get("target_id") or "") for item in self.diffs]
        return {
            "change_id": self.change_id,
            "kind": "agent_placement",
            "lifecycle": self.lifecycle,
            "rationale": self.rationale,
            "revision_before": self.revision_before,
            "revision_after": self.revision_after or None,
            "target_ids": target_ids,
            "diffs": copy.deepcopy(self.diffs),
            "affected_artifacts": list(self.affected_artifacts),
            "validation": copy.deepcopy(self.validation),
            "analysis_validation_summary": copy.deepcopy(
                self.analysis_validation_summary
            ),
            "created_ms": self.created_ms,
            "applied_ms": self.applied_ms,
            "accepted_ms": self.accepted_ms,
        }


@dataclass
class SessionStore:
    max_history_turns: int
    max_handoffs: int
    kb: KnowledgeBase
    kb_max_snippets: int
    model: str
    temperature: float
    stt_model: str
    stt_language: str
    stt_max_audio_bytes: int
    openai: OpenAIResponsesClient
    project_manager: ProjectManager
    default_room_plan_path: str = "examples/room_plan.example.json"
    default_agents_path: str = "examples/agents.example.json"
    default_memory_mode: str = MEMORY_MODE_SHARED
    guard_config: GuardConfig = field(default_factory=GuardConfig.from_environment)
    _turn_locks: Dict[str, threading.RLock] = field(default_factory=dict, init=False, repr=False)
    _turn_locks_guard: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)
    sessions: Dict[str, SessionState] = field(default_factory=dict)
    kb_cache: Dict[str, KnowledgeBase] = field(default_factory=dict)
    arrow_sessions: Dict[str, ArrowProjectDraft] = field(default_factory=dict)
    arrow_authoring_changes: Dict[str, ArrowPlacementAuthoringChange] = field(
        default_factory=dict
    )
    arrow_authoring_pending: Dict[str, str] = field(default_factory=dict)
    arrow_authoring_undo: Dict[str, str] = field(default_factory=dict)
    _arrow_mutation_locks: Dict[str, threading.RLock] = field(
        default_factory=dict,
        init=False,
        repr=False,
        compare=False,
    )
    _arrow_mutation_locks_guard: threading.Lock = field(
        default_factory=threading.Lock,
        init=False,
        repr=False,
        compare=False,
    )

    @contextmanager
    def _arrow_mutation_scope(
        self,
        *,
        session_id: Optional[str] = None,
        case_id: Optional[str] = None,
    ) -> Iterator[None]:
        """Serialize every Wizard mutation for the same session or case.

        A deterministic key order avoids deadlocks when an operation owns both
        its per-session and per-case lock.  RLock is intentional: commit and
        placement helpers may re-enter the same guarded scope in future without
        weakening the ThreadingHTTPServer contract.
        """

        keys = sorted(
            {
                key
                for key in (
                    f"case:{str(case_id).strip()}" if case_id else "",
                    f"session:{str(session_id).strip()}" if session_id else "",
                )
                if key and not key.endswith(":")
            }
        )
        with self._arrow_mutation_locks_guard:
            locks = [
                self._arrow_mutation_locks.setdefault(key, threading.RLock())
                for key in keys
            ]
        for lock in locks:
            lock.acquire()
        try:
            yield
        finally:
            for lock in reversed(locks):
                lock.release()

    def _project_root(self) -> Path:
        return Path(__file__).resolve().parents[1]

    def _load_json_file(self, rel_path: str) -> Dict[str, Any]:
        path = (self._project_root() / rel_path).resolve()
        # Safety: ensure file is inside project
        if self._project_root() not in path.parents and path != self._project_root():
            raise ValueError("Ungültiger Pfad (außerhalb Projekt).")
        return json.loads(path.read_text(encoding="utf-8"))

    def create_session(
        self,
        room_plan: Dict[str, Any],
        agent_dicts: List[Dict[str, Any]],
        session_id: Optional[str] = None,
        kb: Optional[KnowledgeBase] = None,
        project_id: Optional[str] = None,
        memory_mode: Optional[str] = None,
        roomcontract_contract: Optional[Dict[str, Any]] = None,
    ) -> SessionState:
        if not session_id:
            session_id = str(uuid.uuid4())
        mode = normalize_memory_mode(memory_mode, default=normalize_memory_mode(self.default_memory_mode))

        agents_list: List[AgentSpec] = [AgentSpec.from_dict(d, i) for i, d in enumerate(agent_dicts)]
        agents_map = {a.id: a for a in agents_list}
        contract_kind = str((roomcontract_contract or {}).get("kind") or "")
        runtime_context = copy.deepcopy(
            (roomcontract_contract or {}).get("runtime_context") or {}
        )
        if contract_kind == "v2":
            contract_agents = [
                item
                for item in runtime_context.get("agents", [])
                if isinstance(item, dict)
            ]
            contract_agents_by_source: Dict[str, Dict[str, Any]] = {}
            contract_agents_by_entity: Dict[str, Dict[str, Any]] = {}
            for item in contract_agents:
                source_id = str(item.get("source_agent_id") or "").strip()
                entity_id = str(item.get("roomcontract_agent_id") or "").strip()
                if (
                    not source_id
                    or not entity_id
                    or source_id in contract_agents_by_source
                    or entity_id in contract_agents_by_entity
                ):
                    raise RoomContractContractError(
                        "Pinned V2 runtime context requires unique, non-empty agent "
                        "source and entity identifiers."
                    )
                contract_agents_by_source[source_id] = item
                contract_agents_by_entity[entity_id] = item
            if set(contract_agents_by_source) != set(agents_map):
                raise RoomContractContractError(
                    "Materialized agents do not exactly match the agents in the "
                    "pinned RoomContract V2 model."
                )
            for agent in agents_list:
                contract_agent = contract_agents_by_source[agent.id]
                modeled_targets: List[str] = []
                for target_entity_id in contract_agent.get("handoff_target_ids") or []:
                    target = contract_agents_by_entity.get(str(target_entity_id))
                    target_source_id = str((target or {}).get("source_agent_id") or "").strip()
                    if not target_source_id or target_source_id not in agents_map:
                        raise RoomContractContractError(
                            f"Agent {agent.id!r} has an unresolved modeled handoff target "
                            f"{target_entity_id!r}."
                        )
                    if target_source_id == agent.id:
                        raise RoomContractContractError(
                            f"Agent {agent.id!r} cannot hand off to itself."
                        )
                    if target_source_id not in modeled_targets:
                        modeled_targets.append(target_source_id)
                # The executable model, not agents.json, is authoritative for online
                # handoffs.  This also prevents a stale/tampered client projection
                # from silently widening the handoff graph.
                agent.handoff_targets = modeled_targets

        agent_inputs = []
        for idx, agent in enumerate(agents_list):
            source = agent_dicts[idx] if idx < len(agent_dicts) else {}
            agent_inputs.append(
                {
                    "id": agent.id,
                    "preferred_zone_ids": agent.preferred_zone_ids,
                    "preferred_spawn_tags": agent.preferred_spawn_tags,
                    "position": source.get("position") if isinstance(source, dict) else None,
                    "forward": source.get("forward") if isinstance(source, dict) else None,
                    "spawn_point_id": source.get("spawn_point_id") if isinstance(source, dict) else None,
                }
            )

        placements = assign_spawn_points(
            room_plan=room_plan,
            agents=agent_inputs,
        )

        st = SessionState(
            session_id=session_id,
            agents=agents_map,
            placements=placements,
            kb=kb or self.kb,
            memory_mode=mode,
            history=[],
            agent_histories={a.id: [] for a in agents_list},
            project_id=project_id,
            roomcontract_contract_kind=contract_kind,
            roomcontract_model_version=str((roomcontract_contract or {}).get("model_version") or ""),
            roomcontract_model_sha256=str((roomcontract_contract or {}).get("model_sha256") or ""),
            roomcontract_profile=str((roomcontract_contract or {}).get("profile") or "none"),
            roomcontract_contract_fingerprint=(
                contract_runtime_fingerprint(roomcontract_contract)
                if roomcontract_contract
                else ""
            ),
            roomcontract_runtime_context=copy.deepcopy(
                runtime_context or None
            ),
        )
        st.pinned_contract = copy.deepcopy(roomcontract_contract or {})
        st.commit_fingerprint = contract_commit_fingerprint(
            roomcontract_contract or {}, self.guard_config.commit_variant,
            project_dir=self.project_manager._project_dir(project_id) if project_id else None,
        ) if roomcontract_contract else ""
        if self.guard_config.routing_mode == "table" and contract_kind == "v2":
            from .verified_routing import verified_table
            st.routing_table = verified_table(roomcontract_contract)
        st.server_active_agent_id = next(iter(st.agents), "")
        st.publication_generation = (roomcontract_contract or {}).get("publication_generation")
        self.sessions[session_id] = st
        return st

    @contextmanager
    def session_turn_scope(self, session_id: str) -> Iterator[None]:
        with self._turn_locks_guard:
            lock = self._turn_locks.setdefault(str(session_id), threading.RLock())
        with lock:
            yield

    def commit_chat_active(self, session_id: str, output: Dict[str, Any]) -> None:
        st = self.sessions[session_id]
        agent_id = str(output.get("active_agent_id") or "")
        if agent_id not in st.agents:
            raise RoomContractContractError("Committed active agent is unknown.", code="E_ACTIVE_AGENT_UNKNOWN")
        st.server_active_agent_id = agent_id

    def switch_agent(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        session_id = str(payload.get("session_id") or "")
        with self.session_turn_scope(session_id):
            st = self.sessions.get(session_id)
            if st is None:
                raise RoomContractContractError("Unknown session.", code="E_SCHEMA")
            agent_id = str(payload.get("active_agent_id") or "")
            if agent_id not in st.agents:
                raise RoomContractContractError("Unknown addressed agent.", code="E_ACTIVE_AGENT_UNKNOWN")
            from .runtime_trace import _append_jsonl_transaction
            if not st.project_id:
                raise RoomContractContractError("Switch audit requires a project.", code="E_SCHEMA")
            audit = self.project_manager._project_dir(st.project_id) / "runtime_guard_audit.jsonl"
            event = {"event_type": "switch_agent", "session_id": session_id,
                     "from": st.server_active_agent_id, "to": agent_id,
                     "model_sha256": st.roomcontract_model_sha256}
            _append_jsonl_transaction(audit, [event], None, [])
            st.server_active_agent_id = agent_id
            st.touch()
            return {"session_id": session_id, "active_agent_id": agent_id}

    def setup_from_request(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        project_id = str(payload.get("project_id") or "").strip()
        if project_id and self.guard_config.publication_protocol == "cooperative":
            from .publication import project_lock
            with project_lock(self.project_manager._project_dir(project_id)):
                return self._setup_from_request_unlocked(payload)
        return self._setup_from_request_unlocked(payload)

    def _setup_from_request_unlocked(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Supports:
        - direct: {"room_plan": {...}, "agents": [{"..."}]}
        - via paths: {"room_plan_path": "examples/room_plan.example.json", "agents_path": "examples/agents.example.json"}
        - via project: {"project_id": "demo_project"}
        """
        project_id = str(payload.get("project_id") or "").strip() or None
        project_room_plan = None
        project_agents = None
        project_kb = None
        roomcontract_contract: Optional[Dict[str, Any]] = None
        if project_id:
            project_room_plan = self.project_manager.load_room_plan(project_id)
            project_agents = self.project_manager.load_agents(project_id).get("agents", [])
            project_kb = self._get_project_kb(project_id)
            roomcontract_contract = load_project_contract(self.project_manager._project_dir(project_id), publication_protocol=self.guard_config.publication_protocol)
            if roomcontract_contract.get("kind") == "v2":
                # Fail before the session map is mutated unless V2 provides one exact
                # setup action through the validated Step -> CapabilityUse -> Binding chain.
                select_runtime_action(
                    roomcontract_contract.get("runtime_context") or {},
                    "setup",
                )
        memory_mode = normalize_memory_mode(payload.get("memory_mode"), default=self.default_memory_mode)

        room_plan_path = payload.get("room_plan_path")
        if room_plan_path:
            room_plan = self._load_json_file(str(room_plan_path))
        elif project_room_plan is not None:
            room_plan = project_room_plan
        else:
            room_plan = payload.get("room_plan") or {}
            if not room_plan:
                room_plan = self._load_json_file(self.default_room_plan_path)

        agents_path = payload.get("agents_path")
        if agents_path:
            agents_doc = self._load_json_file(str(agents_path))
            agent_dicts = agents_doc.get("agents") or []
        elif project_agents is not None:
            agent_dicts = project_agents
        else:
            agent_dicts = payload.get("agents") or payload.get("agent_specs") or []
            if not agent_dicts:
                agents_doc = self._load_json_file(self.default_agents_path)
                agent_dicts = agents_doc.get("agents") or []

        session_id = payload.get("session_id")
        st = self.create_session(
            room_plan=room_plan,
            agent_dicts=agent_dicts,
            session_id=session_id,
            kb=project_kb,
            project_id=project_id,
            memory_mode=memory_mode,
            roomcontract_contract=roomcontract_contract,
        )

        source_agent_by_id = {
            str(item.get("id") or ""): item
            for item in agent_dicts
            if isinstance(item, dict) and str(item.get("id") or "")
        }
        runtime_context = copy.deepcopy(st.roomcontract_runtime_context or {})
        contract_agents_by_source = {
            str(item.get("source_agent_id") or ""): item
            for item in runtime_context.get("agents", [])
            if isinstance(item, dict) and str(item.get("source_agent_id") or "")
        }
        agents_out = []
        for aid, agent in st.agents.items():
            pl = st.placements.get(aid, {})
            source = source_agent_by_id.get(aid, {})
            contract_agent = contract_agents_by_source.get(aid, {})
            agents_out.append(
                {
                    "id": agent.id,
                    "display_name": agent.display_name,
                    "voice": agent.voice,
                    "voice_style": agent.voice_style,
                    "tts_model": agent.tts_model,
                    "position": pl.get("position", {"x": 0, "y": 0, "z": 0}),
                    "forward": pl.get("forward", {"x": 0, "y": 0, "z": 1}),
                    "spawn_point_id": pl.get("spawn_point_id"),
                    "zone_id": pl.get("zone_id"),
                    "tags": pl.get("tags", []),
                    "voice_gender": source.get("voice_gender"),
                    "roomcontract_agent_id": source.get("roomcontract_agent_ref")
                    or contract_agent.get("roomcontract_agent_id"),
                    "roomcontract_entity_id": source.get("roomcontract_entity_ref")
                    or contract_agent.get("entity_id"),
                    "provided_capability_ids": contract_agent.get("provided_capability_ids") or [],
                    "plays_actor_ids": contract_agent.get("plays_actor_ids") or [],
                    "responsible_zone_ids": contract_agent.get("responsible_zone_ids") or [],
                    "grounded_asset_ids": contract_agent.get("grounded_asset_ids") or [],
                    "grounded_object_group_ids": contract_agent.get("grounded_object_group_ids") or [],
                    "handoff_target_ids": contract_agent.get("handoff_target_source_agent_ids") or [],
                }
            )

        contract = roomcontract_contract or {
            "model_version": "",
            "profile": "none",
            "model_sha256": "",
            "runtime_context": None,
        }
        context = copy.deepcopy(st.roomcontract_runtime_context or {})
        return {
            "session_id": st.session_id,
            "memory_mode": st.memory_mode,
            "agents": agents_out,
            "metamodel_version": contract.get("model_version") or "",
            "trace_schema_version": context.get("trace_schema_version") or "",
            "model_sha256": contract.get("model_sha256") or "",
            "roomcontract_profile": contract.get("profile") or "none",
            "roomcontract_model_endpoint": (
                f"/projects/{project_id}/roomcontract-v2"
                if project_id and contract.get("kind") == "v2"
                else None
            ),
            "runtime_validation_target_id": context.get("runtime_validation_target_id"),
            "spatial_entities": copy.deepcopy(context.get("spatial_entities") or []),
            "roomcontract": copy.deepcopy(context) if context else None,
        }

    def preflight_runtime_action(
        self,
        session_id: str,
        action_kind: str,
        *,
        scenario_id: Optional[str] = None,
        provider_entity_id: Optional[str] = None,
        target_id: Optional[str] = None,
        require_targetless: bool = False,
    ) -> Dict[str, Any]:
        """Revalidate a session's pinned V2 contract and one concrete action.

        Legacy/non-RoomContract sessions retain their previous behavior and return
        an empty preflight descriptor.
        """

        session_id = str(session_id or "").strip()
        st = self.sessions.get(session_id)
        if st is None:
            raise RoomContractContractError("Unbekannte session_id. Bitte /setup erneut aufrufen.", code="E_SCHEMA")
        if st.roomcontract_contract_kind != "v2":
            return {
                "kind": st.roomcontract_contract_kind,
                "contract_fingerprint": "",
                "action": None,
            }
        if not st.project_id or not st.roomcontract_contract_fingerprint:
            raise RoomContractContractError("V2 session is missing its pinned project contract.", code="E_CONTRACT_DRIFT")
        current = load_project_contract(self.project_manager._project_dir(st.project_id), publication_protocol=self.guard_config.publication_protocol)
        current_fingerprint = contract_runtime_fingerprint(current)
        if current.get("kind") != "v2" or current_fingerprint != st.roomcontract_contract_fingerprint:
            raise RoomContractContractError("RoomContract V2 project drift detected: the project no longer "
                "matches the contract pinned when the session was created.", code="E_CONTRACT_DRIFT")
        pinned_action = select_runtime_action(
            st.roomcontract_runtime_context or {},
            action_kind,
            scenario_id=scenario_id,
            provider_entity_id=provider_entity_id,
            target_id=target_id,
            require_targetless=require_targetless,
        )
        current_action = select_runtime_action(
            current.get("runtime_context") or {},
            action_kind,
            scenario_id=scenario_id,
            provider_entity_id=provider_entity_id,
            target_id=target_id,
            require_targetless=require_targetless,
        )
        if _canonical_runtime_value(pinned_action) != _canonical_runtime_value(current_action):
            raise RoomContractContractError(f"RoomContract V2 action drift detected for {action_kind!r}.", code="E_CONTRACT_DRIFT")
        return {
            "kind": "v2",
            "contract_fingerprint": st.commit_fingerprint,
            "action": copy.deepcopy(pinned_action),
        }

    def snapshot_session_mutation(self, session_id: str) -> Dict[str, Any]:
        """Capture only mutable conversational state for HTTP transaction rollback."""

        st = self.sessions.get(str(session_id or "").strip())
        if st is None:
            raise ValueError("Unbekannte session_id. Bitte /setup erneut aufrufen.")
        return {
            "history": copy.deepcopy(st.history),
            "agent_histories": copy.deepcopy(st.agent_histories),
            "server_active_agent_id": st.server_active_agent_id,
            "ignored_handoff_proposals": copy.deepcopy(st.ignored_handoff_proposals),
            "updated_ms": st.updated_ms,
        }

    def restore_session_mutation(self, session_id: str, snapshot: Dict[str, Any]) -> None:
        # Prepare every possibly failing copy/conversion before one attribute-map
        # replacement. The turn lock serializes participating readers/writers.
        with self.session_turn_scope(session_id):
            st = self.sessions.get(str(session_id or "").strip())
            if st is None:
                return
            restored = dict(st.__dict__)
            restored.update({
                "server_active_agent_id": str(snapshot.get("server_active_agent_id") or ""),
                "ignored_handoff_proposals": copy.deepcopy(snapshot.get("ignored_handoff_proposals") or []),
                "history": copy.deepcopy(snapshot.get("history") or []),
                "agent_histories": copy.deepcopy(snapshot.get("agent_histories") or {}),
                "updated_ms": int(snapshot.get("updated_ms") or st.updated_ms),
            })
            st.__dict__ = restored

    def roomcontract_v2_document(self, project_id: str) -> Dict[str, Any]:
        project_id = str(project_id or "").strip()
        if not project_id:
            raise ValueError("project_id fehlt.")
        self.project_manager._require_project(project_id)
        return load_v2_document(self.project_manager._project_dir(project_id))

    def roomcontract_v2_bytes(self, project_id: str) -> bytes:
        """Return the exact hashed model bytes used by the V2 runtime contract."""

        project_id = str(project_id or "").strip()
        if not project_id:
            raise ValueError("project_id fehlt.")
        self.project_manager._require_project(project_id)
        contract = load_project_contract(self.project_manager._project_dir(project_id), publication_protocol=self.guard_config.publication_protocol)
        if contract.get("kind") != "v2":
            raise ValueError("Projekt stellt keine native RoomContract-V2-Instanz bereit.")
        model_path = Path(str(contract.get("instance_path") or ""))
        if not model_path.is_file():
            raise ValueError("Native RoomContract-V2-Instanz fehlt.")
        return model_path.read_bytes()

    def tts(self, payload: Dict[str, Any]) -> Tuple[bytes, str]:
        text = str(payload.get("text") or "").strip()
        if not text:
            raise ValueError("text fehlt.")
        voice = str(payload.get("voice") or "").strip() or "alloy"
        tts_model = str(payload.get("tts_model") or "").strip() or "gpt-4o-mini-tts"
        response_format = str(payload.get("response_format") or "mp3").strip() or "mp3"
        print(
            "[TTS] Anfrage vorbereiten: "
            f"text_len={len(text)}, voice={voice}, model={tts_model}, format={response_format}",
            flush=True,
        )
        audio, content_type = create_tts_audio(
            api_key=self.openai.api_key,
            text=text,
            voice=voice,
            model=tts_model,
            response_format=response_format,
            timeout_seconds=self.openai.timeout_seconds,
        )
        print(
            "[TTS] Antwort erhalten: "
            f"bytes={len(audio)}, content_type={content_type}",
            flush=True,
        )
        return audio, content_type

    def stt(self, payload: Dict[str, Any], files: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        file_info = files.get("audio") or files.get("file")
        if not file_info:
            raise ValueError("audio fehlt.")

        audio = file_info.get("content") or b""
        if not isinstance(audio, (bytes, bytearray)) or not audio:
            raise ValueError("audio ist leer.")
        if len(audio) > self.stt_max_audio_bytes:
            raise ValueError(f"audio ist zu groß ({len(audio)} Bytes, Limit {self.stt_max_audio_bytes}).")

        model = str(payload.get("model") or self.stt_model or "whisper-1").strip()
        language = str(payload.get("language") or self.stt_language or "").strip() or None
        prompt = str(payload.get("prompt") or "").strip() or None
        filename = str(file_info.get("filename") or "speech.wav").strip() or "speech.wav"
        content_type = str(file_info.get("content_type") or "audio/wav").strip() or "audio/wav"

        print(
            "[STT] Anfrage vorbereiten: "
            f"bytes={len(audio)}, filename={filename}, content_type={content_type}, model={model}, language={language or ''}",
            flush=True,
        )
        result = create_transcription(
            api_key=self.openai.api_key,
            audio=bytes(audio),
            filename=filename,
            content_type=content_type,
            model=model,
            language=language,
            prompt=prompt,
            timeout_seconds=self.openai.timeout_seconds,
        )

        text = str(result.get("text") or "").strip()
        print(f"[STT] Transkript erhalten: text_len={len(text)}", flush=True)
        return {
            "text": text,
            "model": model,
            "language": language,
        }

    def _get_project_kb(self, project_id: str) -> KnowledgeBase:
        if project_id in self.kb_cache:
            return self.kb_cache[project_id]
        kb_root = self.project_manager.project_kb_root(project_id)
        kb = KnowledgeBase(kb_root, chunk_chars=self.kb.chunk_chars)
        self.kb_cache[project_id] = kb
        return kb

    def refresh_project_kb(self, project_id: str) -> KnowledgeBase:
        if project_id in self.kb_cache:
            del self.kb_cache[project_id]
        return self._get_project_kb(project_id)

    # -------------------- Chat orchestration --------------------

    @staticmethod
    def _bounded_spatial_text(
        value: Any,
        field_name: str,
        *,
        maximum: int = SPATIAL_ID_MAX_LENGTH,
        required: bool = False,
    ) -> str:
        if value is None:
            text = ""
        elif not isinstance(value, str):
            raise RoomContractContractError(f"spatial_context.{field_name} muss ein String sein.", code="E_SCHEMA")
        else:
            text = value.strip()
        if required and not text:
            raise RoomContractContractError(f"spatial_context.{field_name} fehlt.", code="E_SCHEMA")
        if len(text) > maximum:
            raise RoomContractContractError(f"spatial_context.{field_name} ueberschreitet das Limit "
                f"von {maximum} Zeichen.", code="E_SCHEMA")
        return text

    @staticmethod
    def _finite_spatial_number(
        value: Any,
        field_name: str,
        *,
        absolute_limit: float = SPATIAL_COORDINATE_LIMIT,
    ) -> float:
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
        ):
            raise RoomContractContractError(f"spatial_context.{field_name} muss eine endliche JSON-Zahl sein.", code="E_SCHEMA")
        number = float(value)
        if abs(number) > absolute_limit:
            raise RoomContractContractError(f"spatial_context.{field_name} liegt ausserhalb des Limits "
                f"+/-{absolute_limit:g}.", code="E_SCHEMA")
        return number

    @staticmethod
    def _v2_interaction_mode(
        action: Dict[str, Any],
        payload: Dict[str, Any],
    ) -> str:
        request_schema = action.get("request_wire_schema")
        if not isinstance(request_schema, dict):
            raise RoomContractContractError("Pinned V2 chat action has no executable request wire schema.", code="E_SCHEMA")
        if request_schema.get("wireContractVersion") != WIRE_CONTRACT_VERSION:
            raise RoomContractContractError("Pinned V2 chat action has an unsupported wire contract version.", code="E_SCHEMA")
        properties = request_schema.get("properties")
        mode_schema = (
            properties.get("interaction_mode")
            if isinstance(properties, dict)
            else None
        )
        modeled_modes = (
            list(mode_schema.get("enum") or [])
            if isinstance(mode_schema, dict)
            else []
        )
        if modeled_modes != list(INTERACTION_MODES):
            raise RoomContractContractError("Pinned V2 chat action does not model the exact interaction modes.", code="E_SCHEMA")
        raw_mode = payload.get("interaction_mode")
        if not isinstance(raw_mode, str) or not raw_mode.strip():
            raise RoomContractContractError("interaction_mode fehlt fuer RoomContract V2; erlaubt sind "
                "'deictic' und 'non_deictic'.", code="E_SCHEMA")
        mode = raw_mode.strip().lower()
        if mode not in modeled_modes:
            raise RoomContractContractError(f"Ungueltiger interaction_mode {mode!r}; erlaubt sind "
                + ", ".join(modeled_modes)
                + ".", code="E_SCHEMA")
        return mode

    def _v2_interaction_mode_for_context(
        self,
        st: SessionState,
        payload: Dict[str, Any],
    ) -> str:
        actions = runtime_actions_for_kind(
            st.roomcontract_runtime_context or {},
            "chat",
        )
        if not actions:
            raise RoomContractContractError("Pinned V2 session has no executable chat action.", code="E_NO_DECLARED_ACTION")
        modes = {
            self._v2_interaction_mode(action, payload)
            for action in actions
        }
        if len(modes) != 1:
            raise RoomContractContractError("Pinned V2 chat actions disagree on their interaction-mode "
                "wire contract.", code="E_SCHEMA")
        return next(iter(modes))

    @staticmethod
    def _v2_provider_entity_id(
        st: SessionState,
        source_agent_id: str,
    ) -> str:
        matches = [
            str(
                item.get("roomcontract_agent_id")
                or item.get("entity_id")
                or ""
            ).strip()
            for item in (st.roomcontract_runtime_context or {}).get(
                "agents",
                [],
            )
            if isinstance(item, dict)
            and str(item.get("source_agent_id") or "").strip()
            == source_agent_id
        ]
        matches = [item for item in matches if item]
        if len(matches) != 1:
            raise RoomContractContractError(f"Pinned V2 agent {source_agent_id!r} has no unique provider "
                "Entity.", code="E_ACTIVE_AGENT_UNKNOWN")
        return matches[0]

    def _preflight_v2_interaction_action(
        self,
        *,
        st: SessionState,
        session_id: str,
        action_kind: str,
        interaction_mode: str,
        provider_entity_id: str,
        target_id: Optional[str],
    ) -> Dict[str, Any]:
        if self.guard_config.routing_mode == "reach_only":
            current = load_project_contract(
                self.project_manager._project_dir(st.project_id),
                publication_protocol=self.guard_config.publication_protocol,
            )
            if contract_runtime_fingerprint(current) != st.roomcontract_contract_fingerprint:
                raise RoomContractContractError("Contract changed before generation.", code="E_CONTRACT_DRIFT")
            return {"kind": "v2", "contract_fingerprint": st.commit_fingerprint,
                    "action": {"action_kind": action_kind, "provider_entity_id": provider_entity_id,
                               "target_ids": [target_id] if target_id else [],
                               "_experimental_undeclared": True}}
        candidates = runtime_actions_for_kind(
            st.roomcontract_runtime_context or {},
            action_kind,
        )
        if not candidates:
            raise RoomContractContractError(f"Pinned V2 session has no executable {action_kind} action.", code="E_NO_DECLARED_ACTION")
        legacy_single_chain = (
            len(candidates) == 1
            and not str(candidates[0].get("scenario_id") or "").strip()
        )
        if legacy_single_chain:
            return self.preflight_runtime_action(session_id, action_kind)
        if interaction_mode == "deictic":
            if not target_id:
                raise RoomContractContractError("A deictic V2 action requires a trusted model target.", code="E_UNKNOWN_ENTITY")
            return self.preflight_runtime_action(
                session_id,
                action_kind,
                provider_entity_id=provider_entity_id,
                target_id=target_id,
            )

        # Preserve old single-chain V2 fixtures.  A multi-chain non-deictic
        # request, however, may only use an explicitly target-less provider
        # chain; selecting an arbitrary asset chain would create false evidence.
        if len(candidates) == 1:
            return self.preflight_runtime_action(session_id, action_kind)
        return self.preflight_runtime_action(
            session_id,
            action_kind,
            provider_entity_id=provider_entity_id,
            require_targetless=True,
        )

    @staticmethod
    def _v2_model_binding(action: Dict[str, Any]) -> Dict[str, str]:
        if action.get("_experimental_undeclared"):
            return {}
        fields = (
            "runtime_binding_id",
            "runtime_action_id",
            "capability_id",
            "capability_use_id",
        )
        binding = {
            field_name: str(action.get(field_name) or "").strip()
            for field_name in fields
        }
        missing = [
            field_name
            for field_name, value in binding.items()
            if not value
        ]
        if missing:
            raise RoomContractContractError(
                "Pinned V2 chat action has an incomplete model binding: "
                + ", ".join(missing)
                + "."
            )
        return binding

    def _validate_spatial_context(
        self,
        st: SessionState,
        raw_context: Any,
    ) -> Optional[Dict[str, Any]]:
        """Validate and resolve an optional client selection against the pinned V2 model.

        The client supplies observation data only.  Entity, group, zone, and routing
        claims are reconstructed from the immutable runtime context pinned at setup.
        """

        if raw_context is None:
            return None
        if not isinstance(raw_context, dict):
            raise RoomContractContractError("spatial_context muss ein JSON-Objekt sein.", code="E_SELECTION_STATE")
        if st.roomcontract_contract_kind != "v2":
            raise RoomContractContractError("spatial_context wird nur fuer eine gepinnte RoomContract-V2-Session akzeptiert.", code="E_SELECTION_STATE")
        allowed_fields = {
            "model_sha256",
            "state",
            "entity_id",
            "source_object_id",
            "source_id",
            "object_group_id",
            "zone_id",
            "hit_position",
            "distance_m",
            "selection_modality",
            "modality",
            "candidate_entity_ids",
            "ambiguous",
            "ambiguity",
            "ambiguity_reason",
            # Compatibility-only presentation hints emitted by older Unity clients.
            # They are validated below but never used as identity/model evidence.
            "display_name",
            "synonyms",
        }
        unknown_fields = sorted(set(raw_context) - allowed_fields)
        if unknown_fields:
            raise RoomContractContractError("spatial_context enthaelt unbekannte Felder: "
                + ", ".join(unknown_fields)
                + ".", code="E_SCHEMA")

        # Accept the legacy Unity wire shape without trusting its presentation data.
        # The canonical name and aliases are reconstructed from the pinned V2 model.
        if raw_context.get("display_name") is not None:
            self._bounded_spatial_text(
                raw_context.get("display_name"),
                "display_name",
                maximum=256,
            )
        supplied_synonyms = raw_context.get("synonyms")
        if supplied_synonyms is not None:
            if not isinstance(supplied_synonyms, list):
                raise RoomContractContractError("spatial_context.synonyms muss eine Liste sein.", code="E_SCHEMA")
            if len(supplied_synonyms) > 32:
                raise RoomContractContractError("spatial_context.synonyms enthaelt zu viele Eintraege.", code="E_SCHEMA")
            for synonym in supplied_synonyms:
                self._bounded_spatial_text(
                    synonym,
                    "synonyms[]",
                    maximum=256,
                    required=True,
                )

        supplied_hash = self._bounded_spatial_text(
            raw_context.get("model_sha256"),
            "model_sha256",
            maximum=64,
            required=True,
        ).upper()
        expected_hash = str(st.roomcontract_model_sha256 or "").strip().upper()
        if self.guard_config.digest_check and (not expected_hash or supplied_hash != expected_hash):
            raise RoomContractContractError("Stale spatial_context: model_sha256 stimmt nicht mit dem "
                "bei /setup gepinnten RoomContract-V2-Modell ueberein.", code="E_STALE_DIGEST")

        state = self._bounded_spatial_text(
            raw_context.get("state"),
            "state",
            maximum=16,
            required=True,
        ).lower()
        ambiguity = raw_context.get("ambiguity")
        ambiguous_value = raw_context.get("ambiguous")
        if ambiguous_value is not None and not isinstance(ambiguous_value, bool):
            raise RoomContractContractError("spatial_context.ambiguous muss ein Boolean sein.", code="E_SELECTION_STATE")
        ambiguity_flag = bool(ambiguous_value)
        if isinstance(ambiguity, bool):
            ambiguity_flag = ambiguity_flag or ambiguity
        elif isinstance(ambiguity, dict):
            if len(ambiguity) > 8:
                raise RoomContractContractError("spatial_context.ambiguity enthaelt zu viele Felder.", code="E_SELECTION_STATE")
            for ambiguity_key, ambiguity_value in ambiguity.items():
                if len(str(ambiguity_key)) > 64 or len(str(ambiguity_value)) > SPATIAL_REASON_MAX_LENGTH:
                    raise RoomContractContractError("spatial_context.ambiguity enthaelt einen zu langen Wert.", code="E_SELECTION_STATE")
            ambiguity_flag = ambiguity_flag or bool(
                ambiguity.get("ambiguous")
                or ambiguity.get("is_ambiguous")
                or ambiguity.get("reason")
            )
        elif ambiguity is not None:
            raise RoomContractContractError("spatial_context.ambiguity muss ein Boolean oder Objekt sein.", code="E_SELECTION_STATE")
        ambiguity_reason = self._bounded_spatial_text(
            raw_context.get("ambiguity_reason"),
            "ambiguity_reason",
            maximum=SPATIAL_REASON_MAX_LENGTH,
        )
        if state != "resolved":
            raise RoomContractContractError("spatial_context.state muss 'resolved' sein; none/ambiguous wird fail-closed abgelehnt.", code="E_SELECTION_STATE")
        if ambiguity_flag or ambiguity_reason:
            raise RoomContractContractError("Mehrdeutiger spatial_context wird fail-closed abgelehnt.", code="E_SELECTION_STATE")

        runtime_context = st.roomcontract_runtime_context or {}
        spatial_entities = [
            item
            for item in runtime_context.get("spatial_entities", [])
            if isinstance(item, dict)
        ]
        by_entity_id: Dict[str, Dict[str, Any]] = {}
        for item in spatial_entities:
            entity_id = str(item.get("entity_id") or "").strip()
            if not entity_id or entity_id in by_entity_id:
                raise RoomContractContractError("Pinned V2 runtime context contains ambiguous spatial entity identifiers.", code="E_UNKNOWN_ENTITY")
            by_entity_id[entity_id] = item

        supplied_entity_id = self._bounded_spatial_text(
            raw_context.get("entity_id"),
            "entity_id",
        )
        supplied_source_id = self._bounded_spatial_text(
            raw_context.get("source_object_id")
            or raw_context.get("source_id")
            or None,
            "source_object_id",
        )
        if not supplied_entity_id and not supplied_source_id:
            raise RoomContractContractError("spatial_context benoetigt entity_id oder source_object_id.", code="E_UNKNOWN_ENTITY")

        selected: Optional[Dict[str, Any]] = None
        if supplied_entity_id:
            selected = by_entity_id.get(supplied_entity_id)
            if selected is None:
                raise RoomContractContractError(f"Unbekannte spatial_context.entity_id: {supplied_entity_id!r}.", code="E_UNKNOWN_ENTITY")
        if supplied_source_id:
            source_matches = [
                item
                for item in spatial_entities
                if str(item.get("source_id") or "").strip() == supplied_source_id
                and str(item.get("kind") or "").strip() == "asset"
                and str(item.get("entity_role") or "").strip() == "sceneObject"
            ]
            if len(source_matches) != 1:
                qualifier = "unbekannt" if not source_matches else "mehrdeutig"
                raise RoomContractContractError(f"spatial_context.source_object_id ist im gepinnten Modell {qualifier}: "
                    f"{supplied_source_id!r}.", code="E_UNKNOWN_ENTITY")
            if selected is not None and selected.get("entity_id") != source_matches[0].get("entity_id"):
                raise RoomContractContractError("spatial_context.entity_id und source_object_id bezeichnen "
                    "unterschiedliche Modellobjekte.", code="E_ID_MISMATCH")
            selected = source_matches[0]

        if selected is None:
            raise RoomContractContractError("spatial_context konnte nicht aufgeloest werden.", code="E_UNKNOWN_ENTITY")
        if (
            str(selected.get("kind") or "").strip() != "asset"
            or str(selected.get("entity_role") or "").strip() != "sceneObject"
        ):
            raise RoomContractContractError("spatial_context muss ein konkretes Szeneobjekt (asset/sceneObject) referenzieren.", code="E_UNKNOWN_ENTITY")

        selected_entity_id = str(selected.get("entity_id") or "")
        selected_source_id = str(selected.get("source_id") or "")
        candidate_ids_raw = raw_context.get("candidate_entity_ids")
        if candidate_ids_raw is None:
            candidate_ids: List[str] = []
        elif not isinstance(candidate_ids_raw, list):
            raise RoomContractContractError("spatial_context.candidate_entity_ids muss eine Liste sein.", code="E_SELECTION_STATE")
        else:
            if len(candidate_ids_raw) > SPATIAL_CANDIDATE_LIMIT:
                raise RoomContractContractError("spatial_context.candidate_entity_ids ueberschreitet das "
                    f"Limit von {SPATIAL_CANDIDATE_LIMIT}.", code="E_SELECTION_STATE")
            candidate_ids = []
            for candidate in candidate_ids_raw:
                candidate_id = self._bounded_spatial_text(
                    candidate,
                    "candidate_entity_ids[]",
                    required=True,
                )
                if not candidate_id or candidate_id not in by_entity_id:
                    raise RoomContractContractError(f"spatial_context enthaelt unbekannten Kandidaten {candidate_id!r}.", code="E_SELECTION_STATE")
                if candidate_id in candidate_ids:
                    raise RoomContractContractError("spatial_context.candidate_entity_ids enthaelt Duplikate.", code="E_SELECTION_STATE")
                candidate_ids.append(candidate_id)
        if len(candidate_ids) > 1 or (
            candidate_ids and candidate_ids[0] != selected_entity_id
        ):
            raise RoomContractContractError("Mehrdeutige spatial_context-Kandidaten werden fail-closed abgelehnt.", code="E_SELECTION_STATE")

        hit_position_raw = raw_context.get("hit_position")
        if not isinstance(hit_position_raw, dict):
            raise RoomContractContractError("spatial_context.hit_position muss ein Objekt mit x/y/z sein.", code="E_SCHEMA")
        if set(hit_position_raw) != {"x", "y", "z"}:
            raise RoomContractContractError("spatial_context.hit_position darf nur x, y und z enthalten.", code="E_SCHEMA")
        hit_position = {
            axis: self._finite_spatial_number(
                hit_position_raw.get(axis),
                f"hit_position.{axis}",
            )
            for axis in ("x", "y", "z")
        }
        distance_m = self._finite_spatial_number(
            raw_context.get("distance_m"),
            "distance_m",
            absolute_limit=SPATIAL_DISTANCE_LIMIT_METERS,
        )
        if distance_m < 0:
            raise RoomContractContractError("spatial_context.distance_m darf nicht negativ sein.", code="E_SCHEMA")
        selection_modality = self._bounded_spatial_text(
            raw_context.get("selection_modality"),
            "selection_modality",
            maximum=64,
            required=True,
        ).lower()
        supplied_modality_alias = self._bounded_spatial_text(
            raw_context.get("modality"),
            "modality",
            maximum=64,
        ).lower()
        if supplied_modality_alias and supplied_modality_alias != selection_modality:
            raise RoomContractContractError("spatial_context.modality widerspricht selection_modality.", code="E_SCHEMA")
        if selection_modality not in SPATIAL_SELECTION_MODALITIES:
            raise RoomContractContractError("spatial_context.selection_modality ist unbekannt; erlaubt sind "
                + ", ".join(sorted(SPATIAL_SELECTION_MODALITIES))
                + ".", code="E_SCHEMA")

        group_ids: List[str] = []
        for group_id in selected.get("object_group_ids") or []:
            group = by_entity_id.get(str(group_id))
            if (
                group is None
                or str(group.get("entity_role") or "") != "objectGroup"
                or str(group.get("kind") or "") != "asset"
            ):
                raise RoomContractContractError(f"Szeneobjekt {selected_entity_id!r} referenziert eine ungueltige "
                    f"Objektgruppe {group_id!r}.", code="E_PUBLICATION_INCONSISTENT")
            if str(group_id) not in group_ids:
                group_ids.append(str(group_id))
        if not group_ids:
            source_group = str(selected.get("source_group") or "").strip()
            group_ids = [
                str(item.get("entity_id"))
                for item in spatial_entities
                if source_group
                and str(item.get("entity_role") or "") == "objectGroup"
                and str(item.get("source_group") or "") == source_group
            ]

        zone_ids = [
            str(item.get("entity_id"))
            for item in spatial_entities
            if str(item.get("kind") or "") == "zone"
            and selected_source_id in {
                str(source_object_id)
                for source_object_id in item.get("source_object_ids") or []
            }
        ]

        supplied_group_id = self._bounded_spatial_text(
            raw_context.get("object_group_id"),
            "object_group_id",
        )
        if supplied_group_id:
            trusted_group_aliases = set(group_ids)
            for group_id in group_ids:
                group = by_entity_id[group_id]
                trusted_group_aliases.update(
                    {
                        str(group.get("source_id") or "").strip(),
                        str(group.get("source_group") or "").strip(),
                    }
                )
            trusted_group_aliases.discard("")
            if supplied_group_id not in trusted_group_aliases:
                raise RoomContractContractError("spatial_context.object_group_id widerspricht dem gepinnten V2-Modell.", code="E_ID_MISMATCH")
        supplied_zone_id = self._bounded_spatial_text(
            raw_context.get("zone_id"),
            "zone_id",
        )
        if supplied_zone_id:
            trusted_zone_aliases = set(zone_ids)
            trusted_zone_aliases.update(
                str(by_entity_id[zone_id].get("source_id") or "").strip()
                for zone_id in zone_ids
            )
            trusted_zone_aliases.discard("")
            if supplied_zone_id not in trusted_zone_aliases:
                raise RoomContractContractError("spatial_context.zone_id widerspricht dem gepinnten V2-Modell.", code="E_ID_MISMATCH")

        grounded_entity_ids = [selected_entity_id]
        for related_id in group_ids + zone_ids:
            if related_id not in grounded_entity_ids:
                grounded_entity_ids.append(related_id)
        evidence: List[Dict[str, Any]] = [
            {
                "relation": "selected_scene_object",
                "subject_id": selected_entity_id,
                "source_object_id": selected_source_id,
                "source": "pinned_roomcontract_v2",
            }
        ]
        evidence.extend(
            {
                "relation": "objectGroup",
                "subject_id": selected_entity_id,
                "object_id": group_id,
                "source": "pinned_roomcontract_v2",
            }
            for group_id in group_ids
        )
        evidence.extend(
            {
                "relation": "zone_contains_source_object",
                "subject_id": zone_id,
                "source_object_id": selected_source_id,
                "source": "pinned_roomcontract_v2",
            }
            for zone_id in zone_ids
        )
        return {
            "status": "resolved",
            "model_sha256": expected_hash,
            "selected_entity_id": selected_entity_id,
            "selected_source_object_id": selected_source_id,
            "selected_name": str(selected.get("name") or selected_source_id),
            "object_group_ids": group_ids,
            "zone_ids": zone_ids,
            "grounded_entity_ids": grounded_entity_ids,
            "hit_position": hit_position,
            "distance_m": distance_m,
            "selection_modality": selection_modality,
            "evidence": evidence,
        }

    @staticmethod
    def _allowed_handoff_ids(st: SessionState, agent: AgentSpec) -> List[str]:
        if st.roomcontract_contract_kind != "v2" and not agent.handoff_targets:
            # Preserve the pre-V2 contract: legacy agent projections without an
            # explicit allow-list may hand off to any other materialized agent.
            return [
                agent_id
                for agent_id in st.agents
                if agent_id != agent.id
            ]
        allowed: List[str] = []
        for target_id in agent.handoff_targets:
            if target_id in st.agents and target_id != agent.id and target_id not in allowed:
                allowed.append(target_id)
        return allowed

    @staticmethod
    def _spatial_handoff_announcement(
        target: AgentSpec,
        grounding: Optional[Dict[str, Any]],
    ) -> str:
        object_name = str(
            (grounding or {}).get("selected_name")
            or (grounding or {}).get("selected_source_object_id")
            or "dieses Objekt"
        ).strip()
        return (
            f"Für {object_name} ist {target.display_name} zuständig. "
            f"Ich leite dich jetzt zu {target.display_name} weiter."
        )

    def _resolve_spatial_route(
        self,
        st: SessionState,
        requested_agent_id: str,
        grounding: Dict[str, Any],
    ) -> Dict[str, Any]:
        if self.guard_config.routing_mode == "table":
            from .verified_routing import table_route
            if st.routing_table is None:
                st.routing_table = __import__(
                    __package__ + ".verified_routing", fromlist=["verified_table"]
                ).verified_table(st.pinned_contract or {})
            verdict = table_route(st.routing_table, requested_agent_id, grounding["selected_entity_id"])
            if verdict["decision"] == "REJECT":
                raise RoomContractContractError("Published routing table rejects this pair.", code=verdict["reason"])
            if verdict["decision"] == "ANSWER_AFTER_HANDOFF" and self.max_handoffs <= 0:
                raise RoomContractContractError("Handoffs are disabled.", code="E_NO_HANDOFF_PATH")
            provider = verdict["provider"]
            return {
                "requested_agent_id": requested_agent_id, "selected_agent_id": provider,
                "priority": "verified_table", "candidate_agent_ids": [provider],
                "modeled_handoff": provider != requested_agent_id,
                "reason": "Provider and action selected from the verified publication table.",
                "declared_action_id": verdict["action"],
            }
        runtime_agents = [
            item
            for item in (st.roomcontract_runtime_context or {}).get("agents", [])
            if isinstance(item, dict)
        ]
        selected_entity_id = grounding["selected_entity_id"]
        group_ids = set(grounding.get("object_group_ids") or [])
        zone_ids = set(grounding.get("zone_ids") or [])

        levels = (
            (
                "asset",
                [
                    str(item.get("source_agent_id") or "")
                    for item in runtime_agents
                    if selected_entity_id in (item.get("grounded_asset_ids") or [])
                ],
            ),
            (
                "group",
                [
                    str(item.get("source_agent_id") or "")
                    for item in runtime_agents
                    if group_ids.intersection(item.get("grounded_object_group_ids") or [])
                ],
            ),
            (
                "zone",
                [
                    str(item.get("source_agent_id") or "")
                    for item in runtime_agents
                    if zone_ids.intersection(item.get("responsible_zone_ids") or [])
                ],
            ),
        )
        priority = ""
        candidate_agent_ids: List[str] = []
        for level, raw_candidates in levels:
            candidates = [
                candidate
                for candidate in raw_candidates
                if candidate in st.agents and candidate not in candidate_agent_ids
            ]
            if candidates:
                priority = level
                candidate_agent_ids = candidates
                break
        if not candidate_agent_ids:
            raise RoomContractContractError(f"Das gepinnte V2-Modell weist dem Szeneobjekt "
                f"{selected_entity_id!r} keinen verantwortlichen Agenten zu.", code="E_UNOWNED")
        if len(candidate_agent_ids) > 1 and self.guard_config.routing_mode != "firstmatch":
            raise RoomContractContractError(f"Das gepinnte V2-Modell weist dem Szeneobjekt "
                f"{selected_entity_id!r} auf {priority!r}-Ebene mehrere "
                f"verantwortliche Agenten zu: {candidate_agent_ids!r}.", code="E_AMBIGUOUS_OWNER")

        if self.guard_config.routing_mode == "firstmatch":
            candidate_agent_ids = candidate_agent_ids[:1]
        requested_agent = st.agents[requested_agent_id]
        modeled_handoff = requested_agent_id not in candidate_agent_ids
        if not modeled_handoff:
            selected_agent_id = requested_agent_id
        else:
            if self.max_handoffs <= 0:
                raise RoomContractContractError("Das raeumliche Routing erfordert einen Handoff, aber Handoffs sind deaktiviert.", code="E_NO_HANDOFF_PATH")
            allowed_targets = self._allowed_handoff_ids(st, requested_agent)
            selected_agent_id = next(
                (
                    target_id
                    for target_id in allowed_targets
                    if target_id in candidate_agent_ids
                ),
                "",
            )
            if not selected_agent_id:
                raise RoomContractContractError(f"Kein modellierter Handoff von {requested_agent_id!r} erreicht "
                    f"einen fuer {selected_entity_id!r} verantwortlichen Agenten.", code="E_NO_HANDOFF_PATH")

        relation_label = {
            "asset": "groundedAsset",
            "group": "groundedObjectGroup",
            "zone": "responsibleZone",
        }[priority]
        if modeled_handoff:
            reason = (
                f"Spatial routing ({priority} priority): {selected_agent_id} is the "
                f"first modeled handoff target of {requested_agent_id} whose "
                f"{relation_label} covers {selected_entity_id}."
            )
        else:
            reason = (
                f"Spatial routing ({priority} priority): {requested_agent_id} already "
                f"covers {selected_entity_id} through {relation_label}."
            )
        return {
            "requested_agent_id": requested_agent_id,
            "selected_agent_id": selected_agent_id,
            "priority": priority,
            "candidate_agent_ids": candidate_agent_ids,
            "modeled_handoff": modeled_handoff,
            "reason": reason,
        }

    @staticmethod
    def _decorate_grounded_chat_response(
        response: Dict[str, Any],
        grounding: Optional[Dict[str, Any]],
        routing: Optional[Dict[str, Any]],
        *,
        interaction_mode: Optional[str] = None,
        model_binding: Optional[Dict[str, str]] = None,
        handoff_model_binding: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        if interaction_mode is None:
            return response
        out = dict(response)
        out["interaction_mode"] = interaction_mode
        out["model_binding"] = copy.deepcopy(model_binding or {})
        handoff = out.get("handoff")
        if isinstance(handoff, dict):
            # Both spatial and model-produced handoffs reached this point only
            # after the pinned V2 relation/allow-list was validated.
            handoff = dict(handoff)
            handoff["modeled_handoff"] = True
            out["handoff"] = handoff
            out["handoff_model_binding"] = copy.deepcopy(
                handoff_model_binding or {}
            )
        grounding_fields = (
            "grounded_entity_ids",
            "grounding_evidence",
            "routing_reason",
            "grounding",
            "routing",
        )
        if interaction_mode == "non_deictic":
            for field_name in grounding_fields:
                out.pop(field_name, None)
            return out
        if grounding is None or routing is None:
            raise RoomContractContractError(
                "A deictic V2 response requires validated grounding and routing."
            )
        out["grounded_entity_ids"] = list(grounding.get("grounded_entity_ids") or [])
        out["grounding_evidence"] = copy.deepcopy(grounding.get("evidence") or [])
        out["routing_reason"] = routing.get("reason")
        out["grounding"] = copy.deepcopy(grounding)
        out["routing"] = copy.deepcopy(routing)
        return out

    def _trim_history(self, history: List[Dict[str, str]]) -> List[Dict[str, str]]:
        # keep last N turns (user+assistant pairs). A turn is a user message.
        max_user_msgs = max(1, int(self.max_history_turns))
        # find last max_user_msgs user messages and keep everything after the earliest of those.
        user_indices = [i for i, m in enumerate(history) if m.get("role") == "user"]
        if len(user_indices) <= max_user_msgs:
            return history
        cutoff_user_idx = user_indices[-max_user_msgs]
        return history[cutoff_user_idx:]

    def _agent_history(self, st: SessionState, agent_id: str) -> List[Dict[str, str]]:
        return st.agent_histories.setdefault(agent_id, [])

    def _commit_agent_history(self, st: SessionState, agent_id: str, history: List[Dict[str, str]]) -> None:
        st.agent_histories[agent_id] = self._trim_history(history)

    def _handoff_brief(self, res: Dict[str, Any], user_text: str) -> str:
        brief = str(res.get("handoff_brief") or "").strip()
        if brief:
            return brief
        reason = str(res.get("handoff_reason") or "").strip()
        if reason:
            return f"Nutzerfrage: {user_text}\nWeiterleitungsgrund: {reason}"
        return f"Nutzerfrage: {user_text}"

    def _handoff_user_context(
        self,
        from_agent: AgentSpec,
        user_text: str,
        handoff_brief: str,
        handoff_reason: Optional[str],
    ) -> str:
        lines = [f"Uebergabekontext von {from_agent.display_name}: {handoff_brief}"]
        if handoff_reason:
            lines.append(f"Weiterleitungsgrund: {handoff_reason}")
        lines.append(f"Aktuelle Nutzerfrage: {user_text}")
        return "\n".join(lines)

    def _build_developer_prompt(
        self,
        agent: AgentSpec,
        others: List[AgentSpec],
        kb_snippets: List[Dict[str, Any]],
        allow_handoff: bool,
        grounding: Optional[Dict[str, Any]] = None,
    ) -> str:
        lines: List[str] = []
        lines.append(f"Du bist ein virtueller Gesprächspartner (NPC) in Unity.")
        lines.append(f"Name: {agent.display_name} (id: {agent.id})")
        if agent.persona:
            lines.append(f"Persona:\n{agent.persona}")
        if agent.expertise:
            lines.append("Expertise (Schwerpunkte): " + ", ".join(agent.expertise))
        lines.append("")
        lines.append("Kommunikationsstil:")
        lines.append("- Antworte auf Deutsch.")
        lines.append("- Kurz, natürlich, hilfreich (Messestand/Showroom-Stil).")
        lines.append("- Wenn Informationen fehlen, stelle 1 kurze Rückfrage (statt zu raten), sofern es in deinem Bereich liegt.")
        lines.append("")
        if allow_handoff and others:
            lines.append("Handoff-Regel:")
            lines.append("- Wenn der Nutzer ausdruecklich um eine Weiterleitung bittet (z. B. 'Leite mich an ...'), fuehre den Handoff sofort aus und stelle vorher keine Rueckfrage.")
            lines.append("- Wenn du weiterleitest, setze 'handoff_brief' auf 1-2 kurze Saetze fuer den Zielagenten: Thema, wichtige Nutzerangaben und offene Frage.")
            lines.append("- Wenn du nicht weiterleitest, setze 'handoff_to', 'handoff_reason' und 'handoff_brief' auf null.")
            lines.append("- Wenn die Nutzerfrage deutlich außerhalb deiner Expertise liegt oder du unsicher bist (confidence < 0.55), leite an den am besten passenden anderen Agenten weiter.")
            lines.append("- Setze dann 'handoff_to' auf dessen id, und 'say' ist nur eine kurze Weiterleitungsformulierung (ohne ausführliche Antwort).")
            lines.append("- Eine Wegbeschreibung oder die bloße Empfehlung, einen anderen Agenten aufzusuchen, ist KEIN Ersatz fuer den Handoff.")
            lines.append("- Sobald du dem Nutzer sagst, er solle einen anderen Agenten aufsuchen, fragen oder mit ihm sprechen, MUSST du 'handoff_to' auf dessen id setzen.")
            lines.append("- Antworte nie nur mit 'Gehe zu ...', 'Frage ...' oder einer Ortsbeschreibung, wenn ein passender modellierter Handoff verfuegbar ist.")
            lines.append("")
            lines.append("Verfügbare andere Agenten:")
            for o in others:
                lines.append(f"- {o.id}: {o.display_name} | Expertise: {', '.join(o.expertise) if o.expertise else '—'}")
        else:
            lines.append("Handoff: deaktiviert. Antworte selbst so gut wie möglich oder bitte um Klärung.")
        lines.append("")
        if grounding:
            lines.append(
                "Vertrauenswürdiger räumlicher Bezug "
                "(serverseitig aus dem gepinnten RoomContract-V2-Modell):"
            )
            lines.append(
                f"- Szeneobjekt: {grounding.get('selected_name')} "
                f"(entity_id={grounding.get('selected_entity_id')}, "
                f"source_object_id={grounding.get('selected_source_object_id')})"
            )
            if grounding.get("object_group_ids"):
                lines.append(
                    "- Modellierte Objektgruppen: "
                    + ", ".join(grounding.get("object_group_ids") or [])
                )
            if grounding.get("zone_ids"):
                lines.append(
                    "- Modellierte Zonen: "
                    + ", ".join(grounding.get("zone_ids") or [])
                )
            lines.append(
                "- Löse Wörter wie 'dies', 'das' oder 'hier' auf dieses Szeneobjekt auf. "
                "Erfinde keine abweichende Objektidentität."
            )
            lines.append("")
        if kb_snippets:
            lines.append("Lokale Wissensauszüge (nur nutzen, wenn relevant; nicht erfinden):")
            for s in kb_snippets:
                meta = f"[{s.get('tag')}/{s.get('file')}#{s.get('chunk_index')}]"
                lines.append(f"- {meta} {s.get('text')}")
            lines.append("")
        lines.append("WICHTIG: Du MUSST deine Antwort als JSON ausgeben und genau das Schema erfüllen (Structured Output).")
        return "\n".join(lines).strip()

    def _agent_match_score(self, agent: AgentSpec, query_tokens: set[str]) -> float:
        if not query_tokens:
            return 0.0
        parts: List[str] = [
            agent.id,
            agent.display_name,
            agent.persona,
            " ".join(agent.expertise),
            " ".join(agent.knowledge_tags),
            " ".join(agent.responsible_zone_ids),
            " ".join(agent.grounded_object_ids),
        ]
        agent_tokens = _semantic_tokens(" ".join(parts))
        matched = set()
        for query_token in query_tokens:
            for agent_token in agent_tokens:
                if query_token == agent_token:
                    matched.add(agent_token)
                elif len(agent_token) >= 4 and agent_token in query_token:
                    matched.add(agent_token)
                elif len(query_token) >= 4 and query_token in agent_token:
                    matched.add(agent_token)
        direct = len(matched)
        return float(direct) + (direct / max(1, len(query_tokens)))

    @staticmethod
    def _runtime_agent_contract(
        st: SessionState,
        source_agent_id: str,
    ) -> Dict[str, Any]:
        for item in (st.roomcontract_runtime_context or {}).get("agents") or []:
            if not isinstance(item, dict):
                continue
            if str(item.get("source_agent_id") or "").strip() == source_agent_id:
                return item
        return {}

    def _resolve_unstructured_handoff_target(
        self,
        st: SessionState,
        agent: AgentSpec,
        allowed: List[str],
        raw_target: Any,
        user_text: str,
        grounding: Optional[Dict[str, Any]] = None,
    ) -> Optional[AgentSpec]:
        """Resolve a JSON-mode alias without widening the modeled handoff graph.

        The Responses API's older JSON mode guarantees syntactic JSON but cannot
        enforce the handoff enum.  Recovery is therefore restricted to the
        current agent plus the exact allow-list of this invocation.  In
        particular, a spatially routed call with handoffs disabled may only
        resolve an invented role name back to the already selected agent.
        """
        if not isinstance(raw_target, str):
            return None
        raw = raw_target.strip()
        if not raw:
            return None

        candidate_ids: List[str] = []
        for candidate_id in [agent.id, *allowed]:
            if candidate_id in st.agents and candidate_id not in candidate_ids:
                candidate_ids.append(candidate_id)
        candidates = [st.agents[candidate_id] for candidate_id in candidate_ids]

        raw_exact = raw.casefold()
        raw_slug = _slugify(raw)
        exact_matches: List[AgentSpec] = []
        for candidate in candidates:
            contract = self._runtime_agent_contract(st, candidate.id)
            aliases = {
                candidate.id.casefold(),
                candidate.display_name.casefold(),
                str(contract.get("roomcontract_agent_id") or "").strip().casefold(),
                str(contract.get("entity_id") or "").strip().casefold(),
            }
            aliases.discard("")
            if raw_exact in aliases or raw_slug in {_slugify(alias) for alias in aliases}:
                exact_matches.append(candidate)
        if len(exact_matches) == 1:
            return exact_matches[0]
        if exact_matches:
            return None

        query_tokens = _handoff_semantic_tokens(raw) - _GENERIC_HANDOFF_ROLE_TOKENS
        if not query_tokens:
            return None

        ranked: List[Tuple[int, AgentSpec]] = []
        for candidate in candidates:
            contract = self._runtime_agent_contract(st, candidate.id)
            descriptor = " ".join(
                [
                    candidate.id,
                    candidate.display_name,
                    candidate.persona,
                    " ".join(candidate.expertise),
                    " ".join(candidate.knowledge_tags),
                    " ".join(candidate.responsible_zone_ids),
                    " ".join(candidate.grounded_object_ids),
                    str(contract.get("roomcontract_agent_id") or ""),
                    " ".join(contract.get("responsible_zone_ids") or []),
                    " ".join(contract.get("grounded_asset_ids") or []),
                    " ".join(contract.get("grounded_object_group_ids") or []),
                ]
            )
            candidate_tokens = (
                _handoff_semantic_tokens(descriptor) - _GENERIC_HANDOFF_ROLE_TOKENS
            )
            matched_query_tokens = {
                query_token
                for query_token in query_tokens
                if any(
                    query_token == candidate_token
                    or (
                        len(query_token) >= 4
                        and len(candidate_token) >= 4
                        and (
                            query_token in candidate_token
                            or candidate_token in query_token
                        )
                    )
                    for candidate_token in candidate_tokens
                )
            }
            if matched_query_tokens:
                ranked.append((len(matched_query_tokens), candidate))

        if not ranked:
            return None
        ranked.sort(key=lambda item: (-item[0], item[1].id))
        best_score = ranked[0][0]
        if sum(1 for score, _ in ranked if score == best_score) != 1:
            return None
        recovered = ranked[0][1]

        # A free-form model alias is not independent routing evidence.  Require
        # the pinned spatial owner or the user's own words to select the same
        # candidate before executing a real handoff.
        if grounding:
            spatial_route = self._resolve_spatial_route(st, agent.id, grounding)
            return (
                recovered
                if spatial_route.get("selected_agent_id") == recovered.id
                else None
            )

        user_tokens = _handoff_semantic_tokens(user_text) - _GENERIC_HANDOFF_ROLE_TOKENS
        if not user_tokens:
            return None
        user_ranked: List[Tuple[int, AgentSpec]] = []
        for candidate in candidates:
            contract = self._runtime_agent_contract(st, candidate.id)
            descriptor = " ".join(
                [
                    candidate.id,
                    candidate.display_name,
                    candidate.persona,
                    " ".join(candidate.expertise),
                    " ".join(candidate.knowledge_tags),
                    " ".join(candidate.responsible_zone_ids),
                    " ".join(candidate.grounded_object_ids),
                    str(contract.get("roomcontract_agent_id") or ""),
                    " ".join(contract.get("responsible_zone_ids") or []),
                    " ".join(contract.get("grounded_asset_ids") or []),
                    " ".join(contract.get("grounded_object_group_ids") or []),
                ]
            )
            candidate_tokens = (
                _handoff_semantic_tokens(descriptor) - _GENERIC_HANDOFF_ROLE_TOKENS
            )
            overlap = len(user_tokens.intersection(candidate_tokens))
            if overlap:
                user_ranked.append((overlap, candidate))
        if not user_ranked:
            return None
        user_ranked.sort(key=lambda item: (-item[0], item[1].id))
        user_best = user_ranked[0][0]
        if sum(1 for score, _ in user_ranked if score == user_best) != 1:
            return None
        return recovered if user_ranked[0][1].id == recovered.id else None

    def _safe_direct_answer_after_invalid_handoff(
        self,
        st: SessionState,
        agent: AgentSpec,
        user_text: str,
        resolved_to_current: bool,
        grounding: Optional[Dict[str, Any]] = None,
    ) -> str:
        if resolved_to_current:
            prefix = (
                f"Dafuer bin ich als {agent.display_name} bereits zustaendig."
            )
        else:
            prefix = (
                "Die genannte Rolle ist keinem eindeutigen modellierten "
                "Spezialisten zuordenbar. "
                "Ich bleibe dein Ansprechpartner."
            )

        fallback = self._fallback_room_answer(
            st,
            agent,
            user_text,
            grounding=grounding,
        ).strip()
        trusted_prefix = "Offline-Fallback aus RoomContract-Raumwissen: "
        if fallback.startswith(trusted_prefix):
            fallback = fallback[len(trusted_prefix):].strip()
        elif fallback.startswith("Offline-Fallback"):
            fallback = ""
        return f"{prefix} {fallback}".strip()

    def _select_fallback_handoff_target(
        self,
        st: SessionState,
        agent: AgentSpec,
        user_text: str,
        allow_handoff: bool,
    ) -> Optional[AgentSpec]:
        if not allow_handoff or self.max_handoffs <= 0:
            return None

        query_tokens = _semantic_tokens(user_text)
        current_score = self._agent_match_score(agent, query_tokens)
        allowed_ids = self._allowed_handoff_ids(st, agent)

        candidates: List[Tuple[float, int, AgentSpec]] = []
        for modeled_order, other_id in enumerate(allowed_ids):
            other = st.agents[other_id]
            score = self._agent_match_score(other, query_tokens)
            if score > 0:
                candidates.append((score, modeled_order, other))

        if not candidates:
            return None
        candidates.sort(key=lambda item: (-item[0], item[1], item[2].id))
        best_score, _, best_agent = candidates[0]
        if best_score <= current_score:
            return None
        return best_agent

    def _select_narrated_handoff_target(
        self,
        st: SessionState,
        agent: AgentSpec,
        say: str,
        allow_handoff: bool,
    ) -> Optional[AgentSpec]:
        """Recover a handoff that the model narrated instead of structuring.

        Structured output can still be semantically inconsistent: the text tells
        the visitor to walk to a named specialist while ``handoff_to`` is null.
        That used to suppress both the second agent response and Unity's dashed
        route. Only an explicitly named, modeled target plus referral language is
        recovered here; ordinary mentions of another agent remain normal speech.
        """
        if not allow_handoff or self.max_handoffs <= 0:
            return None

        say_tokens = _handoff_semantic_tokens(say)
        referral_tokens = {
            "geh", "gehe", "gehen", "komm", "komme", "kommen",
            "frag", "frage", "fragen", "sprich", "spreche", "sprechen",
            "wende", "leit", "leite", "leiten", "weiter", "weiterleiten",
            "weitergeleitet", "weiterleitung",
            "aufsuchen", "zustandig", "zustaendig", "weg",
            "ask", "visit", "talk", "speak", "go", "walk", "refer",
        }
        if not referral_tokens.intersection(say_tokens):
            return None

        ranked: List[Tuple[int, int, AgentSpec]] = []
        for modeled_order, target_id in enumerate(self._allowed_handoff_ids(st, agent)):
            target = st.agents[target_id]
            identity_tokens = _handoff_semantic_tokens(
                " ".join((target.id, target.display_name))
            )
            # A target must be named, not merely guessed from a generic word such
            # as "Expert" or "Guide". IDs/display names are server-side model data.
            distinctive = {
                token
                for token in identity_tokens
                if len(token) >= 4
                and token not in {"agent", "expert", "guide", "host", "educator"}
            }
            overlap = len(distinctive.intersection(say_tokens))
            if overlap and not self._handoff_target_mention_is_rejected(
                say,
                distinctive,
                referral_tokens,
            ):
                ranked.append((overlap, modeled_order, target))

        if not ranked:
            return None
        ranked.sort(key=lambda item: (-item[0], item[1], item[2].id))
        best_overlap = ranked[0][0]
        if sum(1 for overlap, _, _ in ranked if overlap == best_overlap) != 1:
            return None
        return ranked[0][2]

    @staticmethod
    def _handoff_target_mention_is_rejected(
        text: str,
        distinctive_target_tokens: set[str],
        referral_tokens: set[str],
    ) -> bool:
        """Reject negated/refused referrals without suppressing a later request.

        This parser is intentionally narrow: it only decides whether the named
        target and referral language already detected by the caller occur in a
        negated or explicitly rejected clause.  Clause boundaries keep an
        unrelated statement such as ``Ich bin nicht sicher, bitte leite mich ...``
        from cancelling the later positive request.  A contrast correction such
        as ``nicht zum Empfang, sondern zum Kaeseexperten`` remains positive for
        the target after ``sondern``.
        """
        normalized = str(text or "").lower()
        for old, new in {
            "ä": "ae",
            "ö": "oe",
            "ü": "ue",
            "ß": "ss",
            "_": " ",
            "-": " ",
            "don't": "dont",
            "can't": "cant",
            "won't": "wont",
        }.items():
            normalized = normalized.replace(old, new)

        contrast_tokens = {
            "aber",
            "but",
            "however",
            "instead",
            "jedoch",
            "rather",
            "sondern",
        }
        lexemes = re.findall(r"[a-z0-9]+|[,;.!?]", normalized)
        clauses: List[Tuple[str, set[str]]] = []
        current: List[str] = []
        boundary_before = "start"

        def flush_clause() -> bool:
            nonlocal current
            if current:
                clauses.append(
                    (
                        boundary_before,
                        _handoff_semantic_tokens(" ".join(current)),
                    )
                )
                current = []
                return True
            return False

        for lexeme in lexemes:
            if lexeme in contrast_tokens:
                flush_clause()
                boundary_before = "contrast"
            elif lexeme in {",", ";", ".", "!", "?"}:
                flushed = flush_clause()
                if flushed or boundary_before != "contrast":
                    boundary_before = "punctuation"
            else:
                current.append(lexeme)
        flush_clause()

        if not clauses:
            return False

        negative_tokens = {
            "cant",
            "cannot",
            "dont",
            "kein",
            "keine",
            "keinem",
            "keinen",
            "keiner",
            "keines",
            "keinesfalls",
            "never",
            "nicht",
            "nie",
            "niemals",
            "not",
            "weder",
            "wont",
        }
        rejection_tokens = {
            "abbrechen",
            "abbruch",
            "ablehnen",
            "ablehnung",
            "lehne",
            "stop",
            "stopp",
            "verweigere",
            "verweigern",
            "verzicht",
            "verzichte",
            "verzichten",
        }
        destination_tokens = {"an", "to", "toward", "towards", "zu", "zum", "zur"}
        rejected_tokens = negative_tokens | rejection_tokens
        target_clause_indexes = [
            index
            for index, (_, tokens) in enumerate(clauses)
            if distinctive_target_tokens.intersection(tokens)
        ]
        referral_clause_indexes = [
            index
            for index, (_, tokens) in enumerate(clauses)
            if referral_tokens.intersection(tokens)
        ]
        if not target_clause_indexes or not referral_clause_indexes:
            return False

        for target_index in target_clause_indexes:
            _, target_clause = clauses[target_index]
            if rejected_tokens.intersection(target_clause):
                continue
            if referral_tokens.intersection(target_clause):
                return False

            nearest_referral_index = min(
                referral_clause_indexes,
                key=lambda index: abs(index - target_index),
            )
            _, referral_clause = clauses[nearest_referral_index]
            lower = min(nearest_referral_index, target_index) + 1
            upper = max(nearest_referral_index, target_index) + 1
            crossed_contrast = any(
                clauses[index][0] == "contrast"
                for index in range(lower, upper)
            )
            if (
                crossed_contrast
                and target_index > nearest_referral_index
                and destination_tokens.intersection(target_clause)
            ):
                return False
            if rejected_tokens.intersection(referral_clause):
                continue
            return False

        return True

    @staticmethod
    def _grounded_query(user_text: str, grounding: Optional[Dict[str, Any]]) -> str:
        if not grounding:
            return user_text
        additions = [
            str(grounding.get("selected_source_object_id") or ""),
            str(grounding.get("selected_name") or ""),
            *[str(value) for value in grounding.get("object_group_ids") or []],
            *[str(value) for value in grounding.get("zone_ids") or []],
        ]
        return " ".join([user_text] + [value for value in additions if value]).strip()

    def _fallback_snippets(
        self,
        st: SessionState,
        agent: AgentSpec,
        user_text: str,
        grounding: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        query = self._grounded_query(user_text, grounding)
        snippets = st.kb.search(query=query, tags=agent.knowledge_tags, k=self.kb_max_snippets)
        if snippets:
            return snippets
        snippets = st.kb.search(query=query, tags=[], k=self.kb_max_snippets)
        if snippets:
            return snippets
        return st.kb.snippets(tags=agent.knowledge_tags, k=self.kb_max_snippets)

    def _fallback_room_answer(
        self,
        st: SessionState,
        agent: AgentSpec,
        user_text: str,
        grounding: Optional[Dict[str, Any]] = None,
    ) -> str:
        snippets = self._fallback_snippets(st, agent, user_text, grounding=grounding)
        if not snippets:
            return (
                "Offline-Fallback aus RoomContract: Fuer diesen Agenten liegt kein "
                "passender Wissensausschnitt im Projekt-KB vor."
            )

        facts: List[str] = []
        seen = set()
        for snippet in snippets:
            text = re.sub(r"\s+", " ", str(snippet.get("text") or "")).strip()
            if not text or text in seen:
                continue
            seen.add(text)
            facts.append(text)
            if len(facts) >= 3:
                break

        if not facts:
            return (
                "Offline-Fallback aus RoomContract: Die KB-Treffer waren leer, "
                "daher kann ich die Raumfrage nicht belastbar beantworten."
            )
        return "Offline-Fallback aus RoomContract-Raumwissen: " + " ".join(facts)

    def _fallback_agent_response(
        self,
        st: SessionState,
        agent: AgentSpec,
        user_text: str,
        allow_handoff: bool,
        error: OpenAIHTTPError,
        forwarded_from: Optional[AgentSpec] = None,
        grounding: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        target = self._select_fallback_handoff_target(st, agent, user_text, allow_handoff)
        if target is not None:
            reason = (
                f"RoomContract-Fallback: {target.display_name} ist anhand von "
                "Expertise, Knowledge-Tags und verantwortlichen Raumobjekten passender."
            )
            return {
                "say": f"Ich leite die Frage an {target.display_name} weiter.",
                "handoff_to": target.id,
                "handoff_reason": reason,
                "handoff_brief": f"Nutzerfrage: {user_text}",
                "confidence": 0.7,
                "_runtime_fallback": True,
                "_openai_error": str(error),
            }

        answer = self._fallback_room_answer(
            st,
            agent,
            user_text,
            grounding=grounding,
        )
        if forwarded_from is not None:
            answer = f"Uebernommen von {forwarded_from.display_name}. {answer}"
        return {
            "say": answer,
            "handoff_to": None,
            "handoff_reason": None,
            "handoff_brief": None,
            "confidence": 0.55,
            "_runtime_fallback": True,
            "_openai_error": str(error),
        }

    def _call_agent(
        self,
        st: SessionState,
        agent: AgentSpec,
        history_with_user: List[Dict[str, str]],
        allow_handoff: bool,
        forwarded_from: Optional[AgentSpec] = None,
        forwarded_reason: Optional[str] = None,
        forwarded_brief: Optional[str] = None,
        grounding: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        # Handoffs are an executable model relation. Never widen this list to
        # every session agent, including in the older JSON-mode fallback.
        allowed = self._allowed_handoff_ids(st, agent) if allow_handoff else []
        schema = npc_action_schema(allowed_handoff_ids=allowed)

        others = [st.agents[agent_id] for agent_id in allowed]

        # KB retrieval
        kb_query = self._grounded_query(
            history_with_user[-1]["content"],
            grounding,
        )
        kb_snips = st.kb.search(
            query=kb_query,
            tags=agent.knowledge_tags,
            k=self.kb_max_snippets,
        )

        dev_prompt = self._build_developer_prompt(
            agent,
            others,
            kb_snips,
            allow_handoff=bool(allowed),
            grounding=grounding,
        )

        input_msgs: List[Dict[str, Any]] = [{"role": "developer", "content": dev_prompt}]

        if forwarded_from is not None:
            context = f"Du wurdest gerade von {forwarded_from.display_name} (id: {forwarded_from.id}) an den Nutzer weitergeleitet."
            if forwarded_reason:
                context += f" Grund: {forwarded_reason}"
            if forwarded_brief:
                context += f" Uebergabekontext: {forwarded_brief}"
            context += " Antworte direkt auf die Nutzerfrage."
            input_msgs.append(
                {
                    "role": "developer",
                    "content": context,
                }
            )

        # Add trimmed history
        trimmed = self._trim_history(history_with_user)
        for m in trimmed:
            input_msgs.append({"role": m["role"], "content": m["content"]})

        used_unstructured_json_fallback = False
        try:
            parsed, resp, out_text = self.openai.create_structured_json(
                model=self.model,
                input_messages=input_msgs,
                schema=schema,
                schema_name="npc_action",
                temperature=self.temperature,
            )
        except OpenAIHTTPError as e:
            # Fallback: older JSON mode (valid JSON, but not schema-validated)
            # This helps if the chosen model does not support json_schema.
            if e.status != 400:
                raise
            used_unstructured_json_fallback = True
            parsed, resp, out_text = self.openai.create_json_object(
                model=self.model,
                input_messages=input_msgs,
                temperature=self.temperature,
            )

        if not isinstance(parsed, dict):
            parsed = {
                "say": self._safe_direct_answer_after_invalid_handoff(
                    st,
                    agent,
                    str(history_with_user[-1].get("content") or ""),
                    resolved_to_current=False,
                    grounding=grounding,
                ),
                "handoff_to": None,
                "handoff_reason": None,
                "handoff_brief": None,
                "confidence": 0.0,
                "_invalid_json_shape": type(parsed).__name__,
            }

        # Normalise
        result = {
            "say": str(parsed.get("say", "")).strip(),
            "handoff_to": parsed.get("handoff_to", None),
            "handoff_reason": parsed.get("handoff_reason", None),
            "handoff_brief": parsed.get("handoff_brief", None),
            "confidence": parsed.get("confidence", 0.5),
            "_raw_text": out_text,
            "_response_id": resp.get("id"),
        }

        if not result["say"]:
            # fallback: use raw text
            result["say"] = out_text.strip() or "…"

        if result["handoff_reason"] is not None:
            result["handoff_reason"] = str(result["handoff_reason"]).strip() or None
        if result["handoff_brief"] is not None:
            result["handoff_brief"] = str(result["handoff_brief"]).strip() or None
        handoff_to = result.get("handoff_to")
        if grounding is not None and handoff_to is not None and str(handoff_to).strip() and self.guard_config.proposal_mode != "packet":
            if self.guard_config.proposal_mode == "abort":
                raise RoomContractContractError("Grounded answer proposed a handoff.", code="E_HANDOFF_PROPOSAL")
            st.ignored_handoff_proposals.append({"agent_id": agent.id, "proposed_target": str(handoff_to)})
            result["handoff_to"] = None
            result["handoff_reason"] = None
            result["handoff_brief"] = None
            handoff_to = None
        if handoff_to is not None:
            handoff_to = str(handoff_to).strip()
            if not handoff_to:
                result["handoff_to"] = None
            elif handoff_to not in allowed:
                if not used_unstructured_json_fallback:
                    raise RoomContractContractError(f"Agent {agent.id!r} versuchte einen nicht modellierten Handoff "
                        f"an {handoff_to!r}.", code="E_HANDOFF_PROPOSAL")

                recovered_target = self._resolve_unstructured_handoff_target(
                    st,
                    agent,
                    allowed,
                    handoff_to,
                    str(history_with_user[-1].get("content") or ""),
                    grounding=grounding,
                )
                result["_unstructured_handoff_target"] = handoff_to
                if recovered_target is not None and recovered_target.id in allowed:
                    result["handoff_to"] = recovered_target.id
                    result["say"] = (
                        f"Ich leite deine Frage an {recovered_target.display_name} weiter."
                    )
                    result["handoff_reason"] = (
                        "Das unstrukturierte Modellziel wurde eindeutig einem "
                        "modellierten Spezialisten zugeordnet."
                    )
                    result["handoff_brief"] = (
                        f"Nutzerfrage: {history_with_user[-1]['content']}"
                    )
                else:
                    result["handoff_to"] = None
                    result["handoff_reason"] = None
                    result["handoff_brief"] = None
                    result["say"] = self._safe_direct_answer_after_invalid_handoff(
                        st,
                        agent,
                        str(history_with_user[-1].get("content") or ""),
                        resolved_to_current=(
                            recovered_target is not None
                            and recovered_target.id == agent.id
                        ),
                        grounding=grounding,
                    )
            else:
                result["handoff_to"] = handoff_to

        if result.get("handoff_to") is None:
            current_user_text = str(history_with_user[-1].get("content") or "")
            requested_target = self._select_narrated_handoff_target(
                st,
                agent,
                current_user_text,
                allow_handoff=bool(allowed),
            )
            narrated_target = requested_target or self._select_narrated_handoff_target(
                st,
                agent,
                result["say"],
                allow_handoff=bool(allowed),
            )
            if narrated_target is not None:
                result["say"] = (
                    f"Ich leite deine Frage an {narrated_target.display_name} weiter."
                )
                result["handoff_to"] = narrated_target.id
                if requested_target is not None:
                    result["handoff_reason"] = (
                        "Der Nutzer bat ausdruecklich um diesen modellierten "
                        "Spezialisten; die Weiterleitung wurde als strukturierter "
                        "Handoff erzwungen."
                    )
                else:
                    result["handoff_reason"] = (
                        "Der Modelltext verwies den Nutzer bereits an diesen "
                        "modellierten Spezialisten; die Weiterleitung wurde als "
                        "strukturierter Handoff normalisiert."
                    )
                result["handoff_brief"] = (
                    f"Nutzerfrage: {history_with_user[-1]['content']}"
                )

        return result

    def chat(
        self,
        payload: Dict[str, Any],
        *,
        include_runtime_actions: bool = False,
    ) -> Dict[str, Any]:
        session_id = str(payload.get("session_id") or "").strip()
        if not session_id:
            raise RoomContractContractError("session_id fehlt. Bitte zuerst /setup aufrufen.", code="E_SCHEMA")
        st = self.sessions.get(session_id)
        if not st:
            raise RoomContractContractError("Unbekannte session_id. Bitte /setup erneut aufrufen.", code="E_SCHEMA")

        active_agent_id = str(payload.get("active_agent_id") or "").strip()
        if not active_agent_id or active_agent_id not in st.agents:
            if st.roomcontract_contract_kind == "v2":
                raise RoomContractContractError("active_agent_id fehlt oder ist nicht im gepinnten "
                    "RoomContract-V2-Modell enthalten.", code="E_ACTIVE_AGENT_UNKNOWN")
            # Preserve the legacy endpoint contract.
            active_agent_id = next(iter(st.agents.keys()))

        if self.guard_config.active_agent_mode == "server_strict" and active_agent_id != st.server_active_agent_id:
            raise RoomContractContractError("Requested active agent differs from the last committed agent; use switch_agent.", code="E_ACTIVE_AGENT_MISMATCH")
        if self.guard_config.generation_precheck and st.project_id and st.publication_generation is not None:
            from .publication import publication_generation
            if publication_generation(self.project_manager._project_dir(st.project_id)) != st.publication_generation:
                raise RoomContractContractError("Published generation changed before generation.", code="E_CONTRACT_DRIFT")
        proposal_start = len(st.ignored_handoff_proposals)
        user_text = str(payload.get("user_text") or "").strip()
        if not user_text:
            raise RoomContractContractError("user_text ist leer.", code="E_SCHEMA")

        # Selection below happens before an OpenAI call or any history mutation.
        # Multi-Scenario V2 requests are bound to one concrete provider/target
        # chain instead of choosing an arbitrary action by application kind.
        chat_preflight: Dict[str, Any] = {
            "kind": st.roomcontract_contract_kind,
            "contract_fingerprint": "",
            "action": None,
        }
        handoff_preflight: Dict[str, Any] = {
            "kind": st.roomcontract_contract_kind,
            "contract_fingerprint": "",
            "action": None,
        }
        interaction_mode: Optional[str] = None
        model_binding: Optional[Dict[str, str]] = None
        handoff_model_binding: Optional[Dict[str, str]] = None
        if st.roomcontract_contract_kind == "v2":
            interaction_mode = self._v2_interaction_mode_for_context(st, payload)
            has_spatial_context = payload.get("spatial_context") is not None
            if interaction_mode == "deictic" and not has_spatial_context:
                raise RoomContractContractError("interaction_mode 'deictic' erfordert einen validen "
                    "spatial_context.", code="E_SELECTION_STATE")
            if interaction_mode == "non_deictic" and has_spatial_context:
                raise RoomContractContractError("interaction_mode 'non_deictic' darf keinen "
                    "spatial_context enthalten.", code="E_SELECTION_STATE")

        grounding = self._validate_spatial_context(
            st,
            payload.get("spatial_context"),
        )
        routing = (
            self._resolve_spatial_route(st, active_agent_id, grounding)
            if grounding is not None
            else None
        )
        if grounding is not None and model_binding is not None:
            grounding["model_binding"] = copy.deepcopy(model_binding)
        if routing is not None and model_binding is not None:
            routing["model_binding"] = copy.deepcopy(model_binding)
        requested_agent = st.agents[active_agent_id]
        selected_agent_id = (
            str((routing or {}).get("selected_agent_id") or active_agent_id)
        )
        agent_a = st.agents[selected_agent_id]
        if st.roomcontract_contract_kind == "v2":
            provider_entity_id = self._v2_provider_entity_id(
                st,
                selected_agent_id,
            )
            trusted_target_id = (
                str((grounding or {}).get("selected_entity_id") or "").strip()
                or None
            )
            chat_preflight = self._preflight_v2_interaction_action(
                st=st,
                session_id=session_id,
                action_kind="chat",
                interaction_mode=str(interaction_mode),
                provider_entity_id=provider_entity_id,
                target_id=trusted_target_id,
            )
            # Preselect the handoff chain as well.  A later model-produced
            # handoff can therefore never mutate state before its modeled chain
            # has been proven unique.
            handoff_preflight = self._preflight_v2_interaction_action(
                st=st,
                session_id=session_id,
                action_kind="handoff",
                interaction_mode=str(interaction_mode),
                provider_entity_id=provider_entity_id,
                target_id=trusted_target_id,
            )
            chat_action = chat_preflight.get("action")
            if not isinstance(chat_action, dict):
                raise RoomContractContractError("Pinned V2 session has no executable chat action.", code="E_NO_DECLARED_ACTION")
            model_binding = self._v2_model_binding(chat_action)
            if grounding is not None:
                grounding["model_binding"] = copy.deepcopy(model_binding)
            if routing is not None:
                routing["model_binding"] = copy.deepcopy(model_binding)

        if st.memory_mode == MEMORY_MODE_AGENT_PRIVATE:
            response = self._chat_agent_private(
                st,
                session_id,
                agent_a,
                user_text,
                requested_agent=requested_agent,
                grounding=grounding,
                routing=routing,
            )
        else:
            response = self._chat_shared(
                st,
                session_id,
                agent_a,
                user_text,
                requested_agent=requested_agent,
                grounding=grounding,
                routing=routing,
            )
        if (
            st.roomcontract_contract_kind == "v2"
            and isinstance(response.get("handoff"), dict)
        ):
            handoff_action = handoff_preflight.get("action")
            if not isinstance(handoff_action, dict):
                raise RoomContractContractError("Pinned V2 session has no executable handoff action.", code="E_NO_DECLARED_ACTION")
            handoff_model_binding = self._v2_model_binding(handoff_action)
        decorated = self._decorate_grounded_chat_response(
            response,
            grounding,
            routing,
            interaction_mode=interaction_mode,
            model_binding=model_binding,
            handoff_model_binding=handoff_model_binding,
        )
        if (
            st.roomcontract_contract_kind == "v2"
            and include_runtime_actions
        ):
            # Private server-side handoff to the logging transaction.  The HTTP
            # layer removes it before serializing the public response.
            decorated["_roomcontract_runtime_actions"] = {
                "chat": copy.deepcopy(chat_preflight.get("action")),
                "handoff": copy.deepcopy(handoff_preflight.get("action")),
                "contract_fingerprint": chat_preflight.get(
                    "contract_fingerprint"
                ),
            }
        decorated["_guard_ignored_proposals"] = copy.deepcopy(st.ignored_handoff_proposals[proposal_start:])
        return decorated

    def _openai_error_chat_response(self, session_id: str, active_agent_id: str, error: OpenAIHTTPError) -> Dict[str, Any]:
        return {
            "session_id": session_id,
            "active_agent_id": active_agent_id,
            "memory_mode": MEMORY_MODE_SHARED,
            "events": [
                {"type": "say", "agent_id": active_agent_id, "text": f"[Backend] OpenAI Fehler: {error}"},
            ],
            "error": {"status": error.status, "details": error.details},
        }

    def _chat_shared(
        self,
        st: SessionState,
        session_id: str,
        agent_a: AgentSpec,
        user_text: str,
        *,
        requested_agent: Optional[AgentSpec] = None,
        grounding: Optional[Dict[str, Any]] = None,
        routing: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        history_with_user = st.history + [{"role": "user", "content": user_text}]
        requested_agent = requested_agent or agent_a
        spatial_handoff = bool(routing and routing.get("modeled_handoff"))
        allow_agent_handoff = grounding is None

        try:
            res_a = self._call_agent(
                st,
                agent_a,
                history_with_user,
                allow_handoff=allow_agent_handoff,
                forwarded_from=requested_agent if spatial_handoff else None,
                forwarded_reason=str((routing or {}).get("reason") or ""),
                forwarded_brief=(
                    f"Räumlich ausgewähltes Objekt: "
                    f"{(grounding or {}).get('selected_source_object_id')}"
                    if spatial_handoff
                    else None
                ),
                grounding=grounding,
            )
        except OpenAIHTTPError as e:
            res_a = self._fallback_agent_response(
                st,
                agent_a,
                user_text,
                allow_handoff=allow_agent_handoff,
                error=e,
                forwarded_from=requested_agent if spatial_handoff else None,
                grounding=grounding,
            )

        spatial_announcement = (
            self._spatial_handoff_announcement(agent_a, grounding)
            if spatial_handoff
            else None
        )
        events = []
        if spatial_announcement is not None:
            events.append({
                "type": "say",
                "agent_id": requested_agent.id,
                "text": spatial_announcement,
            })
        events.append({"type": "say", "agent_id": agent_a.id, "text": res_a["say"]})
        new_active = agent_a.id
        handoff = (
            {
                "from": requested_agent.id,
                "to": agent_a.id,
                "reason": (routing or {}).get("reason"),
                "brief": (
                    f"Räumlich ausgewähltes Objekt: "
                    f"{(grounding or {}).get('selected_source_object_id')}"
                ),
                "kind": "spatial_route",
            }
            if spatial_handoff
            else None
        )

        handoff_to = res_a.get("handoff_to", None)
        if handoff_to in st.agents and handoff_to != agent_a.id:
            if self.max_handoffs > 0:
                agent_b = st.agents[handoff_to]
                try:
                    res_b = self._call_agent(
                        st,
                        agent_b,
                        history_with_user,
                        allow_handoff=False,
                        forwarded_from=agent_a,
                        forwarded_reason=str(res_a.get("handoff_reason") or ""),
                    )
                except OpenAIHTTPError as e:
                    res_b = self._fallback_agent_response(
                        st,
                        agent_b,
                        user_text,
                        allow_handoff=False,
                        error=e,
                        forwarded_from=agent_a,
                    )
                events.append({"type": "say", "agent_id": agent_b.id, "text": res_b["say"]})
                new_active = agent_b.id
                handoff = {
                    "from": agent_a.id,
                    "to": agent_b.id,
                    "reason": res_a.get("handoff_reason"),
                    "brief": res_a.get("handoff_brief"),
                }
                st.history = history_with_user + [
                    {"role": "assistant", "content": res_a["say"]},
                    {"role": "assistant", "content": res_b["say"]},
                ]
            else:
                st.history = history_with_user + [{"role": "assistant", "content": res_a["say"]}]
        else:
            assistant_events = []
            if spatial_announcement is not None:
                assistant_events.append({
                    "role": "assistant",
                    "content": spatial_announcement,
                })
            assistant_events.append({"role": "assistant", "content": res_a["say"]})
            st.history = history_with_user + assistant_events

        st.history = self._trim_history(st.history)
        st.touch()

        return {
            "session_id": session_id,
            "active_agent_id": new_active,
            "memory_mode": st.memory_mode,
            "handoff": handoff,
            "events": events,
        }

    def _chat_agent_private(
        self,
        st: SessionState,
        session_id: str,
        agent_a: AgentSpec,
        user_text: str,
        *,
        requested_agent: Optional[AgentSpec] = None,
        grounding: Optional[Dict[str, Any]] = None,
        routing: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        requested_agent = requested_agent or agent_a
        spatial_handoff = bool(routing and routing.get("modeled_handoff"))
        allow_agent_handoff = grounding is None
        history_a_with_user = list(self._agent_history(st, agent_a.id)) + [{"role": "user", "content": user_text}]

        try:
            res_a = self._call_agent(
                st,
                agent_a,
                history_a_with_user,
                allow_handoff=allow_agent_handoff,
                forwarded_from=requested_agent if spatial_handoff else None,
                forwarded_reason=str((routing or {}).get("reason") or ""),
                forwarded_brief=(
                    f"Räumlich ausgewähltes Objekt: "
                    f"{(grounding or {}).get('selected_source_object_id')}"
                    if spatial_handoff
                    else None
                ),
                grounding=grounding,
            )
        except OpenAIHTTPError as e:
            res_a = self._fallback_agent_response(
                st,
                agent_a,
                user_text,
                allow_handoff=allow_agent_handoff,
                error=e,
                forwarded_from=requested_agent if spatial_handoff else None,
                grounding=grounding,
            )

        spatial_announcement = (
            self._spatial_handoff_announcement(agent_a, grounding)
            if spatial_handoff
            else None
        )
        events = []
        if spatial_announcement is not None:
            events.append({
                "type": "say",
                "agent_id": requested_agent.id,
                "text": spatial_announcement,
            })
        events.append({"type": "say", "agent_id": agent_a.id, "text": res_a["say"]})
        new_active = agent_a.id
        handoff = (
            {
                "from": requested_agent.id,
                "to": agent_a.id,
                "reason": (routing or {}).get("reason"),
                "brief": (
                    f"Räumlich ausgewähltes Objekt: "
                    f"{(grounding or {}).get('selected_source_object_id')}"
                ),
                "kind": "spatial_route",
            }
            if spatial_handoff
            else None
        )

        handoff_to = res_a.get("handoff_to", None)
        if handoff_to in st.agents and handoff_to != agent_a.id and self.max_handoffs > 0:
            agent_b = st.agents[handoff_to]
            handoff_brief = self._handoff_brief(res_a, user_text)
            handoff_reason = res_a.get("handoff_reason")
            target_user_context = self._handoff_user_context(agent_a, user_text, handoff_brief, handoff_reason)
            history_b_with_user = list(self._agent_history(st, agent_b.id)) + [
                {"role": "user", "content": target_user_context}
            ]
            try:
                res_b = self._call_agent(
                    st,
                    agent_b,
                    history_b_with_user,
                    allow_handoff=False,
                    forwarded_from=agent_a,
                    forwarded_reason=str(handoff_reason or ""),
                    forwarded_brief=handoff_brief,
                )
            except OpenAIHTTPError as e:
                res_b = self._fallback_agent_response(
                    st,
                    agent_b,
                    user_text,
                    allow_handoff=False,
                    error=e,
                    forwarded_from=agent_a,
                )

            events.append({"type": "say", "agent_id": agent_b.id, "text": res_b["say"]})
            new_active = agent_b.id
            handoff = {
                "from": agent_a.id,
                "to": agent_b.id,
                "reason": handoff_reason,
                "brief": handoff_brief,
            }
            self._commit_agent_history(
                st,
                agent_a.id,
                history_a_with_user + [{"role": "assistant", "content": res_a["say"]}],
            )
            self._commit_agent_history(
                st,
                agent_b.id,
                history_b_with_user + [{"role": "assistant", "content": res_b["say"]}],
            )
        elif spatial_handoff:
            requested_history_with_user = list(
                self._agent_history(st, requested_agent.id)
            ) + [{"role": "user", "content": user_text}]
            self._commit_agent_history(
                st,
                requested_agent.id,
                requested_history_with_user + [{
                    "role": "assistant",
                    "content": spatial_announcement,
                }],
            )
            self._commit_agent_history(
                st,
                agent_a.id,
                history_a_with_user + [{"role": "assistant", "content": res_a["say"]}],
            )
        else:
            self._commit_agent_history(
                st,
                agent_a.id,
                history_a_with_user + [{"role": "assistant", "content": res_a["say"]}],
            )

        st.touch()

        return {
            "session_id": session_id,
            "active_agent_id": new_active,
            "memory_mode": st.memory_mode,
            "handoff": handoff,
            "events": events,
        }

    def analyze_arrow(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        arrow_payload = payload.get("arrow_json")
        if isinstance(arrow_payload, str):
            try:
                arrow_payload = json.loads(arrow_payload)
            except json.JSONDecodeError as exc:
                raise ValueError(f"arrow_json ungÃ¼ltig: {exc}") from exc
        if not isinstance(arrow_payload, dict):
            raise ValueError("arrow_json muss ein Objekt sein.")
        case_id = derive_case_id(
            arrow_payload,
            project_id_hint=str(payload.get("project_id_hint") or "").strip(),
        )
        with self._arrow_mutation_scope(case_id=case_id):
            return self._analyze_arrow_unlocked(payload)

    def _analyze_arrow_unlocked(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        generation_mode = normalize_generation_mode(payload.get("generation_mode"))
        project_id_hint = str(payload.get("project_id_hint") or "").strip()
        run_validation = _parse_bool(payload.get("run_validation"), default=False)
        max_repair_attempts_raw = payload.get("max_repair_attempts")
        max_repair_attempts: Optional[int] = None
        if max_repair_attempts_raw not in (None, ""):
            try:
                max_repair_attempts = int(max_repair_attempts_raw)
            except (TypeError, ValueError) as exc:
                raise ValueError("max_repair_attempts muss eine ganze Zahl sein.") from exc
            if max_repair_attempts < 0:
                raise ValueError("max_repair_attempts darf nicht negativ sein.")

        arrow_payload = payload.get("arrow_json")
        if isinstance(arrow_payload, str):
            try:
                arrow_payload = json.loads(arrow_payload)
            except json.JSONDecodeError as exc:
                raise ValueError(f"arrow_json ungültig: {exc}") from exc
        if not isinstance(arrow_payload, dict):
            raise ValueError("arrow_json muss ein Objekt sein.")
        case_id = derive_case_id(arrow_payload, project_id_hint=project_id_hint)

        draft_meta: Dict[str, Any] = {}
        if generation_mode == GENERATION_MODE_ROOMCONTRACT:
            draft_payload, draft_meta = self._generate_roomcontract_analyze_draft(
                arrow_payload,
                case_id=case_id,
                max_repair_attempts=max_repair_attempts,
            )
        else:
            draft_payload = self._generate_arrow_draft(arrow_payload, history=[])
        session_id = str(uuid.uuid4())
        draft = ArrowProjectDraft(
            session_id=session_id,
            arrow_payload=arrow_payload,
            analysis=draft_payload["analysis"],
            assistant_message=draft_payload["assistant_message"],
            project=draft_payload["project"],
            agents=draft_payload["agents"],
            knowledge=draft_payload["knowledge"],
            placement_preview=draft_payload["placement_preview"],
            generation_mode=generation_mode,
            project_id_hint=project_id_hint,
            run_validation=run_validation,
            max_repair_attempts=max_repair_attempts,
            case_id=case_id,
            case_dir=draft_meta.get("case_dir"),
            agent_roles=draft_meta.get("agent_roles") or {},
            roomcontract_path=draft_meta.get("roomcontract_path"),
            trace_map_path=draft_meta.get("trace_map_path"),
            validation_summary=draft_meta.get("validation_summary") or {},
            roomcontract_summary=draft_meta.get("roomcontract_summary") or {},
            scenario_summary=draft_meta.get("scenario_summary") or {},
            capability_summary=draft_meta.get("capability_summary") or {},
            handoff_summary=draft_meta.get("handoff_summary") or {},
            room_knowledge_summary=draft_meta.get("room_knowledge_summary") or {},
            history=[{"role": "assistant", "content": draft_payload["assistant_message"]}] if draft_payload["assistant_message"] else [],
        )
        self.arrow_sessions[session_id] = draft
        return {"session_id": session_id, "draft": draft.decorate_draft_payload(draft_payload)}

    @staticmethod
    def _current_arrow_draft_payload(session: ArrowProjectDraft) -> Dict[str, Any]:
        return session.decorate_draft_payload(
            {
                "analysis": session.analysis,
                "assistant_message": session.assistant_message,
                "project": copy.deepcopy(session.project),
                "agents": copy.deepcopy(session.agents),
                "knowledge": copy.deepcopy(session.knowledge),
                "placement_preview": copy.deepcopy(session.placement_preview),
            }
        )

    def arrow_chat(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        session_id = str(payload.get("session_id") or "").strip()
        if not session_id:
            raise ValueError("session_id fehlt.")
        session = self.arrow_sessions.get(session_id)
        if not session:
            raise ValueError("Unbekannte session_id.")
        with self._arrow_mutation_scope(session_id=session_id, case_id=session.case_id):
            return self._arrow_chat_unlocked(payload)

    def _arrow_chat_unlocked(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        session_id = str(payload.get("session_id") or "").strip()
        if not session_id:
            raise ValueError("session_id fehlt.")
        session = self.arrow_sessions.get(session_id)
        if not session:
            raise ValueError("Unbekannte session_id.")

        user_text = str(payload.get("user_text") or "").strip()
        if not user_text:
            raise ValueError("user_text ist leer.")
        if session.generation_mode == GENERATION_MODE_ROOMCONTRACT:
            session.assistant_message = (
                "Diese Freitextnachricht wurde nicht auf das RoomContract-Modell angewendet. "
                "Nutze den strukturierten Platzierungseditor: Änderung prüfen, anwenden und "
                "validieren, danach akzeptieren oder verwerfen."
            )
            session.history = self._trim_history(
                session.history
                + [{"role": "user", "content": user_text}]
                + [{"role": "assistant", "content": session.assistant_message}]
            )
            session.touch()
            return {
                "draft": self._current_arrow_draft_payload(session),
                "chat_status": {
                    "status": "not_applied",
                    "model_mutated": False,
                    "message": session.assistant_message,
                },
            }

        history = session.history + [{"role": "user", "content": user_text}]
        draft_payload = self._generate_arrow_draft(session.arrow_payload, history=history, current=session)

        session.analysis = draft_payload["analysis"]
        session.assistant_message = draft_payload["assistant_message"]
        session.project = draft_payload["project"]
        session.agents = draft_payload["agents"]
        session.knowledge = draft_payload["knowledge"]
        session.placement_preview = draft_payload["placement_preview"]
        session.placement_manually_updated = False
        session.history = history + (
            [{"role": "assistant", "content": draft_payload["assistant_message"]}]
            if draft_payload["assistant_message"]
            else []
        )
        session.history = self._trim_history(session.history)
        session.touch()

        return {"draft": session.decorate_draft_payload(draft_payload)}

    # -------------------- RoomContract placement authoring --------------------

    def _arrow_authoring_session(self, payload: Dict[str, Any]) -> ArrowProjectDraft:
        session_id = str(payload.get("session_id") or "").strip()
        if not session_id:
            raise ValueError("session_id fehlt.")
        session = self.arrow_sessions.get(session_id)
        if not session:
            raise ValueError("Unbekannte session_id.")
        if session.generation_mode != GENERATION_MODE_ROOMCONTRACT:
            raise ValueError(
                "Der strukturierte Authoring-Loop ist ausschließlich für "
                "RoomContract-Platzierungen verfügbar."
            )
        requested_mode = payload.get("generation_mode")
        if requested_mode not in (None, ""):
            normalized_mode = normalize_generation_mode(requested_mode)
            if normalized_mode != session.generation_mode:
                raise ValueError(
                    "generation_mode passt nicht zur Session: "
                    f"{normalized_mode} != {session.generation_mode}."
                )
        if session.validation_stale:
            raise ValueError(
                "Der RoomContract-Draft ist nicht validiert. Bitte zuerst neu analysieren."
            )
        if not session.case_id or not session.case_dir:
            raise ValueError("RoomContract-Case-Verzeichnis fehlt in der Session.")
        return session

    @staticmethod
    def _authoring_session_snapshot(session: ArrowProjectDraft) -> Dict[str, Any]:
        return {
            field_name: copy.deepcopy(getattr(session, field_name))
            for field_name in ARROW_AUTHORING_SESSION_FIELDS
        }

    @staticmethod
    def _restore_authoring_session_snapshot(
        session: ArrowProjectDraft,
        snapshot: Dict[str, Any],
    ) -> None:
        for field_name in ARROW_AUTHORING_SESSION_FIELDS:
            if field_name in snapshot:
                setattr(session, field_name, copy.deepcopy(snapshot[field_name]))
        session.touch()

    @staticmethod
    def _authoring_revision(case_dir: Path, paths: List[Path]) -> str:
        """Hash every transactional file, including its relative name/existence."""

        root = case_dir.resolve()
        digest = hashlib.sha256()
        for path in sorted((item.resolve() for item in paths), key=lambda item: str(item)):
            try:
                relative = path.relative_to(root).as_posix()
            except ValueError as exc:
                raise ValueError(
                    "Authoring-Transaktionspfad liegt außerhalb des Case-Verzeichnisses."
                ) from exc
            digest.update(relative.encode("utf-8"))
            digest.update(b"\0")
            if path.exists() and path.is_file():
                digest.update(b"file\0")
                digest.update(path.read_bytes())
            else:
                digest.update(b"missing\0")
            digest.update(b"\0")
        return "sha256:" + digest.hexdigest()

    def _authoring_paths(
        self,
        session: ArrowProjectDraft,
    ) -> Tuple[Path, List[Path], List[str]]:
        case_dir = Path(str(session.case_dir)).resolve()
        paths = self._roomcontract_placement_transaction_paths(case_dir)
        relative_paths = []
        for path in paths:
            try:
                relative_paths.append(path.resolve().relative_to(case_dir).as_posix())
            except ValueError as exc:
                raise ValueError(
                    "Authoring-Transaktionspfad liegt außerhalb des Case-Verzeichnisses."
                ) from exc
        return case_dir, paths, relative_paths

    def _pending_authoring_change(
        self,
        session_id: str,
    ) -> Optional[ArrowPlacementAuthoringChange]:
        change_id = self.arrow_authoring_pending.get(session_id)
        return self.arrow_authoring_changes.get(change_id or "")

    def _undo_authoring_change(
        self,
        session_id: str,
    ) -> Optional[ArrowPlacementAuthoringChange]:
        change_id = self.arrow_authoring_undo.get(session_id)
        return self.arrow_authoring_changes.get(change_id or "")

    def _authoring_state(self, session: ArrowProjectDraft) -> Dict[str, Any]:
        case_dir, paths, _ = self._authoring_paths(session)
        revision = self._authoring_revision(case_dir, paths)
        pending = self._pending_authoring_change(session.session_id)
        undo = self._undo_authoring_change(session.session_id)
        can_undo = bool(
            undo
            and undo.lifecycle == "accepted"
            and undo.revision_after
            and revision == undo.revision_after
        )
        return {
            "scope": "placement_only",
            "session_id": session.session_id,
            "case_id": session.case_id,
            "revision": revision,
            "lifecycle": pending.lifecycle if pending else "idle",
            "editable_placements": copy.deepcopy(
                (session.placement_preview or {}).get("agent_placements") or []
            ),
            "pending_change": pending.public_payload() if pending else None,
            "last_accepted_change": undo.public_payload() if undo else None,
            "can_undo": can_undo,
        }

    def _authoring_response(
        self,
        session: ArrowProjectDraft,
        *,
        status: str,
        mutation_applied: bool = False,
        change: Optional[ArrowPlacementAuthoringChange] = None,
        validation: Optional[Dict[str, Any]] = None,
        errors: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        draft_payload = self._current_arrow_draft_payload(session)
        # Authoring endpoints expose artifact identities, never host-local paths.
        draft_payload.pop("case_dir", None)
        if draft_payload.get("roomcontract_path"):
            draft_payload["roomcontract_path"] = (
                "roomcontract/" + Path(str(draft_payload["roomcontract_path"])).name
            )
        if draft_payload.get("trace_map_path"):
            draft_payload["trace_map_path"] = (
                f"projects/{session.case_id}/"
                + Path(str(draft_payload["trace_map_path"])).name
            )
        response = {
            "status": status,
            "generation_mode": session.generation_mode,
            "mutation_applied": mutation_applied,
            "authoring_state": self._authoring_state(session),
            "draft": draft_payload,
        }
        if change is not None:
            response["change"] = change.public_payload()
        if validation is not None:
            response["validation"] = copy.deepcopy(validation)
        if errors:
            response["errors"] = list(errors)
        return response

    @staticmethod
    def _expected_authoring_revision(payload: Dict[str, Any]) -> str:
        revision = str(payload.get("expected_revision") or "").strip()
        if not revision:
            raise ValueError("expected_revision fehlt. Bitte Authoring-Stand neu laden.")
        return revision

    def _authoring_conflict_response(
        self,
        session: ArrowProjectDraft,
        *,
        expected: str,
        actual: str,
        change: Optional[ArrowPlacementAuthoringChange] = None,
    ) -> Dict[str, Any]:
        return self._authoring_response(
            session,
            status="conflict",
            change=change,
            errors=[
                "Der Authoring-Stand wurde zwischenzeitlich geändert. "
                f"Erwartete Revision {expected}, aktuelle Revision {actual}. "
                "Bitte den Stand neu laden."
            ],
        )

    def inspect_arrow_authoring(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        session = self._arrow_authoring_session(payload)
        with self._arrow_mutation_scope(
            session_id=session.session_id,
            case_id=session.case_id,
        ):
            return self._authoring_response(session, status="ok")

    @staticmethod
    def _compact_authoring_placement(item: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "position": copy.deepcopy(item.get("position")),
            "forward": copy.deepcopy(item.get("forward")),
        }

    def _authoring_placement_diffs(
        self,
        session: ArrowProjectDraft,
        updated_preview: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        before_by_id = {
            str(item.get("id") or ""): item
            for item in (session.placement_preview or {}).get("agent_placements") or []
            if isinstance(item, dict) and str(item.get("id") or "")
        }
        after_by_id = {
            str(item.get("id") or ""): item
            for item in updated_preview.get("agent_placements") or []
            if isinstance(item, dict) and str(item.get("id") or "")
        }
        agent_by_id = {
            str(item.get("id") or ""): item
            for item in session.agents
            if isinstance(item, dict) and str(item.get("id") or "")
        }
        diffs: List[Dict[str, Any]] = []
        for agent_id in sorted(after_by_id):
            before = before_by_id.get(agent_id) or {}
            after = after_by_id[agent_id]
            compact_before = self._compact_authoring_placement(before)
            compact_after = self._compact_authoring_placement(after)
            if compact_before == compact_after:
                continue
            display_name = str(
                (agent_by_id.get(agent_id) or {}).get("display_name")
                or after.get("display_name")
                or agent_id
            )
            diffs.append(
                {
                    "target_id": agent_id,
                    "target_display_name": display_name,
                    "before": compact_before,
                    "after": compact_after,
                    "explanation": (
                        f"Platzierung von {display_name} [{agent_id}] wird "
                        "auf die angezeigte Position und Blickrichtung geändert."
                    ),
                }
            )
        return diffs

    def _validate_authoring_placement_preview(
        self,
        session: ArrowProjectDraft,
        placements: List[Dict[str, Any]],
        *,
        adapter: Optional[RoomContractAdapter] = None,
    ) -> Dict[str, Any]:
        case_dir = Path(str(session.case_dir)).resolve()
        adapter = adapter or RoomContractAdapter.discover(
            backend_root=self._project_root()
        )
        common = adapter.import_pipeline_module("common")
        placement_module = adapter.import_pipeline_module("agent_placement")
        normalized_path = case_dir / "intermediate" / "scene_graph.normalized.json"
        roles_path = case_dir / "intermediate" / "agent_roles.generated.json"
        placements_path = case_dir / "intermediate" / "agent_placements.json"
        try:
            normalized_scene = common.read_json(normalized_path)
            agent_roles = common.read_json(roles_path)
            existing_placements = common.read_json(placements_path)
        except Exception as exc:
            return {
                "status": "invalid",
                "errors": [f"Placement-Artefakte konnten nicht geladen werden: {exc}"],
                "warnings": [],
                "metrics": {},
            }

        existing_by_id = {
            str(item.get("id") or ""): item
            for item in existing_placements.get("agent_placements") or []
            if isinstance(item, dict) and str(item.get("id") or "")
        }
        role_by_id = {
            str(item.get("id") or ""): item
            for item in agent_roles.get("agents") or []
            if isinstance(item, dict) and str(item.get("id") or "")
        }
        artifact_entries = []
        for placement in placements:
            agent_id = placement["id"]
            entry = copy.deepcopy(existing_by_id.get(agent_id) or {})
            entry.update(copy.deepcopy(placement))
            entry.setdefault(
                "display_name",
                (role_by_id.get(agent_id) or {}).get("display_name") or agent_id,
            )
            artifact_entries.append(entry)
        placement_payload = {
            "schema": placement_module.PLACEMENT_ARTIFACT_SCHEMA,
            "schema_version": placement_module.PLACEMENT_ARTIFACT_SCHEMA_VERSION,
            "placement_algorithm_version": placement_module.PLACEMENT_ALGORITHM_VERSION,
            "origin": "wizard_manual",
            "room_bounds": copy.deepcopy(
                existing_placements.get("room_bounds")
                or normalized_scene.get("room_bounds")
                or {}
            ),
            "agent_placements": artifact_entries,
        }
        return placement_module.validate_agent_placements(
            placement_payload,
            normalized_scene=normalized_scene,
            agent_roles=agent_roles,
        )

    def preview_arrow_authoring(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        session = self._arrow_authoring_session(payload)
        with self._arrow_mutation_scope(
            session_id=session.session_id,
            case_id=session.case_id,
        ):
            return self._preview_arrow_authoring_unlocked(session, payload)

    def _preview_arrow_authoring_unlocked(
        self,
        session: ArrowProjectDraft,
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        pending = self._pending_authoring_change(session.session_id)
        if pending:
            return self._authoring_response(
                session,
                status="conflict",
                change=pending,
                errors=[
                    "Es gibt bereits eine offene Placement-Änderung. "
                    "Bitte diese zuerst anwenden, akzeptieren oder verwerfen."
                ],
            )

        case_dir, paths, affected_artifacts = self._authoring_paths(session)
        current_revision = self._authoring_revision(case_dir, paths)
        expected_revision = self._expected_authoring_revision(payload)
        if expected_revision != current_revision:
            return self._authoring_conflict_response(
                session,
                expected=expected_revision,
                actual=current_revision,
            )

        change_payload = payload.get("change")
        if not isinstance(change_payload, dict):
            raise ValueError("change muss ein Objekt sein.")
        unknown_fields = sorted(
            set(change_payload) - {"kind", "rationale", "agent_placements"}
        )
        if unknown_fields:
            raise ValueError(
                "change enthält unbekannte Felder: " + ", ".join(unknown_fields) + "."
            )
        if str(change_payload.get("kind") or "").strip() != "agent_placement":
            raise ValueError(
                "Dieser Loop unterstützt ausschließlich kind='agent_placement'."
            )
        rationale = str(change_payload.get("rationale") or "").strip()
        if len(rationale) > 500:
            raise ValueError("change.rationale darf höchstens 500 Zeichen enthalten.")
        if not rationale:
            rationale = "Manuelle Platzierungsänderung im Unity-Wizard."

        placements, shape_validation = self._validate_requested_arrow_placements(
            session,
            change_payload.get("agent_placements"),
        )
        if shape_validation.get("status") != "valid":
            return self._authoring_response(
                session,
                status="invalid",
                validation=shape_validation,
                errors=list(shape_validation.get("errors") or []),
            )
        updated_preview = self._merge_placement_preview(session, placements)
        diffs = self._authoring_placement_diffs(session, updated_preview)
        if not diffs:
            no_change_validation = {
                "status": "invalid",
                "errors": ["Die strukturierte Placement-Änderung enthält keinen Unterschied."],
                "warnings": [],
                "metrics": shape_validation.get("metrics") or {},
            }
            return self._authoring_response(
                session,
                status="invalid",
                validation=no_change_validation,
                errors=no_change_validation["errors"],
            )

        preview_validation = self._validate_authoring_placement_preview(
            session,
            placements,
        )
        if preview_validation.get("status") != "valid":
            return self._authoring_response(
                session,
                status="invalid",
                validation=preview_validation,
                errors=list(preview_validation.get("errors") or []),
            )

        change = ArrowPlacementAuthoringChange(
            change_id="PLC-" + uuid.uuid4().hex[:10].upper(),
            session_id=session.session_id,
            case_id=str(session.case_id),
            rationale=rationale,
            revision_before=current_revision,
            placements=copy.deepcopy(placements),
            updated_preview=copy.deepcopy(updated_preview),
            diffs=diffs,
            validation=copy.deepcopy(preview_validation),
            affected_artifacts=affected_artifacts,
        )
        self.arrow_authoring_changes[change.change_id] = change
        self.arrow_authoring_pending[session.session_id] = change.change_id
        return self._authoring_response(
            session,
            status="preview_ready",
            change=change,
            validation=preview_validation,
        )

    def _required_pending_authoring_change(
        self,
        session: ArrowProjectDraft,
        payload: Dict[str, Any],
    ) -> ArrowPlacementAuthoringChange:
        change_id = str(payload.get("change_id") or "").strip()
        if not change_id:
            raise ValueError("change_id fehlt.")
        pending = self._pending_authoring_change(session.session_id)
        if not pending or pending.change_id != change_id:
            raise ValueError("Die angegebene Placement-Änderung ist nicht offen.")
        return pending

    def apply_arrow_authoring(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        session = self._arrow_authoring_session(payload)
        with self._arrow_mutation_scope(
            session_id=session.session_id,
            case_id=session.case_id,
        ):
            change = self._required_pending_authoring_change(session, payload)
            if change.lifecycle != "previewed":
                raise ValueError("Nur eine geprüfte Preview kann angewendet werden.")
            case_dir, paths, _ = self._authoring_paths(session)
            current_revision = self._authoring_revision(case_dir, paths)
            expected_revision = self._expected_authoring_revision(payload)
            if (
                expected_revision != current_revision
                or current_revision != change.revision_before
            ):
                return self._authoring_conflict_response(
                    session,
                    expected=expected_revision,
                    actual=current_revision,
                    change=change,
                )

            adapter = RoomContractAdapter.discover(backend_root=self._project_root())
            files_before = self._snapshot_files(paths)
            session_before = self._authoring_session_snapshot(session)
            result = self._update_roomcontract_placement(
                session,
                placements=copy.deepcopy(change.placements),
                updated_preview=copy.deepcopy(change.updated_preview),
                adapter=adapter,
            )
            if result.get("status") != "ok":
                rollback_errors = self._restore_files(files_before)
                self._restore_authoring_session_snapshot(session, session_before)
                validation = copy.deepcopy(result.get("validation") or {})
                if rollback_errors:
                    validation.setdefault("errors", []).extend(
                        "Authoring-Rollback: " + error for error in rollback_errors
                    )
                    validation["status"] = "invalid"
                change.validation = validation
                return self._authoring_response(
                    session,
                    status="invalid",
                    change=change,
                    validation=validation,
                    errors=list(validation.get("errors") or []),
                )

            change.files_before = files_before
            change.session_before = session_before
            change.files_after = self._snapshot_files(paths)
            change.session_after = self._authoring_session_snapshot(session)
            change.revision_after = self._authoring_revision(case_dir, paths)
            change.validation = copy.deepcopy(result.get("validation") or {})
            change.analysis_validation_summary = copy.deepcopy(
                result.get("analysis_validation_summary") or {}
            )
            change.lifecycle = "applied_pending_accept"
            change.applied_ms = _now_ms()
            return self._authoring_response(
                session,
                status="applied_pending_accept",
                mutation_applied=True,
                change=change,
                validation=change.validation,
            )

    def accept_arrow_authoring(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        session = self._arrow_authoring_session(payload)
        with self._arrow_mutation_scope(
            session_id=session.session_id,
            case_id=session.case_id,
        ):
            change = self._required_pending_authoring_change(session, payload)
            if change.lifecycle != "applied_pending_accept":
                raise ValueError(
                    "Die Placement-Änderung muss vor dem Akzeptieren angewendet "
                    "und validiert werden."
                )
            case_dir, paths, _ = self._authoring_paths(session)
            current_revision = self._authoring_revision(case_dir, paths)
            expected_revision = self._expected_authoring_revision(payload)
            if (
                expected_revision != current_revision
                or current_revision != change.revision_after
            ):
                return self._authoring_conflict_response(
                    session,
                    expected=expected_revision,
                    actual=current_revision,
                    change=change,
                )

            old_undo_id = self.arrow_authoring_undo.pop(session.session_id, None)
            if old_undo_id and old_undo_id != change.change_id:
                self.arrow_authoring_changes.pop(old_undo_id, None)
            self.arrow_authoring_pending.pop(session.session_id, None)
            self.arrow_authoring_undo[session.session_id] = change.change_id
            change.lifecycle = "accepted"
            change.accepted_ms = _now_ms()
            session.touch()
            return self._authoring_response(
                session,
                status="accepted",
                mutation_applied=True,
                change=change,
                validation=change.validation,
            )

    @staticmethod
    def _restored_case_is_valid(
        adapter: RoomContractAdapter,
        case_dir: Path,
    ) -> Tuple[bool, Dict[str, Any]]:
        report = adapter.validate_analyze_case(case_dir)
        return report.get("status") == "valid", report

    def _restore_authoring_change(
        self,
        session: ArrowProjectDraft,
        change: ArrowPlacementAuthoringChange,
        *,
        applied_files: Dict[Path, Optional[bytes]],
        applied_session: Dict[str, Any],
    ) -> Tuple[bool, List[str]]:
        errors = self._restore_files(change.files_before)
        if not errors:
            self._restore_authoring_session_snapshot(session, change.session_before)
            adapter = RoomContractAdapter.discover(backend_root=self._project_root())
            valid, report = self._restored_case_is_valid(
                adapter,
                Path(str(session.case_dir)).resolve(),
            )
            if not valid:
                errors.extend(
                    "Validierung nach Wiederherstellung: " + str(error)
                    for error in report.get("errors") or ["Analyze-Status ist nicht valid."]
                )
        if errors:
            recovery_errors = self._restore_files(applied_files)
            self._restore_authoring_session_snapshot(session, applied_session)
            errors.extend(
                "Wiederherstellung des angewendeten Stands: " + error
                for error in recovery_errors
            )
            return False, errors
        return True, []

    def discard_arrow_authoring(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        session = self._arrow_authoring_session(payload)
        with self._arrow_mutation_scope(
            session_id=session.session_id,
            case_id=session.case_id,
        ):
            change = self._required_pending_authoring_change(session, payload)
            case_dir, paths, _ = self._authoring_paths(session)
            current_revision = self._authoring_revision(case_dir, paths)
            expected_revision = self._expected_authoring_revision(payload)
            expected_change_revision = (
                change.revision_after
                if change.lifecycle == "applied_pending_accept"
                else change.revision_before
            )
            if (
                expected_revision != current_revision
                or current_revision != expected_change_revision
            ):
                return self._authoring_conflict_response(
                    session,
                    expected=expected_revision,
                    actual=current_revision,
                    change=change,
                )

            mutation_was_applied = change.lifecycle == "applied_pending_accept"
            if mutation_was_applied:
                applied_files = self._snapshot_files(paths)
                applied_session = self._authoring_session_snapshot(session)
                restored, errors = self._restore_authoring_change(
                    session,
                    change,
                    applied_files=applied_files,
                    applied_session=applied_session,
                )
                if not restored:
                    return self._authoring_response(
                        session,
                        status="invalid",
                        mutation_applied=True,
                        change=change,
                        errors=errors,
                    )
                restored_revision = self._authoring_revision(case_dir, paths)
                if restored_revision != change.revision_before:
                    self._restore_files(applied_files)
                    self._restore_authoring_session_snapshot(session, applied_session)
                    return self._authoring_response(
                        session,
                        status="invalid",
                        mutation_applied=True,
                        change=change,
                        errors=[
                            "Discard konnte den bytegenauen Ausgangsstand nicht wiederherstellen."
                        ],
                    )

            self.arrow_authoring_pending.pop(session.session_id, None)
            change.lifecycle = "discarded"
            response = self._authoring_response(
                session,
                status="discarded",
                mutation_applied=False,
                change=change,
            )
            self.arrow_authoring_changes.pop(change.change_id, None)
            return response

    def undo_arrow_authoring(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        session = self._arrow_authoring_session(payload)
        with self._arrow_mutation_scope(
            session_id=session.session_id,
            case_id=session.case_id,
        ):
            if self._pending_authoring_change(session.session_id):
                raise ValueError(
                    "Eine offene Placement-Änderung muss zuerst akzeptiert oder verworfen werden."
                )
            change = self._undo_authoring_change(session.session_id)
            if not change or change.lifecycle != "accepted":
                raise ValueError("Es gibt keine akzeptierte Placement-Änderung zum Rückgängigmachen.")
            requested_change_id = str(payload.get("change_id") or "").strip()
            if requested_change_id and requested_change_id != change.change_id:
                raise ValueError("change_id bezeichnet nicht die letzte akzeptierte Änderung.")

            case_dir, paths, _ = self._authoring_paths(session)
            current_revision = self._authoring_revision(case_dir, paths)
            expected_revision = self._expected_authoring_revision(payload)
            if (
                expected_revision != current_revision
                or current_revision != change.revision_after
            ):
                return self._authoring_conflict_response(
                    session,
                    expected=expected_revision,
                    actual=current_revision,
                    change=change,
                )

            applied_files = self._snapshot_files(paths)
            applied_session = self._authoring_session_snapshot(session)
            restored, errors = self._restore_authoring_change(
                session,
                change,
                applied_files=applied_files,
                applied_session=applied_session,
            )
            if not restored:
                return self._authoring_response(
                    session,
                    status="invalid",
                    mutation_applied=True,
                    change=change,
                    errors=errors,
                )
            restored_revision = self._authoring_revision(case_dir, paths)
            if restored_revision != change.revision_before:
                self._restore_files(applied_files)
                self._restore_authoring_session_snapshot(session, applied_session)
                return self._authoring_response(
                    session,
                    status="invalid",
                    mutation_applied=True,
                    change=change,
                    errors=[
                        "Undo konnte den bytegenauen Ausgangsstand nicht wiederherstellen."
                    ],
                )

            self.arrow_authoring_undo.pop(session.session_id, None)
            change.lifecycle = "undone"
            response = self._authoring_response(
                session,
                status="undone",
                mutation_applied=False,
                change=change,
            )
            self.arrow_authoring_changes.pop(change.change_id, None)
            return response

    def update_arrow_placement(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        session_id = str(payload.get("session_id") or "").strip()
        if not session_id:
            raise ValueError("session_id fehlt.")
        session = self.arrow_sessions.get(session_id)
        if not session:
            raise ValueError("Unbekannte session_id.")
        with self._arrow_mutation_scope(session_id=session_id, case_id=session.case_id):
            return self._update_arrow_placement_unlocked(payload)

    def _update_arrow_placement_unlocked(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        session_id = str(payload.get("session_id") or "").strip()
        if not session_id:
            raise ValueError("session_id fehlt.")
        session = self.arrow_sessions.get(session_id)
        if not session:
            raise ValueError("Unbekannte session_id.")

        requested_generation_mode = payload.get("generation_mode")
        if requested_generation_mode not in (None, ""):
            normalized_mode = normalize_generation_mode(requested_generation_mode)
            if normalized_mode != session.generation_mode:
                raise ValueError(
                    "generation_mode passt nicht zur Session: "
                    f"{normalized_mode} != {session.generation_mode}."
                )

        functional_adapter: Optional[RoomContractAdapter] = None
        functional_placement_module: Any = None
        planar_tolerance = PLACEMENT_PLANAR_TOLERANCE
        if session.generation_mode == GENERATION_MODE_ROOMCONTRACT:
            pending_change = self._pending_authoring_change(session.session_id)
            if pending_change:
                invalid = {
                    "status": "invalid",
                    "errors": [
                        "Es gibt eine offene strukturierte Placement-Änderung. "
                        "Bitte diese zuerst akzeptieren oder verwerfen."
                    ],
                    "warnings": [],
                    "metrics": {},
                }
                return self._placement_update_response(
                    session,
                    validation=invalid,
                    status="invalid",
                )
            try:
                functional_adapter = RoomContractAdapter.discover(backend_root=self._project_root())
                functional_placement_module = functional_adapter.import_pipeline_module("agent_placement")
                planar_tolerance = float(
                    functional_placement_module.PLACEMENT_FLOOR_TOLERANCE
                )
            except Exception as exc:
                invalid = {
                    "status": "invalid",
                    "errors": [f"Placement-Vertrag konnte nicht geladen werden: {exc}"],
                    "warnings": [],
                    "metrics": {},
                }
                return self._placement_update_response(session, validation=invalid, status="invalid")

        placements, validation = self._validate_requested_arrow_placements(
            session,
            payload.get("agent_placements"),
            planar_tolerance=planar_tolerance,
        )
        if validation["status"] != "valid":
            return self._placement_update_response(session, validation=validation, status="invalid")

        updated_preview = self._merge_placement_preview(session, placements)
        if session.generation_mode == GENERATION_MODE_LEGACY:
            session.placement_preview = updated_preview
            session.placement_manually_updated = True
            session.touch()
            return self._placement_update_response(
                session,
                validation=validation,
                status="ok",
                placement_preview=updated_preview,
                mutation_applied=True,
            )

        if session.validation_stale:
            invalid = {
                "status": "invalid",
                "errors": [
                    "Der RoomContract-Draft enthält ausstehende Refinements und muss vor einem Placement-Update neu analysiert werden."
                ],
                "warnings": [],
                "metrics": validation.get("metrics") or {},
            }
            return self._placement_update_response(session, validation=invalid, status="invalid")
        if not session.case_dir:
            invalid = {
                "status": "invalid",
                "errors": ["RoomContract-Case-Verzeichnis fehlt in der Session."],
                "warnings": [],
                "metrics": validation.get("metrics") or {},
            }
            return self._placement_update_response(session, validation=invalid, status="invalid")

        result = self._update_roomcontract_placement(
            session,
            placements=placements,
            updated_preview=updated_preview,
            adapter=functional_adapter,
            placement_module=functional_placement_module,
        )
        if result.get("status") == "ok":
            stale_undo_id = self.arrow_authoring_undo.pop(session.session_id, None)
            if stale_undo_id:
                self.arrow_authoring_changes.pop(stale_undo_id, None)
        return result

    @staticmethod
    def _validate_requested_arrow_placements(
        session: ArrowProjectDraft,
        raw_placements: Any,
        *,
        planar_tolerance: float = PLACEMENT_PLANAR_TOLERANCE,
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        expected_ids = [
            str(agent.get("id") or "").strip()
            for agent in session.agents
            if isinstance(agent, dict) and str(agent.get("id") or "").strip()
        ]
        expected_set = set(expected_ids)
        errors: List[str] = []
        by_id: Dict[str, Dict[str, Any]] = {}
        received_ids: List[str] = []
        seen_ids: set[str] = set()

        if not isinstance(raw_placements, list):
            errors.append("agent_placements muss eine Liste sein.")
            raw_placements = []

        for index, raw in enumerate(raw_placements):
            if not isinstance(raw, dict):
                errors.append(f"agent_placements[{index}] muss ein Objekt sein.")
                continue
            agent_id = str(raw.get("id") or "").strip()
            if not agent_id:
                errors.append(f"agent_placements[{index}].id fehlt.")
                continue
            received_ids.append(agent_id)
            if agent_id in seen_ids:
                errors.append(f"Doppelte Agent-ID in agent_placements: {agent_id}.")
                continue
            seen_ids.add(agent_id)

            canonical_vectors: Dict[str, Dict[str, float]] = {}
            for field_name in ("position", "forward"):
                raw_vector = raw.get(field_name)
                if not isinstance(raw_vector, dict):
                    errors.append(f"agent_placements[{index}].{field_name} muss ein Vektorobjekt sein.")
                    continue
                vector: Dict[str, float] = {}
                for component in ("x", "y", "z"):
                    value = raw_vector.get(component)
                    if isinstance(value, bool) or not isinstance(value, (int, float)):
                        errors.append(
                            f"agent_placements[{index}].{field_name}.{component} muss eine endliche Zahl sein."
                        )
                        continue
                    try:
                        numeric = float(value)
                    except (OverflowError, TypeError, ValueError):
                        numeric = math.nan
                    if not math.isfinite(numeric):
                        errors.append(
                            f"agent_placements[{index}].{field_name}.{component} muss eine endliche Zahl sein."
                        )
                        continue
                    vector[component] = numeric
                if len(vector) == 3:
                    canonical_vectors[field_name] = vector

            forward = canonical_vectors.get("forward")
            position = canonical_vectors.get("position")
            if position is not None and abs(position["y"]) > planar_tolerance:
                errors.append(f"agent_placements[{index}].position muss auf der Bodenebene liegen (y=0).")
            if forward is not None:
                if abs(forward["y"]) > planar_tolerance:
                    errors.append(f"agent_placements[{index}].forward muss planar sein (y=0).")
                planar_length = math.hypot(forward["x"], forward["z"])
                if abs(planar_length - 1.0) > PLACEMENT_FORWARD_TOLERANCE:
                    errors.append(
                        f"agent_placements[{index}].forward muss normalisiert sein (XZ-Länge=1)."
                    )

            if len(canonical_vectors) == 2:
                by_id[agent_id] = {
                    "id": agent_id,
                    "position": canonical_vectors["position"],
                    "forward": canonical_vectors["forward"],
                }

        received_set = set(received_ids)
        missing = sorted(expected_set - received_set)
        extra = sorted(received_set - expected_set)
        if missing:
            errors.append("Placements fehlen für Agenten: " + ", ".join(missing) + ".")
        if extra:
            errors.append("Placements enthalten unbekannte Agenten: " + ", ".join(extra) + ".")
        if len(raw_placements) != len(expected_ids):
            errors.append(
                f"Es werden exakt {len(expected_ids)} Agentenplacements erwartet; erhalten: {len(raw_placements)}."
            )

        metrics = {
            "expected_agent_count": len(expected_ids),
            "received_placement_count": len(raw_placements),
            "accepted_placement_count": len(by_id) if not errors else 0,
        }
        if errors:
            return [], {"status": "invalid", "errors": errors, "warnings": [], "metrics": metrics}
        return [by_id[agent_id] for agent_id in expected_ids], {
            "status": "valid",
            "errors": [],
            "warnings": [],
            "metrics": metrics,
        }

    @staticmethod
    def _merge_placement_preview(
        session: ArrowProjectDraft,
        placements: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        preview = copy.deepcopy(session.placement_preview or {})
        existing_by_id = {
            str(item.get("id") or ""): item
            for item in preview.get("agent_placements") or []
            if isinstance(item, dict) and str(item.get("id") or "")
        }
        agent_by_id = {
            str(agent.get("id") or ""): agent
            for agent in session.agents
            if isinstance(agent, dict) and str(agent.get("id") or "")
        }
        merged = []
        for placement in placements:
            agent_id = placement["id"]
            item = copy.deepcopy(existing_by_id.get(agent_id) or {})
            item.update(copy.deepcopy(placement))
            item.setdefault("display_name", (agent_by_id.get(agent_id) or {}).get("display_name") or agent_id)
            merged.append(item)
        preview["agent_placements"] = merged
        return preview

    @staticmethod
    def _placement_update_response(
        session: ArrowProjectDraft,
        *,
        validation: Dict[str, Any],
        status: str,
        placement_preview: Optional[Dict[str, Any]] = None,
        mutation_applied: bool = False,
        analysis_validation_summary: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        response = {
            "status": status,
            "generation_mode": session.generation_mode,
            "placement_preview": copy.deepcopy(
                placement_preview if placement_preview is not None else session.placement_preview
            ),
            "validation": copy.deepcopy(validation),
            "mutation_applied": mutation_applied,
        }
        if analysis_validation_summary is not None:
            response["analysis_validation_summary"] = copy.deepcopy(analysis_validation_summary)
        return response

    def _update_roomcontract_placement(
        self,
        session: ArrowProjectDraft,
        *,
        placements: List[Dict[str, Any]],
        updated_preview: Dict[str, Any],
        adapter: Optional[RoomContractAdapter] = None,
        placement_module: Any = None,
    ) -> Dict[str, Any]:
        case_dir = Path(str(session.case_dir)).resolve()
        adapter = adapter or RoomContractAdapter.discover(backend_root=self._project_root())
        common = adapter.import_pipeline_module("common")
        placement_module = placement_module or adapter.import_pipeline_module("agent_placement")

        normalized_path = case_dir / "intermediate" / "scene_graph.normalized.json"
        semantics_path = case_dir / "intermediate" / "scene_semantics.json"
        roles_path = case_dir / "intermediate" / "agent_roles.generated.json"
        placements_path = case_dir / "intermediate" / "agent_placements.json"
        placement_validation_path = case_dir / "validation" / "agent_placement_validation.json"

        try:
            normalized_scene = common.read_json(normalized_path)
            agent_roles = common.read_json(roles_path)
            existing_placements = common.read_json(placements_path) if placements_path.exists() else {}
        except Exception as exc:
            invalid = {
                "status": "invalid",
                "errors": [f"Placement-Artefakte konnten nicht geladen werden: {exc}"],
                "warnings": [],
                "metrics": {},
            }
            return self._placement_update_response(session, validation=invalid, status="invalid")

        existing_by_id = {
            str(item.get("id") or ""): item
            for item in existing_placements.get("agent_placements") or []
            if isinstance(item, dict) and str(item.get("id") or "")
        }
        role_by_id = {
            str(agent.get("id") or ""): agent
            for agent in agent_roles.get("agents") or []
            if isinstance(agent, dict) and str(agent.get("id") or "")
        }
        artifact_entries: List[Dict[str, Any]] = []
        for placement in placements:
            agent_id = placement["id"]
            entry = copy.deepcopy(existing_by_id.get(agent_id) or {})
            entry.update(copy.deepcopy(placement))
            entry.setdefault("display_name", (role_by_id.get(agent_id) or {}).get("display_name") or agent_id)
            artifact_entries.append(entry)
        placement_payload = {
            "schema": placement_module.PLACEMENT_ARTIFACT_SCHEMA,
            "schema_version": placement_module.PLACEMENT_ARTIFACT_SCHEMA_VERSION,
            "placement_algorithm_version": placement_module.PLACEMENT_ALGORITHM_VERSION,
            "origin": "wizard_manual",
            "room_bounds": copy.deepcopy(
                existing_placements.get("room_bounds") or normalized_scene.get("room_bounds") or {}
            ),
            "agent_placements": artifact_entries,
        }
        placement_validation = placement_module.validate_agent_placements(
            placement_payload,
            normalized_scene=normalized_scene,
            agent_roles=agent_roles,
        )
        if placement_validation.get("status") != "valid":
            return self._placement_update_response(
                session,
                validation=placement_validation,
                status="invalid",
            )

        transaction_paths = self._roomcontract_placement_transaction_paths(case_dir)
        snapshots = self._snapshot_files(transaction_paths)
        token = uuid.uuid4().hex
        placement_tmp = placements_path.with_name(f".{placements_path.name}.{token}.tmp")
        validation_tmp = placement_validation_path.with_name(
            f".{placement_validation_path.name}.{token}.tmp"
        )
        try:
            common.write_json(placement_tmp, placement_payload)
            common.write_json(validation_tmp, placement_validation)
            os.replace(placement_tmp, placements_path)
            os.replace(validation_tmp, placement_validation_path)
            common.update_manifest(
                case_dir,
                stage_id="agent_placement",
                status="success",
                input_paths=[normalized_path, semantics_path, roles_path],
                output_paths=[placements_path, placement_validation_path],
                errors=placement_validation.get("errors"),
                warnings=placement_validation.get("warnings"),
                metadata={
                    **(placement_validation.get("metrics") or {}),
                    "manual_wizard_update": True,
                },
            )

            for stage_id in ROOMCONTRACT_PLACEMENT_DEPENDENT_STAGES:
                stage_result = adapter.run_stage(case_dir, stage_id)
                if str(stage_result.get("status") or "").lower() not in {"success", "valid"}:
                    stage_errors = [str(item) for item in stage_result.get("errors") or []]
                    detail = "; ".join(stage_errors) or f"status={stage_result.get('status')}"
                    raise RuntimeError(f"{stage_id} ist fehlgeschlagen: {detail}")

            analyze_report = adapter.validate_analyze_case(case_dir)
            if analyze_report.get("status") != "valid":
                detail = "; ".join(str(item) for item in analyze_report.get("errors") or [])
                raise RuntimeError("Analyze-Validierung nach Placement-Update ist ungültig: " + detail)
            analyze_summary = adapter.summarize_analyze_validation(analyze_report)
            session_values = self._roomcontract_session_values_after_placement(
                session,
                case_dir=case_dir,
                adapter=adapter,
                analyze_report=analyze_report,
                analyze_summary=analyze_summary,
                updated_preview=updated_preview,
            )
        except Exception as exc:
            rollback_errors = self._restore_files(snapshots)
            error_text = f"Placement-Update wurde vollständig zurückgerollt: {exc}"
            if rollback_errors:
                error_text += " | Rollback-Fehler: " + "; ".join(rollback_errors)
            invalid = {
                "status": "invalid",
                "errors": [error_text],
                "warnings": [],
                "metrics": placement_validation.get("metrics") or {},
            }
            return self._placement_update_response(session, validation=invalid, status="invalid")
        finally:
            for temp_path in (placement_tmp, validation_tmp):
                try:
                    if temp_path.exists():
                        temp_path.unlink()
                except OSError:
                    pass

        session.placement_preview = session_values["placement_preview"]
        session.placement_manually_updated = True
        session.agent_roles = session_values["agent_roles"]
        session.roomcontract_path = session_values["roomcontract_path"]
        session.trace_map_path = None
        session.validation_summary = session_values["validation_summary"]
        session.roomcontract_summary = session_values["roomcontract_summary"]
        session.scenario_summary = session_values["scenario_summary"]
        session.capability_summary = session_values["capability_summary"]
        session.handoff_summary = session_values["handoff_summary"]
        session.room_knowledge_summary = session_values["room_knowledge_summary"]
        session.touch()
        return self._placement_update_response(
            session,
            validation=placement_validation,
            status="ok",
            placement_preview=session.placement_preview,
            mutation_applied=True,
            analysis_validation_summary=session.validation_summary,
        )

    @staticmethod
    def _roomcontract_placement_transaction_paths(case_dir: Path) -> List[Path]:
        return [
            case_dir / "intermediate" / "agent_placements.json",
            case_dir / "validation" / "agent_placement_validation.json",
            case_dir / "stage_manifest.json",
            case_dir / "roomcontract" / "roomcontract.instance.generated.json",
            case_dir / "validation" / "roomcontract_invariant_validation.json",
            case_dir / "intermediate" / "agent_roles.generated.json",
            case_dir / "intermediate" / "handoff_matrix.json",
            case_dir / "validation" / "handoff_derivation_validation.json",
            case_dir / "roomcontract" / "roomcontract.v2.instance.json",
            case_dir / "roomcontract" / "roomcontract.v2.assembly_report.json",
            case_dir / "validation" / "roomcontract_invariants_validation.json",
            case_dir / "validation" / "placement_metrics.json",
        ]

    @staticmethod
    def _snapshot_files(paths: List[Path]) -> Dict[Path, Optional[bytes]]:
        return {
            path: path.read_bytes() if path.exists() and path.is_file() else None
            for path in paths
        }

    @staticmethod
    def _restore_files(snapshots: Dict[Path, Optional[bytes]]) -> List[str]:
        errors: List[str] = []
        for path, original in snapshots.items():
            try:
                if original is None:
                    if path.exists():
                        path.unlink()
                    continue
                path.parent.mkdir(parents=True, exist_ok=True)
                restore_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.restore")
                try:
                    restore_path.write_bytes(original)
                    os.replace(restore_path, path)
                finally:
                    if restore_path.exists():
                        restore_path.unlink()
            except Exception as exc:
                errors.append(f"{path}: {exc}")
        return errors

    def _roomcontract_session_values_after_placement(
        self,
        session: ArrowProjectDraft,
        *,
        case_dir: Path,
        adapter: RoomContractAdapter,
        analyze_report: Dict[str, Any],
        analyze_summary: Dict[str, Any],
        updated_preview: Dict[str, Any],
    ) -> Dict[str, Any]:
        common = adapter.import_pipeline_module("common")
        normalized_scene = common.read_json(case_dir / "intermediate" / "scene_graph.normalized.json")
        scene_semantics = common.read_json(case_dir / "intermediate" / "scene_semantics.json")
        group_summary = common.read_json(case_dir / "intermediate" / "object_group_summary.json")
        agent_roles = common.read_json(case_dir / "intermediate" / "agent_roles.generated.json")
        roomcontract_path = case_dir / "roomcontract" / "roomcontract.instance.generated.json"
        roomcontract_instance = common.read_json(roomcontract_path)
        return {
            "placement_preview": copy.deepcopy(updated_preview),
            "agent_roles": agent_roles,
            "roomcontract_path": str(roomcontract_path),
            "validation_summary": analyze_summary,
            "roomcontract_summary": self._build_roomcontract_summary(roomcontract_instance),
            "scenario_summary": self._build_scenario_summary(roomcontract_instance),
            "capability_summary": self._build_capability_summary(roomcontract_instance),
            "handoff_summary": self._build_handoff_summary(agent_roles, analyze_report),
            "room_knowledge_summary": self._build_room_knowledge_summary(
                normalized_scene,
                scene_semantics,
                group_summary,
                session.knowledge,
                roomcontract_instance,
            ),
        }

    def _validate_roomcontract_placement_for_commit(
        self,
        *,
        adapter: RoomContractAdapter,
        case_dir: Path,
    ) -> Dict[str, Any]:
        """Revalidate the exact current placement immediately before materialization."""

        common = adapter.import_pipeline_module("common")
        placement_module = adapter.import_pipeline_module("agent_placement")
        placements_path = case_dir / "intermediate" / "agent_placements.json"
        placement_validation_path = case_dir / "validation" / "agent_placement_validation.json"
        metrics_path = case_dir / "validation" / "placement_metrics.json"
        normalized_path = case_dir / "intermediate" / "scene_graph.normalized.json"
        roles_path = case_dir / "intermediate" / "agent_roles.generated.json"
        errors: List[str] = []
        warnings: List[str] = []
        artifact_sha256 = ""

        try:
            placements = common.read_json(placements_path)
            normalized_scene = common.read_json(normalized_path)
            agent_roles = common.read_json(roles_path)
            stored_validation = common.read_json(placement_validation_path)
        except Exception as exc:
            return {
                "status": "invalid",
                "errors": [f"Placement-Commit-Guard konnte Artefakte nicht laden: {exc}"],
                "warnings": [],
                "metrics": {},
            }

        expected_headers = {
            "schema": placement_module.PLACEMENT_ARTIFACT_SCHEMA,
            "schema_version": placement_module.PLACEMENT_ARTIFACT_SCHEMA_VERSION,
            "placement_algorithm_version": placement_module.PLACEMENT_ALGORITHM_VERSION,
        }
        for field_name, expected in expected_headers.items():
            if placements.get(field_name) != expected:
                errors.append(
                    f"Placement-Artefakt {field_name} ist nicht aktuell: "
                    f"erwartet {expected!r}, gefunden {placements.get(field_name)!r}."
                )
        origin = str(placements.get("origin") or "")
        if origin not in placement_module.PLACEMENT_ORIGINS:
            errors.append(f"Placement-Artefakt hat ungÃ¼ltige origin: {origin!r}.")

        try:
            artifact_sha256 = placement_module.placement_artifact_sha256(placements)
        except Exception as exc:
            errors.append(f"Placement-Artefakt kann nicht kanonisch gehasht werden: {exc}")

        strict_validation = placement_module.validate_agent_placements(
            placements,
            normalized_scene=normalized_scene,
            agent_roles=agent_roles,
        )
        if strict_validation.get("status") != "valid":
            errors.extend(
                "Aktuelle Placement-Validierung: " + str(item)
                for item in strict_validation.get("errors") or []
            )
        warnings.extend(str(item) for item in strict_validation.get("warnings") or [])
        if artifact_sha256 and strict_validation.get("placement_artifact_sha256") != artifact_sha256:
            errors.append("Aktuelle Placement-Validierung meldet nicht den kanonischen Artefakt-Hash.")

        if stored_validation.get("status") != "valid":
            errors.append("Gespeicherte Agent-Placement-Validierung ist nicht valid.")
        if artifact_sha256 and stored_validation.get("placement_artifact_sha256") != artifact_sha256:
            errors.append(
                "Gespeicherte Agent-Placement-Validierung gehÃ¶rt nicht zum aktuellen Artefakt-Hash."
            )
        if stored_validation.get("placement_algorithm_version") != placement_module.PLACEMENT_ALGORITHM_VERSION:
            errors.append("Gespeicherte Agent-Placement-Validierung nutzt nicht die aktuelle Algorithmusversion.")

        manifest = common.load_manifest(case_dir)

        def stage_entry(stage_id: str) -> Optional[Dict[str, Any]]:
            return next(
                (
                    item
                    for item in manifest.get("stages") or []
                    if isinstance(item, dict) and item.get("stage_id") == stage_id
                ),
                None,
            )

        def verify_manifest_file(
            stage: Optional[Dict[str, Any]],
            *,
            collection: str,
            path: Path,
            label: str,
        ) -> None:
            if not stage or stage.get("status") != "success":
                errors.append(f"Manifest-Stage {label} fehlt oder ist nicht success.")
                return
            record = next(
                (
                    item
                    for item in stage.get(collection) or []
                    if isinstance(item, dict)
                    and adapter._recorded_input_matches_path(case_dir, item.get("path"), path)
                ),
                None,
            )
            if not record:
                errors.append(f"Manifest-Stage {label} referenziert {path.name} nicht.")
                return
            actual_file_sha = common.sha256_file(path) if path.is_file() else ""
            if record.get("sha256") != actual_file_sha:
                errors.append(f"Manifest-Hash fÃ¼r {path.name} ist nicht aktuell.")

        placement_stage = stage_entry("agent_placement")
        verify_manifest_file(
            placement_stage,
            collection="outputs",
            path=placements_path,
            label="agent_placement",
        )
        verify_manifest_file(
            placement_stage,
            collection="outputs",
            path=placement_validation_path,
            label="agent_placement",
        )

        try:
            metrics_report = common.read_json(metrics_path)
        except Exception as exc:
            errors.append(f"Placement-Metriken fehlen oder sind ungÃ¼ltig: {exc}")
            metrics_report = {}
        if metrics_report.get("status") != "valid":
            errors.append("Placement-Metriken sind nicht valid.")
        metrics_stage = stage_entry("placement_metrics")
        verify_manifest_file(
            metrics_stage,
            collection="inputs",
            path=placements_path,
            label="placement_metrics",
        )
        verify_manifest_file(
            metrics_stage,
            collection="outputs",
            path=metrics_path,
            label="placement_metrics",
        )

        return {
            "status": "valid" if not errors else "invalid",
            "errors": errors,
            "warnings": warnings,
            "metrics": {
                "placement_artifact_sha256": artifact_sha256,
                "placement_algorithm_version": placements.get("placement_algorithm_version"),
                "placement_origin": origin,
            },
        }

    def commit_arrow_project(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        session_id = str(payload.get("session_id") or "").strip()
        if not session_id:
            raise ValueError("session_id fehlt.")
        session = self.arrow_sessions.get(session_id)
        if not session:
            raise ValueError("Unbekannte session_id.")
        with self._arrow_mutation_scope(session_id=session_id, case_id=session.case_id):
            return self._commit_arrow_project_unlocked(payload)

    def _commit_arrow_project_unlocked(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        session_id = str(payload.get("session_id") or "").strip()
        if not session_id:
            raise ValueError("session_id fehlt.")
        session = self.arrow_sessions.get(session_id)
        if not session:
            raise ValueError("Unbekannte session_id.")

        requested_generation_mode_raw = payload.get("generation_mode")
        if requested_generation_mode_raw not in (None, ""):
            requested_generation_mode = normalize_generation_mode(requested_generation_mode_raw)
            if requested_generation_mode != session.generation_mode:
                raise ValueError(
                    f"generation_mode passt nicht zur Session: "
                    f"{requested_generation_mode} != {session.generation_mode}."
                )
        display_name = str(payload.get("display_name") or session.project.get("display_name") or "").strip()
        if not display_name:
            raise ValueError("display_name fehlt.")
        project_id = str(payload.get("project_id") or "").strip() or None
        description = str(payload.get("description") or session.project.get("description") or "").strip()

        if session.generation_mode == GENERATION_MODE_ROOMCONTRACT:
            return self._commit_roomcontract_project(
                session,
                display_name=display_name,
                project_id=project_id,
                description=description,
            )

        meta = self.project_manager.create_project(display_name=display_name, project_id=project_id, description=description)
        project_id = meta["id"]

        placement_preview = (
            copy.deepcopy(session.placement_preview)
            if session.placement_manually_updated
            else normalize_placement_preview(
                session.arrow_payload,
                session.agents,
                session.placement_preview,
            )
        )
        placement_lookup = {}
        for placement in placement_preview.get("agent_placements") or []:
            if isinstance(placement, dict) and placement.get("id"):
                placement_lookup[placement["id"]] = placement

        agents_with_positions = []
        for agent in session.agents:
            agent_copy = dict(agent)
            placement = placement_lookup.get(agent_copy.get("id"), {})
            position = placement.get("position")
            if position:
                agent_copy["position"] = position
            agent_copy["forward"] = placement.get("forward") or {"x": 0, "y": 0, "z": 1}
            agent_copy["spawn_point_id"] = placement.get("spawn_point_id")
            agent_copy["zone_id"] = placement.get("zone_id")
            agent_copy["tags"] = placement.get("tags", [])
            agents_with_positions.append(agent_copy)

        self.project_manager.save_agents(project_id, agents_with_positions)
        self.project_manager.save_room_plan(project_id, session.arrow_payload)
        for entry in session.knowledge:
            tag = str(entry.get("tag") or "").strip()
            name = str(entry.get("name") or "").strip()
            if not tag or not name:
                continue
            text = str(entry.get("text") or "")
            self.project_manager.upsert_knowledge(project_id, tag=tag, name=name, text=text, overwrite=True)

        self.refresh_project_kb(project_id)
        placement_list = []
        for agent in agents_with_positions:
            placement = placement_lookup.get(agent.get("id"), {})
            placement_list.append(
                {
                    "id": agent.get("id"),
                    "display_name": agent.get("display_name"),
                    "position": placement.get("position"),
                    "forward": placement.get("forward"),
                    "spawn_point_id": placement.get("spawn_point_id"),
                    "zone_id": placement.get("zone_id"),
                    "tags": placement.get("tags", []),
                }
            )
        fallback_room_objects = (
            rdl_slice_obstacles(session.arrow_payload)
            if _is_rdl(session.arrow_payload)
            else summarize_room_objects(session.arrow_payload, floor_only=True)
        )
        return {
            "status": "ok",
            "generation_mode": session.generation_mode,
            "project": meta,
            "placements": placement_list,
            "room_objects": placement_preview.get("room_objects") or fallback_room_objects,
            "room_bounds": placement_preview.get("room_bounds"),
        }

    def _commit_roomcontract_project(
        self,
        session: ArrowProjectDraft,
        *,
        display_name: str,
        project_id: Optional[str],
        description: str,
    ) -> Dict[str, Any]:
        if project_id and session.case_id and project_id != session.case_id:
            return self._roomcontract_commit_response(
                session,
                status="needs_repair",
                validation_summary=self._commit_error_summary(
                    "RoomContract-Projekt-ID muss vor Analyze feststehen. "
                    f"Commit-ID '{project_id}' passt nicht zur Case-ID '{session.case_id}'."
                ),
            )
        pending_change = self._pending_authoring_change(session.session_id)
        if pending_change:
            return self._roomcontract_commit_response(
                session,
                status="needs_authoring_decision",
                validation_summary=self._commit_error_summary(
                    "Es gibt eine offene strukturierte Placement-Änderung "
                    f"({pending_change.change_id}, Status {pending_change.lifecycle}). "
                    "Bitte die Änderung zuerst akzeptieren oder verwerfen."
                ),
            )
        if session.validation_stale:
            return self._roomcontract_commit_response(
                session,
                status="needs_regeneration",
                validation_summary=self._commit_error_summary(
                    "Der RoomContract-Draft enthaelt vorgemerkte Chat-Aenderungen und ist nicht final validiert. "
                    "Bitte Analyze/Regeneration erneut ausfuehren, bevor ein Runtime-Projekt final committet wird."
                ),
            )
        if not session.case_dir:
            return self._roomcontract_commit_response(
                session,
                status="needs_repair",
                validation_summary=self._commit_error_summary("RoomContract-Case-Verzeichnis fehlt in der Session."),
            )

        adapter = RoomContractAdapter.discover(backend_root=self._project_root())
        case_dir = Path(session.case_dir)
        analyze_report = adapter.validate_analyze_case(case_dir)
        if analyze_report.get("status") != "valid":
            validation_summary = adapter.summarize_analyze_validation(analyze_report)
            session.validation_summary = validation_summary
            session.touch()
            return self._roomcontract_commit_response(
                session,
                status="needs_repair",
                validation_summary=validation_summary,
            )

        stage_errors: List[str] = []
        deterministic_commit_stages = [
            "roomcontract_invariants",
            *[stage_id for stage_id in COMMIT_STAGE_IDS if stage_id not in ANALYZE_STAGE_IDS],
        ]
        for stage_id in deterministic_commit_stages:
            if stage_id == "project_materialization":
                placement_guard = self._validate_roomcontract_placement_for_commit(
                    adapter=adapter,
                    case_dir=case_dir,
                )
                if placement_guard.get("status") != "valid":
                    stage_errors.extend(
                        "agent_placement_commit_guard: " + str(error)
                        for error in placement_guard.get("errors") or []
                    )
                    if not stage_errors:
                        stage_errors.append("agent_placement_commit_guard: status=invalid")
                    break
            try:
                result = adapter.run_stage_deterministic_first(case_dir, stage_id)
            except Exception as exc:
                stage_errors.append(f"{stage_id}: {exc}")
                break
            if str(result.get("status") or "").lower() not in {"success", "valid"}:
                for error in result.get("errors") or []:
                    stage_errors.append(f"{stage_id}: {error}")
                if not stage_errors:
                    stage_errors.append(f"{stage_id}: status={result.get('status')}")
                break

        commit_report = adapter.validate_commit_case(case_dir)
        if stage_errors:
            commit_report = dict(commit_report)
            commit_report["status"] = "invalid"
            commit_report["errors"] = stage_errors + list(commit_report.get("errors") or [])
        validation_summary = adapter.summarize_commit_validation(commit_report)
        session.validation_summary = validation_summary
        session.trace_map_path = str(adapter.paths.backend_root / "projects" / case_dir.name / "trace_map.json")
        session.touch()

        if validation_summary.get("status") != "valid":
            return self._roomcontract_commit_response(
                session,
                status="needs_repair",
                validation_summary=validation_summary,
            )

        meta = self.project_manager.update_metadata(case_dir.name, display_name=display_name, description=description)
        self.refresh_project_kb(case_dir.name)
        committed = self._roomcontract_commit_response(
            session,
            status="ok",
            project=meta,
            validation_summary=validation_summary,
        )
        stale_undo_id = self.arrow_authoring_undo.pop(session.session_id, None)
        if stale_undo_id:
            self.arrow_authoring_changes.pop(stale_undo_id, None)
        return committed

    @staticmethod
    def _commit_error_summary(message: str) -> Dict[str, Any]:
        return {
            "status": "invalid",
            "schema_status": "not_run",
            "invariant_status": "not_run",
            "materialization_status": "not_run",
            "traceability_status": "not_run",
            "handoff_status": "not_run",
            "error_count": 1,
            "warning_count": 0,
            "traceability_average_coverage": 0.0,
            "handoff_decision_accuracy": 0.0,
            "errors": [message],
            "warnings": [],
        }

    def _roomcontract_commit_response(
        self,
        session: ArrowProjectDraft,
        *,
        status: str,
        validation_summary: Dict[str, Any],
        project: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        case_id = session.case_id or ""
        project_dir = self._project_root() / "projects" / case_id if case_id else None
        agents_doc = self._read_json_if_exists(project_dir / "agents.json") if project_dir else {}
        placements = []
        for agent in agents_doc.get("agents") or []:
            if not isinstance(agent, dict):
                continue
            placements.append(
                {
                    "id": agent.get("id"),
                    "display_name": agent.get("display_name"),
                    "position": agent.get("position"),
                    "forward": agent.get("forward"),
                    "spawn_point_id": agent.get("spawn_point_id"),
                    "zone_id": agent.get("zone_id"),
                    "tags": agent.get("tags", []),
                }
            )
        placement_preview = session.placement_preview or {}
        room_objects = placement_preview.get("room_objects") or (
            rdl_slice_obstacles(session.arrow_payload)
            if _is_rdl(session.arrow_payload)
            else summarize_room_objects(session.arrow_payload, floor_only=True)
        )
        return {
            "status": status,
            "generation_mode": session.generation_mode,
            "project": project,
            "placements": placements or placement_preview.get("agent_placements") or [],
            "room_objects": room_objects,
            "room_bounds": placement_preview.get("room_bounds"),
            "roomcontract_path": session.roomcontract_path,
            "trace_map_path": str(project_dir / "trace_map.json") if project_dir else session.trace_map_path,
            "validation_summary": validation_summary,
            "roomcontract_summary": session.roomcontract_summary,
        }

    def _generate_roomcontract_analyze_draft(
        self,
        arrow_payload: Dict[str, Any],
        *,
        case_id: str,
        max_repair_attempts: Optional[int],
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        adapter = RoomContractAdapter.discover(backend_root=self._project_root())
        initialized = adapter.initialize_case_from_payload(arrow_payload, case_id=case_id)
        case_dir = Path(initialized["case_dir"])
        stage_errors: List[str] = []
        stage_results: List[Dict[str, Any]] = []

        for stage_id in ANALYZE_STAGE_IDS:
            kwargs: Dict[str, Any] = {}
            if stage_id in {"scene_semantics", "agent_roles", "knowledge_synthesis"}:
                kwargs["max_repair_attempts"] = 3 if max_repair_attempts is None else max_repair_attempts
            try:
                result = adapter.run_stage_deterministic_first(case_dir, stage_id, **kwargs)
            except Exception as exc:
                stage_errors.append(f"{stage_id}: {exc}")
                break

            stage_results.append({"stage_id": stage_id, **result})
            if str(result.get("status") or "").lower() not in {"success", "valid"}:
                for error in result.get("errors") or []:
                    stage_errors.append(f"{stage_id}: {error}")
                if not stage_errors:
                    stage_errors.append(f"{stage_id}: status={result.get('status')}")
                break

        analyze_report = adapter.validate_analyze_case(case_dir)
        if stage_errors:
            analyze_report = dict(analyze_report)
            analyze_report["status"] = "invalid"
            analyze_report["errors"] = stage_errors + list(analyze_report.get("errors") or [])
        validation_summary = adapter.summarize_analyze_validation(analyze_report)

        agent_roles = self._read_json_if_exists(case_dir / "intermediate" / "agent_roles.generated.json")
        knowledge_doc = self._read_json_if_exists(case_dir / "intermediate" / "knowledge.generated.json")
        placements_doc = self._read_json_if_exists(case_dir / "intermediate" / "agent_placements.json")
        roomcontract_instance = self._read_json_if_exists(case_dir / "roomcontract" / "roomcontract.instance.generated.json")
        normalized_scene = self._read_json_if_exists(case_dir / "intermediate" / "scene_graph.normalized.json")
        scene_semantics = self._read_json_if_exists(case_dir / "intermediate" / "scene_semantics.json")
        group_summary = self._read_json_if_exists(case_dir / "intermediate" / "object_group_summary.json")
        if not roomcontract_instance:
            validation_summary = self._mark_roomcontract_analyze_invalid(
                validation_summary,
                "RoomContract-Instanz wurde nicht erzeugt. Die Analyse darf nicht als Legacy-Draft interpretiert werden.",
            )

        agents = [dict(agent) for agent in agent_roles.get("agents") or [] if isinstance(agent, dict)]
        knowledge = [
            {
                "tag": str(entry.get("tag") or ""),
                "name": str(entry.get("name") or ""),
                "text": str(entry.get("text") or ""),
            }
            for entry in knowledge_doc.get("knowledge_entries") or []
            if isinstance(entry, dict)
        ]
        room_objects = (
            rdl_slice_obstacles(arrow_payload)
            if _is_rdl(arrow_payload)
            else summarize_room_objects(arrow_payload, floor_only=True)
        )
        placement_preview = {
            "room_objects": room_objects,
            "agent_placements": placements_doc.get("agent_placements") or [],
            "room_bounds": placements_doc.get("room_bounds") or normalized_scene.get("room_bounds"),
        }

        roomcontract_path = case_dir / "roomcontract" / "roomcontract.instance.generated.json"
        draft_payload = {
            "assistant_message": self._roomcontract_analyze_message(validation_summary),
            "analysis": self._roomcontract_analysis_text(case_id, validation_summary, stage_results),
            "project": {
                "display_name": case_id.replace("_", " ").title(),
                "description": "Generated RoomContract preview project for Interactive Agents.",
            },
            "agents": agents,
            "knowledge": knowledge,
            "placement_preview": placement_preview,
        }
        draft_meta = {
            "case_dir": str(case_dir),
            "agent_roles": agent_roles,
            "roomcontract_path": str(roomcontract_path) if roomcontract_path.exists() else None,
            "trace_map_path": None,
            "validation_summary": validation_summary,
            "roomcontract_summary": self._build_roomcontract_summary(roomcontract_instance)
            or self._minimal_roomcontract_summary(case_id, validation_summary),
            "scenario_summary": self._build_scenario_summary(roomcontract_instance),
            "capability_summary": self._build_capability_summary(roomcontract_instance),
            "handoff_summary": self._build_handoff_summary(agent_roles, analyze_report),
            "room_knowledge_summary": self._build_room_knowledge_summary(
                normalized_scene,
                scene_semantics,
                group_summary,
                knowledge,
                roomcontract_instance,
            ),
        }
        return draft_payload, draft_meta

    @staticmethod
    def _minimal_roomcontract_summary(case_id: str, validation_summary: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "case_id": case_id,
            "schema": "roomcontract_case_study",
            "metamodel_version": "",
            "use_case_id": "",
            "main_scenario_id": "",
            "actor_count": 0,
            "entity_count": 0,
            "agent_count": 0,
            "capability_count": 0,
            "runtime_binding_count": 0,
            "validation_case_count": 0,
            "satisfy_relationship_count": 0,
            "status": validation_summary.get("status") or "invalid",
        }

    @staticmethod
    def _mark_roomcontract_analyze_invalid(
        validation_summary: Dict[str, Any],
        message: str,
    ) -> Dict[str, Any]:
        summary = dict(validation_summary or {})
        errors = list(summary.get("errors") or [])
        if message not in errors:
            errors.insert(0, message)
        summary.update(
            {
                "status": "invalid",
                "invariant_status": summary.get("invariant_status") or "invalid",
                "error_count": max(int(summary.get("error_count") or 0), len(errors)),
                "errors": errors,
            }
        )
        return summary

    @staticmethod
    def _read_json_if_exists(path: Path) -> Dict[str, Any]:
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8-sig"))
        except Exception:
            return {}

    @staticmethod
    def _roomcontract_analyze_message(validation_summary: Dict[str, Any]) -> str:
        if validation_summary.get("status") == "valid":
            return (
                "RoomContract-Analyze abgeschlossen. Der Draft ist validiert und als Preview sichtbar; "
                "es wurden noch keine Runtime-Projektdateien committet."
            )
        return (
            "RoomContract-Analyze abgeschlossen, aber die Validierung ist nicht gueltig. "
            "Bitte die angezeigten Fehler beheben; es werden keine Projektdateien committet."
        )

    @staticmethod
    def _roomcontract_analysis_text(
        case_id: str,
        validation_summary: Dict[str, Any],
        stage_results: List[Dict[str, Any]],
    ) -> str:
        lines = [
            f"RoomContract-Case: {case_id}",
            f"Analyze-Status: {validation_summary.get('status')}",
            f"Schema/Semantik/Rollen/Wissen/Placement: {validation_summary.get('schema_status')}",
            f"RoomContract-Invarianten: {validation_summary.get('invariant_status')}",
            f"Handoff-Ableitung: {validation_summary.get('handoff_status')}",
            f"Fehler: {validation_summary.get('error_count', 0)}",
            f"Warnungen: {validation_summary.get('warning_count', 0)}",
        ]
        if stage_results:
            lines.append("Ausgefuehrte Stages: " + ", ".join(str(item.get("stage_id")) for item in stage_results))
        return "\n".join(lines)

    @staticmethod
    def _build_roomcontract_summary(instance: Dict[str, Any]) -> Dict[str, Any]:
        if not instance:
            return {}
        use_case, scenario = SessionStore._main_use_case_and_scenario(instance)
        return {
            "case_id": instance.get("caseId"),
            "schema": instance.get("schema"),
            "metamodel_version": instance.get("metamodelVersion"),
            "use_case_id": use_case.get("id"),
            "main_scenario_id": scenario.get("id"),
            "actor_count": len(instance.get("actors") or []),
            "entity_count": len(instance.get("entities") or []),
            "agent_count": len(instance.get("agents") or []),
            "capability_count": len(instance.get("capabilities") or []),
            "runtime_binding_count": len(instance.get("runtimeBindings") or []),
            "validation_case_count": len(instance.get("validationCases") or []),
            "satisfy_relationship_count": len(instance.get("satisfyRelationships") or []),
        }

    @staticmethod
    def _build_scenario_summary(instance: Dict[str, Any]) -> Dict[str, Any]:
        if not instance:
            return {}
        use_case, scenario = SessionStore._main_use_case_and_scenario(instance)
        return {
            "use_case_id": use_case.get("id"),
            "main_scenario_id": scenario.get("id"),
            "goal": scenario.get("goal") or use_case.get("goal"),
            "step_count": len(scenario.get("steps") or []),
            "validation_case_count": len(instance.get("validationCases") or []),
        }

    @staticmethod
    def _build_capability_summary(instance: Dict[str, Any]) -> Dict[str, Any]:
        if not instance:
            return {}
        runtime_bindings = instance.get("runtimeBindings") or []
        binding_counts: Dict[str, int] = {}
        runtime_action_count = 0
        for binding in runtime_bindings:
            if not isinstance(binding, dict):
                continue
            capability_id = str(binding.get("capability_id") or "")
            binding_counts[capability_id] = binding_counts.get(capability_id, 0) + 1
            runtime_action_count += len(binding.get("runtimeActions") or [])
        return {
            "capability_count": len(instance.get("capabilities") or []),
            "runtime_binding_count": len(runtime_bindings),
            "runtime_action_count": runtime_action_count,
            "capabilities": [
                {
                    "id": capability.get("id"),
                    "runtime_binding_count": binding_counts.get(str(capability.get("id") or ""), 0),
                }
                for capability in instance.get("capabilities") or []
                if isinstance(capability, dict)
            ],
        }

    @staticmethod
    def _build_handoff_summary(agent_roles: Dict[str, Any], analyze_report: Dict[str, Any]) -> Dict[str, Any]:
        agents = [agent for agent in agent_roles.get("agents") or [] if isinstance(agent, dict)]
        agent_ids = {str(agent.get("id") or "") for agent in agents}
        declared_pairs = []
        self_handoff_count = 0
        valid_target_count = 0
        for agent in agents:
            source = str(agent.get("id") or "")
            for target in agent.get("handoff_targets") or []:
                target_id = str(target)
                declared_pairs.append((source, target_id))
                if target_id == source:
                    self_handoff_count += 1
                if target_id in agent_ids and target_id != source:
                    valid_target_count += 1
        pair_count = len(declared_pairs)
        validations = analyze_report.get("validations") or {}
        handoff_metrics = (validations.get("handoff_derivation") or {}).get("metrics") or {}
        return {
            "agent_count": len(agents),
            "declared_handoff_pair_count": pair_count,
            "valid_handoff_target_ratio": (valid_target_count / pair_count) if pair_count else 1.0,
            "handoff_decision_accuracy": float(handoff_metrics.get("handoff_decision_accuracy") or 0.0),
            "self_handoff_count": self_handoff_count,
        }

    @staticmethod
    def _build_room_knowledge_summary(
        normalized_scene: Dict[str, Any],
        scene_semantics: Dict[str, Any],
        group_summary: Dict[str, Any],
        knowledge: List[Dict[str, Any]],
        roomcontract_instance: Dict[str, Any],
    ) -> Dict[str, Any]:
        semantic_zones = scene_semantics.get("semantic_zones") or []
        knowledge_tags = {str(entry.get("tag") or "") for entry in knowledge if isinstance(entry, dict)}
        agent_tags = {
            str(tag)
            for agent in roomcontract_instance.get("agents") or []
            if isinstance(agent, dict)
            for tag in agent.get("knowledge_tags") or []
        }
        object_groups = [
            str(group.get("group") or "")
            for group in group_summary.get("groups") or []
            if isinstance(group, dict) and not group.get("is_structural")
        ]
        grounded_groups = {
            str(group)
            for agent in roomcontract_instance.get("agents") or []
            if isinstance(agent, dict)
            for group in agent.get("grounded_object_groups") or []
        }
        return {
            "room_object_count": len(normalized_scene.get("objects") or []),
            "semantic_zone_count": len(semantic_zones),
            "knowledge_file_count": len(knowledge),
            "agent_to_knowledge_tag_coverage": (
                len(agent_tags & knowledge_tags) / len(agent_tags)
                if agent_tags
                else 1.0
            ),
            "object_group_to_agent_role_grounding": (
                len(set(object_groups) & grounded_groups) / len(set(object_groups))
                if object_groups
                else 1.0
            ),
            "important_object_groups": object_groups,
            "semantic_zones": [
                str(zone.get("zone_id") or zone.get("name") or "")
                for zone in semantic_zones
                if isinstance(zone, dict)
            ],
        }

    @staticmethod
    def _main_use_case_and_scenario(instance: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        use_cases = (instance.get("requirementsModel") or {}).get("useCases") or []
        use_case = use_cases[0] if use_cases and isinstance(use_cases[0], dict) else {}
        scenarios = use_case.get("scenarios") or []
        scenario = scenarios[0] if scenarios and isinstance(scenarios[0], dict) else {}
        return use_case, scenario

    def _generate_arrow_draft(
        self,
        arrow_payload: Dict[str, Any],
        *,
        history: List[Dict[str, str]],
        current: Optional[ArrowProjectDraft] = None,
    ) -> Dict[str, Any]:
        schema = arrow_project_schema()
        arrow_text = json.dumps(arrow_payload, ensure_ascii=False, indent=2)
        current_summary = ""
        if current is not None:
            current_summary = json.dumps(
                {
                    "analysis": current.analysis,
                    "project": current.project,
                    "agents": current.agents,
                    "knowledge": current.knowledge,
                    "placement_preview": current.placement_preview,
                },
                ensure_ascii=False,
                indent=2,
            )

        dev_prompt = (
            "Du bist ein Projekt-Assistent für Unity. Analysiere die folgende RDLI-Datei (JSON) "
            "und leite daraus eine Projektbeschreibung, passende Agenten (mit Personas), und benötigte "
            "Wissenseinträge ab. Antworte präzise, strukturiert und auf Deutsch. "
            "Die Agentenauswahl soll sich am Raumtyp orientieren (z. B. Klassenraum -> Lehrer, Schüler, Rektor; "
            "Firmenpräsentation -> PR, Marketing, Vertrieb, Technik). Nutze die Raum-Beschreibung/Metadaten "
            "aus der RDLI-Datei als primäre Leitlinie für Rollen, Ton und Expertise. "
            "Gib außerdem für jeden Agenten passende Voice-Settings an: "
            "voice_gender (\"weiblich\" oder \"männlich\"), voice (Stimm-ID passend zum Geschlecht), "
            "voice_style (z. B. klar, kreativ, präzise, warm, neutral) und tts_model (gpt-4o-mini-tts). "
            "Verwende nach Möglichkeit folgende Stimm-IDs: weiblich = coral, nova, shimmer; "
            "männlich = alloy, verse, onyx, fable, echo. "
            "Gib eine kurze assistant_message, die dem Nutzer die Analyse und evtl. Rückfragen zusammenfasst. "
            "Erstelle zusätzlich eine placement_preview mit:\n"
            "- room_objects: nur Objekte am Boden (y nahe 0) mit id, name, position (x,y,z) und radius.\n"
            "- agent_placements: sinnvolle, kontextbezogene Agentenpositionen (x,y,z; y=0).\n"
            "Achte darauf, dass Agenten nicht mit room_objects überlappen und untereinander "
            "einen Mindestabstand halten. Verwende nur die RDLI-Informationen für Objektlage."
            "\n\nRDLI JSON:\n"
            f"{arrow_text}"
        )

        input_msgs: List[Dict[str, Any]] = [{"role": "developer", "content": dev_prompt}]
        if current_summary:
            input_msgs.append(
                {
                    "role": "developer",
                    "content": "Aktueller Entwurf (bei Aktualisierung berücksichtigen):\n" + current_summary,
                }
            )
        for m in history:
            input_msgs.append({"role": m["role"], "content": m["content"]})

        try:
            parsed, resp, out_text = self.openai.create_structured_json(
                model=self.model,
                input_messages=input_msgs,
                schema=schema,
                schema_name="arrow_project",
                temperature=self.temperature,
            )
        except OpenAIHTTPError as e:
            if e.status != 400:
                raise
            parsed, resp, out_text = self.openai.create_json_object(
                model=self.model,
                input_messages=input_msgs,
                temperature=self.temperature,
            )

        return self._normalize_arrow_draft(parsed, room_plan=arrow_payload, fallback=current)

    def _normalize_arrow_draft(
        self,
        parsed: Dict[str, Any],
        *,
        room_plan: Dict[str, Any],
        fallback: Optional[ArrowProjectDraft] = None,
    ) -> Dict[str, Any]:
        fallback_project = fallback.project if fallback else {}
        fallback_agents = fallback.agents if fallback else []
        fallback_knowledge = fallback.knowledge if fallback else []

        assistant_message = str(parsed.get("assistant_message") or fallback.assistant_message if fallback else "").strip()
        analysis = str(parsed.get("analysis") or fallback.analysis if fallback else "").strip()

        project_data = parsed.get("project") or {}
        display_name = str(project_data.get("display_name") or fallback_project.get("display_name") or "Neues Projekt").strip()
        description = str(project_data.get("description") or fallback_project.get("description") or "").strip()

        agents_raw = parsed.get("agents")
        if not isinstance(agents_raw, list):
            agents_raw = fallback_agents
        agents: List[Dict[str, Any]] = []
        for idx, agent in enumerate(agents_raw or []):
            if not isinstance(agent, dict):
                continue
            display = str(agent.get("display_name") or f"Agent {idx+1}").strip()
            agent_id = str(agent.get("id") or _slugify(display) or f"agent_{idx+1}").strip()
            persona = str(agent.get("persona") or "").strip()
            voice = str(agent.get("voice") or "").strip()
            voice_gender = str(agent.get("voice_gender") or "").strip()
            voice_style = str(agent.get("voice_style") or "").strip()
            tts_model = str(agent.get("tts_model") or "").strip()
            expertise = agent.get("expertise") or []
            if isinstance(expertise, str):
                expertise = [expertise]
            knowledge_tags = agent.get("knowledge_tags") or []
            if isinstance(knowledge_tags, str):
                knowledge_tags = [knowledge_tags]
            if not voice_gender and voice:
                if voice in {"coral", "nova", "shimmer"}:
                    voice_gender = "weiblich"
                elif voice in {"alloy", "verse", "onyx", "fable", "echo"}:
                    voice_gender = "männlich"
            if not voice and voice_gender:
                voice = "coral" if voice_gender == "weiblich" else "alloy"
            if not voice:
                voice = "alloy"
            if not voice_gender:
                voice_gender = "weiblich" if voice in {"coral", "nova", "shimmer"} else "männlich"
            if not voice_style:
                voice_style = "neutral"
            if tts_model.lower() == "standard":
                tts_model = ""
            if not tts_model:
                tts_model = "gpt-4o-mini-tts"
            agents.append(
                {
                    "id": agent_id,
                    "display_name": display,
                    "persona": persona,
                    "voice": voice,
                    "voice_gender": voice_gender,
                    "voice_style": voice_style,
                    "tts_model": tts_model,
                    "expertise": [str(x) for x in expertise],
                    "knowledge_tags": [str(x) for x in knowledge_tags],
                }
            )

        knowledge_raw = parsed.get("knowledge")
        if not isinstance(knowledge_raw, list):
            knowledge_raw = fallback_knowledge
        knowledge: List[Dict[str, Any]] = []
        for entry in knowledge_raw or []:
            if not isinstance(entry, dict):
                continue
            tag = str(entry.get("tag") or "").strip()
            name = str(entry.get("name") or "").strip()
            text = str(entry.get("text") or "").strip()
            knowledge.append({"tag": tag, "name": name, "text": text})

        placement_preview_raw = parsed.get("placement_preview")
        placement_preview_fallback = fallback.placement_preview if fallback else {}
        placement_preview = normalize_placement_preview(
            room_plan,
            agents,
            placement_preview_raw if isinstance(placement_preview_raw, dict) else placement_preview_fallback,
        )

        return {
            "assistant_message": assistant_message,
            "analysis": analysis,
            "project": {
                "display_name": display_name,
                "description": description,
            },
            "agents": agents,
            "knowledge": knowledge,
            "placement_preview": placement_preview,
        }

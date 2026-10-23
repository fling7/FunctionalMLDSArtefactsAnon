"""Gate 0: native-model routing verification, independent of backend code.

The structural authoring validator is a separate baseline. This module only
implements model-bound admission semantics from SPEC v1 and its amendments.
Request identity, the session pin, active-agent tracking, request schemas and
commit checks remain runtime obligations.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict, deque
from pathlib import Path
from typing import Any, Mapping

DIGEST_SCHEME = "sha256-lf-v1"
CHECK_REGISTRY = {
    "INV-075": {"code": "ROUTE075", "severity": "error", "check": "unique deciding-level owner"},
    "INV-076": {"code": "ROUTE076", "severity": "error", "check": "owner exists"},
    "INV-077": {"code": "ROUTE077", "severity": "error", "check": "unique native answering path and matching trace"},
    "INV-078": {"code": "ROUTE078", "severity": "error", "check": "agent-only, distinct, non-self handoff targets"},
    "INV-079": {"code": "ROUTE079", "severity": "warning", "check": "uncovered latent shared ownership"},
    "INV-080": {"code": "ROUTE080", "severity": "report", "check": "pairs requiring multiple handoffs or without a path"},
    "INV-081": {"code": "ROUTE081", "severity": "error", "check": "declared LF-normalized serialization digest"},
}


def serialization_digest(raw: bytes) -> str:
    return hashlib.sha256(raw.replace(b"\r\n", b"\n")).hexdigest().upper()


def _refs(obj: Mapping[str, Any], key: str) -> list[str]:
    value = obj.get(key, [])
    return value if isinstance(value, list) and all(isinstance(x, str) for x in value) else []


def _type(obj: Mapping[str, Any]) -> str:
    return str(obj.get("type", "")).rsplit("::", 1)[-1]


def _reject(reason: str) -> dict[str, Any]:
    return {"decision": "REJECT", "reason": reason, "provider": None, "action": None}


class NativeRoutingIndex:
    """Independent reader of native objects and their declaration references."""
    def __init__(self, instance: Mapping[str, Any], trace: Mapping[str, Any]):
        records = instance.get("objects") if isinstance(instance, Mapping) else None
        if not isinstance(records, list) or not isinstance(trace, Mapping):
            raise ValueError("instance.objects and trace must be list/object")
        self.by_id: dict[str, dict[str, Any]] = {}
        for record in records:
            if not isinstance(record, dict) or not isinstance(record.get("id"), str) or not record["id"]:
                raise ValueError("native records require nonempty string IDs")
            if record["id"] in self.by_id:
                raise ValueError("duplicate native object ID: " + record["id"])
            self.by_id[record["id"]] = record
        self.agents = {i: o for i, o in self.by_id.items() if _type(o) == "Agent"}
        self.objects = {i: o for i, o in self.by_id.items() if _type(o) == "Entity" and o.get("kind") == "asset" and o.get("entityRole") == "sceneObject"}
        self.groups = {i: o for i, o in self.by_id.items() if _type(o) == "Entity" and o.get("kind") == "asset" and o.get("entityRole") == "objectGroup"}
        self.zones = {i: o for i, o in self.by_id.items() if _type(o) == "Entity" and o.get("kind") == "zone"}
        self.wire = {i: o.get("sourceAgentId") for i, o in self.agents.items()}
        if any(not isinstance(v, str) or not v for v in self.wire.values()):
            raise ValueError("agents require nonempty sourceAgentId values")
        self.duplicate_wire_ids = {wire for wire in self.wire.values() if list(self.wire.values()).count(wire) > 1}
        self.owners: dict[str, dict[str, set[str]]] = {key: defaultdict(set) for key in ("groundedAsset", "groundedObjectGroup", "responsibleZone")}
        for aid, agent in self.agents.items():
            for key in self.owners:
                for target in _refs(agent, key):
                    self.owners[key][target].add(aid)
        self.steps: dict[str, list[str]] = defaultdict(list)
        self.uses: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        self.bindings: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for oid, obj in self.by_id.items():
            typ = _type(obj)
            if typ == "ScenarioStep":
                for use in _refs(obj, "capabilityUse"):
                    self.steps[use].append(oid)
            elif typ == "CapabilityUse":
                for provider in set(_refs(obj, "provider")):
                    for target in set(_refs(obj, "target")):
                        self.uses[provider, target].append(obj)
            elif typ == "RuntimeBinding":
                for capability in set(_refs(obj, "capability")):
                    self.bindings[capability].append(obj)
        actions = trace.get("runtime_actions", [])
        if not isinstance(actions, list) or not all(isinstance(x, dict) for x in actions):
            raise ValueError("trace.runtime_actions must contain objects")
        self.trace_by_use: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for entry in actions:
            if entry.get("action_kind") == "chat":
                self.trace_by_use[str(entry.get("capability_use_id", ""))].append(entry)
        self.answer_kind: dict[str, bool] = {}
        for oid, obj in self.by_id.items():
            if _type(obj) == "RuntimeAction":
                self.answer_kind[oid] = self._is_answering(obj)

    def _is_answering(self, action: Mapping[str, Any]) -> bool:
        explicit = []
        for schema_id in _refs(action, "inputSchema"):
            schema = self.by_id.get(schema_id, {})
            try:
                parsed = json.loads(schema.get("text", "null"))
            except (ValueError, TypeError):
                continue
            if isinstance(parsed, dict) and "applicationActionKind" in parsed:
                explicit.append(parsed["applicationActionKind"])
        if explicit:
            return "chat" in explicit
        return any(self.by_id.get(loc, {}).get("kind") == "endpoint" and self.by_id.get(loc, {}).get("value") == "POST /chat" for loc in _refs(action, "locator"))

    def ownership(self, target: str) -> tuple[str | None, list[str]]:
        obj = self.objects[target]
        groups = _refs(obj, "objectGroup")
        zones = [z for z, row in self.zones.items() if obj.get("sourceId") in _refs(row, "sourceObjectId")]
        for level, key, ids in [("asset", "groundedAsset", [target]), ("group", "groundedObjectGroup", groups), ("zone", "responsibleZone", zones)]:
            owners: set[str] = set()
            for oid in ids:
                owners.update(self.owners[key].get(oid, set()))
            if owners:
                return level, sorted(owners)
        return None, []

    def answering_path(self, provider: str, target: str) -> tuple[str | None, str | None]:
        selected = []
        for use in self.uses.get((provider, target), []):
            caps = _refs(use, "typeRef")
            candidates = []
            for cap in caps:
                for binding in self.bindings.get(cap, []):
                    for action in _refs(binding, "runtimeAction"):
                        if self.answer_kind.get(action, False):
                            candidates.append((cap, binding, action))
            # Only a native route can identify an answering use. A trace-only
            # or broken use never adds a second path beside a complete one.
            if candidates and self.steps.get(use["id"]):
                selected.append((use, candidates))
        if len(selected) > 1:
            return "E_ACTION_AMBIGUOUS", None
        if not selected:
            return "E_NO_DECLARED_ACTION", None
        use, candidates = selected[0]
        caps = _refs(use, "typeRef")
        steps = self.steps.get(use["id"], [])
        if len(caps) > 1 or len(_refs(use, "provider")) > 1 or len(candidates) > 1 or len(steps) > 1:
            return "E_ACTION_AMBIGUOUS", None
        if len(caps) != 1 or len(candidates) != 1 or len(steps) != 1 or _refs(use, "provider") != [provider]:
            return "E_NO_DECLARED_ACTION", None
        cap, binding, action = candidates[0]
        if _type(self.by_id.get(cap, {})) != "Capability" or cap not in _refs(self.agents[provider], "providedCapability"):
            return "E_NO_DECLARED_ACTION", None
        if _refs(binding, "capability") != [cap]:
            return "E_NO_DECLARED_ACTION", None
        expected = {"scenario_step_id": steps[0], "capability_use_id": use["id"], "capability_id": cap, "provider_entity_id": provider, "runtime_binding_id": binding["id"], "runtime_action_id": action}
        projections = self.trace_by_use.get(use["id"], [])
        matching = [row for row in projections if all(row.get(k) == v for k, v in expected.items()) and set(_refs(row, "target_ids")) == set(_refs(use, "target"))]
        if len(matching) > 1:
            return "E_ACTION_AMBIGUOUS", None
        if len(matching) != 1:
            return "E_NO_DECLARED_ACTION", None
        return None, action

    def distance(self, start: str, end: str) -> int | None:
        queue = deque([(start, 0)])
        seen = {start}
        while queue:
            node, depth = queue.popleft()
            if node == end:
                return depth
            for nxt in _refs(self.agents.get(node, {}), "handoffTarget"):
                if nxt in self.agents and nxt not in seen:
                    seen.add(nxt)
                    queue.append((nxt, depth + 1))
        return None


def verify_routing(instance: Mapping[str, Any], trace: Mapping[str, Any], *, model_sha256: str,
                   project: Mapping[str, Any] | None = None, model_bytes: bytes | None = None) -> dict[str, Any]:
    """Return deterministic Gate 0 issues and the full model-only decision table.

    INV-081 is explicitly not evaluated for in-memory calls without publication
    metadata and source bytes. Use load_and_verify for a publishable artifact.
    Invalid models still receive tables for comparison; never cache them as verified.
    """
    digest = str(model_sha256).upper()
    result: dict[str, Any] = {"format": "rcm-routing-table-v1", "model_sha256": digest, "digest_scheme": DIGEST_SCHEME, "ok": True, "issues": [], "checks": {}, "routing_table": {}, "objects": {}, "ownership": {}, "latent_ambiguities": [], "reachability": []}
    issues = result["issues"]
    def issue(inv: str, location: str, message: str, **details: Any) -> None:
        item = CHECK_REGISTRY[inv]
        issues.append({"invariant": inv, "code": item["code"], "severity": item["severity"], "location": location, "message": message, **details})
    try:
        index = NativeRoutingIndex(instance, trace)
    except (ValueError, TypeError) as exc:
        result.update(ok=False)
        issues.append({"invariant": None, "code": "E_PUBLICATION_INCONSISTENT", "severity": "error", "location": "instance", "message": str(exc)})
        return result
    if index.duplicate_wire_ids:
        issues.append({"invariant": None, "code": "E_PUBLICATION_INCONSISTENT", "severity": "error", "location": "agents", "message": "Duplicate wire agent IDs cannot identify a unique table row.", "duplicate_wire_ids": sorted(index.duplicate_wire_ids)})
    for aid, agent in sorted(index.agents.items()):
        targets = _refs(agent, "handoffTarget")
        raw = agent.get("handoffTarget", [])
        if not isinstance(raw, list) or len(targets) != len(raw) or len(set(targets)) != len(targets) or aid in targets or any(t not in index.agents for t in targets):
            issue("INV-078", aid, "Handoff targets must be distinct other Agent records.")
    paths: dict[str, tuple[str | None, str | None]] = {}
    for target, obj in sorted(index.objects.items()):
        result["objects"][target] = obj.get("sourceId")
        level, owners = index.ownership(target)
        result["ownership"][target] = {"level": level, "owners": [index.wire[a] for a in owners]}
        if len(owners) > 1:
            issue("INV-075", target, "Several owners at the deciding level; no fallback is allowed.", level=level, owners=[index.wire[a] for a in owners])
        elif not owners:
            issue("INV-076", target, "No owner exists at asset, group, or zone level.")
        else:
            paths[target] = index.answering_path(owners[0], target)
            if paths[target][0]:
                issue("INV-077", target, "The selected answering declaration is missing, broken, or ambiguous.", reason=paths[target][0], provider=index.wire[owners[0]])
    for kind, entities, owner_key in [("group", index.groups, "groundedObjectGroup"), ("zone", index.zones, "responsibleZone")]:
        for oid, obj in sorted(entities.items()):
            owners = index.owners[owner_key].get(oid, set())
            if len(owners) > 1:
                members = sorted(t for t, o in index.objects.items() if (oid in _refs(o, "objectGroup") if kind == "group" else o.get("sourceId") in _refs(obj, "sourceObjectId")))
                uncovered = [t for t in members if len(index.owners["groundedAsset"].get(t, set())) != 1]
                result["latent_ambiguities"].append({"entity": oid, "kind": kind, "owners": sorted(index.wire[a] for a in owners), "members": members, "uncovered_members": uncovered, "shielded": not uncovered})
                if uncovered:
                    issue("INV-079", oid, "Shared ownership has members without unique asset-level coverage.", uncovered_members=uncovered)
    for start in sorted(index.agents, key=lambda a: index.wire[a]):
        table = result["routing_table"].setdefault(index.wire[start], {})
        for target in sorted(index.objects):
            level, owners = index.ownership(target)
            if index.wire[start] in index.duplicate_wire_ids:
                verdict = _reject("E_ACTIVE_AGENT_UNKNOWN")
            elif not owners:
                verdict = _reject("E_UNOWNED")
            elif len(owners) > 1:
                verdict = _reject("E_AMBIGUOUS_OWNER")
            else:
                provider = owners[0]
                distance = index.distance(start, provider)
                if distance is None or distance > 1:
                    verdict = _reject("E_NO_HANDOFF_PATH")
                    row = {"start_agent": index.wire[start], "target": target, "provider": index.wire[provider], "shortest_handoffs": distance, "classification": "no_path" if distance is None else "multi_hop"}
                    result["reachability"].append(row)
                    issue("INV-080", f"{index.wire[start]}/{target}", "The provider is outside the one-handoff admission limit.", **row)
                elif paths[target][0]:
                    verdict = _reject(paths[target][0])
                else:
                    verdict = {"decision": "ANSWER_LOCAL" if start == provider else "ANSWER_AFTER_HANDOFF", "reason": None, "provider": index.wire[provider], "action": paths[target][1]}
            table[target] = verdict
    digest_evaluated = project is not None or model_bytes is not None
    if digest_evaluated:
        if project is None or model_bytes is None:
            issue("INV-081", "publication", "Digest verification requires project metadata and serialized model bytes.")
        else:
            calculated = serialization_digest(model_bytes)
            for location, declared_digest, scheme in [("project", project.get("roomcontract_model_sha256"), project.get("roomcontract_digest_scheme")), ("trace", trace.get("model_sha256"), trace.get("digest_scheme"))]:
                if scheme != DIGEST_SCHEME or str(declared_digest).upper() != calculated or digest != calculated:
                    legacy = hashlib.sha256(model_bytes).hexdigest().upper()
                    issue("INV-081", location, "Publish profile requires an explicit sha256-lf-v1 scheme and matching serialization digest.", declared_scheme=scheme, declared_digest=declared_digest, canonical_digest=calculated, legacy_raw_digest=legacy, legacy_digest_matches=str(declared_digest).upper() == legacy)
    for inv, check in CHECK_REGISTRY.items():
        found = sum(x.get("invariant") == inv for x in issues)
        result["checks"][inv] = {"code": check["code"], "status": "not evaluated" if inv == "INV-081" and not digest_evaluated else ("fail" if found else "pass"), "issue_count": found}
    result["ok"] = not any(x["severity"] == "error" for x in issues)
    return result


def lookup_route(report: Mapping[str, Any], start_agent_id: str, entity_id: str) -> dict[str, Any]:
    if start_agent_id not in report.get("routing_table", {}):
        return _reject("E_ACTIVE_AGENT_UNKNOWN")
    return dict(report["routing_table"][start_agent_id].get(entity_id, _reject("E_UNKNOWN_ENTITY")))


def load_and_verify(instance_path: str | Path, trace_path: str | Path, project_path: str | Path | None = None) -> dict[str, Any]:
    raw = Path(instance_path).read_bytes()
    trace = json.loads(Path(trace_path).read_text(encoding="utf-8-sig"))
    project = json.loads(Path(project_path).read_text(encoding="utf-8-sig")) if project_path is not None else None
    return verify_routing(json.loads(raw.decode("utf-8-sig")), trace, model_sha256=serialization_digest(raw), project=project, model_bytes=raw)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--instance", required=True, type=Path)
    parser.add_argument("--trace", required=True, type=Path)
    parser.add_argument("--project", required=True, type=Path)
    parser.add_argument("--output", type=Path, default=Path("routing_table.json"))
    args = parser.parse_args()
    report = load_and_verify(args.instance, args.trace, args.project)
    artifact = {"format": "rcm-routing-publication-v1", "by_digest": {report["model_sha256"]: report}}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(artifact, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"ok": report["ok"], "pairs": sum(len(v) for v in report["routing_table"].values()), "issues": len(report["issues"]), "output": str(args.output)}))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

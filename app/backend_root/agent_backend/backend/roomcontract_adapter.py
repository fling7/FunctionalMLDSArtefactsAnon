from __future__ import annotations

import importlib
import hashlib
import json
import re
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


BACKEND_RELATIVE_ROOT = Path("app/backend_root/agent_backend")
DEFAULT_OUTPUT_RELATIVE_ROOT = Path("output/wizard_roomcontract")

STAGE_RUNNERS: Dict[str, Tuple[str, str]] = {
    "rdl_ingestion": ("rdl_ingestion", "run_ingestion_for_case"),
    "scene_semantics": ("scene_semantics", "run_scene_semantics_for_case"),
    "agent_roles": ("agent_roles", "run_agent_roles_for_case"),
    "knowledge_synthesis": ("knowledge_synthesis", "run_knowledge_synthesis_for_case"),
    "agent_placement": ("agent_placement", "run_agent_placement_for_case"),
    "placement_metrics": (
        "validators.placement_metrics",
        "run_placement_metrics_for_case",
    ),
    "roomcontract_assembly": ("roomcontract_assembler", "run_roomcontract_assembly_for_case"),
    "handoff_derivation": ("handoff_derivation", "run_handoff_derivation_for_case"),
    "roomcontract_v2_assembly": (
        "roomcontract_v2_assembler",
        "run_roomcontract_v2_assembly_for_case",
    ),
    "project_materialization": ("project_materializer", "run_project_materializer_for_case"),
    "schema_validation": ("validators.schema_validator", "run_schema_validation_for_case"),
    "roomcontract_invariants": (
        "validators.roomcontract_invariants",
        "run_roomcontract_invariant_validation_for_case",
    ),
    "traceability_metrics": ("validators.traceability_metrics", "run_traceability_metrics_for_case"),
    "handoff_metrics": ("validators.handoff_metrics", "run_handoff_metrics_for_case"),
    "stage_completion": ("stage_completion", "run_stage_completion_for_case"),
}

ANALYZE_STAGE_IDS = (
    "rdl_ingestion",
    "scene_semantics",
    "agent_roles",
    "knowledge_synthesis",
    "agent_placement",
    "placement_metrics",
    "roomcontract_assembly",
    "handoff_derivation",
    "roomcontract_v2_assembly",
    "roomcontract_invariants",
)

ANALYZE_PREVIEW_ARTIFACTS = {
    "normalized_scene": "intermediate/scene_graph.normalized.json",
    "object_group_summary": "intermediate/object_group_summary.json",
    "scene_semantics": "intermediate/scene_semantics.json",
    "agent_roles": "intermediate/agent_roles.generated.json",
    "handoff_matrix": "intermediate/handoff_matrix.json",
    "knowledge": "intermediate/knowledge.generated.json",
    "agent_placements": "intermediate/agent_placements.json",
    "placement_metrics": "validation/placement_metrics.json",
    "roomcontract": "roomcontract/roomcontract.instance.generated.json",
    "roomcontract_v2": "roomcontract/roomcontract.v2.instance.json",
    "roomcontract_validation": "validation/roomcontract_invariant_validation.json",
    "handoff_derivation_validation": "validation/handoff_derivation_validation.json",
    "roomcontract_v2_validation": "roomcontract/roomcontract.v2.assembly_report.json",
    "roomcontract_explicit_invariants": "validation/roomcontract_invariants_validation.json",
}

ANALYZE_VALIDATION_ARTIFACTS = {
    "rdl_ingestion": "validation/rdl_ingestion_validation.json",
    "scene_semantics": "validation/scene_semantics_validation.json",
    "agent_roles": "validation/agent_roles_validation.json",
    "knowledge_synthesis": "validation/knowledge_synthesis_validation.json",
    "agent_placement": "validation/agent_placement_validation.json",
    "placement_metrics": "validation/placement_metrics.json",
    "roomcontract_assembly": "validation/roomcontract_invariant_validation.json",
    "handoff_derivation": "validation/handoff_derivation_validation.json",
    "roomcontract_v2_assembly": "roomcontract/roomcontract.v2.assembly_report.json",
    "roomcontract_invariants": "validation/roomcontract_invariants_validation.json",
}

COMMIT_STAGE_IDS = (
    *ANALYZE_STAGE_IDS,
    "project_materialization",
    "schema_validation",
    "traceability_metrics",
    "handoff_metrics",
)

COMMIT_REQUIRED_ARTIFACTS = {
    **ANALYZE_PREVIEW_ARTIFACTS,
    "project_materialization_validation": "validation/project_materialization_validation.json",
    "schema_validation": "validation/schema_validation.json",
    "traceability_metrics": "validation/traceability_metrics.json",
    "handoff_metrics": "validation/handoff_metrics.json",
    "backend_project": "projects/{case_id}/project.json",
    "backend_room_plan": "projects/{case_id}/room_plan.json",
    "backend_agents": "projects/{case_id}/agents.json",
    "backend_trace_map": "projects/{case_id}/trace_map.json",
    "backend_trace_map_v2": "projects/{case_id}/trace_map.v2.json",
    "backend_trace_map_v05": "projects/{case_id}/trace_map.v05.json",
    "backend_roomcontract_v2": "projects/{case_id}/roomcontract.v2.instance.json",
    "backend_roomcontract_v05": "projects/{case_id}/roomcontract.v05.instance.json",
    "backend_kb_root": "projects/{case_id}/kb",
}

COMMIT_VALIDATION_ARTIFACTS = {
    **ANALYZE_VALIDATION_ARTIFACTS,
    "project_materialization": "validation/project_materialization_validation.json",
    "schema_validation": "validation/schema_validation.json",
    "traceability_metrics": "validation/traceability_metrics.json",
    "handoff_metrics": "validation/handoff_metrics.json",
}

DETERMINISTIC_FIRST_STAGE_SPECS = {
    "rdl_ingestion": {
        "inputs": ["input/source_rdl.json"],
        "outputs": [
            "intermediate/scene_graph.normalized.json",
            "intermediate/object_group_summary.json",
            "validation/rdl_ingestion_validation.json",
        ],
        "validation": "validation/rdl_ingestion_validation.json",
        "repair_type": "deterministic_normalization",
    },
    "scene_semantics": {
        "inputs": ["intermediate/scene_graph.normalized.json", "intermediate/object_group_summary.json"],
        "outputs": ["intermediate/scene_semantics.json", "validation/scene_semantics_validation.json"],
        "validation": "validation/scene_semantics_validation.json",
        "repair_type": "deterministic_recovery",
        "llm_stage": True,
    },
    "agent_roles": {
        "inputs": [
            "intermediate/scene_graph.normalized.json",
            "intermediate/object_group_summary.json",
            "intermediate/scene_semantics.json",
        ],
        "outputs": [
            "intermediate/agent_roles.generated.json",
            "intermediate/handoff_matrix.json",
            "validation/agent_roles_validation.json",
        ],
        "validation": "validation/agent_roles_validation.json",
        "repair_type": "deterministic_recovery",
        "llm_stage": True,
    },
    "knowledge_synthesis": {
        "inputs": [
            "intermediate/scene_graph.normalized.json",
            "intermediate/scene_semantics.json",
            "intermediate/agent_roles.generated.json",
        ],
        "outputs": [
            "intermediate/knowledge.generated.json",
            "validation/knowledge_synthesis_validation.json",
        ],
        "validation": "validation/knowledge_synthesis_validation.json",
        "repair_type": "deterministic_recovery",
        "llm_stage": True,
    },
    "agent_placement": {
        "inputs": [
            "intermediate/scene_graph.normalized.json",
            "intermediate/scene_semantics.json",
            "intermediate/agent_roles.generated.json",
        ],
        "outputs": ["intermediate/agent_placements.json", "validation/agent_placement_validation.json"],
        "validation": "validation/agent_placement_validation.json",
        "validation_contract": {"placement_algorithm_version": "2.0.0"},
        "repair_type": "deterministic_geometry_recompute",
    },
    "placement_metrics": {
        "inputs": [
            "intermediate/scene_graph.normalized.json",
            "intermediate/scene_semantics.json",
            "intermediate/agent_roles.generated.json",
            "intermediate/agent_placements.json",
        ],
        "outputs": ["validation/placement_metrics.json"],
        "validation": "validation/placement_metrics.json",
        "repair_type": "deterministic_metrics_regeneration",
    },
    "roomcontract_assembly": {
        "inputs": [
            "intermediate/scene_graph.normalized.json",
            "intermediate/scene_semantics.json",
            "intermediate/agent_roles.generated.json",
            "intermediate/agent_placements.json",
        ],
        "outputs": [
            "roomcontract/roomcontract.instance.generated.json",
            "validation/roomcontract_invariant_validation.json",
        ],
        "validation": "validation/roomcontract_invariant_validation.json",
        "repair_type": "deterministic_regeneration",
    },
    "handoff_derivation": {
        "inputs": [
            "intermediate/agent_roles.generated.json",
            "intermediate/handoff_matrix.json",
            "roomcontract/roomcontract.instance.generated.json",
        ],
        "outputs": [
            "intermediate/agent_roles.generated.json",
            "intermediate/handoff_matrix.json",
            "roomcontract/roomcontract.instance.generated.json",
            "validation/handoff_derivation_validation.json",
        ],
        "validation": "validation/handoff_derivation_validation.json",
        "repair_type": "deterministic_regeneration",
    },
    "roomcontract_v2_assembly": {
        "inputs": [
            "roomcontract/roomcontract.instance.generated.json",
        ],
        "outputs": [
            "roomcontract/roomcontract.v2.instance.json",
            "roomcontract/roomcontract.v2.assembly_report.json",
        ],
        "validation": "roomcontract/roomcontract.v2.assembly_report.json",
        "repair_type": "deterministic_regeneration",
    },
    "roomcontract_invariants": {
        "inputs": ["roomcontract/roomcontract.instance.generated.json"],
        "outputs": ["validation/roomcontract_invariants_validation.json"],
        "validation": "validation/roomcontract_invariants_validation.json",
        "repair_type": "deterministic_regeneration",
    },
    "project_materialization": {
        "inputs": [
            "input/source_rdl.json",
            "intermediate/agent_roles.generated.json",
            "intermediate/agent_placements.json",
            "intermediate/knowledge.generated.json",
            "roomcontract/roomcontract.instance.generated.json",
            "roomcontract/roomcontract.v2.instance.json",
        ],
        "outputs": ["validation/project_materialization_validation.json"],
        "validation": "validation/project_materialization_validation.json",
        "repair_type": "deterministic_regeneration",
    },
    "schema_validation": {
        "inputs": [
            "roomcontract/roomcontract.instance.generated.json",
            "roomcontract/roomcontract.v2.instance.json",
        ],
        "outputs": ["validation/schema_validation.json"],
        "validation": "validation/schema_validation.json",
        "repair_type": "deterministic_regeneration",
    },
    "traceability_metrics": {
        "inputs": ["roomcontract/roomcontract.instance.generated.json"],
        "outputs": ["validation/traceability_metrics.json"],
        "validation": "validation/traceability_metrics.json",
        "repair_type": "deterministic_regeneration",
    },
    "handoff_metrics": {
        "inputs": [
            "intermediate/agent_roles.generated.json",
            "intermediate/handoff_matrix.json",
        ],
        "outputs": ["validation/handoff_metrics.json"],
        "validation": "validation/handoff_metrics.json",
        "repair_type": "deterministic_regeneration",
    },
}


@dataclass(frozen=True)
class RoomContractAdapterPaths:
    workspace_root: Path
    backend_root: Path
    pipeline_root: Path
    output_root: Path


@dataclass
class RoomContractAdapter:
    paths: RoomContractAdapterPaths

    @classmethod
    def discover(
        cls,
        *,
        workspace_root: Optional[Path] = None,
        backend_root: Optional[Path] = None,
        output_root: Optional[Path] = None,
    ) -> "RoomContractAdapter":
        workspace = workspace_root.resolve() if workspace_root else find_workspace_root()
        backend = backend_root.resolve() if backend_root else (workspace / BACKEND_RELATIVE_ROOT).resolve()
        pipeline = (workspace / "tools" / "case_study_pipeline").resolve()
        output = output_root.resolve() if output_root else (workspace / DEFAULT_OUTPUT_RELATIVE_ROOT).resolve()

        if not backend.exists():
            raise FileNotFoundError(f"Backend root nicht gefunden: {backend}")
        if not pipeline.exists():
            raise FileNotFoundError(f"RoomContract-Pipeline nicht gefunden: {pipeline}")

        return cls(
            RoomContractAdapterPaths(
                workspace_root=workspace,
                backend_root=backend,
                pipeline_root=pipeline,
                output_root=output,
            )
        )

    def ensure_pipeline_importable(self) -> None:
        workspace = str(self.paths.workspace_root)
        if workspace not in sys.path:
            sys.path.insert(0, workspace)

    def import_pipeline_module(self, module_name: str):
        self.ensure_pipeline_importable()
        return importlib.import_module(f"tools.case_study_pipeline.{module_name}")

    def validate_environment(self) -> Dict[str, str]:
        self.ensure_pipeline_importable()
        ingestion = self.import_pipeline_module("rdl_ingestion")
        if not hasattr(ingestion, "initialize_case") or not hasattr(ingestion, "run_ingestion_for_case"):
            raise RuntimeError("rdl_ingestion stellt die erwarteten Funktionen nicht bereit.")
        return {
            "workspace_root": str(self.paths.workspace_root),
            "backend_root": str(self.paths.backend_root),
            "pipeline_root": str(self.paths.pipeline_root),
            "output_root": str(self.paths.output_root),
        }

    def analyze_stage_plan(self) -> Dict[str, Any]:
        return {
            "stages": list(ANALYZE_STAGE_IDS),
            "artifacts": dict(ANALYZE_PREVIEW_ARTIFACTS),
            "validations": dict(ANALYZE_VALIDATION_ARTIFACTS),
            "materializes_backend_project": False,
            "requires_llm": True,
            "stops_before_commit": True,
            "requires_valid_analyze_gate": True,
        }

    def commit_stage_plan(self, *, case_id: str = "{case_id}") -> Dict[str, Any]:
        safe_case_id = require_safe_case_id(case_id) if case_id != "{case_id}" else case_id
        artifacts = {
            key: value.format(case_id=safe_case_id)
            for key, value in COMMIT_REQUIRED_ARTIFACTS.items()
        }
        return {
            "stages": list(COMMIT_STAGE_IDS),
            "artifacts": artifacts,
            "validations": dict(COMMIT_VALIDATION_ARTIFACTS),
            "materializes_backend_project": True,
            "requires_llm": True,
            "requires_valid_materialization": True,
            "minimum_blocking_validations": [
                "roomcontract_invariants",
                "project_materialization",
                "schema_validation",
            ],
            "required_metric_reports": [
                "traceability_metrics",
                "handoff_metrics",
            ],
        }

    def initialize_case_from_payload(self, payload: Dict[str, Any], *, case_id: str) -> Dict[str, str]:
        if not isinstance(payload, dict):
            raise ValueError("RDL-Payload muss ein Objekt sein.")
        safe_case_id = require_safe_case_id(case_id)
        self.ensure_case_can_be_written(payload, safe_case_id)
        source_path = self.write_source_payload(payload, safe_case_id)
        ingestion = self.import_pipeline_module("rdl_ingestion")
        initialized = ingestion.initialize_case(source_path, self.paths.output_root, safe_case_id)
        return {
            "case_id": safe_case_id,
            "source_path": str(source_path),
            "case_dir": str(initialized["case_dir"]),
            "source_copy": str(initialized["source_copy"]),
            "hash_path": str(initialized["hash_path"]),
        }

    def write_source_payload(self, payload: Dict[str, Any], case_id: str) -> Path:
        safe_case_id = require_safe_case_id(case_id)
        source_path = self.paths.output_root / "_wizard_inputs" / f"{safe_case_id}.source_rdl.json"
        source_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return source_path

    def derive_case_id(
        self,
        payload: Dict[str, Any],
        *,
        project_id_hint: str = "",
        display_name: str = "",
        include_hash: bool = True,
    ) -> str:
        return derive_case_id(
            payload,
            project_id_hint=project_id_hint,
            display_name=display_name,
            include_hash=include_hash,
        )

    def ensure_case_can_be_written(self, payload: Dict[str, Any], case_id: str, *, allow_overwrite: bool = False) -> None:
        safe_case_id = require_safe_case_id(case_id)
        case_dir = self.paths.output_root / safe_case_id
        if allow_overwrite or not case_dir.exists():
            return

        new_hash = payload_hash(payload)
        existing_source_path = case_dir / "input" / "source_rdl.json"
        if existing_source_path.exists():
            existing_payload = json.loads(existing_source_path.read_text(encoding="utf-8"))
            if payload_hash(existing_payload) == new_hash:
                return
            raise FileExistsError(
                f"Case-Verzeichnis existiert bereits mit anderem RDL-Payload: {case_dir}. "
                "Bitte andere Projekt-ID waehlen oder bewusstes Ueberschreiben implementieren."
            )

        existing_hash_path = case_dir / "input" / "source_rdl.sha256"
        if existing_hash_path.exists():
            raise FileExistsError(
                f"Case-Verzeichnis existiert bereits, aber source_rdl.json fehlt: {case_dir}. "
                "Bitte andere Projekt-ID waehlen oder bewusstes Ueberschreiben implementieren."
            )

        if any(case_dir.iterdir()):
            raise FileExistsError(
                f"Case-Verzeichnis existiert bereits und besitzt keinen vergleichbaren Source-Hash: {case_dir}."
            )

    def run_stage(self, case_dir: Path, stage_id: str, **kwargs: Any) -> Dict[str, Any]:
        if stage_id not in STAGE_RUNNERS:
            allowed = ", ".join(sorted(STAGE_RUNNERS))
            raise ValueError(f"Unbekannte RoomContract-Stage: {stage_id}. Erlaubt: {allowed}.")

        module_name, function_name = STAGE_RUNNERS[stage_id]
        module = self.import_pipeline_module(module_name)
        runner = getattr(module, function_name)
        case_path = Path(case_dir).resolve()

        if stage_id in {"project_materialization", "schema_validation"}:
            kwargs.setdefault("backend_root", self.paths.backend_root)
        return runner(case_path, **kwargs)

    def run_stage_deterministic_first(self, case_dir: Path, stage_id: str, **kwargs: Any) -> Dict[str, Any]:
        case_path = Path(case_dir).resolve()
        recovered = self.try_deterministic_recovery(case_path, stage_id)
        if recovered is not None:
            self.write_repair_log(case_path)
            return recovered
        result = self.run_stage(case_path, stage_id, **kwargs)
        self.write_repair_log(case_path)
        return result

    def try_deterministic_recovery(self, case_dir: Path, stage_id: str) -> Optional[Dict[str, Any]]:
        spec = DETERMINISTIC_FIRST_STAGE_SPECS.get(stage_id)
        if not spec:
            return None
        case_path = Path(case_dir).resolve()
        validation_path = case_path / str(spec["validation"])
        if not self._validation_is_valid(validation_path):
            return None
        validation = self._read_json_if_exists(validation_path)
        for field, expected in (spec.get("validation_contract") or {}).items():
            if validation.get(field) != expected:
                return None

        input_paths = [case_path / str(path) for path in spec.get("inputs", [])]
        if not self._manifest_inputs_match(case_path, stage_id, input_paths):
            return None
        recovery_input_paths = self._current_manifest_input_paths(case_path, stage_id) or input_paths

        output_paths = self._stage_output_paths(case_path, stage_id, spec)
        # Never let deterministic repair hide a mutation.  First verify every
        # recorded output that is still present; only missing, explicitly
        # derivable knowledge-base files may be repaired afterwards.
        if not self._manifest_outputs_match(
            case_path,
            stage_id,
            output_paths,
            allow_missing_derived=True,
        ):
            return None
        self._repair_deterministic_derived_outputs(case_path, stage_id)
        output_paths = self._stage_output_paths(case_path, stage_id, spec)
        if not output_paths or not all(path.exists() for path in output_paths):
            return None
        if not self._manifest_outputs_match(case_path, stage_id, output_paths):
            return None

        common = self.import_pipeline_module("common")
        common.update_manifest(
            case_path,
            stage_id=stage_id,
            status="success",
            input_paths=recovery_input_paths,
            output_paths=output_paths,
            errors=validation.get("errors"),
            warnings=validation.get("warnings"),
            metadata={
                "recovered_without_rerun": True,
                "recovered_without_llm": bool(spec.get("llm_stage")),
                "repair_type": spec.get("repair_type"),
                "llm_used": False,
                "attempts_used": 0,
                "metrics": validation.get("metrics", {}),
            },
        )
        return {
            "case_id": case_path.name,
            "status": "success",
            "validation": validation,
            "validation_path": str(validation_path),
            "deterministic_recovery": True,
            "llm_used": False,
        }

    def _manifest_inputs_match(self, case_dir: Path, stage_id: str, expected_paths: List[Path]) -> bool:
        """Return true only when the successful manifest entry still matches every input.

        The batch pipeline uses recorded SHA-256 input hashes as its cache key.
        Deterministic adapter recovery must apply the same rule; a valid-looking
        validation JSON and existing outputs are not evidence that those outputs
        belong to the current inputs.  Case-local paths are remapped by relative
        path so copied fixtures remain portable while retaining hash equality.
        """

        common = self.import_pipeline_module("common")
        manifest = common.load_manifest(case_dir)
        stage = next(
            (
                entry
                for entry in manifest.get("stages", [])
                if isinstance(entry, dict) and entry.get("stage_id") == stage_id
            ),
            None,
        )
        if not stage or stage.get("status") != "success":
            return False

        recorded_inputs = [entry for entry in stage.get("inputs", []) if isinstance(entry, dict)]
        if not recorded_inputs:
            return False

        for expected in expected_paths:
            expected = Path(expected)
            if not expected.exists() or not expected.is_file():
                return False
            record = next(
                (
                    entry
                    for entry in recorded_inputs
                    if self._recorded_input_matches_path(case_dir, entry.get("path"), expected)
                ),
                None,
            )
            if not record or record.get("sha256") != self._sha256_file(expected):
                return False

        # Also verify additional inputs recorded by the real stage runner (for
        # example project files and JSON schemas used by schema_validation).
        # This prevents reuse when an input outside the compact stage spec drifts.
        for record in recorded_inputs:
            current_path = self._current_path_for_recorded_input(case_dir, record.get("path"))
            if current_path is None:
                return False
            recorded_hash = record.get("sha256")
            if recorded_hash:
                if (
                    not current_path.exists()
                    or not current_path.is_file()
                    or self._sha256_file(current_path) != recorded_hash
                ):
                    return False
            elif current_path.exists():
                # A formerly absent optional input appearing changes the stage's
                # effective input set and therefore invalidates the cached result.
                return False
        return True

    def _manifest_outputs_match(
        self,
        case_dir: Path,
        stage_id: str,
        expected_paths: List[Path],
        *,
        allow_missing_derived: bool = False,
    ) -> bool:
        """Verify every recorded output digest before deterministic recovery.

        File hashes are already persisted by ``common.update_manifest``.  A
        manifest may additionally provide ``tree_sha256`` for directory outputs;
        when present, it is verified with a deterministic tree hash. Historical
        directory entries without a hash are accepted only when individually
        hashed file records exactly cover the directory.
        """

        common = self.import_pipeline_module("common")
        manifest = common.load_manifest(case_dir)
        stage = next(
            (
                entry
                for entry in reversed(manifest.get("stages", []))
                if isinstance(entry, dict)
                and entry.get("stage_id") == stage_id
                and entry.get("status") == "success"
            ),
            None,
        )
        if not stage:
            return False
        recorded_outputs = [entry for entry in stage.get("outputs", []) if isinstance(entry, dict)]
        if not recorded_outputs:
            return False

        resolved_records: List[Tuple[Path, Dict[str, Any]]] = []
        for record in recorded_outputs:
            current_path = self._current_path_for_recorded_input(case_dir, record.get("path"))
            if current_path is None:
                return False
            if not current_path.exists():
                if allow_missing_derived and self._is_repairable_derived_output(
                    case_dir,
                    stage_id,
                    current_path,
                ):
                    continue
                return False
            resolved_records.append((current_path, record))
            recorded_hash = str(record.get("sha256") or "").strip().lower()
            recorded_tree_hash = str(record.get("tree_sha256") or "").strip().lower()
            if current_path.is_file():
                if not recorded_hash or self._sha256_file(current_path).lower() != recorded_hash:
                    return False
            elif current_path.is_dir():
                if recorded_tree_hash and self._tree_sha256(current_path) != recorded_tree_hash:
                    return False
                if recorded_hash and self._tree_sha256(current_path) != recorded_hash:
                    return False
            else:
                return False

        for current_path, record in resolved_records:
            if not current_path.is_dir():
                continue
            has_directory_hash = bool(
                str(record.get("tree_sha256") or "").strip()
                or str(record.get("sha256") or "").strip()
            )
            if has_directory_hash:
                continue
            allow_empty = bool(
                allow_missing_derived
                and self._is_repairable_derived_output(case_dir, stage_id, current_path)
            )
            if not self._directory_has_complete_file_records(
                current_path,
                resolved_records,
                allow_empty=allow_empty,
            ):
                return False

        for expected in expected_paths:
            expected = Path(expected)
            if not expected.exists():
                if allow_missing_derived and self._is_repairable_derived_output(
                    case_dir,
                    stage_id,
                    expected,
                ):
                    continue
                return False
            if expected.is_dir():
                directory_record = next(
                    (
                        item
                        for current, item in resolved_records
                        if self._same_resolved_path(current, expected)
                    ),
                    None,
                )
                if directory_record:
                    has_tree_hash = bool(
                        str(directory_record.get("tree_sha256") or "").strip()
                        or str(directory_record.get("sha256") or "").strip()
                    )
                    if not has_tree_hash and not self._directory_has_complete_file_records(
                        expected,
                        resolved_records,
                        allow_empty=bool(
                            allow_missing_derived
                            and self._is_repairable_derived_output(case_dir, stage_id, expected)
                        ),
                    ):
                        return False
                elif not self._directory_has_complete_file_records(expected, resolved_records):
                    if not (
                        allow_missing_derived
                        and self._is_repairable_derived_output(case_dir, stage_id, expected)
                        and self._directory_has_complete_file_records(
                            expected,
                            resolved_records,
                            allow_empty=True,
                        )
                    ):
                        return False
                continue
            record = next(
                (
                    item
                    for current, item in resolved_records
                    if self._same_resolved_path(current, expected)
                ),
                None,
            )
            if not record or not str(record.get("sha256") or "").strip():
                return False
        return True

    @classmethod
    def _is_repairable_derived_output(cls, case_dir: Path, stage_id: str, path: Path) -> bool:
        if stage_id != "knowledge_synthesis":
            return False
        kb_root = (Path(case_dir) / "interactive_agents_project" / "kb").resolve()
        try:
            candidate = Path(path).resolve()
            return candidate == kb_root or candidate.is_relative_to(kb_root)
        except (OSError, ValueError):
            return False

    @classmethod
    def _directory_has_complete_file_records(
        cls,
        root: Path,
        resolved_records: List[Tuple[Path, Dict[str, Any]]],
        *,
        allow_empty: bool = False,
    ) -> bool:
        """Return true when individual hashed records exactly cover a directory.

        Historical manifests sometimes listed every generated KB file instead of
        the KB directory.  Those remain recoverable, while an unhashed directory
        record alone cannot prove that files were neither changed nor added.
        """

        root = Path(root).resolve()
        actual_files = {
            path.resolve()
            for path in root.rglob("*")
            if path.is_file()
        }
        recorded_files = set()
        for current, record in resolved_records:
            current = Path(current)
            if not current.is_file() or not str(record.get("sha256") or "").strip():
                continue
            try:
                resolved = current.resolve()
                if resolved.is_relative_to(root):
                    recorded_files.add(resolved)
            except (OSError, ValueError):
                continue
        return (allow_empty or bool(actual_files)) and actual_files == recorded_files

    @staticmethod
    def _same_resolved_path(left: Path, right: Path) -> bool:
        try:
            return Path(left).resolve() == Path(right).resolve()
        except OSError:
            return str(left) == str(right)

    @classmethod
    def _tree_sha256(cls, root: Path) -> str:
        digest = hashlib.sha256()
        root = Path(root)
        for path in sorted(
            (candidate for candidate in root.rglob("*") if candidate.is_file()),
            key=lambda candidate: candidate.relative_to(root).as_posix(),
        ):
            relative = path.relative_to(root).as_posix().encode("utf-8")
            digest.update(len(relative).to_bytes(8, "big"))
            digest.update(relative)
            digest.update(bytes.fromhex(cls._sha256_file(path)))
        return digest.hexdigest()

    def _current_manifest_input_paths(self, case_dir: Path, stage_id: str) -> List[Path]:
        common = self.import_pipeline_module("common")
        manifest = common.load_manifest(case_dir)
        stage = next(
            (
                entry
                for entry in manifest.get("stages", [])
                if isinstance(entry, dict) and entry.get("stage_id") == stage_id
            ),
            None,
        )
        if not stage:
            return []
        paths: List[Path] = []
        for record in stage.get("inputs", []):
            if not isinstance(record, dict):
                continue
            current = self._current_path_for_recorded_input(case_dir, record.get("path"))
            if current is not None and current not in paths:
                paths.append(current)
        return paths

    @staticmethod
    def _sha256_file(path: Path) -> str:
        digest = hashlib.sha256()
        with Path(path).open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _case_relative_from_recorded(case_dir: Path, recorded_path: Path) -> Optional[Path]:
        case_local_roots = {
            "input",
            "intermediate",
            "roomcontract",
            "interactive_agents_project",
            "runtime_logs",
            "validation",
            "paper_artifacts",
        }
        parts = recorded_path.parts
        matching_indexes = [index for index, part in enumerate(parts) if part == case_dir.name]
        for index in reversed(matching_indexes):
            suffix = parts[index + 1 :]
            if suffix and suffix[0] in case_local_roots:
                return Path(*suffix)
        return None

    @classmethod
    def _current_path_for_recorded_input(cls, case_dir: Path, path_value: Any) -> Optional[Path]:
        text = str(path_value or "").strip()
        if not text:
            return None
        recorded_path = Path(text)
        relative = cls._case_relative_from_recorded(case_dir, recorded_path)
        return case_dir / relative if relative is not None else recorded_path

    @classmethod
    def _recorded_input_matches_path(cls, case_dir: Path, path_value: Any, expected: Path) -> bool:
        current = cls._current_path_for_recorded_input(case_dir, path_value)
        if current is None:
            return False
        try:
            return current.resolve() == Path(expected).resolve()
        except OSError:
            return str(current) == str(expected)

    def write_repair_log(self, case_dir: Path) -> Dict[str, Any]:
        repair_log = self.import_pipeline_module("repair_log")
        return repair_log.write_repair_log_for_case(Path(case_dir).resolve())

    def _repair_deterministic_derived_outputs(self, case_dir: Path, stage_id: str) -> None:
        if stage_id != "knowledge_synthesis":
            return
        knowledge_path = case_dir / "intermediate" / "knowledge.generated.json"
        if not knowledge_path.exists():
            return
        knowledge = self._read_json_if_exists(knowledge_path)
        knowledge_module = self.import_pipeline_module("knowledge_synthesis")
        kb_root = case_dir / "interactive_agents_project" / "kb"
        for entry in knowledge.get("knowledge_entries") or []:
            tag = knowledge_module.slugify(str(entry.get("tag") or ""), fallback="common")
            name = knowledge_module.slugify(
                str(entry.get("name") or f"{tag}_entry"),
                fallback=f"{tag}_entry",
            )
            path = kb_root / tag / f"{name}.txt"
            if not path.exists():
                knowledge_module.write_text(path, str(entry.get("text") or "").strip() + "\n")

    def _stage_output_paths(self, case_dir: Path, stage_id: str, spec: Dict[str, Any]) -> List[Path]:
        paths = [case_dir / str(path) for path in spec.get("outputs", [])]
        if stage_id == "knowledge_synthesis":
            kb_root = case_dir / "interactive_agents_project" / "kb"
            paths.append(kb_root)
        if stage_id == "project_materialization":
            project_dir = self.paths.backend_root / "projects" / case_dir.name
            paths.extend(
                [
                    project_dir / "project.json",
                    project_dir / "room_plan.json",
                    project_dir / "agents.json",
                    project_dir / "trace_map.json",
                    project_dir / "trace_map.v2.json",
                    project_dir / "trace_map.v05.json",
                    project_dir / "roomcontract.v2.instance.json",
                    project_dir / "roomcontract.v05.instance.json",
                    project_dir / "kb",
                ]
            )
        return paths

    @staticmethod
    def _validation_is_valid(path: Path) -> bool:
        try:
            return json.loads(path.read_text(encoding="utf-8-sig")).get("status") == "valid"
        except Exception:
            return False

    @staticmethod
    def _read_json_if_exists(path: Path) -> Dict[str, Any]:
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8-sig"))
        except Exception:
            return {}

    def validate_analyze_case(self, case_dir: Path) -> Dict[str, Any]:
        case_path = Path(case_dir).resolve()
        errors = []
        warnings = []
        artifacts: Dict[str, Dict[str, Any]] = {}
        validations: Dict[str, Dict[str, Any]] = {}

        for artifact_id, relative_path in ANALYZE_PREVIEW_ARTIFACTS.items():
            path = case_path / relative_path
            artifact_report = {
                "path": str(path),
                "exists": path.exists(),
                "json_status": "missing",
            }
            if not path.exists():
                errors.append(f"Analyze-Artefakt fehlt: {artifact_id} ({relative_path})")
            else:
                try:
                    json.loads(path.read_text(encoding="utf-8-sig"))
                    artifact_report["json_status"] = "valid"
                except Exception as exc:
                    artifact_report["json_status"] = "invalid"
                    errors.append(f"Analyze-Artefakt ist kein gueltiges JSON: {artifact_id} ({exc})")
            artifacts[artifact_id] = artifact_report

        for validation_id, relative_path in ANALYZE_VALIDATION_ARTIFACTS.items():
            path = case_path / relative_path
            validation_report = {
                "path": str(path),
                "exists": path.exists(),
                "status": "missing",
                "error_count": 0,
                "warning_count": 0,
                "errors": [],
                "warnings": [],
            }
            if not path.exists():
                errors.append(f"Analyze-Validierung fehlt: {validation_id} ({relative_path})")
                validations[validation_id] = validation_report
                continue

            try:
                payload = json.loads(path.read_text(encoding="utf-8-sig"))
            except Exception as exc:
                validation_report["status"] = "invalid_json"
                validation_report["errors"] = [str(exc)]
                validation_report["error_count"] = 1
                errors.append(f"Analyze-Validierung ist kein gueltiges JSON: {validation_id} ({exc})")
                validations[validation_id] = validation_report
                continue

            report_errors = list(payload.get("errors") or [])
            report_warnings = list(payload.get("warnings") or [])
            status = str(payload.get("status") or "").strip().lower()
            validation_report.update(
                {
                    "status": status or "missing_status",
                    "error_count": len(report_errors),
                    "warning_count": len(report_warnings),
                    "errors": report_errors,
                    "warnings": report_warnings,
                    "metrics": payload.get("metrics") or {},
                }
            )
            warnings.extend(f"{validation_id}: {warning}" for warning in report_warnings)
            if status != "valid":
                errors.append(
                    f"Analyze-Validierung ist nicht valid: {validation_id} "
                    f"(status={status or 'missing'}, errors={len(report_errors)})"
                )
                errors.extend(f"{validation_id}: {error}" for error in report_errors)
            validations[validation_id] = validation_report

        return {
            "status": "valid" if not errors else "invalid",
            "case_id": case_path.name,
            "case_dir": str(case_path),
            "errors": errors,
            "warnings": warnings,
            "artifacts": artifacts,
            "validations": validations,
            "metrics": {
                "artifact_count": len(artifacts),
                "valid_artifact_count": len(
                    [item for item in artifacts.values() if item.get("json_status") == "valid"]
                ),
                "validation_count": len(validations),
                "valid_validation_count": len(
                    [item for item in validations.values() if item.get("status") == "valid"]
                ),
            },
        }

    def summarize_analyze_validation(self, report: Dict[str, Any]) -> Dict[str, Any]:
        validations = report.get("validations") or {}
        pre_model_status = combined_validation_status(
            validations,
            (
                "rdl_ingestion",
                "scene_semantics",
                "agent_roles",
                "knowledge_synthesis",
                "agent_placement",
                "placement_metrics",
            ),
        )
        invariant_status = combined_validation_status(
            validations,
            ("roomcontract_assembly", "roomcontract_invariants"),
        )
        handoff_status = combined_validation_status(validations, ("handoff_derivation",))
        errors = list(report.get("errors") or [])
        warnings = list(report.get("warnings") or [])
        return {
            "status": report.get("status") or "invalid",
            "schema_status": pre_model_status,
            "invariant_status": invariant_status,
            "materialization_status": "not_run",
            "traceability_status": "not_run",
            "handoff_status": handoff_status,
            "error_count": len(errors),
            "warning_count": len(warnings),
            "traceability_average_coverage": 0.0,
            "handoff_decision_accuracy": 0.0,
            "errors": errors,
            "warnings": warnings,
        }

    def validate_commit_case(self, case_dir: Path) -> Dict[str, Any]:
        case_path = Path(case_dir).resolve()
        errors = []
        warnings = []
        artifacts: Dict[str, Dict[str, Any]] = {}
        validations: Dict[str, Dict[str, Any]] = {}

        for artifact_id, relative_path in self.commit_stage_plan(case_id=case_path.name)["artifacts"].items():
            path = self._resolve_commit_artifact_path(case_path, relative_path)
            artifact_report = {
                "path": str(path),
                "exists": path.exists(),
                "kind": "directory" if path.exists() and path.is_dir() else "file",
                "json_status": "not_json",
            }
            if not path.exists():
                errors.append(f"Commit-Artefakt fehlt: {artifact_id} ({relative_path})")
            elif path.is_file() and path.suffix.lower() == ".json":
                try:
                    json.loads(path.read_text(encoding="utf-8-sig"))
                    artifact_report["json_status"] = "valid"
                except Exception as exc:
                    artifact_report["json_status"] = "invalid"
                    errors.append(f"Commit-Artefakt ist kein gueltiges JSON: {artifact_id} ({exc})")
            artifacts[artifact_id] = artifact_report

        for validation_id, relative_path in COMMIT_VALIDATION_ARTIFACTS.items():
            path = case_path / relative_path
            validation_report = self._read_validation_report(path)
            if not validation_report["exists"]:
                errors.append(f"Commit-Validierung fehlt: {validation_id} ({relative_path})")
            elif validation_report["status"] != "valid":
                errors.append(
                    f"Commit-Validierung ist nicht valid: {validation_id} "
                    f"(status={validation_report['status']}, errors={validation_report['error_count']})"
                )
                errors.extend(f"{validation_id}: {error}" for error in validation_report["errors"])
            warnings.extend(f"{validation_id}: {warning}" for warning in validation_report["warnings"])
            validations[validation_id] = validation_report

        return {
            "status": "valid" if not errors else "invalid",
            "case_id": case_path.name,
            "case_dir": str(case_path),
            "errors": errors,
            "warnings": warnings,
            "artifacts": artifacts,
            "validations": validations,
            "metrics": {
                "artifact_count": len(artifacts),
                "present_artifact_count": len(
                    [item for item in artifacts.values() if item.get("exists")]
                ),
                "validation_count": len(validations),
                "valid_validation_count": len(
                    [item for item in validations.values() if item.get("status") == "valid"]
                ),
            },
        }

    def summarize_commit_validation(self, report: Dict[str, Any]) -> Dict[str, Any]:
        validations = report.get("validations") or {}
        schema_status = combined_validation_status(
            validations,
            (
                "rdl_ingestion",
                "scene_semantics",
                "agent_roles",
                "knowledge_synthesis",
                "agent_placement",
                "schema_validation",
            ),
        )
        invariant_status = combined_validation_status(
            validations,
            ("roomcontract_assembly", "roomcontract_invariants"),
        )
        materialization_status = combined_validation_status(validations, ("project_materialization",))
        traceability_status = combined_validation_status(validations, ("traceability_metrics",))
        handoff_status = combined_validation_status(validations, ("handoff_derivation", "handoff_metrics"))
        errors = list(report.get("errors") or [])
        warnings = list(report.get("warnings") or [])
        trace_metrics = (validations.get("traceability_metrics") or {}).get("metrics") or {}
        handoff_metrics = (validations.get("handoff_metrics") or {}).get("metrics") or {}
        return {
            "status": report.get("status") or "invalid",
            "schema_status": schema_status,
            "invariant_status": invariant_status,
            "materialization_status": materialization_status,
            "traceability_status": traceability_status,
            "handoff_status": handoff_status,
            "error_count": len(errors),
            "warning_count": len(warnings),
            "traceability_average_coverage": float(trace_metrics.get("average_coverage") or 0.0),
            "handoff_decision_accuracy": float(handoff_metrics.get("handoff_decision_accuracy") or 0.0),
            "errors": errors,
            "warnings": warnings,
        }

    def _resolve_commit_artifact_path(self, case_dir: Path, relative_path: str) -> Path:
        if relative_path.startswith("projects/"):
            return self.paths.backend_root / relative_path
        return case_dir / relative_path

    @staticmethod
    def _read_validation_report(path: Path) -> Dict[str, Any]:
        report = {
            "path": str(path),
            "exists": path.exists(),
            "status": "missing",
            "error_count": 0,
            "warning_count": 0,
            "errors": [],
            "warnings": [],
            "metrics": {},
        }
        if not path.exists():
            return report
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
        except Exception as exc:
            report.update(
                {
                    "status": "invalid_json",
                    "error_count": 1,
                    "errors": [str(exc)],
                }
            )
            return report
        errors = list(payload.get("errors") or [])
        warnings = list(payload.get("warnings") or [])
        report.update(
            {
                "status": str(payload.get("status") or "missing_status").strip().lower(),
                "error_count": len(errors),
                "warning_count": len(warnings),
                "errors": errors,
                "warnings": warnings,
                "metrics": payload.get("metrics") or {},
            }
        )
        return report

    def run_ingestion_from_payload(self, payload: Dict[str, Any], *, case_id: str) -> Dict[str, Any]:
        initialized = self.initialize_case_from_payload(payload, case_id=case_id)
        result = self.run_stage(Path(initialized["case_dir"]), "rdl_ingestion")
        return {
            "case_id": initialized["case_id"],
            "case_dir": initialized["case_dir"],
            "source_path": initialized["source_path"],
            "ingestion": result,
        }


def find_workspace_root(start: Optional[Path] = None) -> Path:
    current = (start or Path(__file__)).resolve()
    if current.is_file():
        current = current.parent

    for candidate in (current, *current.parents):
        if (candidate / "tools" / "case_study_pipeline").is_dir() and (candidate / BACKEND_RELATIVE_ROOT).is_dir():
            return candidate
    raise FileNotFoundError("Workspace-Root mit tools/case_study_pipeline und agent_backend-Backend nicht gefunden.")


def require_safe_case_id(case_id: str) -> str:
    value = str(case_id or "").strip()
    if not value:
        raise ValueError("case_id fehlt.")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", value):
        raise ValueError("case_id darf nur Buchstaben, Zahlen, Punkt, Unterstrich und Bindestrich enthalten.")
    if ".." in value:
        raise ValueError("case_id darf keine '..'-Sequenz enthalten.")
    return value


def derive_case_id(
    payload: Dict[str, Any],
    *,
    project_id_hint: str = "",
    display_name: str = "",
    include_hash: bool = True,
) -> str:
    if not isinstance(payload, dict):
        raise ValueError("RDL-Payload muss ein Objekt sein.")

    explicit = ascii_slug(project_id_hint, fallback="")
    if explicit:
        return require_safe_case_id(explicit)

    source_name = first_non_empty(
        display_name,
        nested_string(payload, "project", "display_name"),
        nested_string(payload, "project", "name"),
        nested_string(payload, "metadata", "display_name"),
        nested_string(payload, "metadata", "name"),
        nested_string(payload, "scene", "sceneName"),
        nested_string(payload, "scene", "name"),
        nested_string(payload, "scene", "displayName"),
        nested_string(payload, "sceneName"),
        nested_string(payload, "name"),
        nested_string(payload, "id"),
        "functional_rdl_case",
    )
    base = ascii_slug(source_name, fallback="functional_rdl_case")
    if include_hash:
        base = f"{base}_{payload_hash(payload)[:8]}"
    return require_safe_case_id(base)


def payload_hash(payload: Dict[str, Any]) -> str:
    return hashlib.sha256(canonical_payload_text(payload).encode("utf-8")).hexdigest()


def canonical_payload_text(payload: Dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def first_non_empty(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def nested_string(payload: Dict[str, Any], *path: str) -> str:
    value: Any = payload
    for key in path:
        if not isinstance(value, dict) or key not in value:
            return ""
        value = value[key]
    if isinstance(value, (dict, list)):
        return ""
    return str(value or "").strip()


def ascii_slug(value: str, fallback: str = "case") -> str:
    text = str(value or "")
    for source, replacement in {
        "ä": "ae",
        "ö": "oe",
        "ü": "ue",
        "Ä": "Ae",
        "Ö": "Oe",
        "Ü": "Ue",
        "ß": "ss",
        "ẞ": "SS",
    }.items():
        text = text.replace(source, replacement)
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.strip().lower()
    text = re.sub(r"[^a-z0-9_-]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text or fallback


def combined_validation_status(validations: Dict[str, Any], validation_ids: Tuple[str, ...]) -> str:
    statuses = []
    for validation_id in validation_ids:
        validation = validations.get(validation_id)
        if not isinstance(validation, dict):
            statuses.append("missing")
            continue
        statuses.append(str(validation.get("status") or "missing").strip().lower())
    if not statuses:
        return "not_run"
    if all(status == "valid" for status in statuses):
        return "valid"
    if any(status in {"invalid", "invalid_json", "missing", "missing_status"} for status in statuses):
        return "invalid"
    return statuses[0]

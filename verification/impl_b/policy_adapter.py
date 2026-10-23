"""Independent admission adapter; all routing and gate decisions execute in ASP.

CLI: python policy_adapter.py input.json
input.json contains instance, trace, request, and session.
No model files, credentials, network resources, or session state are modified.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys

import clingo
import jsonschema
from referencing import Registry
from referencing.exceptions import NoSuchResource

ROOT = Path(__file__).resolve().parent
ENGINE = "clingo ASP " + clingo.__version__
SCALARS = {"kind", "entityRole", "sourceId", "sourceAgentId", "uri", "value"}
REFERENCES = {"groundedAsset", "groundedObjectGroup", "responsibleZone", "handoffTarget", "providedCapability", "objectGroup", "sourceObjectId", "capabilityUse", "provider", "target", "typeRef", "capability", "runtimeAction", "locator", "inputSchema"}
TRACE_FIELDS = {"action_kind", "scenario_step_id", "capability_use_id", "capability_id", "provider_entity_id", "runtime_binding_id", "runtime_action_id", "endpoint"}


def _symbol(value):
    if isinstance(value, str):
        return clingo.String(value)
    if value is None:
        return clingo.Function("null")
    if isinstance(value, bool):
        return clingo.Function("true" if value else "false")
    if isinstance(value, int) and -(2**31) <= value < 2**31:
        return clingo.Number(value)
    if isinstance(value, (int, float)):
        return clingo.Function("number", [clingo.String(str(value))])
    return clingo.Function("object" if isinstance(value, dict) else "array")


def _kind(value):
    if isinstance(value, str): return "string"
    if value is None: return "null"
    if isinstance(value, bool): return "boolean"
    if isinstance(value, dict): return "object"
    if isinstance(value, list): return "array"
    return "number"


def _deny_retrieval(uri):
    # An empty registry with this callback cannot fetch HTTP/file references.
    raise NoSuchResource(ref=uri)


def load_facts(instance, trace, request, session):
    """Translate factual input and JSON Schema validation observations to ASP.

    No ownership, path, identifier, cardinality, priority, or verdict is computed
    here. Relations preserve array positions, including duplicate references.
    """
    facts = []
    def emit(name, *args):
        facts.append(str(clingo.Function(name, [_symbol(a) for a in args])) + ".")

    for label, value in (("instance", instance), ("trace", trace), ("request", request), ("session", session)):
        if not isinstance(value, dict):
            emit("bad_top", label)
    objects = instance.get("objects") if isinstance(instance, dict) else None
    if not isinstance(objects, list):
        emit("bad_top", "objects")
        objects = []
    for index, record in enumerate(objects):
        if not isinstance(record, dict):
            emit("bad_record", index)
            continue
        identifier, typ = record.get("id"), record.get("type")
        if not isinstance(identifier, str) or not identifier or not isinstance(typ, str):
            emit("bad_record", index)
            continue
        emit("obj", index, identifier, typ)
        for key in SCALARS:
            if key in record:
                emit("v", identifier, key, record[key])
                emit("vt", identifier, key, _kind(record[key]))
        for key in REFERENCES:
            if key not in record:
                continue
            values = record[key]
            emit("rt", identifier, key, _kind(values))
            if isinstance(values, list):
                for position, value in enumerate(values):
                    emit("r", identifier, key, position, value)
                    emit("r_type", identifier, key, position, _kind(value))
        if typ == "SchemaReference":
            try:
                schema = json.loads(record["text"])
                if isinstance(schema, dict) and "$schema" in schema:
                    validator_cls = jsonschema.validators.validator_for(schema, default=None)
                    if validator_cls is None:
                        raise ValueError("Unsupported explicitly declared schema dialect")
                else:
                    validator_cls = jsonschema.Draft202012Validator
                validator_cls.check_schema(schema)
                emit("schema_document", identifier)
                if isinstance(schema, dict) and "applicationActionKind" in schema:
                    emit("schema_kind", identifier, schema["applicationActionKind"])
                validator = validator_cls(schema, registry=Registry(retrieve=_deny_retrieval))
                if validator.is_valid(request):
                    emit("schema_pass", identifier)
            except (KeyError, TypeError, ValueError, jsonschema.exceptions.SchemaError,
                    jsonschema.exceptions.ValidationError, jsonschema.exceptions._WrappedReferencingError,
                    NoSuchResource):
                emit("schema_error", identifier)

    for label, value in (("request", request), ("session", session)):
        if isinstance(value, dict):
            for key, item in value.items():
                emit("field", label, key, item)
                emit("field_type", label, key, _kind(item))
    spatial = request.get("spatial_context") if isinstance(request, dict) else None
    if isinstance(spatial, dict):
        for key, item in spatial.items():
            emit("field", "spatial", key, item)
            emit("field_type", "spatial", key, _kind(item))
        candidates = spatial.get("candidate_entity_ids")
        if isinstance(candidates, list):
            for index, item in enumerate(candidates):
                emit("candidate", index, item)
                emit("candidate_type", index, _kind(item))
        ambiguity = spatial.get("ambiguity")
        if isinstance(ambiguity, dict):
            for key, item in ambiguity.items():
                emit("ambiguity_member", key, item)
                # Generic JSON truthiness observation, not an admission decision.
                if bool(item): emit("truthy_ambiguity_member", key)
    for label, value in (("request", spatial), ("session", session)):
        if isinstance(value, dict) and isinstance(value.get("model_sha256"), str):
            digest = value["model_sha256"]
            emit("digest", label, digest.lower())
            if re.fullmatch(r"[a-fA-F0-9]{64}", digest):
                emit("digest_shape", label)

    rows = trace.get("runtime_actions", []) if isinstance(trace, dict) else []
    if isinstance(rows, list):
        for index, row in enumerate(rows):
            if not isinstance(row, dict): continue
            emit("trace_row", index)
            for key in TRACE_FIELDS:
                if key in row: emit("tv", index, key, row[key])
            if isinstance(row.get("target_ids"), list):
                for position, target in enumerate(row["target_ids"]):
                    emit("tr", index, position, target)
                emit("trace_targets_present", index)
            if isinstance(row.get("locator"), dict):
                for key in ("kind", "value"):
                    if key in row["locator"]: emit("tl", index, key, row["locator"][key])
    return "\n".join(facts)


def evaluate(instance, trace, request, session):
    """Return the SPEC/A-001/A-002 verdict without modifying the inputs."""
    control = clingo.Control(["--warn=none", "--models=2"])
    control.load(str(ROOT / "admission.lp"))
    control.add("base", [], load_facts(instance, trace, request, session))
    control.ground([("base", [])])
    answers = []
    with control.solve(yield_=True) as handle:
        for model in handle:
            verdicts = [a for a in model.symbols(shown=True) if a.name == "verdict"]
            if len(verdicts) != 1:
                raise RuntimeError("Admission policy must derive exactly one verdict")
            answer = {}
            for key, term in zip(("decision", "reason", "provider", "action"), verdicts[0].arguments):
                answer[key] = term.string if term.type == clingo.SymbolType.String else None
            answers.append(answer)
    if len(answers) != 1:
        raise RuntimeError("Admission policy must have exactly one stable model")
    return answers[0]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", help="JSON envelope file, or - for standard input")
    args = parser.parse_args(argv)
    try:
        if args.input == "-":
            envelope = json.load(sys.stdin)
        else:
            with open(args.input, encoding="utf-8-sig") as stream:
                envelope = json.load(stream)
        if not isinstance(envelope, dict): envelope = {}
    except (ValueError, OSError):
        envelope = {}
    result = evaluate(*(envelope.get(key) for key in ("instance", "trace", "request", "session")))
    print(json.dumps(result, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

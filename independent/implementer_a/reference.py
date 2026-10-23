"""Independent SPEC v1 admission evaluator with author amendments A-001/A-002/A-003.

Only native model records establish responsibility and executable paths.  Trace
entries corroborate the selected path; they never create one.  evaluate is pure:
it neither modifies its arguments nor performs file/network access.  This module
covers grounded admission, not generation, commit, or publication validation.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import dataclass
import json
import math
from pathlib import Path
import re
import sys
import warnings
from typing import Any

import jsonschema


# RefResolver is retained here for broad installed-jsonschema compatibility.  Its
# sole remote retrieval hook is overridden, so every URI scheme is offline.
with warnings.catch_warnings():
    warnings.simplefilter("ignore", DeprecationWarning)
    _ResolverBase = jsonschema.RefResolver


class _OfflineResolver(_ResolverBase):
    def resolve_remote(self, uri):
        raise ValueError("External schema references are unavailable: " + str(uri))


class _Reject(Exception):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


def _fail(reason: str):
    raise _Reject(reason)


def _verdict(decision, reason=None, provider=None, action=None):
    return {"decision": decision, "reason": reason, "provider": provider, "action": action}


def _refs(record: dict, name: str) -> list[str]:
    """Malformed reference values cannot invent links; absent lists are empty."""
    value = record.get(name, [])
    if not isinstance(value, list) or any(not isinstance(x, str) or not x for x in value):
        return []
    return value


def _wire_string(value):
    return isinstance(value, str) and bool(value)


def _digest(value):
    if isinstance(value, str) and re.fullmatch(r"[0-9a-fA-F]{64}", value):
        return value.lower()
    return None


def _json_finite(value):
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, dict):
        return all(isinstance(k, str) and _json_finite(v) for k, v in value.items())
    if isinstance(value, list):
        return all(_json_finite(v) for v in value)
    return value is None or isinstance(value, (str, int, bool))


def _read_schema_record(record):
    if not isinstance(record, dict) or record.get("type") != "SchemaReference":
        return None
    if record.get("uri") != "json" or not isinstance(record.get("text"), str):
        return None
    try:
        schema = json.loads(record["text"])
    except (ValueError, TypeError):
        return None
    return schema if isinstance(schema, (dict, bool)) else None


@dataclass(frozen=True)
class _Path:
    step: str
    use: str
    capability: str
    provider: str
    binding: str
    action: str
    targets: frozenset[str]
    locator_kind: str
    locator_value: str
    schema_id: str | None


class _Model:
    def __init__(self, instance):
        records = instance.get("objects")
        if not isinstance(records, list):
            _fail("E_PUBLICATION_INCONSISTENT")
        self.by_id = {}
        self.by_type = defaultdict(list)
        for record in records:
            if not isinstance(record, dict):
                _fail("E_PUBLICATION_INCONSISTENT")
            identity = record.get("id")
            kind = record.get("type")
            if not _wire_string(identity) or not _wire_string(kind) or identity in self.by_id:
                _fail("E_PUBLICATION_INCONSISTENT")
            self.by_id[identity] = record
            self.by_type[kind].append(record)
        self.agents = self.by_type["Agent"]
        self.scenes = [r for r in self.by_type["Entity"]
                       if r.get("kind") == "asset" and r.get("entityRole") == "sceneObject"]
        self.groups = [r for r in self.by_type["Entity"]
                       if r.get("kind") == "asset" and r.get("entityRole") == "objectGroup"]
        self.zones = [r for r in self.by_type["Entity"]
                      if r.get("kind") == "zone" and r.get("entityRole") == "semanticZone"]
        self.scene_ids = {r["id"]: r for r in self.scenes}
        self.source_scenes = defaultdict(list)
        self.wire_agents = defaultdict(list)
        for record in self.scenes:
            if _wire_string(record.get("sourceId")):
                self.source_scenes[record["sourceId"]].append(record)
        for record in self.agents:
            if _wire_string(record.get("sourceAgentId")):
                self.wire_agents[record["sourceAgentId"]].append(record)
        self.use_steps = defaultdict(list)
        for step in self.by_type["ScenarioStep"]:
            for use in _refs(step, "capabilityUse"):
                self.use_steps[use].append(step["id"])
        self.capability_bindings = defaultdict(list)
        for binding in self.by_type["RuntimeBinding"]:
            for capability in _refs(binding, "capability"):
                self.capability_bindings[capability].append(binding)

    def record(self, identity, kind):
        record = self.by_id.get(identity)
        return record if record is not None and record.get("type") == kind else None

    def select(self, request):
        context = request.get("spatial_context")
        if not isinstance(context, dict):
            _fail("E_SELECTION_STATE")
        if request.get("interaction_mode") == "non_deictic":
            _fail("E_SELECTION_STATE")
        if context.get("state") != "resolved":
            _fail("E_SELECTION_STATE")
        if context.get("ambiguous") is True or context.get("ambiguity") is True:
            _fail("E_SELECTION_STATE")
        ambiguity = context.get("ambiguity")
        if isinstance(ambiguity, dict) and (ambiguity.get("ambiguous") or ambiguity.get("is_ambiguous")):
            _fail("E_SELECTION_STATE")
        identities = [(key, context[key]) for key in ("entity_id", "source_object_id", "source_id")
                      if key in context]
        if any(not isinstance(value, str) for _, value in identities):
            _fail("E_SELECTION_STATE")
        candidates = context.get("candidate_entity_ids")
        if "candidate_entity_ids" in context:
            if (not isinstance(candidates, list) or len(candidates) != 1
                    or not _wire_string(candidates[0])):
                _fail("E_SELECTION_STATE")
            # The explicit entity identity is the proposed selection even if it
            # ultimately fails existence.  Check contradictory selection first.
            if "entity_id" in context and candidates != [context["entity_id"]]:
                _fail("E_SELECTION_STATE")
        if not identities:
            _fail("E_UNKNOWN_ENTITY")
        resolved = []
        for key, value in identities:
            matches = ([self.scene_ids[value]] if value in self.scene_ids else []) if key == "entity_id" \
                else self.source_scenes.get(value, [])
            if len(matches) != 1:
                _fail("E_UNKNOWN_ENTITY")
            resolved.append(matches[0])
        selected = resolved[0]
        if "candidate_entity_ids" in context and candidates != [selected["id"]]:
            _fail("E_SELECTION_STATE")
        if len({r["id"] for r in resolved}) != 1:
            _fail("E_ID_MISMATCH")
        return selected

    def active(self, request, session):
        identity = request.get("active_agent_id")
        matches = self.wire_agents.get(identity, []) if isinstance(identity, str) else []
        if len(matches) != 1:
            _fail("E_ACTIVE_AGENT_UNKNOWN")
        if session.get("active_agent_mode", "client") == "server_strict":
            if identity != session.get("active_agent_id"):
                _fail("E_ACTIVE_AGENT_MISMATCH")
        return matches[0]

    def owner(self, target):
        target_id = target["id"]
        group_ids = set(_refs(target, "objectGroup"))
        zone_ids = {zone["id"] for zone in self.zones
                    if target.get("sourceId") in _refs(zone, "sourceObjectId")}
        levels = (("groundedAsset", {target_id}),
                  ("groundedObjectGroup", group_ids),
                  ("responsibleZone", zone_ids))
        for relation, members in levels:
            owners = {agent["id"] for agent in self.agents
                      if members.intersection(_refs(agent, relation))}
            if not owners:
                continue
            if len(owners) != 1:
                _fail("E_AMBIGUOUS_OWNER")
            return self.by_id[next(iter(owners))]
        _fail("E_UNOWNED")

    def is_answering(self, action):
        if action is None:
            return False
        # A-002: explicit schema kind is authoritative.  POST /chat is a
        # fallback only when no input schema declares applicationActionKind.
        explicit_kinds = []
        for schema_id in _refs(action, "inputSchema"):
            schema = _read_schema_record(self.record(schema_id, "SchemaReference"))
            if isinstance(schema, dict) and "applicationActionKind" in schema:
                explicit_kinds.append(schema["applicationActionKind"])
        if explicit_kinds:
            return any(kind == "chat" for kind in explicit_kinds)
        for locator_id in _refs(action, "locator"):
            locator = self.record(locator_id, "RuntimeActionLocator")
            if locator and locator.get("kind") == "endpoint" and locator.get("value") == "POST /chat":
                return True
        return False

    def declared_path(self, provider, target):
        provider_id, target_id = provider["id"], target["id"]
        candidate_uses = []
        for use in self.by_type["CapabilityUse"]:
            if provider_id not in _refs(use, "provider") or target_id not in _refs(use, "target"):
                continue
            if not self.use_steps.get(use["id"]):
                continue
            answering = []
            for cap_id in _refs(use, "typeRef"):
                if self.record(cap_id, "Capability") is None or cap_id not in _refs(provider, "providedCapability"):
                    continue
                for binding in self.capability_bindings.get(cap_id, []):
                    for action_id in _refs(binding, "runtimeAction"):
                        action = self.record(action_id, "RuntimeAction")
                        if self.is_answering(action):
                            answering.append((cap_id, binding, action))
            if answering:
                candidate_uses.append((use, answering))
        if not candidate_uses:
            _fail("E_NO_DECLARED_ACTION")
        if len(candidate_uses) != 1:
            _fail("E_ACTION_AMBIGUOUS")
        use, answering = candidate_uses[0]
        if (len(_refs(use, "provider")) > 1 or len(_refs(use, "typeRef")) > 1
                or len(self.use_steps[use["id"]]) > 1 or len(answering) > 1):
            _fail("E_ACTION_AMBIGUOUS")
        cap_id, binding, action = answering[0]
        if self.record(cap_id, "Capability") is None or cap_id not in _refs(provider, "providedCapability"):
            _fail("E_NO_DECLARED_ACTION")
        if len(_refs(binding, "capability")) > 1:
            _fail("E_ACTION_AMBIGUOUS")
        locators = _refs(action, "locator")
        schemas = _refs(action, "inputSchema")
        if len(locators) != 1:
            _fail("E_NO_DECLARED_ACTION")
        locator = self.record(locators[0], "RuntimeActionLocator")
        if (locator is None or locator.get("kind") not in ("endpoint", "tool", "topic")
                or not _wire_string(locator.get("value"))):
            _fail("E_NO_DECLARED_ACTION")
        if any(ref not in self.by_id for ref in _refs(use, "target")):
            _fail("E_NO_DECLARED_ACTION")
        return _Path(self.use_steps[use["id"]][0], use["id"], cap_id, provider_id,
                     binding["id"], action["id"], frozenset(_refs(use, "target")),
                     locator["kind"], locator["value"], schemas[0] if len(schemas) == 1 else None)


def _trace_matches(trace, path):
    rows = trace.get("runtime_actions")
    if not isinstance(rows, list):
        _fail("E_NO_DECLARED_ACTION")
    expected = {"scenario_step_id": path.step, "capability_use_id": path.use,
                "capability_id": path.capability, "provider_entity_id": path.provider,
                "runtime_binding_id": path.binding, "runtime_action_id": path.action}
    matching = []
    inconsistent = False
    for row in rows:
        if not isinstance(row, dict):
            continue
        # Rows for unrelated uses do not establish or invalidate this path.
        if row.get("capability_use_id") != path.use:
            continue
        target_ids = row.get("target_ids")
        matches = (row.get("action_kind") == "chat"
                   and all(row.get(key) == value for key, value in expected.items())
                   and isinstance(target_ids, list)
                   and all(isinstance(x, str) for x in target_ids)
                   and set(target_ids) == path.targets)
        if matches:
            matching.append(row)
        else:
            # Infrastructure projected from the same use is not answering.
            if row.get("action_kind") == "chat" or row.get("runtime_action_id") == path.action:
                inconsistent = True
    if len(matching) > 1:
        _fail("E_ACTION_AMBIGUOUS")
    if len(matching) != 1 or inconsistent:
        _fail("E_NO_DECLARED_ACTION")


def _validate_request(model, path, request):
    schema = _read_schema_record(model.record(path.schema_id, "SchemaReference"))
    if schema is None or not _json_finite(schema) or not _json_finite(request):
        _fail("E_SCHEMA")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            default = None if isinstance(schema, dict) and "$schema" in schema else jsonschema.Draft202012Validator
            validator_class = jsonschema.validators.validator_for(schema, default=default)
            if validator_class is None:
                _fail("E_SCHEMA")
            validator_class.check_schema(schema)
            resolver = _OfflineResolver.from_schema(schema) if isinstance(schema, dict) else None
            validator = validator_class(schema, resolver=resolver)
            validator.validate(request)
    except Exception:
        # Schema syntax, request validation, unsupported dialect/reference, and
        # unavailable remote definitions all fail closed at the schema gate.
        _fail("E_SCHEMA")


def evaluate(instance, trace, request, session):
    """Return the four-key admission verdict without mutating any input.

    Ordering: input structure, pinned digest, selection/identity, active agent,
    specificity and one handoff, native declaration plus trace, declared schema.
    Native duplicate IDs are a publication inconsistency after the digest gate.
    Explicit non_deictic requests are outside this admission evaluator's scope.
    """
    try:
        if not all(isinstance(value, dict) for value in (instance, trace, request, session)):
            _fail("E_PUBLICATION_INCONSISTENT")
        # A target-free request has no defined admission path under this SPEC.
        if request.get("interaction_mode") == "non_deictic":
            _fail("E_SELECTION_STATE")
        context = request.get("spatial_context")
        request_digest = _digest(context.get("model_sha256")) if isinstance(context, dict) else None
        session_digest = _digest(session.get("model_sha256"))
        if request_digest is None or session_digest is None or request_digest != session_digest:
            _fail("E_STALE_DIGEST")
        model = _Model(instance)
        target = model.select(request)
        active = model.active(request, session)
        provider = model.owner(target)
        provider_wire = provider.get("sourceAgentId")
        if not _wire_string(provider_wire) or len(model.wire_agents.get(provider_wire, [])) != 1:
            _fail("E_NO_DECLARED_ACTION")
        local = active["id"] == provider["id"]
        if not local and provider["id"] not in _refs(active, "handoffTarget"):
            _fail("E_NO_HANDOFF_PATH")
        path = model.declared_path(provider, target)
        _trace_matches(trace, path)
        _validate_request(model, path, request)
        return _verdict("ANSWER_LOCAL" if local else "ANSWER_AFTER_HANDOFF",
                        provider=provider_wire, action=path.action)
    except _Reject as rejection:
        return _verdict("REJECT", reason=rejection.reason)


def _reject_nonfinite(text):
    raise ValueError("Non-finite JSON number: " + text)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", help="JSON file containing instance, trace, request, session; '-' reads stdin")
    args = parser.parse_args(argv)
    try:
        content = sys.stdin.read() if args.input == "-" else Path(args.input).read_text(encoding="utf-8-sig")
        bundle = json.loads(content, parse_constant=_reject_nonfinite)
        if not isinstance(bundle, dict) or any(k not in bundle for k in ("instance", "trace", "request", "session")):
            raise ValueError("Input must contain instance, trace, request, and session")
        result = evaluate(bundle["instance"], bundle["trace"], bundle["request"], bundle["session"])
    except (OSError, ValueError, TypeError) as error:
        print(str(error), file=sys.stderr)
        print(json.dumps(_verdict("REJECT", reason="E_PUBLICATION_INCONSISTENT")))
        return 2
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Publication-time routing cache; request identity/schema checks remain in state."""
from __future__ import annotations
import hashlib
import importlib.util
import json
from pathlib import Path
import threading
from .roomcontract_v2_runtime import RoomContractContractError

_CACHE = {}
_LOCK = threading.RLock()
_VERIFIER = None

def verified_table(contract):
    global _VERIFIER
    # The digest indexes model identity. Trace semantics get an additional key:
    # a same-model trace edit must never reuse the previous publication table.
    digest = str(contract.get("model_sha256") or "")
    trace_hash = hashlib.sha256(json.dumps(contract.get("trace"), sort_keys=True,
        separators=(",", ":"), default=str).encode()).hexdigest()
    key = (digest, trace_hash)
    with _LOCK:
        if key not in _CACHE:
            if _VERIFIER is None:
                path = next((p/"tools"/"routing_verifier.py" for p in Path(__file__).resolve().parents
                             if (p/"tools"/"routing_verifier.py").is_file()), None)
                if path is None:
                    raise RoomContractContractError("Publication verifier is unavailable.")
                spec = importlib.util.spec_from_file_location("_verified_room_routing", path)
                _VERIFIER = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(_VERIFIER)
            report = _VERIFIER.verify_routing(contract.get("instance") or {}, contract.get("trace") or {},
                                               model_sha256=digest)
            # Keep explicit reject cells even for faulted experimental publications.
            # Normal publisher policy can require report["ok"] before publication.
            _CACHE[key] = report["routing_table"]
        return _CACHE[key]

def table_route(table, agent_id, entity_id):
    if agent_id not in table:
        return {"decision":"REJECT","reason":"E_ACTIVE_AGENT_UNKNOWN"}
    return table[agent_id].get(entity_id, {"decision":"REJECT","reason":"E_UNKNOWN_ENTITY"})

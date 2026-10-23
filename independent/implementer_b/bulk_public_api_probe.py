"""Record public compiled constructor fallback boundaries without repairs."""
import hashlib
import json
from pathlib import Path

import compiled_policy as backend
import compiled_policy_bulk as bulk
import policy_adapter as original

ROOT = Path(__file__).resolve().parent


def attempt(function):
    try:
        value = function()
        if isinstance(value, (backend.CompiledAdmissionModel, bulk.CompiledAdmissionModel)):
            value = {'mode': value.mode, 'fallback_reason': value.fallback_reason}
        return {'status': 'returned', 'value': value}
    except Exception as error:
        return {'status': 'error', 'type': type(error).__name__, 'message': str(error)}


def main():
    prior = json.loads((ROOT / 'bulk-literal-diagnostics.json').read_text(encoding='utf-8'))
    case = next(row for row in prior['records'] if row['payload_index'] == 1 and row['turn'] == 0)
    instance, trace, request, session = [case[key] for key in ('instance', 'trace', 'request', 'session')]
    results = {'original_evaluate': attempt(lambda: original.evaluate(instance, trace, request, session))}
    for name, module in [('backend', backend), ('bulk', bulk)]:
        results[name] = {
            'exports_evaluate_compiled': hasattr(module, 'evaluate_compiled'),
            'compile_model_default': attempt(lambda module=module: module.compile_model(instance, trace)),
            'compile_model_strict': attempt(lambda module=module: module.compile_model(instance, trace, allow_fallback=False)),
            'evaluate_many_default': attempt(lambda module=module: module.evaluate_many(instance, trace, [(request, session)])),
        }
    protected = json.loads((ROOT / 'bulk-protected-inputs.json').read_text())['protected_sha256']
    unchanged = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest for name, digest in protected.items()}
    output = {
        'scope': 'Owned public APIs only. No integration-level evaluate_compiled wrapper was read or invoked.',
        'input': {key: case[key] for key in ('instance', 'trace', 'request', 'session')},
        'results': results,
        'protected_files_unchanged': unchanged,
        'source_sha256': {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in ('policy_adapter.py', 'admission.lp', 'compiled_policy.py', 'compiled_policy_bulk.py', 'bulk_public_api_probe.py')},
    }
    (ROOT / 'bulk-public-api-probe.json').write_text(json.dumps(output, ensure_ascii=True, indent=2), encoding='utf-8')
    print(json.dumps({'results': results, 'all_protected_unchanged': all(unchanged.values())}, ensure_ascii=True), flush=True)
    assert all(unchanged.values())
    assert results['original_evaluate']['status'] == 'returned'
    for name in ('backend', 'bulk'):
        assert results[name]['exports_evaluate_compiled'] is False
        for method in ('compile_model_default', 'compile_model_strict', 'evaluate_many_default'):
            assert results[name][method]['status'] == 'error'
            assert results[name][method]['type'] == 'RuntimeError'


if __name__ == '__main__':
    main()
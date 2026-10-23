"""Draft native-metadata policy, immutable pins and truthful compile telemetry.

No result caching; source verification belongs outside the inherited bridge.
"""
from pathlib import Path, PurePosixPath
import copy
import datetime
import hashlib
import json
import os

ROOT = Path(__file__).resolve().parents[2]
POLICY = {'id': 'native-records-ge1500-persistent64-v1',
          'threshold_native_records': 1500, 'frozen_before_dispatch': True}
BLOCKED = {'config.json', 'excluded_client',
           'fragebogen-antworten-2026-08-17-vollstaendig-imputiert.json'}


def safe_path(root, name):
    root = Path(root).resolve()
    raw = Path(name)
    path = raw if raw.is_absolute() else root / raw
    # Check lexical components before resolution or reading.
    if any(p.lower() in BLOCKED or p.lower().startswith('\x2eenv') for p in path.parts):
        raise ValueError('Excluded path')
    if '..' in raw.parts:
        raise ValueError('Parent traversal')
    resolved = path.resolve()
    if not resolved.is_relative_to(root):
        raise ValueError('Path outside root')
    cursor = path
    while cursor != root and cursor != cursor.parent:
        if cursor.is_symlink():
            raise ValueError('Linked input/output')
        cursor = cursor.parent
    return resolved


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write_new(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write('\n')


def verify_pins(root, pins):
    if not pins:
        raise ValueError('Empty pins')
    for name, expected in pins.items():
        path = safe_path(root, name)
        if len(expected) != 64 or sha(path) != expected:
            raise ValueError('Pin mismatch: ' + str(name))


def project_pins(project):
    project = Path(project).resolve()
    result = {}
    for parent, dirs, files in os.walk(project):
        dirs[:] = sorted(d for d in dirs if d != '__pycache__')
        for name in dirs:
            safe_path(project, Path(parent) / name)
        for name in sorted(files):
            if name.startswith('runtime') or name.endswith('.log'):
                continue
            path = safe_path(project, Path(parent) / name)
            result[path.relative_to(project).as_posix()] = sha(path)
    return result


def select(instance):
    objects = instance.get('objects') if isinstance(instance, dict) else None
    count = len(objects) if isinstance(objects, list) else None
    return {'native_records': count,
            'selected_mode': 'persistent_compiled_64' if count is not None and count >= 1500 else 'accepted_compiled',
            'reason': 'unclassifiable_accepted' if count is None else
                      ('at_or_above_threshold' if count >= 1500 else 'below_threshold')}


def input_record(project):
    project = Path(project)
    native = (project / 'roomcontract.v2.instance.json').read_bytes()
    return {'input_pins': {
        'model_raw_sha256': hashlib.sha256(native).hexdigest(),
        'model_lf_sha256': hashlib.sha256(native.replace(b'\r\n', b'\n')).hexdigest(),
        'trace_raw_sha256': sha(project / 'trace_map.v2.json')},
        'selection': select(json.loads(native.decode('utf-8-sig'))),
        'project_pins': project_pins(project)}


def event(run, storage_id, kind, **payload):
    if not storage_id.startswith('m_') or any(c not in '0123456789abcdef' for c in storage_id[2:]):
        raise ValueError('Invalid storage identity')
    path = Path(run) / 'hybrid_lifecycle' / storage_id / (kind + '.json')
    write_new(path, dict(payload, event=kind, pid=os.getpid(),
                         utc=datetime.datetime.now(datetime.timezone.utc).isoformat()))
    return path


class RecordedCompiler:
    """Wrap calls without changing returns/exceptions or adding a cache.

    The bridge remains authoritative about which exceptions caused reference
    fallback. Internal mode may already be 'reference' even when selection is
    persistent; these are never conflated.
    """
    def __init__(self, accepted, persistent):
        self.compilers = {'accepted_compiled': accepted, 'persistent_compiled_64': persistent}
        self.snapshots = []

    def __call__(self, instance, trace):
        record = dict(select(instance), internal_compile_mode=None,
                      fallback_reason=None, compile_fallbacks=0, evaluation_fallbacks=0,
                      compile_error=None, evaluation_errors=[], queries=0,
                      last_diagnostics=None)
        self.snapshots.append(record)
        try:
            compiled = self.compilers[record['selected_mode']](instance, trace)
        except Exception as exc:
            record['compile_error'] = {'type': type(exc).__name__, 'message': str(exc)}
            record['compile_fallbacks'] += 1
            raise
        record['internal_compile_mode'] = getattr(compiled, 'mode', None)
        record['fallback_reason'] = getattr(compiled, 'fallback_reason', None)

        class Proxy:
            def __getattr__(self, key):
                return getattr(compiled, key)

            def evaluate(self, request, session):
                record['queries'] += 1
                try:
                    return compiled.evaluate(request, session)
                except Exception as exc:
                    record['evaluation_fallbacks'] += 1
                    record['evaluation_errors'].append({'type': type(exc).__name__, 'message': str(exc)})
                    raise
                finally:
                    # Candidate diagnostics are read-only. A diagnostic failure
                    # is recorded, never converted into a policy fallback.
                    try:
                        record['last_diagnostics'] = copy.deepcopy(compiled.diagnostics()) if hasattr(compiled, 'diagnostics') else None
                    except Exception as exc:
                        record['diagnostic_error'] = {'type': type(exc).__name__, 'message': str(exc)}
        return Proxy()

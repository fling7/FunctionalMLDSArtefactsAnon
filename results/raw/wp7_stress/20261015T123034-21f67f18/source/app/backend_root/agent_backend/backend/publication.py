"""Opt-in cooperative project publication and crash-recoverable evidence pairs.

Only readers and publishers using this interface participate in its guarantees.
Local process crashes are covered; remote filesystems and power-loss durability on
Windows are not promised. Uncooperative direct writes remain outside the lock.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
from pathlib import Path
import threading
import time
import uuid
from typing import Any, Callable, Mapping

MARKER = '.publication.json'
LOCK = '.publication.lock'
JOURNAL = '.evidence-transaction.json'
_LOCKS: dict[str, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()
_HELD = threading.local()
FaultHook = Callable[[str], None] | None


def _error(message: str, code: str = 'E_PUBLICATION_INCONSISTENT') -> Exception:
    # Lazy import avoids the runtime loader/publication import cycle.
    from .roomcontract_v2_runtime import RoomContractContractError
    return RoomContractContractError(message, code=code)


def _hit(hook: FaultHook, phase: str) -> None:
    if hook is not None:
        hook(phase)


def _local_path(project_dir: Path, relative: str) -> Path:
    root = Path(project_dir).resolve()
    path = (root / relative).resolve()
    if Path(relative).is_absolute() or path == root or root not in path.parents:
        raise _error('Publication paths must stay within the project directory.')
    return path


@contextlib.contextmanager
def project_lock(project_dir: Path):
    """Reentrant within a thread; shared by processes using this project path."""
    root = Path(project_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    key = os.path.normcase(str(root))
    with _LOCKS_GUARD:
        lock = _LOCKS.setdefault(key, threading.RLock())
    with lock:
        held = getattr(_HELD, 'projects', None)
        if held is None:
            held = _HELD.projects = set()
        if key in held:
            yield
            return
        with (root / LOCK).open('a+b') as handle:
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b'0')
                handle.flush()
            handle.seek(0)
            if os.name == 'nt':
                import msvcrt
                while True:
                    try:
                        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                        break
                    except OSError as exc:
                        if exc.errno not in (13, 11, 36):
                            raise
                        time.sleep(0.005)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            held.add(key)
            try:
                yield
            finally:
                held.remove(key)
                handle.seek(0)
                if os.name == 'nt':
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _fsync_dir(path: Path) -> None:
    # Python does not expose a portable Windows directory fsync. The process-kill
    # model retains directory entries; sudden power loss is explicitly excluded.
    if os.name != 'nt':
        fd = os.open(path, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def atomic_replace(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temp.open('xb') as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        deadline = time.monotonic() + 5.0
        while True:
            try:
                os.replace(temp, path)
                break
            except PermissionError as exc:
                # Windows readers may briefly deny FILE_SHARE_DELETE. Retry the
                # same complete temporary file; never expose a partial replace.
                if os.name != 'nt' or getattr(exc, 'winerror', None) not in (5, 32, 33) or time.monotonic() >= deadline:
                    raise
                time.sleep(0.005)
        _fsync_dir(path.parent)
    finally:
        if temp.exists():
            temp.unlink()


def read_publication(project_dir: Path) -> dict[str, Any]:
    try:
        marker = json.loads((Path(project_dir) / MARKER).read_text(encoding='utf-8'))
        if marker.get('schema') != 'roomcontract-publication-v1':
            raise ValueError('unknown publication schema')
        generation = marker['generation']
        if isinstance(generation, bool) or not isinstance(generation, int) or generation < 1:
            raise ValueError('generation must be a positive integer')
        if not isinstance(marker.get('files'), dict) or not marker['files']:
            raise ValueError('empty projection manifest')
        for name, digest in marker['files'].items():
            _local_path(Path(project_dir), name)
            if not isinstance(digest, str) or len(digest) != 64:
                raise ValueError('invalid projection digest')
        return marker
    except Exception as exc:
        raise _error('Missing or invalid cooperative publication marker.') from exc


def publication_generation(project_dir: Path) -> int:
    return read_publication(project_dir)['generation']


def collect_projection_bytes(project_dir: Path) -> dict[str, bytes]:
    """Collect project-local deployment and prompt inputs; excludes evidence."""
    root = Path(project_dir)
    names = ['project.json', 'agents.json', 'room_plan.json']
    meta = json.loads((root / 'project.json').read_text(encoding='utf-8'))
    names += [meta.get('roomcontract_model_path') or meta.get('roomcontract_v2_path') or 'roomcontract.v2.instance.json',
              meta.get('roomcontract_trace_map_path') or 'trace_map.v2.json']
    for candidate in ('agent_placements.json', 'placement.json'):
        if (root / candidate).exists():
            names.append(candidate)
    kb = root / 'kb'
    if kb.exists():
        names += [str(p.relative_to(root)).replace('\\', '/') for p in sorted(kb.rglob('*')) if p.is_file()]
    return {str(name).replace('\\', '/'): _local_path(root, str(name)).read_bytes() for name in names}


def _required_names(projections: Mapping[str, bytes]) -> set[str]:
    try:
        meta = json.loads(projections['project.json'])
        return {'project.json', 'agents.json', 'room_plan.json',
                str(meta.get('roomcontract_model_path') or meta.get('roomcontract_v2_path') or 'roomcontract.v2.instance.json'),
                str(meta.get('roomcontract_trace_map_path') or 'trace_map.v2.json')}
    except Exception as exc:
        raise _error('Publication must contain valid project metadata.') from exc


def publish_project(project_dir: Path, projections: Mapping[str, bytes], *,
                    validate: Callable[[Path], Any] | None = None,
                    fault_hook: FaultHook = None) -> dict[str, Any]:
    """Replace full deployment, validate, then atomically flip its generation.

    A failure before the flip leaves a partial deployment which consistent readers
    refuse. Recovery requires publishing a complete deployment again; no automatic
    rollback of model files is claimed. Validation is supplied by the caller to
    avoid coupling publication to a particular metamodel version.
    """
    root = Path(project_dir).resolve()
    payloads = {str(name).replace('\\', '/'): bytes(data) for name, data in projections.items()}
    if not _required_names(payloads).issubset(payloads):
        raise _error('Publication omits a required deployment projection.')
    for name in payloads:
        if name in (MARKER, LOCK, JOURNAL) or name.startswith('runtime_logs/'):
            raise _error('Deployment projections cannot overwrite protocol or evidence files.')
        _local_path(root, name)
    with project_lock(root):
        previous = read_publication(root) if (root / MARKER).exists() else None
        generation = previous['generation'] + 1 if previous else 1
        for name, data in payloads.items():
            _hit(fault_hook, 'before_write:' + name)
            atomic_replace(_local_path(root, name), data)
            _hit(fault_hook, 'after_write:' + name)
        # Remove files omitted by the new full manifest (for example a KB deletion).
        if previous:
            for name in set(previous['files']) - set(payloads):
                _local_path(root, name).unlink(missing_ok=True)
        if validate is not None:
            validate(root)
        marker = {'schema': 'roomcontract-publication-v1', 'generation': generation,
                  'files': {name: hashlib.sha256(data).hexdigest() for name, data in sorted(payloads.items())}}
        _hit(fault_hook, 'before_generation_flip')
        atomic_replace(root / MARKER, json.dumps(marker, sort_keys=True).encode('utf-8'))
        _hit(fault_hook, 'after_generation_flip')
        return marker


def _verified_bytes(root: Path, marker: Mapping[str, Any]) -> dict[str, bytes]:
    out = {}
    for name, expected in marker['files'].items():
        data = _local_path(root, name).read_bytes()
        if hashlib.sha256(data).hexdigest() != expected:
            raise _error('Projection differs from the published manifest: ' + name)
        out[name] = data
    if not _required_names(out).issubset(out):
        raise _error('Publication manifest omits a required projection.')
    # A new KB document is also a prompt mutation, not an unobserved extra file.
    kb = root / 'kb'
    actual_kb = {p.relative_to(root).as_posix() for p in kb.rglob('*') if p.is_file()} if kb.exists() else set()
    if actual_kb != {name for name in out if name.startswith('kb/')}:
        raise _error('Knowledge-base file inventory differs from the publication manifest.')
    return out


def load_consistent_contract(project_dir: Path, loader: Callable[[Path], dict[str, Any]], *,
                             retries: int = 3, fault_hook: FaultHook = None) -> dict[str, Any]:
    """Generation/read/re-read snapshot with full projection hash validation.

    A generation counter alone cannot detect a publisher stopped before its last
    flip. Both manifest verification passes are therefore mandatory.
    """
    root = Path(project_dir).resolve()
    last_error = None
    for _ in range(max(1, retries)):
        before = read_publication(root)
        try:
            projections = _verified_bytes(root, before)
            _hit(fault_hook, 'after_projection_read')
            contract = loader(root)
            for field in ('instance_path', 'trace_path'):
                if contract.get(field):
                    relative = Path(contract[field]).resolve().relative_to(root).as_posix()
                    if relative not in before['files']:
                        raise _error('Loaded contract file is absent from the publication manifest.')
            _verified_bytes(root, before)
            _hit(fault_hook, 'before_generation_reread')
            after = read_publication(root)
            if before != after:
                continue
            contract['publication_generation'] = before['generation']
            contract['publication_protocol'] = 'cooperative'
            contract['publication_projections'] = {name: json.loads(data) for name, data in projections.items() if name.endswith('.json')}
            return contract
        except Exception as exc:
            last_error = exc
            after = read_publication(root)
            if before != after:
                continue
            raise _error('Cooperative publication is incomplete or inconsistent: ' + str(exc)) from exc
    raise _error('Publication changed during every snapshot attempt.') from last_error


APPEND_PHASES = ('before_journal', 'after_journal', 'after_event_partial', 'after_event_write',
                 'after_event_fsync', 'after_validation_partial', 'after_validation_write',
                 'after_validation_fsync', 'before_journal_clear', 'after_journal_clear')


def recover_evidence(project_dir: Path) -> bool:
    """Undo an interrupted uncommitted pair. Safe to repeat after another crash."""
    root = Path(project_dir).resolve()
    with project_lock(root):
        journal = root / JOURNAL
        if not journal.exists():
            return False
        try:
            record = json.loads(journal.read_text(encoding='utf-8'))
            if record.get('schema') != 'roomcontract-evidence-undo-v1':
                raise ValueError('unknown journal schema')
            for item in record['files']:
                path = _local_path(root, item['path'])
                if not path.exists() or path.stat().st_size < item['start']:
                    raise ValueError('evidence shorter than journal start')
                with path.open('r+b') as handle:
                    handle.truncate(item['start'])
                    handle.flush()
                    os.fsync(handle.fileno())
            journal.unlink()
            _fsync_dir(root)
            return True
        except Exception as exc:
            raise _error('Evidence recovery failed; refusing subsequent commits.', 'E_EVIDENCE_APPEND') from exc


def append_evidence_pair(project_dir: Path, event_path: Path, event_payload: bytes,
                         validation_path: Path | None, validation_payload: bytes, *,
                         fault_hook: FaultHook = None) -> None:
    """Append under durable undo intent; visibility is through read_evidence_pair.

    Once the intent is removed the pair is committed. Exceptions from an optional
    observer after that point must not roll back the pair. A process may die after
    commit but before its caller receives success (ordinary acknowledgement gap).
    """
    root = Path(project_dir).resolve()
    with project_lock(root):
        recover_evidence(root)
        paths = [(Path(event_path), event_payload, 'event')]
        if validation_path is not None:
            paths.append((Path(validation_path), validation_payload, 'validation'))
        files = []
        for path, payload, label in paths:
            relative = path.resolve().relative_to(root).as_posix()
            _local_path(root, relative)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch(exist_ok=True)
            files.append({'path': relative, 'start': path.stat().st_size})
        record = {'schema': 'roomcontract-evidence-undo-v1', 'id': uuid.uuid4().hex, 'files': files}
        committed = False
        try:
            _hit(fault_hook, 'before_journal')
            atomic_replace(root / JOURNAL, json.dumps(record, sort_keys=True).encode('utf-8'))
            _hit(fault_hook, 'after_journal')
            for path, payload, label in paths:
                with path.open('ab') as handle:
                    split = len(payload) // 2
                    handle.write(payload[:split])
                    handle.flush()
                    _hit(fault_hook, 'after_' + label + '_partial')
                    handle.write(payload[split:])
                    handle.flush()
                    _hit(fault_hook, 'after_' + label + '_write')
                    os.fsync(handle.fileno())
                    _hit(fault_hook, 'after_' + label + '_fsync')
            _hit(fault_hook, 'before_journal_clear')
            (root / JOURNAL).unlink()
            committed = True
            _fsync_dir(root)
        except Exception as exc:
            if committed:
                # Both file payloads are durable and the process-visible commit
                # already occurred. Directory-sync failure cannot turn success
                # into a rollback; sudden power loss is outside this contract.
                return
            recover_evidence(root)
            raise _error('Evidence pair append failed.', 'E_EVIDENCE_APPEND') from exc
        # This hook models the acknowledgement gap. It is not a write operation.
        # Keep a raised observer exception distinguishable from E_EVIDENCE_APPEND.
        try:
            _hit(fault_hook, 'after_journal_clear')
        except Exception:
            # Diagnostic observer failure cannot uncommit a visible pair. A hard
            # process exit here still demonstrates the acknowledgement gap.
            pass


def read_evidence_pair(project_dir: Path, event_path: Path, validation_path: Path | None):
    """Only this cooperating read interface promises pair visibility."""
    with project_lock(project_dir):
        recover_evidence(project_dir)
        def read(path):
            if path is None or not Path(path).exists():
                return []
            return [json.loads(line) for line in Path(path).read_text(encoding='utf-8').splitlines()]
        return read(event_path), read(validation_path)

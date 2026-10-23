"""Unadopted fresh-batch adapter. No CLI dispatch or active-pool takeover.

The callable is for a future reviewed entry point. A supplied exact frozen lock
and explicit fresh-boundary authorization are required. Tests inject recorders.
"""
from contextlib import contextmanager
from pathlib import Path
import copy
import sys

from .core import ROOT, POLICY, event, input_record, load, safe_path, sha, verify_pins, write_new
from .worker import hybrid_worker, verify_execution
from .paths import repository_path, relative_name, portable_job, execution_job
from .boundary import verify_boundary


def build_modes(run, rows, protocol, prepared=None):
    run = Path(run)
    original = load(run/'mutation_manifest.json')
    lookup = {r['case_id']: r for r in rows}
    if len(lookup) != len(rows):
        raise ValueError('Duplicate source identity')
    selected = []; ids = set(); storage = set()
    for meta in original['models']:
        if meta['id'] in ids or meta['storage_id'] in storage:
            raise ValueError('Duplicate planned identity')
        ids.add(meta['id']); storage.add(meta['storage_id'])
        if meta['room'] not in lookup:
            raise ValueError('Unregistered planned room')
        if meta['status'] not in {'changed', 'incomplete'}:
            continue
        source = lookup[meta['room']]
        project = safe_path(run, run/'models'/meta['storage_id']/Path(source['project_path']).name)
        output = safe_path(run, run/'outcomes'/(meta['storage_id']+'.json'))
        if output.exists():
            raise ValueError('Pre-existing outcome in fresh batch')
        job = portable_job(ROOT, {'project': str(project), 'output': str(output), 'metadata': copy.deepcopy(meta)})
        actual = input_record(project)
        if prepared is not None and prepared.get(str(project)) != actual:
            raise ValueError('Materialized model changed during preparation')
        selected.append(dict(metadata=copy.deepcopy(meta), job=job,
                             source_room_id=source['source_room_id'], source_provenance=copy.deepcopy(source),
                             **actual))
    if prepared is not None and set(prepared) != {str(repository_path(ROOT, r['job']['project'])) for r in selected}:
        raise ValueError('Prepared model identities differ from scheduled manifest')
    manifest = {'schema': 'wp6-hybrid-mode-manifest-portable-v2', 'policy': POLICY,
                'batch_ordinal': protocol['batch_ordinal'],
                'execution_lock_sha256': protocol['lock_sha256'],
                'mutation_manifest_sha256': sha(run/'mutation_manifest.json'),
                'all_original_attempts': len(original['models']), 'rows': selected}
    return manifest


@contextmanager
def record_prepared_inputs(matrix, records, manifest_record=None):
    original = matrix.materialize
    original_write = matrix.write_new
    def materialize(base, mutated, directory):
        result = original(base, mutated, directory)
        path = str(Path(directory).resolve())
        if path in records:
            raise ValueError('Repeated materialization identity')
        records[path] = input_record(directory)
        return result
    def write(path, value):
        result = original_write(path, value)
        if manifest_record is not None and Path(path).name == 'mutation_manifest.json':
            if manifest_record:
                raise ValueError('Repeated mutation manifest publication')
            manifest_record.update(path=str(Path(path).resolve()), sha256=sha(path))
        return result
    matrix.materialize = materialize
    matrix.write_new = write
    try:
        yield
    finally:
        matrix.materialize = original
        matrix.write_new = original_write


def verify_modes(run, manifest):
    verify_pins(run, {'mutation_manifest.json': manifest['mutation_manifest_sha256']})
    for row in manifest['rows']:
        project = safe_path(run, repository_path(ROOT, row['job']['project']))
        if input_record(project) != {k: row[k] for k in ['input_pins', 'selection', 'project_pins']}:
            raise ValueError('Prepared model changed before dispatch')


def confirm_parent(run, job):
    sid = job['metadata']['storage_id']
    paths = {'outcome': Path(job['output']),
             'sidecar': Path(run)/'hybrid_provenance'/(sid+'.json'),
             'performance': Path(run)/'performance_hybrid_memoization'/(sid+'.json'),
             'worker_finished': Path(run)/'hybrid_lifecycle'/sid/'worker_finished.json'}
    done = load(paths['worker_finished']); sidecar = load(paths['sidecar'])
    if any(sidecar.get(k) != job['metadata'][v] for k, v in [('storage_id','storage_id'),('original_id','id'),('room','room')]):
        raise ValueError('Completion provenance identity mismatch')
    if (Path(run)/'worker_failures'/(sid+'.json')).exists() or (Path(run)/'hybrid_lifecycle'/sid/'worker_failed.json').exists():
        raise ValueError('Retained worker failure prevents parent success')
    if sha(paths['outcome']) != done['outcome_sha256'] or sha(paths['sidecar']) != done['sidecar_sha256'] or sha(paths['performance']) != done['performance_sha256']:
        raise ValueError('Worker completion artifact mismatch')
    if sidecar['completion']['outcome_sha256'] != done['outcome_sha256'] or not sidecar['completion']['sidecar_complete']:
        raise ValueError('Incomplete provenance')
    return {name+'_sha256': sha(path) for name, path in paths.items()}


@contextmanager
def scoped_dispatch(matrix, worker, before_enter, envelope, manifest_holder):
    original = matrix.ProcessPoolExecutor
    original_evaluator = matrix.evaluate_one

    class Dispatch:
        def __init__(self, *args, **kwargs):
            self.args = args; self.kwargs = kwargs; self.executor = None; self.ordinal = 0

        def __enter__(self):
            before_enter()
            self.executor = original(*self.args, **self.kwargs)
            self.executor.__enter__()
            return self

        def submit(self, function, job):
            if function is not original_evaluator:
                raise ValueError('Unexpected submitted callable')
            expected = manifest_holder['value']['rows']
            if self.ordinal >= len(expected) or portable_job(ROOT, job) != expected[self.ordinal]['job']:
                raise ValueError('Original submitted job/order mismatch')
            ordinal = self.ordinal; self.ordinal += 1
            sid = job['metadata']['storage_id']; run = repository_path(ROOT, envelope['run_dir'])
            event(run, sid, 'submit_attempt', ordinal=ordinal,
                  mode_manifest_sha256=envelope['mode_manifest_sha256'])
            try:
                future = self.executor.submit(worker, job, copy.deepcopy(envelope))
            except BaseException as exc:
                event(run, sid, 'submit_failed', exception=type(exc).__name__, message=str(exc))
                raise
            event(run, sid, 'submitted', ordinal=ordinal)
            original_result = future.result
            recorded = False

            def result(*args, **kwargs):
                nonlocal recorded
                value = original_result(*args, **kwargs)  # retains original exception
                if not recorded:
                    evidence = confirm_parent(run, job)
                    event(run, sid, 'parent_returned', **evidence)
                    recorded = True
                return value
            future.result = result
            return future

        def __exit__(self, *exc):
            result = self.executor.__exit__(*exc)
            if exc[0] is None and self.ordinal != len(manifest_holder['value']['rows']):
                raise ValueError('Not all scheduled identities submitted')
            return result

    matrix.ProcessPoolExecutor = Dispatch
    try:
        yield
    finally:
        matrix.ProcessPoolExecutor = original


def verify_registered_scope(rows, run, workers, protocol, lock):
    # Scope/authorization are frozen inputs, not mutable command-line claims.
    from experiments.run_mutation_compiled_batch import select_batch
    dispatch = lock['dispatch']
    if dispatch != {'batch_ordinal': protocol['batch_ordinal'], 'run_dir': relative_name(ROOT, run),
                    'workers': workers, 'authorization': protocol['authorization']}:
        raise ValueError('Dispatch scope differs from exact execution lock')
    original = load(safe_path(ROOT, lock['original_execution_lock']['path']))
    inventory = load(safe_path(ROOT, original['source_inventory']['path']))
    queue = load(safe_path(ROOT, original['ordered_queue']['path']))
    if rows != select_batch(queue, inventory, protocol['batch_ordinal']):
        raise ValueError('Requested rows differ from frozen queue/inventory')


def run_fresh(rows, run_dir, workers, protocol, verify=None, *, worker=hybrid_worker):
    """Same frozen planner/main, separate policy manifest and future lifecycle.

    `verify` injection is only for synthetic engineering tests. A production
    entry point must use the default strict verifier and retain the exact lock.
    No timeout is imposed on scientific jobs.
    """
    run = repository_path(ROOT, run_dir)
    verify_boundary(ROOT, rows, run_dir, workers, protocol)
    if run.exists() or any(run.with_name(run.name+s).exists() for s in ['_fresh_protocol.json','_dispatch_check.json']):
        raise FileExistsError('Fresh output/boundary already exists: '+str(run))
    if protocol['batch_ordinal'] < 3 or protocol.get('policy') != POLICY:
        raise ValueError('Grandfathered batch or wrong threshold/policy')
    authorization = protocol.get('authorization', {})
    if (authorization.get('status') != 'root_reviewed_future_dispatch'
        or repository_path(ROOT, authorization.get('run_dir', '')) != run
        or authorization.get('all_prior_submitted_jobs_grandfathered') is not True
        or authorization.get('batch_confirmed_unstarted') is not True
        or authorization.get('ordered_case_ids') != [r['case_id'] for r in rows]):
        raise ValueError('Missing exact future-boundary authorization')
    if workers not in {4, 8} or authorization.get('other_owned_workers', 99)+workers > 12:
        raise ValueError('Worker ceiling/budget not confirmed')
    synthetic_verifier = verify is not None
    verify = verify or (lambda: verify_execution(protocol['lock_path'], protocol['lock_sha256']))
    before = verify()
    if not synthetic_verifier:
        verify_registered_scope(rows, run, workers, protocol, before)
    from experiments.run_mutation_compiled_batch import audit_sources
    from experiments import detection_matrix as matrix
    first = audit_sources(rows)
    write_new(run.with_name(run.name+'_fresh_protocol.json'),
              dict(protocol, source_audits_before_preparation=first, workers=workers,
                   note='Boundary assertion is explicit operator authorization, not inferred from missing outcome files.'))
    holder = {}; prepared = {}; original_manifest = {}; envelope = {'run_dir': run_dir, 'lock_path': protocol['lock_path'], 'lock_sha256': protocol['lock_sha256']}

    def gate():
        verify_boundary(ROOT, rows, run_dir, workers, protocol)
        if verify() != before or audit_sources(rows) != first:
            raise ValueError('Source/lock changed during preparation')
        if original_manifest.get('path') != str(run/'mutation_manifest.json') or original_manifest.get('sha256') != sha(run/'mutation_manifest.json'):
            raise ValueError('Original mutation manifest changed during preparation')
        manifest = build_modes(run, rows, protocol, prepared)
        path = run/'hybrid_mode_manifest.json'
        write_new(path, manifest)
        if verify() != before or audit_sources(rows) != first:
            raise ValueError('Source/lock changed while freezing mode manifest')
        verify_modes(run, manifest)
        holder['value'] = manifest; envelope['mode_manifest_sha256'] = sha(path)
        write_new(run.with_name(run.name+'_dispatch_check.json'),
                  {'unchanged': True, 'mode_manifest_sha256': sha(path),
                   'scheduled_identities': len(manifest['rows']), 'workers': workers})

    argv = sys.argv
    try:
        sys.argv = ['detection_matrix.py', '--run-dir', str(run), '--workers', str(workers)]
        for row in rows:
            sys.argv += ['--project', str(ROOT/row['project_path'])]
        with record_prepared_inputs(matrix, prepared, original_manifest):
            with scoped_dispatch(matrix, worker, gate, envelope, holder):
                result = matrix.main()
        # Keep original summary/status unchanged. Supplemental closure must
        # include parent return evidence, not merely output presence.
        completed = []; unresolved = []
        for row in holder['value']['rows']:
            sid = row['metadata']['storage_id']
            parent = run/'hybrid_lifecycle'/sid/'parent_returned.json'
            try:
                evidence = confirm_parent(run, execution_job(ROOT, row['job']))
                if not parent.exists() or any(load(parent).get(k) != v for k, v in evidence.items()):
                    raise ValueError('Parent return evidence absent/mismatched')
                completed.append(sid)
            except (OSError, ValueError, KeyError) as exc:
                unresolved.append({'storage_id': sid, 'reason': str(exc)})
        write_new(run/'hybrid_closure.json', {'scheduled': len(holder['value']['rows']),
                  'parent_confirmed': completed, 'unresolved': unresolved,
                  'closure_complete': not unresolved, 'next_batch_review_required': bool(unresolved)})
        return result if not unresolved else 1
    finally:
        sys.argv = argv

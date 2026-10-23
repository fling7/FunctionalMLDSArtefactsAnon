"""Unadopted hybrid worker; strict checks occur before inherited fallbacks."""
from pathlib import Path
import copy

from .core import ROOT, POLICY, RecordedCompiler, event, input_record, load, safe_path, sha, verify_pins, write_new

from .paths import repository_path, portable_job

HERE = Path(__file__).resolve().parent
REQUIRED = [
    *(p.relative_to(ROOT).as_posix() for p in [HERE/'__init__.py', HERE/'core.py', HERE/'worker.py', HERE/'adapter.py', HERE/'import_boundary.py', HERE/'compatibility.py', HERE/'paths.py', HERE/'boundary.py', HERE/'retained/analyze_wp7_009.py.txt']),
    *( (HERE/'proposed'/name).relative_to(ROOT).as_posix() for name in ['compiled_policy.py','persistent_policy_v3.py','policy_adapter.py','admission.lp']),
    'experiments/run_mutation_compiled_batch.py', 'experiments/detection_matrix.py',
    'experiments/static_contract_memoization_v3.py', 'experiments/static_policy_compilation.py',
    'verification/impl_b/compiled_policy.py', 'verification/impl_b/policy_adapter.py',
    'verification/impl_b/admission.lp',
]


def verify_execution(lock_path, expected_sha256):
    lock_path = repository_path(ROOT, lock_path)
    verify_pins(ROOT, {str(lock_path): expected_sha256})
    lock = load(lock_path)
    if lock.get('status') != 'frozen' or lock.get('policy') != POLICY:
        raise ValueError('Future dispatch lock/policy is not frozen')
    if any(name not in lock['code_hashes'] for name in REQUIRED):
        raise ValueError('Execution lock omits required implementation source')
    for name in lock['code_hashes']:
        repository_path(ROOT, name)
    verify_pins(ROOT, lock['code_hashes'])
    original = lock['original_execution_lock']
    # The narrow prospective verifier preserves010/008 and all009 pins except
    # the exact root-adopted report-only bytes. Historical locks stay unchanged.
    from .compatibility import verify_execution_pins_compat
    verify_execution_pins_compat(safe_path(ROOT, original['path']), original['sha256'],
                                transition=lock['report_only_dependency_transition'])
    return lock


def verify_job(job, envelope):
    lock = verify_execution(envelope['lock_path'], envelope['lock_sha256'])
    run = repository_path(ROOT, envelope['run_dir'])
    mode_path = run/'hybrid_mode_manifest.json'
    verify_pins(ROOT, {str(mode_path): envelope['mode_manifest_sha256']})
    manifest = load(mode_path)
    if manifest['policy'] != POLICY or manifest['execution_lock_sha256'] != envelope['lock_sha256']:
        raise ValueError('Mode manifest policy/lock mismatch')
    verify_pins(ROOT, {str(run/'mutation_manifest.json'): manifest['mutation_manifest_sha256']})
    matches = [r for r in manifest['rows'] if r['metadata']['storage_id'] == job['metadata']['storage_id']]
    if len(matches) != 1:
        raise ValueError('Missing/duplicate prepared job identity')
    row = matches[0]
    if portable_job(ROOT, job) != row['job']:
        raise ValueError('Original job metadata/path mismatch')
    project = safe_path(run, job['project'])
    if safe_path(run, job['output']) != run/'outcomes'/(job['metadata']['storage_id']+'.json'):
        raise ValueError('Output identity mismatch')
    verify_pins(project, row['project_pins'])
    # Ignore only original runtime logs/cache exclusions; compare full retained
    # static file set as well as native model/trace/count, not baseline proxies.
    if input_record(project) != {k: row[k] for k in ['input_pins','selection','project_pins']}:
        raise ValueError('Prepared model/count/static file set changed')
    return lock, manifest, row


def execute_scoped(job, envelope, verify, matrix, contract_scope, policy_scope, accepted, persistent):
    """Dependency-injected for recording tests; production calls use pinned code."""
    lock, manifest, row = verify(job, envelope)
    run = repository_path(ROOT, envelope['run_dir']); sid = job['metadata']['storage_id']
    event(run, sid, 'worker_started', mode_manifest_sha256=envelope['mode_manifest_sha256'])
    compiler = RecordedCompiler(accepted, persistent)
    try:
        with contract_scope() as contract:
            with policy_scope(matrix, compiler=compiler) as policy:
                result = matrix.evaluate_one(job)
        # No protocol exception is inside the bridge's fallback scope.
        verify(job, envelope)
        if any('diagnostic_error' in s for s in compiler.snapshots):
            raise ValueError('Incomplete compile diagnostics')
        outcome_sha = sha(job['output'])
        sidecar = {
            'schema': 'wp6-hybrid-row-provenance-v1',
            'original_id': job['metadata']['id'], 'storage_id': sid,
            'room': job['metadata']['room'], 'source_room_id': row['source_room_id'],
            'batch_ordinal': manifest['batch_ordinal'],
            'mutation_manifest_sha256': manifest['mutation_manifest_sha256'],
            'execution_lock_sha256': envelope['lock_sha256'],
            'original_execution_lock_sha256': lock['original_execution_lock']['sha256'],
            'report_only_dependency_transition': copy.deepcopy(lock['report_only_dependency_transition']),
            'policy': POLICY, 'input_pins': row['input_pins'],
            'selection': row['selection'], 'source_pins': lock['code_hashes'],
            'snapshots': compiler.snapshots,
            'completion': {'status': 'worker_finished', 'outcome_sha256': outcome_sha,
                           'sidecar_complete': True, 'parent_return_evidence': None,
                           'retained_failure_paths': []}}
        # Original combined diagnostic shape is preserved in a separate file;
        # actual bridge counters include key failures and reference fallbacks.
        performance = run/'performance_hybrid_memoization'/(sid+'.json')
        write_new(performance, {'model': job['metadata']['id'], 'contract': contract,
                               'policy': policy, 'selected_snapshots': compiler.snapshots})
        path = run/'hybrid_provenance'/(sid+'.json')
        write_new(path, sidecar)
        event(run, sid, 'worker_finished', outcome_sha256=outcome_sha,
              sidecar_sha256=sha(path), performance_sha256=sha(performance))
        return result
    except BaseException as exc:
        # Parent still records the original worker failure. This supplements it
        # and never deletes a complete outcome or a partial sidecar.
        event(run, sid, 'worker_failed', exception=type(exc).__name__, message=str(exc),
              outcome_present=Path(job['output']).exists(), snapshots=compiler.snapshots)
        raise


def hybrid_worker(job, envelope):
    verify_job(job, envelope)
    # Strict import/source checks are deliberately outside the compiler bridge.
    from .import_boundary import load_candidate
    candidate = load_candidate()
    from verification.impl_b import compiled_policy as accepted_module
    if Path(accepted_module.__file__).resolve() != ROOT/'verification/impl_b/compiled_policy.py':
        raise ValueError('Accepted compiler module path mismatch')
    from experiments import detection_matrix as matrix
    from experiments.static_contract_memoization_v3 import static_contract_memoization_v3
    from experiments.static_policy_compilation import static_policy_compilation
    verify_job(job, envelope)
    return execute_scoped(job, envelope, verify_job, matrix, static_contract_memoization_v3,
                          static_policy_compilation, accepted_module.compile_model, candidate.compile_model)

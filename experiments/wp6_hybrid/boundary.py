"""Affirmative fresh-boundary evidence, never inferred from missing outcomes."""
from .core import load, verify_pins
from .paths import repository_path

CASE_IDS = ['scene_033_ocean_discovery_mini_r0', 'scene_043_transport_center_mini_r0']
RUN = 'results/raw/wp6_original_batch03_hybrid_v1'


def checked_record(root, ref):
    if not isinstance(ref, dict) or set(ref) != {'path', 'sha256'}:
        raise ValueError('Missing exact boundary evidence pin')
    path = repository_path(root, ref['path'])
    verify_pins(root, {ref['path']: ref['sha256']})
    value = load(path)
    if not isinstance(value, dict):
        raise ValueError('Invalid boundary evidence record')
    return value


def verify_boundary(root, rows, run_name, workers, protocol):
    repository_path(root, run_name)
    repository_path(root, protocol['lock_path'])
    auth = protocol.get('authorization', {})
    if (run_name != RUN or protocol.get('batch_ordinal') != 3
        or workers != 4 or type(workers) is not int
        or [r['case_id'] for r in rows] != CASE_IDS
        or auth.get('status') != 'root_reviewed_future_dispatch'
        or auth.get('run_dir') != run_name or auth.get('ordered_case_ids') != CASE_IDS
        or auth.get('all_prior_submitted_jobs_grandfathered') is not True
        or auth.get('batch_confirmed_unstarted') is not True):
        raise ValueError('Missing exact future-boundary authorization')
    count = auth.get('other_owned_workers')
    if type(count) is not int or not 0 <= count <= 8:
        raise ValueError('Worker ceiling/capacity not confirmed')
    scope = checked_record(root, auth.get('scope_attestation'))
    capacity = checked_record(root, auth.get('capacity_attestation'))
    approval = checked_record(root, auth.get('root_dispatch_approval'))
    common = {'run_dir': run_name, 'batch_ordinal': 3, 'ordered_case_ids': CASE_IDS}
    if any(any(record.get(k) != v for k, v in common.items()) for record in (scope, capacity, approval)):
        raise ValueError('Boundary evidence scope mismatch')
    if (scope.get('schema') != 'wp6-future-scope-attestation-v1'
        or scope.get('status') != 'affirmed_by_campaign_owner'
        or scope.get('official_full_matrix_previously_submitted') is not False
        or scope.get('engineering_probes_disclosed') is not True
        or scope.get('all_prior_submissions_grandfathered') is not True
        or not isinstance(scope.get('positive_lifecycle_pins'), dict) or not scope['positive_lifecycle_pins']):
        raise ValueError('Affirmative unsubmitted-scope evidence required')
    if (capacity.get('schema') != 'wp6-future-capacity-attestation-v1'
        or capacity.get('status') != 'confirmed_after_owned_pool_exit'
        or capacity.get('batch02_pool_terminal') is not True
        or type(capacity.get('other_owned_workers')) is not int or capacity['other_owned_workers'] != count
        or capacity.get('new_workers') != 4 or capacity.get('total_ceiling') != 12
        or not isinstance(capacity.get('terminal_process_evidence_pins'), dict) or not capacity['terminal_process_evidence_pins']):
        raise ValueError('Actual released capacity evidence required')
    if (approval.get('schema') != 'wp6-future-dispatch-approval-v1'
        or approval.get('status') != 'approved_by_root_for_fresh_preparation_and_dispatch'
        or approval.get('scope_attestation') != auth['scope_attestation']
        or approval.get('capacity_attestation') != auth['capacity_attestation']
        or approval.get('source_adoption_freeze') != protocol.get('source_adoption_freeze')
        or not isinstance(approval.get('source_adoption_freeze'), dict)):
        raise ValueError('Separate exact root dispatch approval required')
    checked_record(root, approval['source_adoption_freeze'])
    for record, key in [(scope, 'positive_lifecycle_pins'), (capacity, 'terminal_process_evidence_pins')]:
        for path in record[key]:
            repository_path(root, path)
        verify_pins(root, record[key])
    return {'scope': scope, 'capacity': capacity, 'approval': approval}

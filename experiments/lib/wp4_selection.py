"""WP4-A001 selection over an explicitly terminal, frozen-source WP5 corpus.

No model calls, labels or performance outcomes are used to choose source rooms.
"""
from __future__ import annotations
import hashlib
import json
import stat
from pathlib import Path
from experiments.lib.wp4_amendments import checked_file, digest, frozen_json, read_json, relative_file

COMBINED_SCHEMA = 'wp5-combined-primary-provenance-v1'
COHORT_LABEL = 'Expanded exploratory corpus; adapted after original authoring outcomes and before WP4 model results.'
ELIGIBILITY_FLAGS = ('source_valid', 'pipeline_success', 'project_produced', 'canonical_valid', 'schema_valid', 'gate0_ok')
STRATA = ('original', 'extension_deterministic', 'extension_llm')
MINI = 'gpt-4.1-mini-2025-04-14'


def registered_sources(original, extension):
    ids = list(dict.fromkeys(r['scene_id'] for r in original['evaluation']))
    result = [{'source_room_id': sid, 'corpus_family': 'original', 'source_order_within_stratum': i + 1} for i, sid in enumerate(ids)]
    for family, key in (('extension_deterministic', 'new_deterministic_sources'), ('extension_llm', 'llm_authored_sources')):
        result.extend({'source_room_id': r['source_id'], 'corpus_family': family, 'source_order_within_stratum': i + 1} for i, r in enumerate(extension[key]))
    if len({r['source_room_id'] for r in result}) != len(result):
        raise RuntimeError('Registered source IDs must be distinct across corpus strata')
    return [{**r, 'combined_source_priority': i + 1} for i, r in enumerate(result)]


def select_rows(manifest, original, extension, target=20):
    """Pure selection over the exact registered primary identities, including failures."""
    if manifest.get('schema') != COMBINED_SCHEMA or not all(manifest.get(k) is True for k in ('original_terminal', 'initial_block_terminal', 'manifest_is_complete')):
        raise RuntimeError('Original and extension initial corpus must both be explicitly terminal')
    sources = registered_sources(original, extension)
    by_source = {r['source_room_id']: r for r in sources}
    original_slots = {(r['scene_id'], r['model'], r['repetition']): (i + 1, r) for i, r in enumerate(original['evaluation'])}
    expected = set(original_slots) | {(r['source_room_id'], MINI, 0) for r in sources if r['corpus_family'] != 'original'}
    observed = {}
    audit = []
    candidates = {r['source_room_id']: [] for r in sources}
    for row in manifest['rows']:
        sid = row.get('source_room_id')
        source = by_source.get(sid)
        item = dict(row)
        if source is None:
            raise RuntimeError('Terminal manifest contains an unregistered source: ' + str(sid))
        family = source['corpus_family']
        required_arm = 'original_frozen' if family == 'original' else 'initial_baseline'
        if row.get('arm') != required_arm:
            raise RuntimeError('Terminal manifest contains a nonprimary arm: ' + str(sid))
        if row.get('corpus_family') != family or row.get('source_priority') != source['combined_source_priority']:
            raise RuntimeError('Combined provenance family/priority differs from fixed source order: ' + sid)
        key = (sid, row.get('pipeline_model'), row.get('repetition'))
        if key not in expected:
            raise RuntimeError('Terminal manifest contains an unregistered model variant: ' + str(sid))
        if key in observed:
            raise RuntimeError('Duplicate registered baseline identity: ' + sid)
        if row.get('terminal_status') not in ('completed', 'failed', 'unexecuted_budget_stop'):
            raise RuntimeError('Missing explicit terminal status: ' + sid)
        observed[key] = row
        if family == 'original':
            ordinal, frozen = original_slots[key]
            if row.get('run_ordinal') != ordinal or row.get('source_path') != frozen['source_path'] or row.get('source_sha256') != frozen['source_sha256']:
                raise RuntimeError('Original variant/source provenance differs from frozen plan: ' + sid)
        else:
            ordinal = 1
        attempts = row.get('source_authoring_attempt_count')
        repaired = row.get('source_authoring_repaired')
        if type(attempts) is not int or type(repaired) is not bool:
            raise RuntimeError('Missing explicit source authoring provenance: ' + sid)
        if family == 'extension_llm':
            if attempts not in (0, 1, 2) or repaired != (row.get('source_valid') is True and attempts == 2) or (row.get('source_valid') is True and attempts == 0):
                raise RuntimeError('LLM source exceeds the registered authoring/repair rule: ' + sid)
        elif attempts != 0 or repaired:
            raise RuntimeError('Non-LLM source has unexpected authoring repair: ' + sid)
        eligible = row.get('terminal_status') == 'completed' and row.get('split') == 'evaluation' and all(row.get(k) is True for k in ELIGIBILITY_FLAGS)
        if row.get('eligible_native_success') is not eligible:
            raise RuntimeError('Published eligibility flag conflicts with verified required flags: ' + sid)
        item.update(source, source_stratum=family, registered_variant_order=ordinal,
                    selection_reason='ELIGIBLE_CANDIDATE' if eligible else 'INELIGIBLE_INITIAL_BASELINE')
        audit.append(item)
        if eligible:
            candidates[sid].append(item)
    missing = expected - set(observed)
    if missing:
        raise RuntimeError('Terminal manifest omits registered identities: ' + str(sorted(missing)))
    selected = []
    for source in sources:
        group = sorted(candidates[source['source_room_id']], key=lambda r: r['registered_variant_order'])
        for index, row in enumerate(group):
            if index:
                row['selection_reason'] = 'LATER_ELIGIBLE_ORIGINAL_VARIANT'
            elif len(selected) >= target:
                row['selection_reason'] = 'ELIGIBLE_BEYOND_FIXED_TARGET'
            else:
                row['selection_reason'] = 'SELECTED_FIXED_PRIORITY'
                selected.append(row)
    omitted = [{'source_room_id': s['source_room_id'], 'source_stratum': s['corpus_family'],
                'reason': 'no_eligible_initial_baseline' if not candidates[s['source_room_id']] else 'eligible_beyond_fixed_target'}
               for s in sources if s['source_room_id'] not in {r['source_room_id'] for r in selected}]
    return {'schema': 'wp4-selection-audit-v1', 'cohort_label': COHORT_LABEL, 'target_distinct_sources': target,
            'selected': selected, 'omitted_sources': omitted, 'candidate_rows': audit,
            'eligible_distinct_sources': sum(bool(v) for v in candidates.values()), 'target_met_before_probe_construction': len(selected) >= target}


REQUIRED_PROJECT_INPUTS = frozenset({
    'project.json', 'agents.json', 'room_plan.json',
    'roomcontract.v2.instance.json', 'roomcontract.v05.instance.json',
    'trace_map.json', 'trace_map.v2.json', 'trace_map.v05.json',
})
# These exact backend output paths are diagnostic classifications only, never exemptions.
KNOWN_RUNTIME_OUTPUTS = frozenset({
    'runtime_guard_audit.jsonl', 'runtime_logs/events.jsonl',
    'runtime_logs/runtime_validation.v2.jsonl',
})


def project_refusal(root, row, reason, details):
    record = {'schema': 'wp4-project-provenance-refusal-v1', 'reason': reason,
              'case_id': row.get('case_id'), 'source_room_id': row.get('source_room_id'),
              'run_result_path': row.get('run_result_path'),
              'run_result_sha256': row.get('run_result_sha256'), 'details': details,
              'no_loader_or_copy_authorized': True, 'no_source_replacement': True}
    data = (json.dumps(record, sort_keys=True, indent=2) + '\n').encode('utf-8')
    target = Path(root) / 'results/raw/wp4_provenance_refusals' / (hashlib.sha256(data).hexdigest() + '.json')
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.read_bytes() != data:
        raise RuntimeError('Existing provenance refusal evidence changed')
    if not target.exists(): target.write_bytes(data)
    raise RuntimeError('Selected project provenance refused: ' + reason)


def verify_project_inputs(root, row, run):
    """Close the full materialized file set before any loader or copy.

    Unpinned runtime outputs are classified in a retained refusal, not silently
    accepted or copied. The retained generation input is never mutated.
    """
    root = Path(root).resolve()
    project = relative_file(root, row['project_path'])
    prefix = row['project_path'] + '/'
    declared = {name[len(prefix):]: pin for name, pin in run.get('artifact_sha256', {}).items() if name.startswith(prefix)}
    missing_required = sorted(REQUIRED_PROJECT_INPUTS - set(declared))
    if missing_required or not any(name.startswith('kb/') and name.endswith('.txt') for name in declared):
        project_refusal(root, row, 'MATERIALIZATION_INPUTS_NOT_DECLARED', {'missing_required': missing_required, 'kb_declared': any(name.startswith('kb/') and name.endswith('.txt') for name in declared)})
    for name in declared:
        relative_file(root, prefix + name)
    if not project.is_dir(): project_refusal(root, row, 'PROJECT_DIRECTORY_MISSING', {})
    actual = set()
    pending = [project]
    while pending:
        current = pending.pop()
        metadata = current.lstat()
        linked = current.is_symlink() or bool(getattr(metadata, 'st_file_attributes', 0) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400))
        if linked:
            project_refusal(root, row, 'LINKED_PROJECT_INPUT', {'path': current.relative_to(root).as_posix()})
        if not current.resolve().is_relative_to(project.resolve()):
            project_refusal(root, row, 'PROJECT_INPUT_ESCAPES_DIRECTORY', {'path': current.relative_to(root).as_posix()})
        if current.is_dir():
            pending.extend(sorted(current.iterdir()))
        elif stat.S_ISREG(metadata.st_mode):
            actual.add(current.relative_to(project).as_posix())
        else:
            project_refusal(root, row, 'NONREGULAR_PROJECT_INPUT', {'path': current.relative_to(root).as_posix()})
    missing = sorted(set(declared) - actual); extra = sorted(actual - set(declared))
    if missing or extra:
        project_refusal(root, row, 'PROJECT_FILE_SET_CHANGED', {'missing': missing, 'extra': extra,
            'known_runtime_outputs': sorted(set(extra) & KNOWN_RUNTIME_OUTPUTS),
            'other_unpinned_files': sorted(set(extra) - KNOWN_RUNTIME_OUTPUTS)})
    files = {}
    for name, pin in sorted(declared.items()):
        relative = prefix + name
        try: checked_file(root, relative, pin)
        except RuntimeError:
            project_refusal(root, row, 'PROJECT_INPUT_HASH_CHANGED', {'path': relative, 'expected_sha256': pin})
        files[relative] = pin
    return files


def verify_selected_artifacts(root, selected):
    """Check raw byte pins separately from the native LF-normalized model pin."""
    files = {}
    for row in selected:
        for path_key, hash_key in (('source_path', 'source_sha256'), ('run_result_path', 'run_result_sha256')):
            path, pin = row.get(path_key), row.get(hash_key)
            checked_file(root, path, pin); files[path] = pin
        run = read_json(relative_file(root, row['run_result_path']))
        if run.get('status') != 'success' or run.get('project_dir') != row['project_path'] or run.get('case_id') != row['case_id']:
            raise RuntimeError('Selected run does not match project/case provenance: ' + row['source_room_id'])
        source = run.get('source', {})
        if any(source.get(k) != row[v] for k, v in (('scene_id', 'source_room_id'), ('model', 'pipeline_model'), ('repetition', 'repetition'), ('source_path', 'source_path'), ('source_sha256', 'source_sha256'))):
            raise RuntimeError('Selected run source registration differs: ' + row['source_room_id'])
        files.update(verify_project_inputs(root, row, run))
        model = (Path(row['project_path']) / 'roomcontract.v2.instance.json').as_posix()
        raw_pin = run.get('artifact_sha256', {}).get(model)
        model_path = checked_file(root, model, raw_pin)
        lf_pin = hashlib.sha256(model_path.read_bytes().replace(b'\r\n', b'\n')).hexdigest().upper()
        if lf_pin != row.get('model_sha256'):
            raise RuntimeError('Selected normalized model pin differs: ' + row['source_room_id'])
        files[model] = raw_pin
        row['model_file_sha256'] = raw_pin
    return files


def prepare_selection(root, manifest_path, verified_plan):
    policy = verified_plan.get('_corpus_policy')
    if not policy:
        raise RuntimeError('Expanded corpus requires the reviewed frozen WP4-A001 source amendment')
    root = Path(root)
    path = Path(manifest_path).resolve()
    if not path.is_relative_to(root.resolve()):
        raise RuntimeError('Combined corpus manifest must be inside the workspace')
    manifest = read_json(path)
    original_path = 'prereg/wp5_plan.json'
    original = read_json(checked_file(root, original_path, verified_plan['source_sha256'][original_path]))
    extension_path = policy['extension_plan_path']
    extension, extension_pin = frozen_json(root, extension_path, policy['extension_plan_sha256'])
    if manifest.get('extension_plan_path') != extension_path or manifest.get('extension_plan_sha256') != extension_pin:
        raise RuntimeError('Combined manifest names a different extension freeze')
    source_path = policy['source_freeze_manifest_path']
    sources, sources_pin = frozen_json(root, source_path)
    if manifest.get('source_freeze_manifest_path') != source_path or manifest.get('source_freeze_manifest_sha256') != sources_pin:
        raise RuntimeError('Combined manifest differs from the second-stage accepted-source freeze')
    if sources.get('plan_sha256') != extension_pin:
        raise RuntimeError('Second-stage source freeze does not bind the reviewed extension plan')
    if policy.get('source_order') != [{k: r[k] for k in ('source_room_id', 'corpus_family', 'combined_source_priority')} for r in registered_sources(original, extension)]:
        raise RuntimeError('Source order changed after the WP4 amendment')
    schema_path = policy['accepted_sources_schema_path']
    schema = read_json(checked_file(root, schema_path, policy['accepted_sources_schema_sha256']))
    from jsonschema import Draft202012Validator
    Draft202012Validator(schema).validate(sources)
    if sources.get('schema') != 'wp5-extension-accepted-sources-v1' or sources.get('authoring_terminal') is not True:
        raise RuntimeError('Accepted-source authoring is not terminal')
    expected_sources = [r for r in registered_sources(original, extension) if r['corpus_family'] != 'original']
    if len(sources.get('slots', [])) != len(expected_sources):
        raise RuntimeError('Accepted-source freeze omits registered slots')
    source_files = {}
    for expected, slot in zip(expected_sources, sources['slots']):
        sid = expected['source_room_id']
        if (slot.get('source_id'), slot.get('family'), slot.get('source_family_order')) != (sid, expected['corpus_family'], expected['source_order_within_stratum']):
            raise RuntimeError('Accepted-source order differs from registered extension')
        matching = [r for r in manifest['rows'] if r.get('source_room_id') == sid and r.get('arm') == 'initial_baseline']
        if len(matching) != 1:
            raise RuntimeError('Combined manifest must retain exactly one initial row per source slot')
        row = matching[0]
        if row.get('source_freeze_sha256') != sources_pin or row.get('source_valid') is not (slot['status'] == 'accepted'):
            raise RuntimeError('Combined source eligibility differs from second-stage freeze')
        for key in ('source_path', 'source_sha256', 'source_authoring_attempt_count', 'source_authoring_repaired', 'source_authoring_result_path', 'source_authoring_result_sha256'):
            if row.get(key) != slot.get(key):
                raise RuntimeError('Combined source provenance differs from accepted-source freeze: ' + key)
        if expected['corpus_family'] == 'extension_llm':
            checked_file(root, slot.get('source_authoring_result_path'), slot.get('source_authoring_result_sha256'))
            source_files[slot['source_authoring_result_path']] = slot['source_authoring_result_sha256']
        elif slot.get('source_authoring_result_path') is not None or slot.get('source_authoring_result_sha256') is not None:
            raise RuntimeError('Non-LLM source cannot claim an LLM authoring result')
        if slot['status'] == 'accepted':
            checked_file(root, slot['source_path'], slot['source_sha256'])
            source_files[slot['source_path']] = slot['source_sha256']
        if expected['corpus_family'] == 'extension_deterministic':
            registered = next(r for r in extension['new_deterministic_sources'] if r['source_id'] == sid)
            if (slot['source_path'], slot['source_sha256']) != (registered['path'], registered['sha256']):
                raise RuntimeError('Deterministic source differs from initial extension freeze')
    for row in manifest['rows']:
        if row.get('arm') not in ('original_frozen', 'initial_baseline'):continue
        expected_identity = {'plan_sha256':verified_plan['source_sha256'][original_path] if row.get('corpus_family')=='original' else extension_pin,
                             'family':row.get('corpus_family'),'source_id':row.get('source_room_id'),
                             'pipeline_model':row.get('pipeline_model'),'repetition':row.get('repetition'),'arm':row.get('arm')}
        if row.get('registered_identity') != expected_identity:
            raise RuntimeError('Registered identity differs from its frozen plan: ' + str(row.get('source_room_id')))
    audit = select_rows(manifest, original, extension, target=policy['target_distinct_sources'])
    audit['artifact_sha256'] = {**source_files, **verify_selected_artifacts(root, audit['selected'])}
    # Terminal failures and skipped slots are evidence, even when not selected.
    for row in audit['candidate_rows']:
        checked_file(root, row['run_result_path'], row['run_result_sha256'])
        audit['artifact_sha256'][row['run_result_path']] = row['run_result_sha256']
    audit['input_sha256'] = {path.relative_to(root.resolve()).as_posix(): digest(path), original_path: digest(root / original_path),
                             extension_path: extension_pin, source_path: sources_pin, schema_path: policy['accepted_sources_schema_sha256']}
    audit['source_amendments'] = verified_plan['_source_amendments']
    audit['effective_freeze_sha256'] = verified_plan['_effective_freeze_sha256']
    return audit


def selected_metadata(audit):
    return [{**row, 'author_model': row['pipeline_model'], 'split': 'evaluation'} for row in audit['selected']]

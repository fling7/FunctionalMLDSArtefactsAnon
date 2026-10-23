"""Offline amendment tests; toy provenance records are not scientific evidence."""
import copy
import hashlib
import json
import random
from pathlib import Path
import pytest
from experiments.lib.wp4_amendments import verify_effective_sources, digest
from experiments.lib.wp4_selection import select_rows, registered_sources, verify_selected_artifacts, MINI

FULL = 'gpt-4.1-2025-04-14'


def dump(root, name, value):
    path = root / name; path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True) + '\n', encoding='utf-8')
    return digest(path)


def freeze(root, name, value):
    pin = dump(root, name, value)
    (root / name).with_suffix('.sha256').write_text(pin + '\n', encoding='utf-8')
    return pin


def unit_materialized_inputs(root, project):
    """Complete generated file set with explicitly synthetic, unit-only bytes."""
    from experiments.lib.wp4_selection import REQUIRED_PROJECT_INPUTS
    for name in sorted(REQUIRED_PROJECT_INPUTS | {'kb/unit.txt'}):
        path = root / project / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists(): path.write_text('{"unit_only": true}\n', encoding='utf-8')
    return {p.relative_to(root).as_posix(): digest(p) for p in (root / project).rglob('*') if p.is_file()}


@pytest.fixture
def selection_fixture():
    original = {'evaluation': [
        {'scene_id': 'o1', 'model': MINI, 'repetition': 0, 'source_path': 'sources/o1.json', 'source_sha256': '1' * 64},
        {'scene_id': 'o2', 'model': FULL, 'repetition': 0, 'source_path': 'sources/o2.json', 'source_sha256': '2' * 64},
        {'scene_id': 'o1', 'model': FULL, 'repetition': 0, 'source_path': 'sources/o1.json', 'source_sha256': '1' * 64},
    ]}
    extension = {'new_deterministic_sources': [{'source_id': 'd1'}, {'source_id': 'd2'}],
                 'llm_authored_sources': [{'source_id': 'l1'}, {'source_id': 'l2'}]}
    priorities = {r['source_room_id']: r for r in registered_sources(original, extension)}
    rows = []
    def row(sid, model, ordinal, source=None):
        family = priorities[sid]['corpus_family']
        return {'source_room_id': sid, 'source_priority': priorities[sid]['combined_source_priority'],
                'corpus_family': family, 'arm': 'original_frozen' if family == 'original' else 'initial_baseline',
                'pipeline_model': model, 'repetition': 0, 'run_ordinal': ordinal, 'split': 'evaluation',
                'source_path': source['source_path'] if source else 'sources/' + sid + '.json',
                'source_sha256': source['source_sha256'] if source else 'a' * 64,
                'source_authoring_attempt_count': 1 if family == 'extension_llm' else 0,
                'source_authoring_repaired': False, 'source_valid': True, 'terminal_status': 'completed',
                'pipeline_success': True, 'project_produced': True, 'canonical_valid': True,
                'schema_valid': True, 'gate0_ok': True, 'eligible_native_success': True,
                'project_path': 'projects/' + sid, 'model_sha256': 'B' * 64}
    for i, source in enumerate(original['evaluation'], 1):
        rows.append(row(source['scene_id'], source['model'], i, source))
    for i, source in enumerate(registered_sources(original, extension)[2:], 1):
        rows.append(row(source['source_room_id'], MINI, i))
    manifest = {'schema': 'wp5-combined-primary-provenance-v1', 'original_terminal': True,
                'initial_block_terminal': True, 'manifest_is_complete': True, 'rows': rows}
    return manifest, original, extension


def failed(row, *, source_invalid=False, stop=False):
    row.update(terminal_status='unexecuted_budget_stop' if stop else 'failed', pipeline_success=False,
               project_produced=False, canonical_valid=False, schema_valid=False, gate0_ok=False,
               eligible_native_success=False, project_path=None, model_sha256=None)
    if source_invalid:
        row.update(source_valid=False, source_path=None, source_sha256=None,
                   source_authoring_attempt_count=2, source_authoring_repaired=False)


def test_selection_uses_registered_priority_and_earliest_variant_not_completion_order(selection_fixture):
    manifest, original, extension = selection_fixture
    random.Random(20261015).shuffle(manifest['rows'])
    result = select_rows(manifest, original, extension, target=4)
    assert [r['source_room_id'] for r in result['selected']] == ['o1', 'o2', 'd1', 'd2']
    assert result['selected'][0]['pipeline_model'] == MINI
    assert sum(r['selection_reason'] == 'LATER_ELIGIBLE_ORIGINAL_VARIANT' for r in result['candidate_rows']) == 1
    assert {r['source_room_id'] for r in result['candidate_rows'] if r['selection_reason'] == 'ELIGIBLE_BEYOND_FIXED_TARGET'} == {'l1', 'l2'}


def test_original_earliest_eligible_after_failed_first_variant(selection_fixture):
    manifest, original, extension = selection_fixture
    failed(manifest['rows'][0])
    result = select_rows(manifest, original, extension, target=3)
    assert result['selected'][0]['source_room_id'] == 'o1'
    assert result['selected'][0]['pipeline_model'] == FULL
    assert any(r['selection_reason'] == 'INELIGIBLE_INITIAL_BASELINE' for r in result['candidate_rows'])


@pytest.mark.parametrize('arm', ['targeted_ownership_repair', 'cap_recovery', 'drift_repeat', 'full_model_drift_baseline', 'scene_edit_pipeline'])
def test_later_success_cannot_rescue_failed_initial_baseline(selection_fixture, arm):
    manifest, original, extension = selection_fixture
    initial = next(r for r in manifest['rows'] if r['source_room_id'] == 'd1')
    rescue = {**initial, 'arm': arm}; failed(initial)
    manifest['rows'].append(rescue)
    with pytest.raises(RuntimeError, match='nonprimary arm'):
        select_rows(manifest, original, extension)


def test_source_repair_is_explicit_and_failed_source_slot_retained(selection_fixture):
    manifest, original, extension = selection_fixture
    l1 = next(r for r in manifest['rows'] if r['source_room_id'] == 'l1')
    l1.update(source_authoring_attempt_count=2, source_authoring_repaired=True)
    failed(next(r for r in manifest['rows'] if r['source_room_id'] == 'l2'), source_invalid=True)
    result = select_rows(manifest, original, extension, target=20)
    assert next(r for r in result['selected'] if r['source_room_id'] == 'l1')['source_authoring_repaired']
    assert len(result['selected']) == 5 and not result['target_met_before_probe_construction']
    assert {'source_room_id': 'l2', 'source_stratum': 'extension_llm', 'reason': 'no_eligible_initial_baseline'} in result['omitted_sources']


def test_exhausted_budget_is_terminal_only_when_every_slot_is_explicit(selection_fixture):
    manifest, original, extension = selection_fixture
    failed(manifest['rows'][-1], stop=True)
    assert len(select_rows(manifest, original, extension)['selected']) == 5
    manifest['rows'].pop()
    with pytest.raises(RuntimeError, match='omits registered identities'):
        select_rows(manifest, original, extension)


@pytest.mark.parametrize('field', ['original_terminal', 'initial_block_terminal', 'manifest_is_complete'])
def test_pending_sequence_never_selects_a_corpus(selection_fixture, field):
    manifest, original, extension = selection_fixture; manifest[field] = False
    with pytest.raises(RuntimeError, match='explicitly terminal'): select_rows(manifest, original, extension)


def test_all_twelve_llm_slots_are_fixed_and_no_replacement_follows_failure(selection_fixture):
    manifest, original, extension = selection_fixture
    template = next(r for r in manifest['rows'] if r['source_room_id'] == 'l2')
    for i in range(3, 13):
        extension['llm_authored_sources'].append({'source_id': 'l' + str(i)})
        manifest['rows'].append({**template, 'source_room_id': 'l' + str(i), 'source_priority': i + 4, 'run_ordinal': i + 2})
    failed(next(r for r in manifest['rows'] if r['source_room_id'] == 'l2'), source_invalid=True)
    result = select_rows(manifest, original, extension)
    assert [r['source_room_id'] for r in result['selected']][-10:] == ['l' + str(i) for i in range(3, 13)]
    assert len(result['candidate_rows']) == 17


@pytest.mark.parametrize('change', ['gate0', 'third_repair', 'priority', 'duplicate', 'model'])
def test_inconsistent_provenance_fails_closed(selection_fixture, change):
    manifest, original, extension = selection_fixture
    if change == 'gate0': manifest['rows'][0]['gate0_ok'] = False
    elif change == 'third_repair': manifest['rows'][-1]['source_authoring_attempt_count'] = 3
    elif change == 'priority': manifest['rows'][0]['source_priority'] = 100
    elif change == 'duplicate': manifest['rows'].append(copy.deepcopy(manifest['rows'][0]))
    else: manifest['rows'][0]['pipeline_model'] = 'unregistered-model'
    with pytest.raises(RuntimeError): select_rows(manifest, original, extension)


@pytest.fixture
def frozen_root(tmp_path):
    common = 'experiments/lib/wp4_common.py'; prompt = 'experiments/prompts/wp4/router_1.txt'
    for name, text in ((common, 'original unit source\n'), (prompt, 'frozen unit prompt\n')):
        path = tmp_path / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(text)
    q = {'code_sha256': {common: digest(tmp_path / common)}}
    plan = {'question_plan': q, 'source_sha256': {common: digest(tmp_path / common), prompt: digest(tmp_path / prompt)}}
    base = freeze(tmp_path, 'prereg/wp4_plan.json', plan)
    qpin = freeze(tmp_path, 'prereg/wp4_questions_plan.json', q)
    snapshot = 'prereg/wp4_amendments/001_original_sources/' + common
    (tmp_path / snapshot).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / snapshot).write_bytes((tmp_path / common).read_bytes())
    (tmp_path / common).write_text('amended unit source\n')
    verifier = 'experiments/lib/wp4_amendments.py'
    (tmp_path / verifier).write_text('unit verifier dependency fixture\n')
    overlay = {'schema': 'wp4-source-amendment-v1', 'sequence': 1, 'prior_freeze_sha256': base,
               'base_question_plan_sha256': qpin, 'implementation_updates': {common: {'old_sha256': plan['source_sha256'][common], 'new_sha256': digest(tmp_path / common), 'original_snapshot': snapshot}},
               'added_sources': {verifier: digest(tmp_path / verifier)}}
    return tmp_path, overlay


def test_exact_frozen_overlay_preserves_original_and_effective_hashes(frozen_root):
    root, overlay = frozen_root
    pin = freeze(root, 'prereg/wp4_amendments/001_expanded_corpus.json', overlay)
    result = verify_effective_sources(root)
    common = 'experiments/lib/wp4_common.py'
    assert result['source_sha256'][common] == overlay['implementation_updates'][common]['old_sha256']
    assert result['_effective_source_sha256'][common] == overlay['implementation_updates'][common]['new_sha256']
    assert result['_effective_freeze_sha256'] == pin


def test_unfrozen_draft_never_allows_changed_source(frozen_root):
    root, overlay = frozen_root
    dump(root, 'prereg/wp4_amendments/001_expanded_corpus.DRAFT.json', overlay)
    with pytest.raises(RuntimeError, match='changed or missing'): verify_effective_sources(root)


@pytest.mark.parametrize('change', ['wrong_prior', 'wrong_old', 'wrong_new', 'missing_sidecar', 'prompt_change', 'snapshot_changed', 'unlisted_source_change', 'verifier_unpinned'])
def test_overlay_rejects_unreviewed_changes(frozen_root, change):
    root, overlay = frozen_root
    update = overlay['implementation_updates']['experiments/lib/wp4_common.py']
    if change == 'wrong_prior': overlay['prior_freeze_sha256'] = '0' * 64
    elif change == 'wrong_old': update['old_sha256'] = '0' * 64
    elif change == 'wrong_new': update['new_sha256'] = '0' * 64
    elif change == 'prompt_change': overlay['implementation_updates']['experiments/prompts/wp4/router_1.txt'] = copy.deepcopy(update)
    elif change == 'snapshot_changed': (root / update['original_snapshot']).write_text('altered old evidence')
    elif change == 'unlisted_source_change': (root / 'experiments/prompts/wp4/router_1.txt').write_text('changed prompt')
    elif change == 'verifier_unpinned': overlay['added_sources'] = {}
    freeze(root, 'prereg/wp4_amendments/001_expanded_corpus.json', overlay)
    if change == 'missing_sidecar': (root / 'prereg/wp4_amendments/001_expanded_corpus.sha256').unlink()
    with pytest.raises(RuntimeError): verify_effective_sources(root)


def test_raw_model_bytes_and_native_lf_digest_are_distinct(tmp_path):
    project = tmp_path / 'projects/r'; project.mkdir(parents=True)
    model = project / 'roomcontract.v2.instance.json'; model.write_bytes(b'{\r\n  "unit": true\r\n}\r\n')
    source_pin = dump(tmp_path, 'sources/r.json', {'unit': True})
    source = {'scene_id': 'r', 'model': MINI, 'repetition': 0, 'source_path': 'sources/r.json', 'source_sha256': source_pin}
    run = {'status': 'success', 'case_id': 'unit-r', 'project_dir': 'projects/r', 'source': source,
           'artifact_sha256': unit_materialized_inputs(tmp_path, 'projects/r')}
    pin = dump(tmp_path, 'runs/r.json', run)
    row = {'source_room_id': 'r', 'pipeline_model': MINI, 'repetition': 0, 'source_path': source['source_path'],
           'source_sha256': source_pin, 'run_result_path': 'runs/r.json', 'run_result_sha256': pin,
           'project_path': 'projects/r', 'case_id': 'unit-r', 'model_sha256': hashlib.sha256(model.read_bytes().replace(b'\r\n', b'\n')).hexdigest().upper()}
    assert verify_selected_artifacts(tmp_path, [row])['projects/r/roomcontract.v2.instance.json'] == digest(model)
    model.write_bytes(model.read_bytes().replace(b'\r\n', b'\n'))
    with pytest.raises(RuntimeError, match='PROJECT_INPUT_HASH_CHANGED'): verify_selected_artifacts(tmp_path, [row])


def test_corpus_resume_cannot_switch_selected_sources(tmp_path):
    from experiments.lib.wp4_common import bind_corpus
    corpus = tmp_path / 'corpus'; out = tmp_path / 'run'
    freeze(corpus, 'manifest.json', {'rooms': [{'source_room_id': 'first'}]})
    bind_corpus(out, corpus)
    freeze(corpus, 'manifest.json', {'rooms': [{'source_room_id': 'replacement'}]})
    with pytest.raises(RuntimeError, match='Resume corpus differs'): bind_corpus(out, corpus)

@pytest.fixture
def full_provenance(tmp_path, selection_fixture):
    """Twenty-four fixed extension slots with unit-only artifact bytes."""
    manifest, original, extension = selection_fixture
    templates = {r['corpus_family']: copy.deepcopy(r) for r in manifest['rows']}
    for family, key, prefix in (('extension_deterministic', 'new_deterministic_sources', 'd'), ('extension_llm', 'llm_authored_sources', 'l')):
        extension[key] = [{'source_id': prefix + str(i)} for i in range(1, 13)]
    source_rows = registered_sources(original, extension)
    priorities = {r['source_room_id']: r for r in source_rows}
    manifest['rows'] = [r for r in manifest['rows'] if r['corpus_family'] == 'original']
    for index, item in enumerate(source_rows[2:], 1):
        manifest['rows'].append({**templates[item['corpus_family']], 'source_room_id': item['source_room_id'], 'source_priority': item['combined_source_priority'], 'run_ordinal': index})
    source_pins = {}
    for item in source_rows:
        sid = item['source_room_id']; source_pins[sid] = dump(tmp_path, 'sources/' + sid + '.json', {'unit_source': sid})
    for row in original['evaluation']:
        row['source_sha256'] = source_pins[row['scene_id']]
    for row in extension['new_deterministic_sources']:
        row.update(path='sources/' + row['source_id'] + '.json', sha256=source_pins[row['source_id']])
    original_pin = dump(tmp_path, 'prereg/wp5_plan.json', original)
    extension_pin = freeze(tmp_path, 'prereg/wp5_extension_v1/plan.json', extension)
    slots = []
    for item in source_rows[2:]:
        sid = item['source_room_id']; llm = item['corpus_family'] == 'extension_llm'
        slots.append({'source_id': sid, 'family': item['corpus_family'], 'source_family_order': item['source_order_within_stratum'],
                      'status': 'accepted', 'source_path': 'sources/' + sid + '.json', 'source_sha256': source_pins[sid],
                      'source_authoring_attempt_count': 1 if llm else 0, 'source_authoring_repaired': False,
                      'source_authoring_result_path': 'authoring/' + sid + '.json' if llm else None,
                      'source_authoring_result_sha256': dump(tmp_path, 'authoring/' + sid + '.json', {'unit_only': True, 'source_id': sid}) if llm else None,
                      'validation': {'unit_only': True}})
    accepted = {'schema': 'wp5-extension-accepted-sources-v1', 'plan_sha256': extension_pin, 'authoring_terminal': True, 'slots': slots}
    accepted_pin = freeze(tmp_path, 'prereg/wp5_extension_v1/accepted_sources.json', accepted)
    schema = json.loads(Path('prereg/wp5_extension_v1/accepted_sources.schema.json').read_text(encoding='utf-8-sig'))
    schema['properties']['slots']['minItems'] = schema['properties']['slots']['maxItems'] = 24
    schema_pin = dump(tmp_path, 'prereg/wp5_extension_v1/accepted_sources.schema.json', schema)
    for i, row in enumerate(manifest['rows']):
        sid = row['source_room_id']; project = 'projects/unit_' + str(i); case = 'unit_' + str(i)
        slot = next((x for x in slots if x['source_id'] == sid), {})
        row.update(source_path='sources/' + sid + '.json', source_sha256=source_pins[sid], case_id=case, project_path=project,
                   source_authoring_result_path=slot.get('source_authoring_result_path'), source_authoring_result_sha256=slot.get('source_authoring_result_sha256'),
                   source_freeze_sha256=accepted_pin if row['corpus_family'] != 'original' else None)
        model = tmp_path / project / 'roomcontract.v2.instance.json'; model.parent.mkdir(parents=True)
        model.write_bytes(b'{\r\n "unit_only_model": true\r\n}\r\n')
        row['model_sha256'] = hashlib.sha256(model.read_bytes().replace(b'\r\n', b'\n')).hexdigest().upper()
        source = {'scene_id': sid, 'model': row['pipeline_model'], 'repetition': 0, 'source_path': row['source_path'], 'source_sha256': row['source_sha256']}
        record = {'status': 'success', 'case_id': case, 'project_dir': project, 'source': source, 'artifact_sha256': unit_materialized_inputs(tmp_path, project)}
        row['run_result_path'] = 'runs/' + case + '.json'; row['run_result_sha256'] = dump(tmp_path, row['run_result_path'], record)
        row['registered_identity'] = {'plan_sha256': original_pin if row['corpus_family'] == 'original' else extension_pin,
                                      'family': row['corpus_family'], 'source_id': sid, 'pipeline_model': row['pipeline_model'],
                                      'repetition': 0, 'arm': row['arm']}
    manifest.update(extension_plan_path='prereg/wp5_extension_v1/plan.json', extension_plan_sha256=extension_pin,
                    source_freeze_manifest_path='prereg/wp5_extension_v1/accepted_sources.json', source_freeze_manifest_sha256=accepted_pin)
    manifest_path = 'results/processed/wp5_primary_projects.json'; dump(tmp_path, manifest_path, manifest)
    policy = {'target_distinct_sources': 20, 'extension_plan_path': manifest['extension_plan_path'], 'extension_plan_sha256': extension_pin,
              'source_freeze_manifest_path': manifest['source_freeze_manifest_path'], 'accepted_sources_schema_path': 'prereg/wp5_extension_v1/accepted_sources.schema.json',
              'accepted_sources_schema_sha256': schema_pin, 'source_order': [{k: r[k] for k in ('source_room_id', 'corpus_family', 'combined_source_priority')} for r in source_rows]}
    verified = {'_corpus_policy': policy, 'source_sha256': {'prereg/wp5_plan.json': original_pin},
                '_source_amendments': [{'sequence': 1, 'sha256': 'a' * 64}], '_effective_freeze_sha256': 'a' * 64}
    return tmp_path, manifest_path, manifest, accepted, verified


def test_two_stage_freeze_and_all_terminal_artifacts_select_exact_twenty(full_provenance):
    from experiments.lib.wp4_selection import prepare_selection
    root, path, manifest, accepted, verified = full_provenance
    audit = prepare_selection(root, root / path, verified)
    assert [r['source_room_id'] for r in audit['selected']] == ['o1', 'o2'] + ['d' + str(i) for i in range(1, 13)] + ['l' + str(i) for i in range(1, 7)]
    assert len(audit['candidate_rows']) == 27
    assert all(r['run_result_path'] in audit['artifact_sha256'] for r in manifest['rows'])
    assert audit['input_sha256']['prereg/wp5_extension_v1/accepted_sources.json'] == digest(root / 'prereg/wp5_extension_v1/accepted_sources.json')


@pytest.mark.parametrize('change', ['late_source_edit', 'missing_failed_record', 'freeze_rebound', 'row_identity', 'unfrozen_sources', 'slot_reorder', 'source_repair_relabel', 'authoring_record_changed'])
def test_two_stage_provenance_rejects_changed_or_missing_evidence(full_provenance, change):
    from experiments.lib.wp4_selection import prepare_selection
    root, path, manifest, accepted, verified = full_provenance
    accepted_path = 'prereg/wp5_extension_v1/accepted_sources.json'
    if change == 'late_source_edit': (root / 'sources/l12.json').write_text('changed even though not selected')
    elif change == 'missing_failed_record':
        row = manifest['rows'][-1]; failed(row); (root / row['run_result_path']).unlink(); dump(root, path, manifest)
    elif change == 'freeze_rebound':
        accepted['plan_sha256'] = '0' * 64
        manifest['source_freeze_manifest_sha256'] = freeze(root, accepted_path, accepted); dump(root, path, manifest)
    elif change == 'row_identity':
        manifest['rows'][0]['registered_identity']['plan_sha256'] = '0' * 64; dump(root, path, manifest)
    elif change == 'unfrozen_sources': (root / accepted_path).with_suffix('.sha256').unlink()
    elif change == 'slot_reorder':
        accepted['slots'][0], accepted['slots'][1] = accepted['slots'][1], accepted['slots'][0]
        manifest['source_freeze_manifest_sha256'] = freeze(root, accepted_path, accepted); dump(root, path, manifest)
    elif change == 'authoring_record_changed': (root / 'authoring/l12.json').write_text('changed authoring result')
    else:
        manifest['rows'][-1]['source_authoring_attempt_count'] = 2; manifest['rows'][-1]['source_authoring_repaired'] = True; dump(root, path, manifest)
    with pytest.raises(RuntimeError): prepare_selection(root, root / path, verified)


def test_strata_report_keeps_original_only_and_unscored_outcomes(full_provenance, tmp_path):
    from experiments.lib.wp4_selection import prepare_selection
    from experiments.analyze_wp4 import corpus_strata
    root, path, manifest, accepted, verified = full_provenance
    audit = prepare_selection(root, root / path, verified)
    run = root / 'analysis_run'; audit_pin = dump(run, 'corpus/selection.json', audit)
    rooms = [{**r, 'split': 'evaluation'} for r in audit['selected']]
    freeze(run, 'corpus/manifest.json', {'rooms': rooms, 'selection': {'path': 'selection.json', 'sha256': audit_pin}})
    rows = [{'source_room_id': sid, 'split': 'evaluation', 'baseline': 'B0', 'model': MINI, 'status': status, 'outcome': outcome, 'question_kind': 'neutral', 'temperature': .3, 'repetition': 0}
            for sid, status, outcome in [('o1', 'SUCCESS', 'WRONG_PROVIDER'), ('d1', 'API_ERROR', 'API_ERROR'), ('l1', 'SUCCESS', 'CORRECT')]]
    report = corpus_strata(rows, [], run, None)
    by_family = {r['source_stratum']: r for r in report['strata']}
    assert by_family['original']['routing'][0]['misroute_valid_scored_room_rate'] == 1
    assert by_family['extension_deterministic']['routing'][0]['misroute_valid_scored_room_rate'] is None
    assert by_family['extension_llm']['routing'][0]['misroute_valid_scored_room_rate'] == 0
    assert 'exploratory' in report['cohort_label']
    assert sum(r['selected_sources'] for r in report['counts']) == 20

@pytest.mark.parametrize('invalid', [None, 'missing_extension_pin', 'different_extension_pin', 'schema_changed'])
def test_overlay_binds_first_freeze_but_second_stage_remains_late_bound(frozen_root, full_provenance, invalid):
    root, overlay = frozen_root
    _, path, manifest, accepted, verified = full_provenance
    policy = {**verified['_corpus_policy'], 'schema': 'wp4-expanded-corpus-policy-v1',
              'allow_source_authoring_repair': True, 'max_source_authoring_attempts': 2}
    overlay['corpus_policy'] = policy
    selector = 'experiments/lib/wp4_selection.py'
    (root / selector).write_text('unit selector dependency fixture\n')
    overlay['added_sources'][selector] = digest(root / selector)
    if invalid == 'missing_extension_pin': policy['extension_plan_sha256'] = None
    elif invalid == 'different_extension_pin': policy['extension_plan_sha256'] = '0' * 64
    elif invalid == 'schema_changed': (root / policy['accepted_sources_schema_path']).write_text('{}')
    # An approved first-stage policy can precede source authoring. Corpus selection
    # still rejects absent second-stage bytes before any downstream generation.
    (root / policy['source_freeze_manifest_path']).unlink()
    freeze(root, 'prereg/wp4_amendments/001_expanded_corpus.json', overlay)
    if invalid:
        with pytest.raises(RuntimeError): verify_effective_sources(root)
    else:
        assert verify_effective_sources(root)['_corpus_policy'] == policy
        from experiments.lib.wp4_selection import prepare_selection
        with pytest.raises(RuntimeError): prepare_selection(root, root / path, verified)


def test_unattempted_llm_slot_retains_terminal_authoring_record(full_provenance):
    from experiments.lib.wp4_selection import prepare_selection
    root, path, manifest, accepted, verified = full_provenance
    slot = accepted['slots'][-1]
    slot.update(status='unexecuted_budget_stop', source_path=None, source_sha256=None,
                source_authoring_attempt_count=0, source_authoring_repaired=False)
    slot['source_authoring_result_sha256'] = dump(root, slot['source_authoring_result_path'], {'unit_only': True, 'status': 'unexecuted_budget_stop', 'attempt_count': 0})
    accepted_pin = freeze(root, 'prereg/wp5_extension_v1/accepted_sources.json', accepted)
    manifest['source_freeze_manifest_sha256'] = accepted_pin
    for row in manifest['rows']:
        if row['corpus_family'] != 'original': row['source_freeze_sha256'] = accepted_pin
    row = next(r for r in manifest['rows'] if r['source_room_id'] == slot['source_id'])
    failed(row, stop=True)
    row.update(source_valid=False, source_path=None, source_sha256=None, source_authoring_attempt_count=0,
               source_authoring_result_sha256=slot['source_authoring_result_sha256'])
    row['run_result_sha256'] = dump(root, row['run_result_path'], {'unit_only': True, 'status': 'not_attempted', 'reason': 'source_authoring_budget_stop', 'project_dir': None})
    dump(root, path, manifest)
    audit = prepare_selection(root, root / path, verified)
    assert slot['source_authoring_result_path'] in audit['artifact_sha256']
    assert slot['source_id'] not in {r['source_room_id'] for r in audit['selected']}
    assert audit['eligible_distinct_sources'] == 25


@pytest.mark.parametrize('extra', ['unknown_source', 'nonprimary_arm', 'unregistered_model', 'unregistered_repetition'])
def test_complete_primary_identity_set_rejects_any_extra_row(selection_fixture, extra):
    manifest, original, extension = selection_fixture
    row = copy.deepcopy(manifest['rows'][0])
    if extra == 'unknown_source': row['source_room_id'] = 'guided_not_registered'
    elif extra == 'nonprimary_arm': row['arm'] = 'guided_initial'
    elif extra == 'unregistered_model': row['pipeline_model'] = 'not_registered'
    else: row['repetition'] = 99
    manifest['rows'].append(row)
    with pytest.raises(RuntimeError): select_rows(manifest, original, extension)


@pytest.mark.parametrize('name', ['project.json', 'agents.json', 'room_plan.json', 'trace_map.json', 'trace_map.v2.json', 'trace_map.v05.json', 'roomcontract.v2.instance.json', 'roomcontract.v05.instance.json', 'kb/unit.txt'])
@pytest.mark.parametrize('operation', ['tamper', 'remove'])
def test_every_materialization_file_is_pinned_before_loading(full_provenance, name, operation):
    root, _, manifest, _, _ = full_provenance
    row = manifest['rows'][0]; path = root / row['project_path'] / name
    if operation == 'tamper': path.write_text('unit-only tamper', encoding='utf-8')
    else: path.unlink()
    with pytest.raises(RuntimeError, match='PROJECT_INPUT_HASH_CHANGED|PROJECT_FILE_SET_CHANGED'):
        verify_selected_artifacts(root, [row])
    evidence = list((root / 'results/raw/wp4_provenance_refusals').glob('*.json'))
    assert len(evidence) == 1
    record = json.loads(evidence[0].read_text())
    assert record['no_loader_or_copy_authorized'] and record['no_source_replacement']


@pytest.mark.parametrize('name', ['unexpected.json', 'kb/unpinned.txt', 'runtime_guard_audit.jsonl', 'runtime_logs/events.jsonl', 'runtime_logs/runtime_validation.v2.jsonl'])
def test_unpinned_files_are_retained_and_refused_including_exact_runtime_outputs(full_provenance, name):
    from experiments.lib.wp4_selection import KNOWN_RUNTIME_OUTPUTS
    root, _, manifest, _, _ = full_provenance
    row = manifest['rows'][0]; path = root / row['project_path'] / name
    path.parent.mkdir(parents=True, exist_ok=True); path.write_text('retained unit evidence', encoding='utf-8')
    with pytest.raises(RuntimeError, match='PROJECT_FILE_SET_CHANGED'): verify_selected_artifacts(root, [row])
    record = json.loads(next((root / 'results/raw/wp4_provenance_refusals').glob('*.json')).read_text())
    assert record['details']['extra'] == [name]
    assert record['details']['known_runtime_outputs'] == ([name] if name in KNOWN_RUNTIME_OUTPUTS else [])
    assert path.read_text() == 'retained unit evidence'


@pytest.mark.parametrize('name', ['project.json', 'agents.json', 'room_plan.json', 'trace_map.json', 'trace_map.v2.json', 'trace_map.v05.json', 'roomcontract.v2.instance.json', 'roomcontract.v05.instance.json', 'kb/unit.txt'])
def test_rebound_unit_run_cannot_omit_required_materialization_inputs(full_provenance, name):
    root, _, manifest, _, _ = full_provenance
    row = manifest['rows'][0]; run = json.loads((root / row['run_result_path']).read_text())
    run['artifact_sha256'].pop(row['project_path'] + '/' + name)
    row['run_result_sha256'] = dump(root, row['run_result_path'], run)
    with pytest.raises(RuntimeError, match='MATERIALIZATION_INPUTS_NOT_DECLARED'): verify_selected_artifacts(root, [row])


@pytest.mark.parametrize('relative', ['../escape.json', 'kb/../../escape.json', 'kb\\escape.txt', 'C:/escape.json'])
def test_materialized_paths_cannot_escape_the_selected_project(full_provenance, relative):
    root, _, manifest, _, _ = full_provenance
    row = manifest['rows'][0]; run = json.loads((root / row['run_result_path']).read_text())
    run['artifact_sha256'][row['project_path'] + '/' + relative] = '0' * 64
    row['run_result_sha256'] = dump(root, row['run_result_path'], run)
    with pytest.raises(RuntimeError): verify_selected_artifacts(root, [row])


def test_linked_project_file_is_never_followed(full_provenance):
    root, _, manifest, _, _ = full_provenance
    row = manifest['rows'][0]; outside = root / 'outside.txt'; outside.write_text('outside unit data')
    link = root / row['project_path'] / 'kb/unit.txt'; link.unlink()
    try: link.symlink_to(outside)
    except OSError: pytest.skip('Host does not permit creation of a unit-test symlink')
    with pytest.raises(RuntimeError, match='LINKED_PROJECT_INPUT'): verify_selected_artifacts(root, [row])


def test_project_changed_during_probe_construction_is_refused_before_profiles(full_provenance, monkeypatch):
    from experiments import routing_baselines as routing
    root, path, manifest, _, verified = full_provenance
    monkeypatch.setattr(routing, 'ROOT', root)
    monkeypatch.setattr(routing, 'BACKEND', root / 'unit_backend')
    monkeypatch.setattr(routing, 'verify_freeze', lambda: verified)
    monkeypatch.setattr(routing, 'archive_sources', lambda _: None)
    calls = []
    def fake_probes(project):
        calls.append(project)
        (project / 'agents.json').write_text('unit mutation during probe construction')
        return {}, []
    monkeypatch.setattr(routing, 'project_probes', fake_probes)
    monkeypatch.setattr(routing, 'profiles', lambda _: pytest.fail('Changed project reached profiles loader'))
    with pytest.raises(RuntimeError, match='PROJECT_INPUT_HASH_CHANGED'):
        routing.prepare(root / path, root / 'prepared')
    assert calls == [root / manifest['rows'][0]['project_path']]


def test_changed_project_is_refused_before_any_probe_constructor(full_provenance, monkeypatch):
    from experiments import routing_baselines as routing
    root, path, manifest, _, verified = full_provenance
    monkeypatch.setattr(routing, 'ROOT', root)
    monkeypatch.setattr(routing, 'BACKEND', root / 'unit_backend')
    monkeypatch.setattr(routing, 'verify_freeze', lambda: verified)
    monkeypatch.setattr(routing, 'archive_sources', lambda _: None)
    monkeypatch.setattr(routing, 'project_probes', lambda _: pytest.fail('Unverified project reached loader'))
    (root / manifest['rows'][0]['project_path'] / 'agents.json').write_text('unit tamper')
    with pytest.raises(RuntimeError, match='PROJECT_INPUT_HASH_CHANGED'):
        routing.prepare(root / path, root / 'prepared')
    assert not (root / 'prepared').exists()

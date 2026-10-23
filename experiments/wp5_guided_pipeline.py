"""Separate fixed guided-source pipeline cohort; calls require its own reviewed freeze."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from experiments import wp5_extension as core
ROOT = core.ROOT
PLAN_REL = 'prereg/wp5_guided_pipeline_v1/plan.json'
TERMINAL_REL = 'results/raw/wp5_guided_pipeline_v1/terminal.json'

def pinned(relative, expected):
    path = (ROOT / relative).resolve()
    if not path.is_relative_to(ROOT.resolve()) or not path.is_file() or core.digest(path) != expected:
        raise RuntimeError('Guided pipeline evidence pin failed: ' + relative)
    return path

def load_plan(*, replay=False):
    path = ROOT / PLAN_REL
    core.verify_freeze(path)
    plan = core.read(path)
    if plan.get('status') != 'FROZEN' or not plan.get('implementation_sha256'):
        raise RuntimeError('Guided pipeline protocol has not been reviewed and frozen')
    for relative, expected in plan['implementation_sha256'].items(): pinned(relative, expected)
    base_ref = plan['base_pipeline_plan']
    if base_ref['path'] != core.PLAN_PATH.relative_to(ROOT).as_posix():
        raise RuntimeError('Unexpected base pipeline plan path')
    pinned(base_ref['path'], base_ref['sha256'])
    base = core.load_plan(replay=replay)
    for field in ('stage_order', 'llm_stages', 'temperature'):
        if plan[field] != base[field]: raise RuntimeError('Guided pipeline stage settings changed')
    if plan['prompt_sha256'] != base['original_pipeline_prompt_sha256']:
        raise RuntimeError('Guided pipeline prompt registry changed')
    ref = plan['source_authoring_plan']; pinned(ref['path'], ref['sha256'])
    ref = plan['accepted_source_terminal']; terminal = core.read(pinned(ref['path'], ref['sha256']))
    expected = terminal['rows']
    if terminal.get('terminal') is not True or len(expected) != 12 or len(plan['rows']) != 12:
        raise RuntimeError('Guided source terminal is incomplete')
    if plan['fixed_order'] != [row['source_id'] for row in expected] or len(set(plan['fixed_order'])) != 12:
        raise RuntimeError('Guided source order changed')
    for index, (row, source) in enumerate(zip(plan['rows'], expected), 1):
        if source['status'] != 'accepted' or row['ordinal'] != index or row['source_id'] != source['source_id']:
            raise RuntimeError('Guided accepted source identity changed')
        for key in ('source_path', 'source_sha256', 'source_authoring_result_path', 'source_authoring_result_sha256'):
            if row[key] != source[key]: raise RuntimeError('Guided source provenance changed')
        for relative, pin in source['artifact_sha256'].items(): pinned(relative, pin)
        pinned(row['source_path'], row['source_sha256'])
        pinned(row['source_authoring_result_path'], row['source_authoring_result_sha256'])
        if (row['model'], row['repetition'], row['case_id'], row['family'], row['arm'], row['phase']) != (base['models'][0], 0, row['source_id'] + '_guided_initial_mini_r0', 'guided_llm_source_v2', 'guided_source_pipeline_v1', 'guided_initial'):
            raise RuntimeError('Guided pipeline slot differs from its registered ordinary mini arm')
    prerequisites = plan.get('preceding_terminal_pins', [])
    if [r['phase'] for r in prerequisites] != ['ownership_repair', 'cap_recovery', 'drift', 'source_edit', 'zone_rename']:
        raise RuntimeError('Registered earlier phases must be terminal before guided pipelines')
    for ref in prerequisites:
        record = core.read(pinned(ref['path'], ref['sha256']))
        if ref['phase'] == 'zone_rename':
            if record.get('status') not in ('success', 'failed', 'not_executed'):
                raise RuntimeError('Scripted zone edit is not terminal')
        elif record.get('terminal') is not True:
            raise RuntimeError('A registered earlier phase is not terminal')
    return plan, base

def execute(plan, base, *, replay=False):
    plan_hash = core.digest(ROOT / PLAN_REL)
    results = []; stopped = False
    for slot in plan['rows']:
        pinned(slot['source_path'], slot['source_sha256'])
        row = {'scene_id': slot['source_id'], **{k: slot[k] for k in ('model', 'repetition', 'source_path', 'source_sha256', 'case_id', 'family', 'arm', 'phase', 'source_authoring_result_path', 'source_authoring_result_sha256')},
               'external_execution_plan_path': PLAN_REL, 'external_execution_plan_sha256': plan_hash}
        result = core.skipped_run(row, 'BUDGET_STOP') if stopped else core.run_case(row, base, replay=replay)
        stopped = stopped or core.budget_stop_record(result)
        path = ROOT / 'results/raw/wp5_extension/guided_initial' / slot['case_id'] / 'run_result.json'
        results.append({'ordinal': slot['ordinal'], 'source_id': slot['source_id'], 'case_id': slot['case_id'],
                        'status': result['status'], 'failure_stage': result.get('failure_stage'),
                        'run_result_path': path.relative_to(ROOT).as_posix(), 'run_result_sha256': core.digest(path)})
        print(json.dumps(results[-1]), flush=True)
    terminal = {'schema': 'wp5-guided-pipeline-terminal-v1', 'terminal': True, 'plan_sha256': plan_hash,
                'registered_rows': 12, 'rows': results, 'budget_stopped': stopped,
                'wp4_primary_selection_changed': False, 'interpretation': plan['interpretation']}
    core.write_once(ROOT / TERMINAL_REL, terminal)
    return terminal

def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--replay', action='store_true')
    args = parser.parse_args(); plan, base = load_plan(replay=args.replay)
    execute(plan, base, replay=args.replay)

if __name__ == '__main__': main()

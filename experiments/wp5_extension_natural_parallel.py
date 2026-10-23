"""Two-worker orchestration only; the frozen natural evaluator remains unchanged."""
from __future__ import annotations
import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import hashlib, json, multiprocessing, stat
from pathlib import Path
from experiments import wp5_extension as core
from experiments import wp5_extension_natural as nf
ROOT = core.ROOT
VOLATILE_KEYS = frozenset({'generated_at', 'timestamp', 'elapsed_seconds', 'duration_ms'})

def semantic(value):
    if isinstance(value, dict): return {k: semantic(v) for k, v in value.items() if k not in VOLATILE_KEYS}
    if isinstance(value, list): return [semantic(v) for v in value]
    return value

def volatile(value, path=''):
    rows = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key in VOLATILE_KEYS: rows.append({'path': path + '/' + key, 'value': item})
            else: rows.extend(volatile(item, path + '/' + key))
    elif isinstance(value, list):
        for index, item in enumerate(value): rows.extend(volatile(item, path + '/' + str(index)))
    return rows

def hash_value(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()

def pinned(relative, expected):
    path = (ROOT / relative).resolve()
    if not path.is_relative_to(ROOT.resolve()) or not path.is_file() or core.digest(path) != expected:
        raise RuntimeError('Pinned natural-analysis evidence changed: ' + relative)
    return path

def verify_tree(relative, declared):
    directory = ROOT / relative
    if not directory.resolve().is_relative_to(ROOT.resolve()): raise RuntimeError('Analysis input directory escapes workspace')
    actual = set(); pending = [directory] if directory.exists() else []
    while pending:
        current = pending.pop(); metadata = current.lstat()
        if current.is_symlink() or getattr(metadata, 'st_file_attributes', 0) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400):
            raise RuntimeError('Linked analysis input refused')
        if not current.resolve().is_relative_to(directory.resolve()): raise RuntimeError('Analysis input escapes directory')
        if current.is_dir(): pending.extend(current.iterdir())
        elif stat.S_ISREG(metadata.st_mode): actual.add(current.relative_to(directory).as_posix())
        else: raise RuntimeError('Nonregular analysis input refused')
    if declared != actual: raise RuntimeError('Complete retained analysis input file set changed: ' + relative)

def verify_run(relative, expected):
    path = pinned(relative, expected); run = core.read(path)
    artifacts = run.get('artifact_sha256', {})
    for name, pin in artifacts.items(): pinned(name, pin)
    directories = [path.parent.relative_to(ROOT).as_posix()]
    if run.get('project_dir'): directories.append(run['project_dir'])
    directories.append(run.get('case_dir') or 'results/raw/wp5_extension/cases/' + run['case_id'])
    for directory in directories:
        prefix = directory + '/'
        declared = {name[len(prefix):] for name in artifacts if name.startswith(prefix)}
        if path.parent.relative_to(ROOT).as_posix() == directory: declared.add(path.name)
        verify_tree(directory, declared)
    return run

def equivalence(output, case_id='extension_drift_01_astronomy_gallery_initial_mini_r0'):
    core.load_plan(replay=True)
    terminal_path = ROOT / 'results/raw/wp5_extension/natural_initial_v1/terminal_v2.json'
    pinned(terminal_path.relative_to(ROOT).as_posix(), 'fcf6f800fca630bf6eac53618aad62a08ab0870c9123d2836b80a01e77d32e6e')
    terminal = core.read(terminal_path)
    if terminal.get('terminal') is not True: raise RuntimeError('Equivalence needs completed initial evidence')
    run_rel = 'results/raw/wp5_extension/initial/' + case_id + '/run_result.json'
    verify_run(run_rel, terminal['run_result_sha256'][run_rel])
    retained_rel = 'results/raw/wp5_extension/natural_initial_v1/rooms/' + case_id + '.json'
    retained = pinned(retained_rel, terminal['room_file_sha256'][retained_rel]); before = core.read(retained)
    if not before.get('project_produced'): raise RuntimeError('Equivalence requires an already-completed native row')
    output = Path(output); repeat_path = output / (case_id + '.repeat.json')
    if repeat_path.exists(): raise RuntimeError('Equivalence repeat already exists; preserve it, never rerun silently')
    repeat = nf.safe_analyze_run(ROOT / run_rel, include_runtime=True)
    core.write_once(repeat_path, repeat)
    verify_run(run_rel, terminal['run_result_sha256'][run_rel])
    proof = {'schema': 'wp5-extension-natural-parallel-equivalence-v1', 'case_id': case_id,
             'retained_path': retained_rel, 'retained_sha256': core.digest(retained),
             'repeat_path': repeat_path.relative_to(ROOT).as_posix(), 'repeat_sha256': core.digest(repeat_path),
             'initial_natural_terminal_path': terminal_path.relative_to(ROOT).as_posix(), 'initial_natural_terminal_sha256': core.digest(terminal_path),
             'semantic_equal': semantic(before) == semantic(repeat), 'exact_json_equal': before == repeat,
             'original_semantic_sha256': hash_value(semantic(before)), 'repeat_semantic_sha256': hash_value(semantic(repeat)),
             'excluded_volatile_keys': sorted(VOLATILE_KEYS), 'original_volatile': volatile(before), 'repeat_volatile': volatile(repeat),
             'analysis_sha256': core.digest(Path(nf.__file__)), 'wrapper_sha256': core.digest(Path(__file__)),
             'same_frozen_safe_analyze_run': True, 'input_run_sha256': terminal['run_result_sha256'][run_rel]}
    core.write_once(output / 'equivalence.json', proof)
    if not proof['semantic_equal']: raise RuntimeError('Semantic equivalence failed; both outputs retained')
    print(json.dumps(proof), flush=True)
    return proof

def verify_inputs(plan):
    base = core.load_plan(replay=True); sources = core.load_sources(base)
    if plan['base_plan_sha256'] != core.digest(core.PLAN_PATH): raise RuntimeError('Frozen pipeline plan changed')
    for relative, expected in plan['implementation_sha256'].items(): pinned(relative, expected)
    if plan['analysis_sha256'] != core.digest(Path(nf.__file__)) or plan['wrapper_sha256'] != core.digest(Path(__file__)):
        raise RuntimeError('Frozen analysis/orchestration source changed')
    terminal_ref = plan['drift_terminal']; terminal = core.read(pinned(terminal_ref['path'], terminal_ref['sha256']))
    if terminal.get('terminal') is not True or terminal.get('registered_rows') != 120 or terminal.get('plan_sha256') != plan['base_plan_sha256']:
        raise RuntimeError('Drift input sequence is not terminal')
    expected = sorted(base['fresh_drift_runs'], key=lambda r: r['case_id'])
    queue = [{'case_id': row['case_id'], 'run_result_path': 'results/raw/wp5_extension/drift/' + row['case_id'] + '/run_result.json'} for row in expected]
    if plan['queue'] != queue or len(queue) != 120 or len({r['case_id'] for r in queue}) != 120:
        raise RuntimeError('All120 fixed drift identities must remain in CLI-equivalent case order')
    terminal_rows = {r['case_id']: r for r in terminal['rows']}
    if set(terminal_rows) != {r['case_id'] for r in queue} or len(terminal['rows']) != 120:
        raise RuntimeError('Drift terminal identity set changed')
    if set(plan['run_result_sha256']) != {r['run_result_path'] for r in queue}:
        raise RuntimeError('Frozen run-result map omits or adds identities')
    slots = {r['source_id']: r for r in sources['slots']}
    for item, selected in zip(queue, expected):
        run = verify_run(item['run_result_path'], plan['run_result_sha256'][item['run_result_path']])
        if run['case_id'] != item['case_id'] or run['source'] != core.source_row(selected, slots[selected['source_id']], 'drift') or run['status'] != terminal_rows[item['case_id']]['status']:
            raise RuntimeError('Retained run differs from its frozen drift identity')
    return queue

def completed_files(output, ordered, expected):
    present = {p.relative_to(ROOT).as_posix(): core.digest(p) for p in (output / 'rooms').glob('*.json')}
    if present != expected: raise RuntimeError('Completed-row pins differ from the explicit execution/resume freeze')
    identities = {r['case_id']: r for r in ordered}
    for relative in present:
        row = core.read(ROOT / relative)
        if row.get('room') not in identities: raise RuntimeError('Unregistered completed analysis identity')
        run = core.read(ROOT / identities[row['room']]['run_result_path'])
        if row.get('source') != run['source']: raise RuntimeError('Completed analysis source differs')
        if Path(relative).name != row['room'] + '.json': raise RuntimeError('Completed analysis filename differs')
    return present

def worker(relative, expected, analysis_sha):
    if core.digest(Path(nf.__file__)) != analysis_sha: raise RuntimeError('Frozen evaluator changed')
    verify_run(relative, expected)
    result = nf.safe_analyze_run(ROOT / relative, include_runtime=True)
    verify_run(relative, expected)
    if core.digest(Path(nf.__file__)) != analysis_sha: raise RuntimeError('Frozen evaluator changed during analysis')
    return result

def execute(execution_plan):
    execution_plan = Path(execution_plan); core.verify_freeze(execution_plan); plan = core.read(execution_plan)
    if plan.get('status') != 'FROZEN' or plan.get('workers') != 2: raise RuntimeError('Two-worker execution plan is not frozen')
    evidence = core.read(pinned(plan['equivalence']['path'], plan['equivalence']['sha256']))
    if not evidence.get('semantic_equal') or evidence['analysis_sha256'] != plan['analysis_sha256'] or evidence['wrapper_sha256'] != plan['wrapper_sha256']:
        raise RuntimeError('Equivalence evidence differs from execution sources')
    ordered = verify_inputs(plan); output = (ROOT / plan['output']).resolve()
    if not output.is_relative_to(ROOT.resolve()): raise RuntimeError('Output escapes workspace')
    reused = completed_files(output, ordered, plan['completed_room_sha256'])
    missing = [r for r in ordered if not (output / 'rooms' / (r['case_id'] + '.json')).exists()]
    core.write_once(output / ('execution_' + core.digest(execution_plan) + '.json'),
                    {'execution_plan_sha256': core.digest(execution_plan), 'completed_row_sha256': reused,
                     'scheduled_case_ids': [r['case_id'] for r in missing], 'workers': 2, 'no_completed_identity_rescheduled': True})
    context = multiprocessing.get_context('spawn')
    with ProcessPoolExecutor(max_workers=2, mp_context=context) as pool:
        futures = {pool.submit(worker, r['run_result_path'], plan['run_result_sha256'][r['run_result_path']], plan['analysis_sha256']): r for r in missing}
        for future in as_completed(futures):
            row = futures[future]; result = future.result()
            if result['room'] != row['case_id']: raise RuntimeError('Worker result identity differs')
            core.write_once(output / 'rooms' / (row['case_id'] + '.json'), result)
            print(json.dumps({'case_id': row['case_id'], 'project_produced': result['project_produced']}), flush=True)
    for relative, expected in reused.items(): pinned(relative, expected)
    verify_inputs(plan)
    rows = [core.read(output / 'rooms' / (r['case_id'] + '.json')) for r in ordered]
    terminal = {'schema': 'wp5-extension-natural-parallel-terminal-v1', 'terminal': True,
                'execution_plan_sha256': core.digest(execution_plan), 'registered_rows': 120, 'terminal_rows': len(rows),
                'ordered_case_ids': [r['case_id'] for r in ordered], 'native_rows': sum(r['project_produced'] for r in rows),
                'probes': sum(len(r.get('probes', [])) for r in rows), 'reused_completed_row_sha256': reused,
                'room_file_sha256': {(output / 'rooms' / (r['case_id'] + '.json')).relative_to(ROOT).as_posix(): core.digest(output / 'rooms' / (r['case_id'] + '.json')) for r in ordered},
                'analysis_sha256': plan['analysis_sha256'], 'wrapper_sha256': plan['wrapper_sha256'],
                'statistics': 'No new bootstrap or scientific evaluator code here; final report derives metrics from retained row labels under its separate reporting freeze.'}
    core.write_once(output / 'terminal.json', terminal)
    print(json.dumps({k: v for k, v in terminal.items() if k not in ('room_file_sha256', 'ordered_case_ids')}), flush=True)
    return terminal

def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--equivalence-output', type=Path); parser.add_argument('--execution-plan', type=Path)
    args = parser.parse_args()
    if args.equivalence_output: equivalence(args.equivalence_output.resolve())
    elif args.execution_plan: execute(args.execution_plan.resolve())
    else: parser.error('Choose bounded equivalence or frozen execution plan')

if __name__ == '__main__': main()

"""Unpaid orchestration draft. Never replaces the frozen WP4 preparation source."""
from __future__ import annotations

import argparse
import ast
import copy
import hashlib
import json
import multiprocessing
import stat
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from experiments import routing_baselines as rb
from experiments.lib import wp4_selection as selector

ROOT = rb.ROOT
PREPARE_SHA256 = '582e317e0f731966ce9a2438b4e5bd15cf7f7daa9c16390dec93169a4556761f'


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def pinned(relative, expected):
    path = ROOT / relative
    require(path.resolve().is_relative_to(ROOT.resolve()), 'Evidence escapes workspace')
    require(path.is_file() and not path.is_symlink(), 'Missing or linked evidence: ' + relative)
    require(rb.digest(path) == expected, 'Evidence digest changed: ' + relative)
    return path


def tree(directory):
    directory = Path(directory)
    require(directory.resolve().is_relative_to(ROOT.resolve()), 'Tree escapes workspace')
    pending = [directory] if directory.exists() else []
    result = {}
    while pending:
        path = pending.pop()
        metadata = path.lstat()
        require(not path.is_symlink() and not (getattr(metadata, 'st_file_attributes', 0) & 0x400), 'Linked input refused')
        if stat.S_ISDIR(metadata.st_mode):
            pending.extend(path.iterdir())
        else:
            require(stat.S_ISREG(metadata.st_mode), 'Nonregular input refused')
            result[path.relative_to(directory).as_posix()] = rb.digest(path)
    return dict(sorted(result.items()))


def write_once(path, value):
    require(not Path(path).exists(), 'Existing output must be retained: ' + str(path))
    rb.write_json(path, value)


def copy_once(source, target, expected):
    data = Path(source).read_bytes()
    require(hashlib.sha256(data).hexdigest() == expected, 'Copy source changed')
    target = Path(target)
    require(not target.exists(), 'Copy target already exists')
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open('xb') as stream:
        stream.write(data)


def prepare_loop():
    source = Path(rb.__file__)
    raw_source = source.read_bytes()
    require(hashlib.sha256(raw_source).hexdigest() == PREPARE_SHA256, 'Frozen prepare source changed')
    module = ast.parse(raw_source.decode('utf-8'))
    prepare = next(node for node in module.body if isinstance(node, ast.FunctionDef) and node.name == 'prepare')
    loops = [node for node in prepare.body if isinstance(node, ast.For) and isinstance(node.target, ast.Tuple)
             and [getattr(x, 'id', None) for x in node.target.elts] == ['ri', 'metadata']]
    require(len(loops) == 1, 'Frozen per-room loop shape changed')
    return source, raw_source, loops[0]


def portable_body_hash(body):
    """Identity only: omit Python3.12's empty FunctionDef.type_params field.

    The compiled AST is not normalized. Nonempty type parameters, every other
    field, and all source bytes remain significant and separately pinned.
    """
    normalized = copy.deepcopy(body)
    for node in ast.walk(normalized):
        if isinstance(node, ast.FunctionDef) and 'type_params' in node._fields and node.type_params == []:
            node._fields = tuple(field for field in node._fields if field != 'type_params')
    return hashlib.sha256(ast.dump(normalized, include_attributes=False).encode()).hexdigest()


def loop_source_sha256():
    _, source, loop = prepare_loop()
    return hashlib.sha256(b''.join(source.splitlines(keepends=True)[loop.lineno - 1:loop.end_lineno])).hexdigest()


def lifted_room_body():
    """Compile the unchanged per-room loop with one fixed original ordinal."""
    source, _, original_loop = prepare_loop()
    loop = copy.deepcopy(original_loop)
    original_body_hash = portable_body_hash(ast.Module(body=loop.body, type_ignores=[]))
    loop.iter = ast.parse('[(ri, metadata)]', mode='eval').body
    function = ast.parse("def run_one(ri, metadata, out, selection):\n    index = {'rooms': [], 'omitted_sources': [], 'question_objects': [], 'disagreements': []}\n    return index\n").body[0]
    function.body.insert(1, loop)
    namespace = dict(vars(rb))
    namespace['verify_selected_artifacts'] = selector.verify_selected_artifacts
    compiled = ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[]))
    exec(compile(compiled, str(source) + ':exact_room_loop', 'exec'), namespace)
    return namespace['run_one'], original_body_hash


def verify_example(plan):
    project = ROOT / plan['example']['project_path']
    require(tree(project) == plan['example_project_sha256'], 'Example project file set or bytes changed')


def verify_metadata(plan, metadata):
    if metadata['split'] == 'evaluation':
        selector.verify_selected_artifacts(ROOT, [metadata])
    else:
        require(metadata == plan['example'], 'Example identity changed')
        verify_example(plan)


def verify_plan_inputs(plan):
    frozen = rb.verify_freeze()
    require(frozen['_effective_freeze_sha256'] == plan['effective_freeze_sha256'], 'WP4 freeze changed')
    for relative, expected in plan['implementation_sha256'].items():
        pinned(relative, expected)
    require(rb.digest(Path(__file__)) == plan['wrapper_sha256'], 'Wrapper changed')
    selection_path = pinned(plan['selection']['path'], plan['selection']['sha256'])
    selection = rb.read_json(selection_path)
    summary = pinned(plan['summary']['path'], plan['summary']['sha256'])
    rebuilt = selector.prepare_selection(ROOT, summary, frozen)
    require(rebuilt == selection, 'Exact74 selection or its provenance changed')
    metadata = selector.selected_metadata(selection)
    require(len(metadata) == 20 and len({r['source_room_id'] for r in metadata}) == 20, 'Exactly20 selected evaluation sources required')
    metadata.append(plan['example'])
    require(plan['queue'] == [{'ordinal': i, 'metadata': row} for i, row in enumerate(metadata)], 'Fixed20 plus separate example order changed')
    require(plan['example']['split'] == 'example' and plan['example']['source_room_id'] == 'authored_example', 'Example must remain separate')
    verify_example(plan)
    _, body_hash = lifted_room_body()
    require(body_hash == plan['room_loop_ast_sha256'], 'Exact per-room body changed')
    require(loop_source_sha256() == plan['room_loop_source_sha256'], 'Exact per-room source bytes changed')
    return selection


def fragment_from_room(metadata, room, room_sha256):
    require(all(room.get(k) == v for k, v in metadata.items()), 'Completed room identity/provenance changed')
    probes = room['probes']
    identities = [(p['start_agent'], p['target']['id']) for p in probes]
    require(len(identities) == len(set(identities)), 'Duplicate retained probe identity')
    require(room.get('primary') in probes and all(p in probes for p in room['turn_pairs']), 'Retained room selection is not from its probes')
    return {
        'rooms': [{**metadata, 'file': 'rooms/' + metadata['source_room_id'] + '.json', 'sha256': room_sha256,
                   'probe_count': len(probes), 'agreement_count': sum(p['agreement'] for p in probes),
                   'class_counts': {c: sum(p['class'] == c for p in probes) for c in rb.CLASSES}}],
        'omitted_sources': [],
        'disagreements': [{'source_room_id': metadata['source_room_id'], **p} for p in probes
                          if not p['agreement'] or not p['backend_agreement']],
        'question_objects': [{'source_room_id': metadata['source_room_id'], 'target_id': t['id']}
                             for t in room['question_targets']],
    }


def verify_fragment(metadata, fragment, output):
    expected_keys = {'rooms', 'omitted_sources', 'disagreements', 'question_objects'}
    require(set(fragment) == expected_keys, 'Unexpected fragment fields')
    require(len(fragment['rooms']) + len(fragment['omitted_sources']) == 1, 'Fragment must retain one terminal selected identity')
    if fragment['rooms']:
        row = fragment['rooms'][0]
        require(row['file'] == 'rooms/' + metadata['source_room_id'] + '.json', 'Unexpected room file')
        path = Path(output) / row['file']
        require(path.exists() and rb.digest(path) == row['sha256'], 'Fragment room changed or incomplete')
        require(fragment == fragment_from_room(metadata, rb.read_json(path), row['sha256']), 'Fragment differs from retained room bytes')
    else:
        omitted = fragment['omitted_sources'][0]
        require(all(omitted.get(k) == v for k, v in metadata.items()), 'Omitted identity changed')
        require(omitted.get('reason') == 'no_agreed_probe_or_admitted_probe', 'Unregistered omission reason')
        require(not (Path(output) / 'rooms').exists(), 'Omitted fragment has an unexpected room')


def verify_job(metadata, job_dir, receipt=None):
    job_dir = Path(job_dir)
    fragment = rb.read_json(job_dir / 'fragment.json')
    verify_fragment(metadata, fragment, job_dir)
    allowed = {'fragment.json'}
    if fragment['rooms']:
        allowed.add('rooms/' + metadata['source_room_id'] + '.json')
    actual = tree(job_dir)
    require(set(actual) == allowed, 'Unexpected or missing worker file')
    if receipt is not None:
        require(receipt['fragment_sha256'] == actual['fragment.json'], 'Worker fragment hash differs from receipt')
        require(receipt['file_sha256'] == actual, 'Worker artifacts changed before receipt verification')
    return fragment, actual


def expected_corpus_files(plan, fragments):
    expected = dict(plan['serial_bootstrap_sha256'])
    for fragment in fragments:
        for row in fragment['rooms']:
            require(row['file'] not in expected, 'Duplicate corpus room path')
            expected[row['file']] = row['sha256']
    return expected


def verify_corpus_files(output, expected):
    require(tree(output) == expected, 'Final corpus file set or bytes differ from registered outputs')


def worker(plan, item, job_dir):
    job_dir = Path(job_dir)
    require(not job_dir.exists(), 'Partial/unreceipted worker directory exists; retain and refuse')
    verify_plan_inputs(plan)
    metadata = item['metadata']
    verify_metadata(plan, metadata)
    function, _ = lifted_room_body()
    fragment = function(item['ordinal'], metadata, job_dir, {'frozen_selection': True})
    verify_metadata(plan, metadata)
    verify_fragment(metadata, fragment, job_dir)
    write_once(job_dir / 'fragment.json', fragment)
    _, file_hashes = verify_job(metadata, job_dir)
    return {'ordinal': item['ordinal'], 'metadata': metadata,
            'fragment_sha256': file_hashes['fragment.json'], 'file_sha256': file_hashes}


def merge_fragments(selection, fragments, effective_freeze_sha256, selection_sha256):
    index = {'rooms': [], 'omitted_sources': list(selection['omitted_sources']), 'question_objects': [], 'disagreements': [],
             'cohort_label': selection['cohort_label'], 'selection': {'path': 'selection.json', 'sha256': selection_sha256},
             'effective_freeze_sha256': effective_freeze_sha256}
    for fragment in fragments:
        for key in ('rooms', 'omitted_sources', 'question_objects', 'disagreements'):
            index[key].extend(fragment[key])
    return index


def verify_cutoff(plan):
    cutoff = plan['serial_cutoff']
    require(cutoff['terminal'] is False and cutoff['process_stopped'] is True and cutoff['interruption_reason'], 'Serial cutoff is not explicitly frozen')
    original = ROOT / cutoff['directory']
    require(tree(original) == cutoff['file_sha256'], 'Serial cutoff file set or bytes changed')
    require('manifest.json' not in cutoff['file_sha256'], 'Serial corpus is already terminal; no cutover needed')
    rooms = {p: h for p, h in cutoff['file_sha256'].items() if p.startswith('rooms/')}
    bootstrap = {p: h for p, h in cutoff['file_sha256'].items() if not p.startswith('rooms/')}
    require(bootstrap == plan['serial_bootstrap_sha256'], 'Serial bootstrap evidence changed or unregistered output appeared')
    require(rooms == cutoff['completed_room_sha256'], 'Partial or unregistered serial room file')
    identities = {item['metadata']['source_room_id']: item for item in plan['queue']}
    expected_prefix = {'rooms/' + item['metadata']['source_room_id'] + '.json' for item in plan['queue'][:len(rooms)]}
    require(set(rooms) == expected_prefix, 'Serial completed rooms are not a receipted fixed-order prefix')
    for relative, expected in rooms.items():
        require(relative.endswith('.json') and Path(relative).stem in identities, 'Unregistered serial room identity')
        metadata = identities[Path(relative).stem]['metadata']
        verify_metadata(plan, metadata)
        fragment_from_room(metadata, rb.read_json(original / relative), expected)
    return original, rooms


def verify_equivalence(plan):
    reference = plan['equivalence']; proof = rb.read_json(pinned(reference['path'], reference['sha256']))
    require(proof['byte_equal'] is True and proof['fragment_equal'] is True and proof['native_probe_calls'] == 0,
            'Retained-probe equivalence did not pass')
    require(proof['wrapper_sha256'] == plan['wrapper_sha256'] and proof['room_loop_ast_sha256'] == plan['room_loop_ast_sha256']
            and proof['prepare_source_sha256'] == PREPARE_SHA256, 'Equivalence source pins changed')
    require(proof['room_loop_source_sha256'] == plan['room_loop_source_sha256'], 'Equivalence loop source bytes changed')
    for kind in ('retained', 'repeat'):
        pinned(proof[kind + '_path'], proof[kind + '_sha256'])
    require(proof['retained_sha256'] == proof['repeat_sha256'], 'Equivalence bytes differ')


def execute(plan_path):
    plan_path = Path(plan_path)
    require(plan_path.with_suffix('.sha256').read_text().split()[0] == rb.digest(plan_path), 'Execution sidecar changed')
    plan = rb.read_json(plan_path)
    require(plan['status'] == 'FROZEN' and plan['workers'] == 2, 'Unfrozen orchestration draft cannot execute')
    require(bool(plan.get('source_commit')) and isinstance(plan.get('root_review'), dict), 'Reviewed source checkpoint is missing')
    pinned(plan['root_review']['path'], plan['root_review']['sha256'])
    verify_equivalence(plan)
    selection = verify_plan_inputs(plan)
    original, completed = verify_cutoff(plan)
    output = ROOT / plan['output']
    evidence = ROOT / plan['evidence_output']
    require(not output.exists() and not evidence.exists(), 'Existing orchestration output requires a separately frozen resume')
    require(output.resolve().is_relative_to(ROOT.resolve()) and evidence.resolve().is_relative_to(ROOT.resolve()), 'Output escapes workspace')
    for relative, expected in plan['serial_cutoff']['file_sha256'].items():
        copy_once(original / relative, output / relative, expected)
    evidence.mkdir(parents=True, exist_ok=False)
    write_once(evidence / 'start.json', {'execution_plan_sha256': rb.digest(plan_path), 'completed_room_sha256': completed,
                                       'no_completed_native_probes_rescheduled': True, 'workers': 2})
    fragments = {}
    pending = []
    for item in plan['queue']:
        metadata = item['metadata']; relative = 'rooms/' + metadata['source_room_id'] + '.json'
        if relative in completed:
            fragments[item['ordinal']] = fragment_from_room(metadata, rb.read_json(output / relative), completed[relative])
        else:
            pending.append(item)
    context = multiprocessing.get_context('spawn')
    with ProcessPoolExecutor(max_workers=2, mp_context=context) as pool:
        futures = {pool.submit(worker, plan, item, evidence / 'jobs' / item['metadata']['source_room_id']): item for item in pending}
        for future in as_completed(futures):
            item = futures[future]; receipt = future.result(); metadata = item['metadata']
            job = evidence / 'jobs' / metadata['source_room_id']
            require(receipt['ordinal'] == item['ordinal'] and receipt['metadata'] == metadata, 'Worker identity changed')
            fragment, _ = verify_job(metadata, job, receipt)
            verify_metadata(plan, metadata)
            if fragment['rooms']:
                row = fragment['rooms'][0]; copy_once(job / row['file'], output / row['file'], row['sha256'])
            write_once(evidence / 'receipts' / (metadata['source_room_id'] + '.json'), receipt)
            fragments[item['ordinal']] = fragment
            print(json.dumps({'source_room_id': metadata['source_room_id'], 'room_produced': bool(fragment['rooms'])}), flush=True)
    verify_cutoff(plan); verify_plan_inputs(plan)
    ordered = [fragments[item['ordinal']] for item in plan['queue']]
    expected_files = expected_corpus_files(plan, ordered)
    verify_corpus_files(output, expected_files)
    index = merge_fragments(selection, ordered, plan['effective_freeze_sha256'], plan['selection']['sha256'])
    write_once(output / 'manifest.json', index)
    (output / 'manifest.sha256').write_text(rb.digest(output / 'manifest.json') + '\n', encoding='utf-8')
    expected_files.update({name: rb.digest(output / name) for name in ('manifest.json', 'manifest.sha256')})
    rb.load_corpus(output)
    verify_cutoff(plan); verify_plan_inputs(plan)
    verify_corpus_files(output, expected_files)
    write_once(evidence / 'terminal.json', {'terminal': True, 'execution_plan_sha256': rb.digest(plan_path),
                                         'selected_evaluation_sources': 20, 'separate_example_slots': 1,
                                         'registered_rows': 21, 'room_count': len(index['rooms']),
                                         'manifest_sha256': rb.digest(output / 'manifest.json'),
                                         'corpus_file_sha256': expected_files, 'completed_room_sha256': completed})
    return index


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--execution-plan', type=Path, required=True)
    execute(parser.parse_args().execution_plan)


if __name__ == '__main__':
    main()

"""Unpaid candidate: isolated Driver constructor adaptation, unchanged HTTP body."""
from pathlib import Path
import ast
import copy
import hashlib
import json
import stat

ROOT = Path(__file__).resolve().parents[2]
AUDIT = 'results/raw/wp4_http_containment_audit_v2.json'
AUDIT_SHA = 'df1c493e31b73b63cb4ea0fa28b8b34d38a179d695768098edcee3f126b6bc1b'
DRIVER = 'experiments/lib/backend_driver.py'
DRIVER_SHA = '87465293d5256cf65eb1ead6bf45bef4b60a8d1d3d1c18176af39d01b51d809e'
HTTP = 'experiments/guarded_llm_turns.py'
sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
read = lambda p: json.loads(Path(p).read_text(encoding='utf-8-sig'))


class Refusal(RuntimeError):
    pass


def need(value, message):
    if not value:
        raise Refusal(message)


def regular(root, relative):
    rel = Path(relative)
    parts = tuple(s.casefold() for s in rel.parts)
    need(not rel.anchor and '..' not in parts, 'Escaping relative path')
    need(not any(s.startswith('\x2eenv') or s in {'config.json', 'private', '.private', '.aws', '.git',
         'fragebogen-antworten-2026-08-17-vollstaendig-imputiert.json'} for s in parts), 'Excluded input')
    need(not any(parts[i:i+2] == ('app', 'excluded_client') for i in range(len(parts)-1)), 'Excluded independent tree')
    path = Path(root)
    for part in rel.parts:
        path /= part
        need(not path.is_symlink() and not getattr(path.lstat(), 'st_file_attributes', 0)&0x400, 'Linked input')
    need(path.resolve().is_relative_to(Path(root).resolve()) and path.is_file(), 'Nonregular or escaping input')
    return path


def tree(directory):
    directory = Path(directory)
    result, pending = {}, [directory]
    while pending:
        path = pending.pop()
        info = path.lstat()
        need(not path.is_symlink() and not getattr(info, 'st_file_attributes', 0)&0x400, 'Linked tree')
        if stat.S_ISDIR(info.st_mode):
            pending.extend(path.iterdir())
        else:
            need(stat.S_ISREG(info.st_mode), 'Nonregular tree input')
            relative = path.relative_to(directory).as_posix()
            regular(directory, relative)
            result[relative] = sha(path)
    return result


def write_once(path, value):
    path = Path(path)
    need(path.is_absolute() and path.is_relative_to(ROOT), 'Receipt output escapes workspace')
    need('..' not in path.relative_to(ROOT).parts, 'Escaping receipt output')
    cursor = ROOT
    for part in path.relative_to(ROOT).parts[:-1]:
        cursor /= part
        if cursor.exists():
            need(cursor.is_dir() and not cursor.is_symlink() and not getattr(cursor.lstat(), 'st_file_attributes', 0)&0x400, 'Linked receipt output')
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8', newline='\n') as handle:
        json.dump(value, handle, sort_keys=True, indent=2)
        handle.write('\n')


def load_records(root=ROOT):
    root = Path(root)
    need(sha(regular(root, AUDIT)) == AUDIT_SHA, 'HTTP audit changed')
    audit = read(root/AUDIT)
    for name, pin in audit['input_sha256'].items():
        need(sha(regular(root, name)) == pin, 'Audit input changed: '+name)
    manifest = read(root/'results/raw/wp4_corpus_parallel_v1/manifest.json')
    rows = {r['source_room_id']: r for r in manifest['rooms'] if r['split'] == 'evaluation'}
    need(len(rows) == 20 and set(rows) == {r['source_room_id'] for r in audit['rows']}, 'Fixed20 selection differs')
    result = {}
    for row in audit['rows']:
        m = rows[row['source_room_id']]
        run_path = regular(root, m['run_result_path'])
        need(sha(run_path) == m['run_result_sha256'], 'Run pin changed')
        run = read(run_path)
        prefix = row['project_path']+'/'
        declared = {name[len(prefix):]: pin for name, pin in run['artifact_sha256'].items() if name.startswith(prefix)}
        need('project.json' in declared and 'roomcontract.v05.instance.json' in declared, 'Required legacy copy missing')
        need(tree(root/row['project_path']) == declared, 'Complete original project set changed')
        result[row['project_path']] = {**row, 'declared_project_sha256': declared}
    return result


def adapt_private(driver, source, record, receipt_root):
    source = Path(source)
    need(tree(source) == record['declared_project_sha256'], 'Original project changed during copy')
    need(driver.project.resolve().is_relative_to(Path(driver.temp.name).resolve()) and driver.project.parent == driver.projects,
         'Private project escapes Driver temp')
    need(tree(driver.project) == record['declared_project_sha256'], 'Copied materialization set differs')
    meta_path = regular(driver.project, 'project.json')
    meta = read(meta_path)
    need(str(Path(meta['roomcontract_trace_path']).resolve()) == record['original_trace_path'], 'Legacy metadata pointer changed')
    legacy = regular(driver.project, meta['roomcontract_legacy_path'])
    need(sha(legacy) == record['original_trace_sha256'] == record['copied_legacy_sha256'], 'Legacy copy is not exact')
    updated = copy.deepcopy(meta)
    updated['roomcontract_trace_path'] = str(legacy.resolve())
    need({k for k in set(meta)|set(updated) if meta.get(k)!=updated.get(k)} == {'roomcontract_trace_path'}, 'Unexpected metadata delta')
    before = sha(meta_path)
    meta_path.write_text(json.dumps(updated, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    after_tree = tree(driver.project)
    need({name for name in after_tree if after_tree[name]!=record['declared_project_sha256'][name]} == {'project.json'}, 'Unexpected copied-byte change')
    from backend.runtime_trace import _runtime_log_path
    need(_runtime_log_path(driver.project) == driver.project/'runtime_logs/events.jsonl', 'Append target is not private')
    driver._containment_record = record
    driver._containment_receipt_root = Path(receipt_root)
    driver._containment_original_source = source
    driver._containment_private_baseline = after_tree
    write_once(Path(receipt_root)/(record['source_room_id']+'.adaptation.json'), {
        'source_room_id': record['source_room_id'], 'source_project': record['project_path'],
        'source_project_sha256': record['declared_project_sha256'], 'original_metadata_sha256': before,
        'adapted_metadata_sha256': sha(meta_path), 'changed_metadata_key': 'roomcontract_trace_path',
        'old_value': meta['roomcontract_trace_path'], 'new_value': updated['roomcontract_trace_path'],
        'mechanical_fingerprint_context_changed': True, 'native_model_trace_labels_unchanged': True,
        'generation_calls_by_adapter': 0})


def build_driver_factory(original_module, records, receipt_root, evidence_root, root=ROOT):
    root = Path(root)
    need(Path(original_module.__file__).resolve() == (root/DRIVER).resolve() and sha(root/DRIVER) == DRIVER_SHA, 'Original Driver source changed')
    source = (root/DRIVER).read_text(encoding='utf-8')
    cls = next(n for n in ast.parse(source).body if isinstance(n,ast.ClassDef) and n.name=='Driver')
    node = copy.deepcopy(next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='__init__'))
    original_ast = ast.dump(node, include_attributes=False)
    indexes = [i for i,n in enumerate(node.body) if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call)
               and isinstance(n.value.func,ast.Attribute) and isinstance(n.value.func.value,ast.Name)
               and n.value.func.value.id=='shutil' and n.value.func.attr=='copytree']
    need(len(indexes)==1, 'Exactly one frozen copytree insertion point required')
    insertion = ast.parse('_adapt_private_copy(self, source)').body[0]
    node.body.insert(indexes[0]+1, insertion)
    restored = copy.deepcopy(node)
    del restored.body[indexes[0]+1]
    need(ast.dump(restored,include_attributes=False)==original_ast, 'Unrelated constructor change')
    scope = dict(vars(original_module))
    by_source = {(root/name).resolve(): record for name,record in records.items()}
    def adapted(driver, source):
        key=Path(source).resolve()
        need(key in by_source,'Unregistered source')
        adapt_private(driver, source, by_source[key], receipt_root)
    scope['_adapt_private_copy'] = adapted
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])), '<isolated contained Driver>', 'exec'), scope)
    def close(driver):
        record=driver._containment_record
        need(tree(driver._containment_original_source)==record['declared_project_sha256'], 'Original materialization changed after HTTP')
        actual_private=tree(driver.project)
        baseline=driver._containment_private_baseline
        need(all(actual_private.get(name)==pin for name,pin in baseline.items()),'Copied materialization changed during HTTP')
        need(set(actual_private)-set(baseline) <= {'runtime_logs/events.jsonl','runtime_logs/runtime_validation.v2.jsonl','runtime_guard_audit.jsonl'},'Unexpected private runtime output')
        private={p.relative_to(driver.project).as_posix():sha(p) for p in driver.project.rglob('*.jsonl')}
        collected={}
        room_evidence=Path(evidence_root)/record['source_room_id']
        for folder in room_evidence.iterdir() if room_evidence.exists() else []:
            if folder.is_dir():
                for p in folder.rglob('*.jsonl'):
                    name=p.relative_to(folder).as_posix()
                    need(name not in collected,'Ambiguous collected evidence')
                    collected[name]=sha(p)
        need(private==collected,'Private evidence not collected byte-identically')
        write_once(Path(receipt_root)/(record['source_room_id']+'.closure.json'), {
            'source_room_id':record['source_room_id'],'original_complete_project_unchanged':True,
            'private_jsonl_sha256':private,'collected_jsonl_sha256':collected,'exact_collection':True})
        original_module.Driver.close(driver)
    isolated=type('ContainedEvidenceDriver',(original_module.Driver,),{'__init__':scope['__init__'],'close':close})
    def factory(project=None,client=None):
        need(project is not None and client is not None,'Explicit registered project and client required')
        path=Path(project)
        need(path.is_absolute() and path.is_relative_to(root),'Source project escapes workspace')
        regular(root,(path/'project.json').relative_to(root).as_posix())
        path=path.resolve()
        need(path in by_source,'Unregistered source project')
        need(tree(path)==by_source[path]['declared_project_sha256'],'Original source closure changed before copy')
        driver=isolated(project,client)
        from backend.runtime_trace import contract_runtime_fingerprint
        counterfactual=copy.deepcopy(driver.contract)
        counterfactual['project']['roomcontract_trace_path']=by_source[path]['original_trace_path']
        before_fp=contract_runtime_fingerprint(counterfactual)
        after_fp=contract_runtime_fingerprint(driver.contract)
        need(before_fp!=after_fp,'Expected mechanical path fingerprint change missing')
        write_once(Path(receipt_root)/(by_source[path]['source_room_id']+'.fingerprint_context.json'),{
            'old_metadata_at_same_private_path_fingerprint':before_fp,'adapted_context_fingerprint':after_fp,
            'old_context_is_pure_counterfactual_not_executed':True,'changed_context_key':'roomcontract_trace_path'})
        return driver
    return factory, {'constructor_original_ast':original_ast,'insertions':1,
                     'original_source_segment_sha256':hashlib.sha256(ast.get_source_segment(source,next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='__init__')).encode()).hexdigest()}


def lift_http_run(original_module, driver_factory, expected_source_sha256):
    need(sha(original_module.__file__)==expected_source_sha256,'Original HTTP source changed')
    source=Path(original_module.__file__).read_text(encoding='utf-8')
    node=next(n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name=='run')
    scope=dict(vars(original_module))
    scope['Driver']=driver_factory
    exec(compile(ast.Module(body=[node],type_ignores=[]),'<unchanged HTTP body with isolated Driver>','exec'),scope)
    return scope['run']

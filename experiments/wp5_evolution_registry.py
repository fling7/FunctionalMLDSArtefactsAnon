"""Offline fixed evolution-pair registry; missing native endpoints stay explicit."""
from __future__ import annotations
import argparse,hashlib,json
from pathlib import Path
from experiments.pipeline_runs import ROOT
from experiments.wp5_extension_drift import (label_completeness,independent_projection,compare_run_pair,
    load_project_contract,contract_runtime_fingerprint,contract_commit_fingerprint)

def read(path):return json.loads(Path(path).read_text(encoding='utf-8-sig'))
def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def pin(path):return {'path':Path(path).relative_to(ROOT).as_posix(),'sha256':digest(path)}
def checked(relative,expected):
    path=(ROOT/relative).resolve()
    if not path.is_relative_to(ROOT.resolve()) or digest(path)!=expected:raise RuntimeError('Pinned evolution artifact changed or escaped workspace')
    return path

def registered_pairs(plan):
    pairs=[]
    for source in plan['new_deterministic_sources']:
        for model in plan['models']:
            selected={r['repetition']:r['case_id'] for r in plan['fresh_drift_runs'] if r['source_id']==source['source_id'] and r['model']==model}
            for repetition in range(1,5):pairs.append({'pair_family':'fresh_regeneration','source_id':source['source_id'],'pipeline_model':model,
                'before_case_id':selected[repetition],'after_case_id':selected[repetition+1]})
    base=next(r for r in plan['initial_baselines'] if r['case_id']==plan['zone_rename']['base_case_id'])
    edits={r['edit']:r for r in plan['source_edits']}
    for edit in plan['source_edits']:
        parent=base['case_id'] if edit['parent']=='initial' else edits[edit['parent']]['case_id']
        pairs.append({'pair_family':'source_'+edit['edit'],'source_id':base['source_id'],'pipeline_model':edit['model'],
            'before_case_id':parent,'after_case_id':edit['case_id']})
    pairs.append({'pair_family':'scripted_zone_rename','source_id':base['source_id'],'pipeline_model':base['model'],
        'before_case_id':base['case_id'],'after_case_id':base['case_id']+'_zone_rename_v1'})
    for candidate in plan['targeted_repair_candidates']:
        pairs.append({'pair_family':'ownership_authoring_repair','source_id':candidate['source']['scene_id'],'pipeline_model':candidate['source']['model'],
            'before_case_id':candidate['case_id'],'after_case_id':candidate['case_id']+'_ownershiprepair_v1'})
    for number,row in enumerate(pairs,1):row['pair_id']='wp5_evolution_'+str(number).zfill(3)
    return pairs

def verify_inventory_row(row):
    if row['terminal_status']=='pending':raise RuntimeError('Evolution inventory has a pending registered identity')
    for name in ('run_result','terminal_record'):
        if row.get(name+'_path'):checked(row[name+'_path'],row[name+'_sha256'])
    if not row.get('run_result_path'):
        if row['native_materialized']:raise RuntimeError('Native endpoint lacks retained materialization record')
        return None
    run=read(ROOT/row['run_result_path'])
    if run.get('case_id')!=row['case_id'] or run.get('project_dir')!=row.get('project_path'):raise RuntimeError('Inventory differs from retained project identity')
    if row.get('project_path'):
        project=(ROOT/row['project_path']).resolve()
        if not project.is_relative_to(ROOT.resolve()):raise RuntimeError('Project path escapes workspace')
        prefix=project.relative_to(ROOT).as_posix()+'/'
        expected={rel:value for rel,value in run['artifact_sha256'].items() if rel.startswith(prefix)}
        actual={path.relative_to(ROOT).as_posix() for path in project.rglob('*') if path.is_file()}
        if actual!=set(expected):raise RuntimeError('Retained project file inventory changed')
        for relative,value in expected.items():checked(relative,value)
    if row['native_materialized']:
        model=ROOT/row['project_path']/'roomcontract.v2.instance.json';checked(model.relative_to(ROOT).as_posix(),row['model_file_sha256'])
        if row.get('trace_path'):checked(row['trace_path'],row['trace_sha256'])
        if run['artifact_sha256'].get(model.relative_to(ROOT).as_posix())!=row['model_file_sha256']:raise RuntimeError('Inventory native pin differs from materialization record')
    return run

def endpoint(row,analysis_dirs):
    verify_inventory_row(row)
    result={'case_id':row['case_id'],'materialized':row['native_materialized'],'independent_comparable':False,
        'independent_label_missing_reason':'no_native_model','runtime_adoption_eligible':False,
        'gate0_ok':row.get('gate0_ok'),'loader_status':'not_attempted','object_faults':None,
        'run_result_path':row.get('run_result_path'),'run_result_sha256':row.get('run_result_sha256'),
        'terminal_record_path':row.get('terminal_record_path'),'terminal_record_sha256':row.get('terminal_record_sha256'),
        'project_path':row.get('project_path'),'terminal_status':row['terminal_status']}
    if not row['native_materialized']:return result
    result.update(model_file_sha256=row['model_file_sha256'],model_sha256=row['model_sha256'],independent_label_missing_reason='analysis_missing')
    project=ROOT/row['project_path'];model=project/'roomcontract.v2.instance.json';trace=project/'trace_map.v2.json'
    if not row.get('trace_path'):result['independent_label_missing_reason']='trace_missing'
    analysis_path=ROOT/analysis_dirs[row['phase']]/'rooms'/(row['case_id']+'.json')
    if not analysis_path.exists():raise RuntimeError('Native endpoint natural analysis is not terminal: '+row['case_id'])
    analysis=read(analysis_path);run=read(ROOT/row['run_result_path'])
    if analysis['room']!=row['case_id'] or analysis['source']!=run['source'] or analysis.get('model_sha256')!=row['model_sha256']:raise RuntimeError('Evolution labels differ from retained model identity')
    result.update(analysis_path=analysis_path.relative_to(ROOT).as_posix(),analysis_sha256=digest(analysis_path),
        gate0_ok=analysis.get('Gate0',{}).get('ok',row.get('gate0_ok')),object_faults=analysis.get('object_faults'),runtime_setup_error=analysis.get('runtime_setup_error'))
    try:
        complete,reason=label_completeness(analysis,read(model),read(trace))
        result.update(independent_comparable=complete,independent_label_missing_reason=reason)
        if complete:result['projection']=independent_projection(analysis)
    except Exception as exc:result.update(independent_comparable=False,independent_label_missing_reason='independent_projection_unavailable:'+type(exc).__name__)
    try:
        contract=load_project_contract(project)
        result.update(loader_status='admitted',full_contract_fingerprint=contract_runtime_fingerprint(contract),
            routing_fingerprint=contract_commit_fingerprint(contract,'slice',project_dir=project))
    except Exception as exc:result.update(loader_status='rejected',loader_error=getattr(exc,'code',type(exc).__name__),full_contract_fingerprint=None,routing_fingerprint=None)
    result['runtime_adoption_eligible']=result['loader_status']=='admitted' and result['gate0_ok'] is True and result.get('runtime_setup_error') is None
    return result

def authoring_pins(pair,plan,indexed,phase_status):
    family=pair['pair_family']
    if family not in ('ownership_authoring_repair','scripted_zone_rename'):return []
    phase='ownership_repair' if family=='ownership_authoring_repair' else 'zone_rename'
    folder=ROOT/'results/raw/wp5_extension'/phase/pair['after_case_id'];pins=[]
    before_row=indexed[pair['before_case_id']];after_row=indexed[pair['after_case_id']]
    original=verify_inventory_row(before_row);after_run=verify_inventory_row(after_row)
    def bind(name,expected_value,authority):
        path=folder/name
        expected_bytes=(json.dumps(expected_value,ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode('utf-8')
        if not path.exists() or path.read_bytes()!=expected_bytes:raise RuntimeError('Registered authoring artifact changed: '+name)
        if after_run and path.relative_to(ROOT).as_posix() in after_run['artifact_sha256']:
            checked(path.relative_to(ROOT).as_posix(),after_run['artifact_sha256'][path.relative_to(ROOT).as_posix()])
        pins.append({**pin(path),'authority':authority})
    if family=='ownership_authoring_repair':
        marker=phase_status[phase]['terminal_record'];terminal=read(checked(marker['path'],marker['sha256']))
        candidate=next(c for c in plan['targeted_repair_candidates'] if c['case_id']==pair['before_case_id'])
        records=[r for r in terminal['results'] if r['candidate']==candidate]
        if not records:
            if (folder/'repair_result.json').exists() or any(folder.rglob('*')):raise RuntimeError('Unregistered authoring files after budget stop')
            if not any(r.get('budget_stop') for r in terminal['results']):raise RuntimeError('Missing registered repair terminal record')
            return [{**marker,'authority':'registered phase budget stop; no authoring attempt or native endpoint fabricated'}]
        if len(records)!=1:raise RuntimeError('Duplicate registered repair terminal identity')
        result=records[0];bind('repair_result.json',result,'retained ownership-repair phase terminal record')
        candidate_path=checked(candidate['candidate_path'],candidate['candidate_sha256'])
        checked(candidate['run_result_path'],candidate['run_result_sha256'])
        bind('before/agent_roles.generated.json',read(candidate_path),'preregistered original candidate SHA256; JSON serialization only')
        bind('before/validation.json',result['before_report'],'retained repair-result before_report')
        after_roles=folder/'after/agent_roles.generated.json'
        if after_roles.exists():
            from repro.llm import Gateway,API_BASE,sha256
            request=read(folder/'request.json');response=read(folder/'response.json')
            if request['model']!=candidate['source']['model'] or request['max_output_tokens']!=plan['ownership_repair']['output_cap']:raise RuntimeError('Repair request differs from registered model/cap')
            prompt=plan['ownership_repair']['prompt_path']
            if request['instructions']!=checked(prompt,plan['prompt_sha256'][prompt]).read_text(encoding='utf-8'):raise RuntimeError('Repair request prompt differs')
            payload=json.loads(request['input'])
            if payload['candidate']!=read(candidate_path) or payload['validation']!=result['before_report']:raise RuntimeError('Repair request source candidate changed')
            gateway=Gateway(ROOT,replay=True)
            identity={'experiment_id':'WP5.extension.ownership_repair','item_id':candidate['source']['scene_id'],'repetition_id':pair['after_case_id'],'share':'WP5'}
            cached=gateway.responses(request,**identity)
            if cached!=response:raise RuntimeError('Retained repair response differs from registered gateway cache')
            text='\n'.join(c['text'] for o in cached.get('output',[]) if o.get('type')=='message' for c in o.get('content',[]) if c.get('type')=='output_text')
            bind('after/agent_roles.generated.json',json.loads(text),'registered offline Gateway response with exact experiment/source/repair identity')
            envelope={'version':1,'endpoint':API_BASE+'/responses',**identity,'payload':gateway.prepare(request)}
            cache=gateway.cache/(sha256(envelope)+'.json')
            bind('request.json',request,'canonical registered cached request')
            bind('response.json',cached,'canonical registered cached response')
            pins.append({**pin(cache),'authority':'strict cache envelope and response hashes'})
        if 'after_report' in result:
            if not after_roles.exists():raise RuntimeError('Registered repaired candidate is missing')
            bind('after/validation.json',result['after_report'],'retained repair-result after_report')
        elif (folder/'after/validation.json').exists():raise RuntimeError('Unregistered authoring after report')
    else:
        final=folder/'edit_result.json'
        result=read(final)
        if result['before_case_id']!=pair['before_case_id'] or result['source_run_sha256']!=before_row['run_result_sha256'] or result.get('generation_calls')!=0 or result.get('arm')!='scripted_zone_rename':raise RuntimeError('Zone edit source record changed')
        if result['status']=='not_executed':
            if after_run or (folder/'before').exists() or (folder/'after').exists():raise RuntimeError('Unexpected authored endpoint after omitted zone edit')
            pins.append({**pin(final),'authority':'registered failed preselected baseline; no replacement'})
            return pins
        if not after_run:raise RuntimeError('Executed zone edit lacks its retained run')
        source_path=ROOT/original['case_dir']/'intermediate/scene_semantics.json'
        source=read(checked(source_path.relative_to(ROOT).as_posix(),original['artifact_sha256'][source_path.relative_to(ROOT).as_posix()]))
        bind('before/scene_semantics.json',source,'original retained authoring input pin')
        import copy
        expected=copy.deepcopy(source);zone=min(expected['semantic_zones'],key=lambda z:z['zone_id']);old_name=zone['name'];zone['name']+=' (renamed)'
        bind('after/scene_semantics.json',expected,'registered deterministic zone-label-only transformation')
        if result['zone_id']!=zone['zone_id'] or result['old_name']!=old_name or result['new_name']!=zone['name'] or result['after_case_id']!=pair['after_case_id'] or result['status']!=after_run['status']:raise RuntimeError('Zone edit metadata differs from retained source transformation')
        pins.append({**pin(final),'authority':'verified original-run pin and exact deterministic edit'})
    return pins

def analyze(plan,inventory,raw_drift,analysis_dirs):
    if not inventory.get('all_registered_identities_terminal'):raise RuntimeError('All project identities must be explicitly terminal')
    indexed={r['case_id']:r for r in inventory['rows']}
    if len(indexed)!=len(inventory['rows']):raise RuntimeError('Duplicate registered project identities')
    for row in indexed.values():verify_inventory_row(row)
    expected=registered_pairs(plan);drift=[p for p in expected if p['pair_family']=='fresh_regeneration']
    if [(p['before_case_id'],p['after_case_id']) for p in raw_drift['pairs']]!=[(p['before_case_id'],p['after_case_id']) for p in drift]:raise RuntimeError('Drift pair registry changed')
    if len(raw_drift['runs'])!=120 or [r['case_id'] for r in raw_drift['runs']]!=[r['case_id'] for r in plan['fresh_drift_runs']]:raise RuntimeError('Drift run identity set or order incomplete')
    for run in raw_drift['runs']:
        row=indexed[run['case_id']]
        if run['run_result_sha256']!=row['run_result_sha256'] or run.get('model_file_sha256')!=row.get('model_file_sha256'):raise RuntimeError('Drift evidence differs from exhaustive inventory')
        if run.get('analysis_path'):checked(run['analysis_path'],run['analysis_sha256'])
    cached={r['case_id']:r for r in raw_drift['runs']};pairs=[]
    for registered in expected:
        before_id=registered['before_case_id'];after_id=registered['after_case_id']
        for cid in (before_id,after_id):
            if cid not in cached:cached[cid]=endpoint(indexed[cid],analysis_dirs)
        before,after=cached[before_id],cached[after_id]
        row={**registered,**compare_run_pair(before,after),'authoring_artifacts':authoring_pins(registered,plan,indexed,inventory.get('phase_status',{}))}
        for side,cid in (('before',before_id),('after',after_id)):
            item=indexed[cid]
            for key in ('project_path','run_result_path','run_result_sha256','terminal_record_path','terminal_record_sha256','model_file_sha256','model_sha256','terminal_status'):
                row[side+'_'+key]=item.get(key)
        row.setdefault('routing_table_consensus_defined',False);row.setdefault('routing_table_changed',None)
        row.setdefault('gate0_status_changed',None);row.setdefault('loader_status_changed',None)
        pairs.append(row)
    return {'schema':'wp5-all-evolution-pairs-v1','registered_pairs':len(pairs),'pairs':pairs,'endpoints':[cached[k] for k in sorted(cached)],
        'denominators':{family:{'registered':sum(p['pair_family']==family for p in pairs),
            'materialized':sum(p['pair_family']==family and p['materialized_pair'] for p in pairs),
            'independently_comparable':sum(p['pair_family']==family and p['independent_comparable_pair'] for p in pairs),
            'consensus_routing_table_defined':sum(p['pair_family']==family and p['routing_table_consensus_defined'] for p in pairs)} for family in dict.fromkeys(p['pair_family'] for p in pairs)},
        'limits':'Fixed103 pairs:96 fresh adjacent regenerations,3 source edits,1 scripted zone rename,3 authoring repairs. No gap bridging. Missing native models remain missing. Raw action-ID tables include mechanical case namespaces; no semantic-equivalence claim. Gate0/loader faults never suppress native endpoints.'}

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--protocol',type=Path,required=True);args=parser.parse_args()
    path=args.protocol.resolve();side=path.with_suffix('.sha256')
    if not side.exists() or side.read_text(encoding='ascii').split()[0]!=digest(path):raise RuntimeError('Evolution protocol is not frozen')
    protocol=read(path)
    if protocol.get('status')!='FROZEN':raise RuntimeError('Evolution protocol is not authorized')
    for relative,expected in protocol['implementation_sha256'].items():checked(relative,expected)
    plan_path=checked(protocol['extension_plan_path'],protocol['extension_plan_sha256']);plan=read(plan_path)
    manifest=ROOT/protocol['all_projects_path'];inventory=read(manifest)
    if inventory['extension_plan']['sha256']!=digest(plan_path):raise RuntimeError('Inventory plan differs')
    raw_path=ROOT/protocol['raw_drift_summary_path'];raw=read(raw_path)
    if raw['plan_sha256']!=digest(plan_path) or raw['analysis_sha256']!=protocol['implementation_sha256']['experiments/wp5_extension_drift.py']:raise RuntimeError('Drift protocol differs')
    result=analyze(plan,inventory,raw,protocol['analysis_directories'])
    result.update(protocol=pin(path),extension_plan=pin(plan_path),all_projects=pin(manifest),raw_drift_summary=pin(raw_path),analysis_sha256=digest(Path(__file__)))
    output=(ROOT/protocol['output_directory']).resolve()
    if not output.is_relative_to(ROOT.resolve()):raise RuntimeError('Evolution output escapes workspace')
    output.mkdir(parents=True,exist_ok=True)
    for name,content in [('summary.json',json.dumps(result,sort_keys=True,indent=2)+'\n'),('evolution_pairs.jsonl',''.join(json.dumps(r,sort_keys=True)+'\n' for r in result['pairs']))]:
        target=output/name
        if target.exists() and target.read_text(encoding='utf-8-sig')!=content:raise RuntimeError('Preserve prior evolution evidence; choose a versioned output')
        target.write_text(content,encoding='utf-8',newline='\n')
    print(json.dumps({'registered_pairs':result['registered_pairs'],'denominators':result['denominators']}))
if __name__=='__main__':main()

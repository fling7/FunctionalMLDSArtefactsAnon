"""Fresh-regeneration drift, including materialized routing faults and explicit gaps.

Consumes retained I1/I2 labels, never generation. Native materialization,
independent-label comparability and runtime adoption are separate properties.
"""
from __future__ import annotations
import argparse,hashlib,json
from pathlib import Path
from experiments.wp5_extension import ROOT,PLAN_PATH,read,digest,load_plan,write_once
from experiments.natural_faults import clustered_interval
from tools.routing_verifier import NativeRoutingIndex
from backend.roomcontract_v2_runtime import load_project_contract
from backend.runtime_trace import contract_runtime_fingerprint,contract_commit_fingerprint

def canonical_hash(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
def independent_projection(analysis):
    target_source=analysis.get('Gate0',{}).get('objects',{});owners={sid:set() for sid in target_source.values()};slices={sid:{} for sid in target_source.values()};disagreements=0;provider_conflicts=set();nonconsensus_targets=set()
    for probe in analysis.get('probes',[]):
        sid=target_source[probe['target']];a=probe['verdicts']['I1'];b=probe['verdicts']['I2']
        if a!=b:disagreements+=1;nonconsensus_targets.add(sid)
        if a.get('provider')!=b.get('provider'):provider_conflicts.add(sid)
        if a.get('provider') is not None:owners[sid].add(a['provider'])
        slices[sid][probe['start_agent']]={k:a.get(k) for k in ('decision','reason','provider','action')}
    return {'owners':{sid:next(iter(values)) if len(values)==1 and sid not in provider_conflicts else None for sid,values in owners.items()},
        'query_slice_sha256':{sid:canonical_hash(value) if sid not in nonconsensus_targets else None for sid,value in slices.items()},
        'routing_table_sha256':canonical_hash(slices) if not nonconsensus_targets else None,'independent_disagreements':disagreements,
        'nonconsensus_query_source_objects':sorted(nonconsensus_targets),
        'provider_conflict_objects':sorted(provider_conflicts)}
def partition(owners,matched):
    groups={}
    for sid in matched:
        owner=owners[sid]
        if owner is not None:groups.setdefault(owner,set()).add(sid)
    return sorted(sorted(x) for x in groups.values())
def compare_projections(before,after):
    matched=sorted(set(before['owners'])&set(after['owners']))
    defined=[sid for sid in matched if before['owners'][sid] is not None and after['owners'][sid] is not None]
    changed=[sid for sid in defined if before['owners'][sid]!=after['owners'][sid]]
    query_defined=[sid for sid in matched if before['query_slice_sha256'].get(sid) is not None and after['query_slice_sha256'].get(sid) is not None]
    query_changed=[sid for sid in query_defined if before['query_slice_sha256'][sid]!=after['query_slice_sha256'][sid]]
    table_defined=before['routing_table_sha256'] is not None and after['routing_table_sha256'] is not None
    return {'matched_source_objects':len(matched),'defined_provider_pairs':len(defined),'undefined_provider_pairs':len(matched)-len(defined),
        'provider_id_changed_objects':changed,'provider_id_change_fraction':len(changed)/len(defined) if defined else None,
        'same_ownership_partition_up_to_provider_renaming':partition(before['owners'],defined)==partition(after['owners'],defined),
        'provider_renaming_only_candidate':bool(changed) and partition(before['owners'],defined)==partition(after['owners'],defined),
        'semantic_caveat':'Equal partitions with changed provider ids indicate possible renaming; semantic role equivalence is not asserted.',
        'query_slice_changed_objects':query_changed,'defined_query_slice_pairs':len(query_defined),'undefined_query_slice_pairs':len(matched)-len(query_defined),
        'query_slice_change_fraction':len(query_changed)/len(query_defined) if query_defined else None,
        'routing_table_consensus_defined':table_defined,'routing_table_changed':(before['routing_table_sha256']!=after['routing_table_sha256']) if table_defined else None,
        'independent_disagreements':before['independent_disagreements']+after['independent_disagreements']}
def label_completeness(analysis,instance,trace):
    try:
        index=NativeRoutingIndex(instance,trace)
        expected={(index.wire[a],o) for a in index.agents for o in index.objects}
    except Exception as exc:return False,'native_index_unavailable:'+type(exc).__name__
    probes=analysis.get('probes',[]);actual=[(p.get('start_agent'),p.get('target')) for p in probes]
    if len(actual)!=len(expected) or set(actual)!=expected:return False,'missing_or_duplicate_agent_object_records'
    for probe in probes:
        for name in ('I1','I2'):
            label=probe.get('verdicts',{}).get(name,{})
            if set(('decision','reason','provider','action'))-set(label) or label.get('decision') in ('HARNESS_ERROR','NOT_RUN'):return False,'missing_or_failed_'+name+'_label'
    return True,None

def load_run(selection,analysis_root):
    path=ROOT/'results/raw/wp5_extension/drift'/selection['case_id']/'run_result.json'
    row={'case_id':selection['case_id'],'registered':selection,'terminal':path.exists(),'materialized':False,
         'independent_comparable':False,'independent_label_missing_reason':'no_native_model','runtime_adoption_eligible':False,
         'gate0_ok':None,'loader_status':'not_attempted','object_faults':None}
    if not path.exists():row['status']='missing';return row
    run=read(path)
    if run['plan_sha256']!=digest(PLAN_PATH) or run['case_id']!=selection['case_id'] or any(run['source'].get(k)!=selection[v] for k,v in (('scene_id','source_id'),('model','model'),('repetition','repetition'))):raise RuntimeError('Drift run differs from frozen identity')
    row.update(status=run['status'],pipeline_success=run['status']=='success',terminal_status=run.get('terminal_status'),project_path=run.get('project_dir'),
        run_result_path=path.relative_to(ROOT).as_posix(),run_result_sha256=digest(path),source_sha256=run['source']['source_sha256'])
    model=ROOT/run['project_dir']/'roomcontract.v2.instance.json' if run.get('project_dir') else None
    if model is None or not model.exists():return row
    if run['artifact_sha256'].get(model.relative_to(ROOT).as_posix())!=digest(model):raise RuntimeError('Native drift model changed')
    row.update(materialized=True,model_file_sha256=digest(model),model_sha256=hashlib.sha256(model.read_bytes().replace(b'\r\n',b'\n')).hexdigest().upper(),independent_label_missing_reason='analysis_missing')
    gate_path=path.parent/'routing_verifier.json';gate=read(gate_path) if gate_path.exists() else {}
    row['gate0_ok']=gate.get('ok')
    analysis_path=analysis_root/'rooms'/(selection['case_id']+'.json')
    if analysis_path.exists():
        analysis=read(analysis_path)
        if analysis['room']!=run['case_id'] or analysis['source']!=run['source'] or analysis.get('model_sha256')!=row['model_sha256']:raise RuntimeError('Independent analysis does not match retained run')
        try:complete,reason=label_completeness(analysis,read(model),read(model.parent/'trace_map.v2.json'))
        except Exception as exc:complete,reason=False,'native_or_trace_parse_error:'+type(exc).__name__
        row.update(analysis_path=analysis_path.relative_to(ROOT).as_posix(),analysis_sha256=digest(analysis_path),independent_comparable=complete,
            independent_label_missing_reason=reason,gate0_ok=analysis.get('Gate0',{}).get('ok',row['gate0_ok']),object_faults=analysis.get('object_faults'),
            runtime_setup_error=analysis.get('runtime_setup_error'))
        if complete:row['projection']=independent_projection(analysis)
    try:
        contract=load_project_contract(ROOT/run['project_dir'])
        row.update(loader_status='admitted',full_contract_fingerprint=contract_runtime_fingerprint(contract),routing_fingerprint=contract_commit_fingerprint(contract,'slice',project_dir=ROOT/run['project_dir']))
    except Exception as exc:row.update(loader_status='rejected',loader_error=getattr(exc,'code',type(exc).__name__),full_contract_fingerprint=None,routing_fingerprint=None)
    row['runtime_adoption_eligible']=row['loader_status']=='admitted' and row['gate0_ok'] is True and row.get('runtime_setup_error') is None
    return row

def compare_run_pair(before,after):
    materialized=before['materialized'] and after['materialized']
    comparable=materialized and before['independent_comparable'] and after['independent_comparable']
    row={'materialized_pair':materialized,'independent_comparable_pair':comparable,
        'runtime_adoption_pair':before['runtime_adoption_eligible'] and after['runtime_adoption_eligible'],
        'before_gate0_ok':before['gate0_ok'],'after_gate0_ok':after['gate0_ok'],
        'before_loader_status':before['loader_status'],'after_loader_status':after['loader_status'],
        'before_object_faults':before['object_faults'],'after_object_faults':after['object_faults'],
        'before_missing_independent_reason':before['independent_label_missing_reason'],'after_missing_independent_reason':after['independent_label_missing_reason']}
    if materialized:
        row.update(gate0_transition_known=before['gate0_ok'] is not None and after['gate0_ok'] is not None,object_fault_transition_known=before['object_faults'] is not None and after['object_faults'] is not None,
            gate0_status_changed=(before['gate0_ok']!=after['gate0_ok']) if before['gate0_ok'] is not None and after['gate0_ok'] is not None else None,loader_status_changed=before['loader_status']!=after['loader_status'],
            object_fault_status_changed=(before['object_faults']!=after['object_faults']) if before['object_faults'] is not None and after['object_faults'] is not None else None,
            before_model_file_sha256=before['model_file_sha256'],after_model_file_sha256=after['model_file_sha256'],
            before_model_sha256=before['model_sha256'],after_model_sha256=after['model_sha256'],
            model_byte_digest_changed=before['model_file_sha256']!=after['model_file_sha256'],
            routing_fingerprint_changed=(before.get('routing_fingerprint')!=after.get('routing_fingerprint')) if before.get('routing_fingerprint') and after.get('routing_fingerprint') else None,
            full_contract_fingerprint_changed=(before.get('full_contract_fingerprint')!=after.get('full_contract_fingerprint')) if before.get('full_contract_fingerprint') and after.get('full_contract_fingerprint') else None)
    if comparable:row.update(compare_projections(before['projection'],after['projection']))
    return row

def analyze(plan,analysis_root,output):
    output=Path(output).resolve();analysis_root=Path(analysis_root).resolve()
    runs=[load_run(row,analysis_root) for row in plan['fresh_drift_runs']]
    if not all(r['terminal'] for r in runs):raise RuntimeError('Every registered drift identity must be explicitly terminal')
    lookup={(r['registered']['source_id'],r['registered']['model'],r['registered']['repetition']):r for r in runs};pairs=[]
    for source in plan['new_deterministic_sources']:
        for model in plan['models']:
            for repetition in range(1,5):
                before=lookup[(source['source_id'],model,repetition)];after=lookup[(source['source_id'],model,repetition+1)]
                row={'source':{'scene_id':source['source_id'],'model':model},'before_case_id':before['case_id'],'after_case_id':after['case_id'],
                    'before_repetition':repetition,'after_repetition':repetition+1,'before_status':before['status'],'after_status':after['status'],
                    'before_project_path':before.get('project_path'),'after_project_path':after.get('project_path'),
                    'before_run_result_sha256':before['run_result_sha256'],'after_run_result_sha256':after['run_result_sha256'],
                    'source_sha256':source['sha256'],'selection':'fixed adjacent fresh repetitions; no bridging failed runs'}
                row.update(compare_run_pair(before,after));pairs.append(row)
    summaries={}
    for model in plan['models']:
        all_pairs=[r for r in pairs if r['source']['model']==model];selected=[r for r in all_pairs if r['independent_comparable_pair']]
        materialized=[r for r in all_pairs if r['materialized_pair']]
        summaries[model]={'registered_sources':12,'registered_runs':60,'registered_adjacent_pairs':48,
            'materialized_pairs':len(materialized),'independently_comparable_pairs':len(selected),'comparable_source_clusters':len({r['source']['scene_id'] for r in selected}),
            'provider_id_change_fraction':clustered_interval(selected,lambda r:r['provider_id_change_fraction']),
            'routing_table_change_rate':clustered_interval(selected,lambda r:float(r['routing_table_changed']) if r['routing_table_consensus_defined'] else None),
            'defined_routing_table_pairs':sum(r['routing_table_consensus_defined'] for r in selected),'undefined_routing_table_pairs':sum(not r['routing_table_consensus_defined'] for r in selected),
            'query_slice_change_fraction':clustered_interval(selected,lambda r:r['query_slice_change_fraction']),
            'defined_query_slice_pairs':sum(r['defined_query_slice_pairs'] for r in selected),'undefined_query_slice_pairs':sum(r['undefined_query_slice_pairs'] for r in selected),
            'gate0_transition_pairs':sum(r['gate0_status_changed'] is True for r in materialized),
            'loader_transition_pairs':sum(r['loader_status_changed'] for r in materialized),'object_fault_transition_pairs':sum(r['object_fault_status_changed'] is True for r in materialized),
            'unknown_gate0_transition_pairs':sum(not r['gate0_transition_known'] for r in materialized),'unknown_object_fault_transition_pairs':sum(not r['object_fault_transition_known'] for r in materialized),
            'possible_provider_renaming_pairs':sum(r['provider_renaming_only_candidate'] for r in selected)}
    report={'schema':'wp5-extension-drift-v1','plan_sha256':digest(PLAN_PATH),'analysis_sha256':digest(Path(__file__)),
        'registered_runs':120,'registered_sources':12,'models':plan['models'],'fresh_repetitions_per_source_model':5,
        'completed_attempts':sum(r['terminal_status']!='unexecuted_budget_stop' for r in runs),'successful_runs':sum(r['status']=='success' for r in runs),
        'unexecuted_budget_stop':sum(r['terminal_status']=='unexecuted_budget_stop' for r in runs),
        'materialized_runs':sum(r['materialized'] for r in runs),'independently_comparable_runs':sum(r['independent_comparable'] for r in runs),
        'runtime_adoption_eligible_runs':sum(r['runtime_adoption_eligible'] for r in runs),'registered_adjacent_pairs':96,
        'materialized_adjacent_pairs':sum(r['materialized_pair'] for r in pairs),'independently_comparable_adjacent_pairs':sum(r['independent_comparable_pair'] for r in pairs),
        'source_cluster_summaries':summaries,'runs':runs,'pairs':pairs,
        'status':'COMPLETE' if all(r['terminal_status']!='unexecuted_budget_stop' for r in runs) else 'PARTIAL',
        'limits':'Gate0 or loader faults do not exclude materialized pairs or complete independent labels. Undefined/conflicting providers are object-level denominators. Fresh drift excludes initial baselines and other arms; no failed identity is replaced.'}
    write_once(output/'drift_summary.json',report)
    path=output/'evolution_pairs.jsonl';content=''.join(json.dumps(r,sort_keys=True,ensure_ascii=False)+'\n' for r in pairs)
    if path.exists() and path.read_text(encoding='utf-8')!=content:raise RuntimeError('Preserve prior evolution-pair evidence')
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text(content,encoding='utf-8',newline='\n');return report
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--analysis-root',type=Path,required=True);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    report=analyze(load_plan(replay=True),args.analysis_root,args.output);print(json.dumps({k:v for k,v in report.items() if k not in ('runs','pairs','source_cluster_summaries')}))

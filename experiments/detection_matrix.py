"""All-mutant detection matrix with explicit applicability and setup refusals.

Independent implementations are imported solely through their public evaluate
interfaces. The real backend uses the labelled ScriptedClient for admission tests;
these are deterministic fault tests, never real-LLM outcome evidence.
"""
from __future__ import annotations
import argparse
import copy
import csv
import hashlib
import importlib
import itertools
import json
import math
import os
from pathlib import Path
import shutil
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from experiments.mutations import Bundle, OPERATORS, DESCRIPTIONS, SEED, digest, encoded, mutation_plan, natural_diff_plan, refresh_projections
from tools.routing_verifier import verify_routing, lookup_route

FAULT_REASONS={'E_UNOWNED','E_AMBIGUOUS_OWNER','E_NO_DECLARED_ACTION','E_ACTION_AMBIGUOUS'}
VARIANTS={'runtime':{},'firstmatch':{'routing_mode':'firstmatch'},'reach_only':{'routing_mode':'reach_only'},'table':{'routing_mode':'table'},'no_digest':{'digest_check':False}}


def write_new(path,value):
    path=Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('xb') as stream: stream.write(encoded(value))


def _result(check):
    begin=time.perf_counter_ns()
    try:
        value=check()
        if isinstance(value,list): return {'status':'reject' if value else 'pass','issues':value,'elapsed_ms':(time.perf_counter_ns()-begin)/1e6}
        if isinstance(value,dict):
            ok=value.get('ok',value.get('status')=='valid')
            return {'status':'pass' if ok else 'reject','report':value,'elapsed_ms':(time.perf_counter_ns()-begin)/1e6}
        return {'status':'pass','elapsed_ms':(time.perf_counter_ns()-begin)/1e6}
    except Exception as exc:
        return {'status':'reject','exception':type(exc).__name__,'reason':getattr(exc,'code',None),'message':str(exc),'elapsed_ms':(time.perf_counter_ns()-begin)/1e6}


def legacy_validation_view(instance):
    """Explicit view of fields read by roomcontract_invariants; not an exporter."""
    by={o['id']:o for o in instance['objects']}
    typed=lambda name:[o for o in by.values() if o.get('type')==name]
    refs=lambda obj,key:obj.get(key,[]) if isinstance(obj.get(key,[]),list) else []
    use_cases=[]
    for use_case in typed('UseCase'):
        scenarios=[]
        scenario_ids=[sid for spec in typed('UseCaseScenarioSpecification') if use_case['id'] in refs(spec,'useCase') for sid in refs(spec,'scenario')]
        for sid in scenario_ids:
            sc=by.get(sid,{})
            steps=[]
            for stid in refs(sc,'step'):
                step=by.get(stid,{})
                value={'id':stid,'kind':step.get('kind'),'capabilityUseIds':refs(step,'capabilityUse')}
                # Preserve forbidden shortcuts if an externally supplied diff introduces one.
                for key in ['runtimeActionId','runtimeActionIds','runtimeAction','runtimeActions','runtime_action_id','runtime_action_ids','runtime_action','runtime_actions']:
                    if key in step: value[key]=copy.deepcopy(step[key])
                steps.append(value)
            scenarios.append({'id':sid,'kind':sc.get('kind'),'steps':steps})
        use_cases.append({'id':use_case['id'],'scenarios':scenarios})
    caps=[{'id':c['id'],'effects':[copy.deepcopy(by.get(e,{'id':e})) for e in refs(c,'effect') if e in by]} for c in typed('Capability')]
    uses=[]
    for use in typed('CapabilityUse'):
        row={'id':use['id'],'capability_id':(refs(use,'typeRef') or [None])[0]}
        if len(refs(use,'typeRef'))>1: row['capability_ids']=refs(use,'typeRef')
        uses.append(row)
    bindings=[]
    for binding in typed('RuntimeBinding'):
        actions=[]
        for aid in refs(binding,'runtimeAction'):
            if aid not in by: continue
            action=by[aid]
            locator=by.get((refs(action,'locator') or [''])[0],{})
            actions.append({'id':aid,'endpoint':locator.get('value') if locator.get('kind')=='endpoint' else None})
        bindings.append({'id':binding['id'],'capability_id':(refs(binding,'capability') or [None])[0],'runtimeActions':actions})
    validations=[{'id':v['id'],'expectedOutcome':[],'runtime_binding_ids':[x for x in refs(v,'vvSubject') if by.get(x,{}).get('type')=='RuntimeBinding']} for v in typed('ValidationCase')]
    # RuntimeBindings are also exposed through each VVTarget.
    for value,native in zip(validations,typed('ValidationCase')):
        value['runtime_binding_ids']=list(dict.fromkeys(value['runtime_binding_ids']+[b for t in refs(native,'vvTarget') for b in refs(by.get(t,{}),'runtimeBinding')]))
    return {'validation_view':'native fields consumed by the packet legacy invariant checker; not a lossless v0.5 projection','requirementsModel':{'useCases':use_cases},'capabilities':caps,'capabilityUses':uses,'runtimeBindings':bindings,'stateAssertions':[{'id':s['id']} for s in typed('StateAssertion')],'validationCases':validations}


def role_view(bundle):
    by={o['id']:o for o in bundle.instance['objects']}
    agents=[]
    for obj in by.values():
        if obj.get('type')!='Agent': continue
        agents.append({'id':obj.get('sourceAgentId'),'grounded_object_ids':[by.get(t,{}).get('sourceId',t) for t in obj.get('groundedAsset',[])],'grounded_object_groups':[by.get(t,{}).get('sourceGroup',by.get(t,{}).get('sourceId',t)) for t in obj.get('groundedObjectGroup',[])],'responsible_zone_ids':[by.get(t,{}).get('sourceId',t) for t in obj.get('responsibleZone',[])],'handoff_targets':[by.get(t,{}).get('sourceAgentId',t) for t in obj.get('handoffTarget',[])],'knowledge_tags':obj.get('knowledgeTag',[])})
    return {'agents':agents}


def validators(bundle):
    from tools.dynamic_functional_rdl_v2_model import MODEL
    from tools.validate_dynamic_functional_rdl_v2 import validate_instance
    from tools.case_study_pipeline.validators.schema_validator import _validate_payload, _validate_trace_variant
    from tools.case_study_pipeline.roomcontract_v2_assembler import validate_roomcontract_v2_instance
    from tools.case_study_pipeline.validators.roomcontract_invariants import validate_roomcontract_invariants
    from tools.case_study_pipeline.validators.handoff_metrics import compute_handoff_metrics
    from experiments.lib.backend_driver import BACKEND
    from backend.roomcontract_v2_runtime import _validate_v2_instance,_validate_v2_trace
    instance=bundle.instance
    table=verify_routing(instance,bundle.trace,model_sha256=digest(instance),project=bundle.project,model_bytes=encoded(instance))
    result={
        'Va_structural':_result(lambda:validate_instance(MODEL,instance,'WP6 mutant').to_dict()),
        'Vb_native_schema':_result(lambda:_validate_payload(artifact_id='native_mutant',schema_name='dynamic_functional_rdl_v2_instance.schema.json',payload=instance)),
        'Vb_native_domain':_result(lambda:validate_roomcontract_v2_instance(instance)),
        'Vb_trace_schema':_result(lambda:_validate_trace_variant(artifact_id='trace_mutant',definition_name='traceMapV2',payload=bundle.trace)),
        'Vb_legacy_invariants_view':_result(lambda:validate_roomcontract_invariants(legacy_validation_view(instance))),
        'Vc_instance':_result(lambda:_validate_v2_instance(instance)),
        'Vc_trace':_result(lambda:_validate_v2_trace(bundle.trace,{o['id']:o for o in instance['objects']},digest(instance),instance)),
        'Gate0':{'status':'pass' if table['ok'] else 'reject','issues':table['issues'],'checks':table['checks']},
    }
    # The loader instance validator returns its index, which is not a validation report.
    if 'report' in result['Vc_instance']:
        result['Vc_instance'].pop('report')
        result['Vc_instance']['status']='pass'
    legacy=result['Vb_legacy_invariants_view'].get('report',{})
    if legacy.get('metrics',{}).get('checked_element_count',0)==0:
        result['Vb_legacy_invariants_view']['status']='not_applicable'
        result['Vb_legacy_invariants_view']['reason']='No checked elements; no vacuous pass is credited.'
    roles=role_view(bundle)
    matrix={'handoffs':[{'source_agent_id':a['id'],'target_agent_id':b,'condition':'Synthetic projection of the native edge.','reason':'Declared native handoff.'} for a in roles['agents'] for b in a['handoff_targets']]}
    result['Vb_handoff_metrics']=_result(lambda:compute_handoff_metrics(agent_roles=roles,handoff_matrix=matrix,runtime_events=[],test_results=[],active_model_sha256=digest(instance)))
    result['Vb_handoff_metrics']['scope']='Native role/edge projection; no runtime-event accuracy measurement.'
    result['Vb_placement_metrics']={'status':'not_applicable','reason':'The mutation unit has no original placement authoring artifact; deployed positions alone do not reconstruct placement intentions.'}
    result['Vb_traceability_metrics']={'status':'not_applicable','reason':'Native mutation lacks original knowledge-generation/runtime-event artifacts required for the legacy coverage metric.'}
    return result,table


def request_for(agent,target,model_digest):
    return {'session_id':'regression','active_agent_id':agent,'user_text':'Describe this object.','interaction_mode':'deictic','spatial_context':{'model_sha256':model_digest,'state':'resolved','entity_id':target['id'],'source_object_id':target['sourceId'],'hit_position':{'x':0,'y':0,'z':0},'distance_m':1,'selection_modality':'programmatic'}}


def verdict(value): return {k:value.get(k) for k in ('decision','reason','provider','action')}


def independent_call(evaluator,instance,trace,request,session):
    try: return evaluator(instance,trace,request,session)
    except Exception as exc:
        return {'decision':None,'reason':None,'provider':None,'action':None,'evaluation_error':{'exception':type(exc).__name__,'message':str(exc)}}



def evaluate_one(job):
    """One worker owns one mutant and every pair/checker for it."""
    project=Path(job['project'])
    output=Path(job['output'])
    metadata=job['metadata']
    bundle=Bundle.load(project)
    outcomes,table=validators(bundle)
    from experiments.lib.backend_driver import Driver
    from backend.guard_config import GuardConfig
    i1=importlib.import_module('verification.impl_a.reference').evaluate
    i2=importlib.import_module('verification.impl_b.policy_adapter').evaluate
    session={'model_sha256':digest(bundle.instance),'active_agent_mode':'client'}
    agents=[o['sourceAgentId'] for o in bundle.instance['objects'] if o.get('type')=='Agent']
    targets=[o for o in bundle.instance['objects'] if o.get('entityRole')=='sceneObject']
    driver=None
    try:
        driver=Driver(project)
        outcomes['backend_setup']={'status':'pass'}
    except Exception as exc:
        outcomes['backend_setup']={'status':'reject','reason':getattr(exc,'code',None),'exception':type(exc).__name__,'message':str(exc)}
    rows=[]
    try:
        for start,target in itertools.product(agents,targets):
            req=request_for(start,target,session['model_sha256'])
            row={'start_agent':start,'target':target['id'],'request':req,'I1':independent_call(i1,bundle.instance,bundle.trace,req,session),'I2':independent_call(i2,bundle.instance,bundle.trace,req,session),'Gate0':lookup_route(table,start,target['id']),'variants':{}}
            for name,config in VARIANTS.items():
                if driver is None:
                    row['variants'][name]={'status':'not_run_setup_refused','reason':outcomes['backend_setup'].get('reason')}
                    continue
                driver.store.guard_config=GuardConfig(**config)
                row['variants'][name]=driver.probe(req)
            # Stale-digest ablation is a request mutation, counted separately from model mutants.
            stale=copy.deepcopy(req);stale['spatial_context']['model_sha256']='0'*64
            row['stale_request']={'I1':independent_call(i1,bundle.instance,bundle.trace,stale,session),'I2':independent_call(i2,bundle.instance,bundle.trace,stale,session)}
            for name,config in [('runtime',{}),('no_digest',{'digest_check':False})]:
                if driver is None: row['stale_request'][name]={'status':'not_run_setup_refused'}
                else:
                    driver.store.guard_config=GuardConfig(**config)
                    row['stale_request'][name]=driver.probe(stale)
            rows.append(row)
    finally:
        if driver is not None: driver.close()
    disagreements=[{'start_agent':row['start_agent'],'target':row['target'],'I1':verdict(row['I1']),'I2':verdict(row['I2'])} for row in rows if verdict(row['I1'])!=verdict(row['I2']) or row['I1'].get('evaluation_error') or row['I2'].get('evaluation_error')]
    property_failures=[{'start_agent':r['start_agent'],'target':r['target'],'outcome':r['variants']['runtime']} for r in rows if r['variants']['runtime'].get('decision')=='REJECT' and (r['variants']['runtime'].get('model_calls',0)!=0 or not r['variants']['runtime'].get('unchanged_before_restore',False))]
    outcomes['I3_rejection_atomicity']={'status':'not_applicable' if driver is None else 'reject' if property_failures else 'pass','failures':property_failures,'scope':'Independent of I1/I2 verdicts: rejected normal admission makes zero ScriptedClient calls and leaves the session snapshot unchanged. Random-model Hypothesis G1-G5 coverage is a separate WP2 experiment.'}
    outcomes['runtime_routing_faults']={'status':'not_applicable' if driver is None else 'reject' if any(r['variants']['runtime'].get('reason') in FAULT_REASONS for r in rows) else 'pass'}
    i1_fault=any(row['I1'].get('reason') in FAULT_REASONS for row in rows)
    i2_fault=any(row['I2'].get('reason') in FAULT_REASONS for row in rows)
    unexpected=[r for r in rows if r['I1'].get('reason') not in FAULT_REASONS | {None,'E_NO_HANDOFF_PATH'} or r['I2'].get('reason') not in FAULT_REASONS | {None,'E_NO_HANDOFF_PATH'}]
    groundtruth=None if disagreements or unexpected else i1_fault
    outcomes['I1_reference']={'status':'reject' if i1_fault else 'pass','scope':'Defines ground truth, subject to I2 agreement; perfect agreement is by construction.'}
    outcomes['I2_policy']={'status':'reject' if i2_fault else 'pass'}
    reasons={r['I1'].get('reason') for r in rows}
    fault_classes=([name for name,codes in [('ownership',{'E_UNOWNED','E_AMBIGUOUS_OWNER'}),('action',{'E_NO_DECLARED_ACTION','E_ACTION_AMBIGUOUS'})] if reasons & codes] or ['reachability_only' if 'E_NO_HANDOFF_PATH' in reasons else 'no_fault'])
    result={'metadata':metadata,'model_sha256':digest(bundle.instance),'unit':'mutant model','probe_count':len(rows),'checkers':outcomes,'groundtruth':{'routing_faulty':groundtruth,'I1':i1_fault,'I2':i2_fault,'excluded_reason':'independent verdict disagreement' if disagreements else 'out-of-scope or malformed request/model outcome' if unexpected else None,'fault_classes':fault_classes},'independent_disagreements':disagreements,'probes':rows,'llm_condition':'unit-test ScriptedClient only; no real-LLM result','commit_scope':'Driver.probe tests admission via the real SessionStore, restores its snapshot, and does not exercise the HTTP commit/evidence path.'}
    write_new(output,result)
    return {'id':metadata['id'],'path':str(output),'groundtruth':groundtruth,'pairs':len(rows),'setup':outcomes['backend_setup']['status']}


def wilson(success,total):
    if not total:return None
    z=1.959963984540054
    phat=success/total
    den=1+z*z/total
    center=(phat+z*z/(2*total))/den
    half=z*math.sqrt(phat*(1-phat)/total+z*z/(4*total*total))/den
    return [center-half,center+half]


def aggregate(run_dir):
    run_dir=Path(run_dir)
    records=[json.loads(path.read_text(encoding='utf-8')) for path in sorted((run_dir/'outcomes').glob('*.json'))]
    rows=[]
    checkers=sorted({key for record in records for key in record['checkers'] if not key.startswith('I3_')})
    groups={'all':records}
    for operator in OPERATORS:
        groups[operator]=[r for r in records if r['metadata'].get('operators')==[operator]]
    for room in sorted({r['metadata']['room'] for r in records}):
        groups['room:'+room]=[r for r in records if r['metadata']['room']==room]
        for operator in (*OPERATORS,'natural_diff'):
            groups['room:'+room+'/operator:'+operator]=[r for r in records if r['metadata']['room']==room and r['metadata'].get('operators')==[operator]]
    for kind in ['ownership','action','reachability_only','no_fault']:
        groups['fault_class:'+kind]=[r for r in records if kind in r['groundtruth'].get('fault_classes',[])]
    groups['two_operator']=[r for r in records if len(r['metadata'].get('operators',[]))==2 and r['metadata'].get('status')=='changed']
    for group,data in groups.items():
        for checker in checkers+['Va_Vb_union','authoring_loader_union']:
            counts={k:0 for k in ('tp','fp','fn','tn','excluded_groundtruth','not_applicable')}
            for record in data:
                truth=record['groundtruth']['routing_faulty']
                if truth is None: counts['excluded_groundtruth']+=1;continue
                if checker.endswith('_union'):
                    statuses=[value['status'] for key,value in record['checkers'].items() if key.startswith(('Va_','Vb_') if checker=='Va_Vb_union' else ('Va_','Vb_','Vc_'))]
                    status='reject' if 'reject' in statuses else 'pass' if statuses and all(x=='pass' for x in statuses) else 'not_applicable'
                else: status=record['checkers'].get(checker,{}).get('status','not_applicable')
                if status not in {'pass','reject'}: counts['not_applicable']+=1;continue
                counts['tp' if truth and status=='reject' else 'fn' if truth else 'fp' if status=='reject' else 'tn']+=1
            n=sum(counts[k] for k in ('tp','fp','fn','tn'))
            rows.append({'group':group,'checker':checker,'n_models':n,**counts,'sensitivity_wilson95':wilson(counts['tp'],counts['tp']+counts['fn']),'false_positive_wilson95':wilson(counts['fp'],counts['fp']+counts['tn'])})
    ablations=[]
    for variant in VARIANTS:
        wrong_probes=wrong_models=executed=setup_refused=0
        for record in records:
            any_wrong=False
            for row in record['probes']:
                outcome=row['variants'][variant]
                if outcome.get('status')=='not_run_setup_refused':setup_refused+=1;continue
                executed+=1
                wrong=outcome.get('decision') in {'ANSWER_LOCAL','ANSWER_AFTER_HANDOFF'} and verdict(outcome)!=verdict(row['I1']) and verdict(row['I1'])==verdict(row['I2'])
                wrong_probes+=int(wrong);any_wrong|=wrong
            wrong_models+=int(any_wrong)
        ablations.append({'variant':variant,'executed_probes':executed,'setup_refused_probes':setup_refused,'wrongly_admitted_probes':wrong_probes,'models_with_wrong_admission':wrong_models})
    stale_ablations=[]
    for variant in ['runtime','no_digest']:
        admitted=executed=refused=0
        for record in records:
            for row in record['probes']:
                outcome=row['stale_request'][variant]
                if outcome.get('status')=='not_run_setup_refused':refused+=1;continue
                executed+=1
                if verdict(row['stale_request']['I1'])==verdict(row['stale_request']['I2']) and row['stale_request']['I1'].get('reason')=='E_STALE_DIGEST':
                    admitted+=int(outcome.get('decision') in {'ANSWER_LOCAL','ANSWER_AFTER_HANDOFF'})
        stale_ablations.append({'variant':variant,'executed_probes':executed,'setup_refused_probes':refused,'wrongly_admitted_stale_requests':admitted})
    manifest=json.loads((run_dir/'mutation_manifest.json').read_text(encoding='utf-8'))
    planned=sum(m['status'] in {'changed','incomplete'} for m in manifest['models'])
    summary={'planned_model_evaluations':planned,'evaluation_complete':len(records)==planned,'eligibility_counts':{status:sum(m['status']==status for m in manifest['models']) for status in ['changed','incomplete','not_applicable','no_op']},'worker_failures':len(list((run_dir/'worker_failures').glob('*.json'))) if (run_dir/'worker_failures').exists() else 0,'unit':'mutant models; probes are correlated within each model','models_evaluated':len(records),'independent_disagreement_models':sum(bool(r['independent_disagreements']) for r in records),'matrix':rows,'admission_ablations':ablations,'stale_digest_ablations':stale_ablations,'behavior_properties':{'I3_rejection_atomicity':{status:sum(r['checkers']['I3_rejection_atomicity']['status']==status for r in records) for status in ['pass','reject','not_applicable']}},'limitations':['Original knowledge/placement authoring artifacts are absent for native mutant units; affected metrics have explicit applicability status.','No B0/B1 model-routing calls or LLM judges are substituted by ScriptedClient.','Natural-diff mutants require separately supplied WP5 evolution pairs.','Runtime setup refusals are counted separately and never presented as executed routing decisions.','No-op/incomplete operator pairs are not credited as successful two-fault combinations.']}
    write_new(run_dir/'summary.json',summary)
    with (run_dir/'detection_matrix.csv').open('x',encoding='utf-8',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    return summary


def materialize(base,mutated,directory):
    directory=Path(directory)
    shutil.copytree(base,directory,ignore=shutil.ignore_patterns('runtime*.jsonl','*.log','__pycache__'))
    for name,value in [('roomcontract.v2.instance.json',mutated.instance),('trace_map.v2.json',mutated.trace),('trace_map.json',mutated.trace),('project.json',mutated.project),('agents.json',mutated.agents)]: (directory/name).write_bytes(encoded(value))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project',type=Path,action='append')
    parser.add_argument('--run-dir',type=Path,required=True)
    parser.add_argument('--workers',type=int,default=4)
    parser.add_argument('--evolution-pairs',type=Path,help='WP5 JSONL rows: pair_id, before_project, after_project; no synthetic replacements')
    parser.add_argument('--aggregate-only',action='store_true')
    args=parser.parse_args()
    if args.aggregate_only:
        print(json.dumps({'models_evaluated':aggregate(args.run_dir)['models_evaluated']}));return
    freeze=json.loads((ROOT/'prereg/WP6_PLAN.sha256.json').read_text(encoding='utf-8'))
    for path,expected in freeze['code_hashes'].items():
        if hashlib.sha256((ROOT/path).read_bytes()).hexdigest()!=expected:raise RuntimeError('WP6 code changed after freeze: '+path)
    args.run_dir.mkdir(parents=True,exist_ok=False)
    (args.run_dir/'outcomes').mkdir()
    jobs=[];manifest=[]
    batches=[]
    for source in args.project or []:
        bundle=Bundle.load(source)
        batches.append((source,bundle,mutation_plan(bundle)))
    if args.evolution_pairs:
        for line in args.evolution_pairs.read_text(encoding='utf-8').splitlines():
            if not line.strip():continue
            pair=json.loads(line)
            before=Bundle.load(Path(pair['before_project']))
            after=Bundle.load(Path(pair['after_project']))
            batches.append((Path(pair['after_project']),after,natural_diff_plan(before,after,str(pair['pair_id']))))
    for source,bundle,planned_mutants in batches:
        base_id=bundle.instance.get('caseId',source.name)
        for meta,mutated in planned_mutants:
            meta['room']=base_id
            entry_id=base_id+'__'+meta['id']
            meta['id']=entry_id
            storage_id='m_'+hashlib.sha256(entry_id.encode()).hexdigest()[:16]
            meta['storage_id']=storage_id
            manifest.append(meta)
            if meta['status'] not in {'changed','incomplete'}:continue
            try: mutated=refresh_projections(mutated)
            except Exception as exc:
                meta['projection_error']={'exception':type(exc).__name__,'message':str(exc)}
                # Keep the actual mutated bytes and stale projection; this is a real refusal case.
                mutated.project['roomcontract_model_sha256']=digest(mutated.instance)
                mutated.trace['model_sha256']=digest(mutated.instance)
            project=args.run_dir/'models'/storage_id/source.name
            materialize(source,mutated,project)
            jobs.append({'project':str(project),'output':str(args.run_dir/'outcomes'/(storage_id+'.json')),'metadata':meta})
    write_new(args.run_dir/'mutation_manifest.json',{'seed':SEED,'models':manifest,'freeze':freeze})
    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        futures={executor.submit(evaluate_one,job):job for job in jobs}
        for future in as_completed(futures):
            job=futures[future]
            try: print(json.dumps(future.result()),flush=True)
            except Exception as exc:
                write_new(args.run_dir/'worker_failures'/Path(job['output']).name,{'metadata':job['metadata'],'exception':type(exc).__name__,'message':str(exc)})
                print(json.dumps({'id':job['metadata']['id'],'worker_failure':str(exc)}),flush=True)
    summary=aggregate(args.run_dir)
    print(json.dumps({'models_evaluated':summary['models_evaluated'],'evaluation_complete':summary['evaluation_complete'],'workers_failed':summary['worker_failures']}))
    return 0 if summary['evaluation_complete'] else 1

if __name__=='__main__':raise SystemExit(main())

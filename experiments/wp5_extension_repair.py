"""One preregistered repair of retained natural authoring failures, no replacement sampling."""
from contextlib import redirect_stdout
import copy,io,json
from pathlib import Path
from experiments.wp5_extension import ROOT,PLAN_PATH,read,digest,write_once,safe_path,run_case,output_text
from repro.llm import Gateway,sanitize
from experiments.pipeline_runs import budget_stop_record
from tools.case_study_pipeline.agent_roles import agent_roles_schema,validate_agent_roles
from tools.case_study_pipeline.knowledge_synthesis import validate_knowledge
from tools.case_study_pipeline.roomcontract_assembler import assemble_roomcontract_instance,validate_roomcontract_instance

def preservation_report(before,after):
    allowed={'grounded_object_ids','responsible_zone_ids'}
    def invariant(value):
        result=copy.deepcopy(value)
        for agent in result.get('agents',[]):
            for key in allowed:agent.pop(key,None)
        return result
    return {'status':'valid' if invariant(before)==invariant(after) else 'invalid',
            'allowed_changed_fields':sorted(allowed),'agent_order_and_all_other_fields_identical':invariant(before)==invariant(after)}
def authoring_report(roles,semantics,normalized,knowledge):
    report={'agent_roles':validate_agent_roles(roles,scene_semantics=semantics,normalized_scene=normalized),
      'knowledge':validate_knowledge(knowledge,normalized_scene=normalized,agent_roles=roles)}
    try:
        model=assemble_roomcontract_instance(case_id='repair_authoring_check',normalized_scene=normalized,scene_semantics=semantics,agent_roles=roles)
        report['assembly']=validate_roomcontract_instance(model)
    except Exception as exc:
        report['assembly']={'status':'invalid','error_type':type(exc).__name__,'error':sanitize(str(exc))[:2000]}
    report['status']='valid' if all(report[k].get('status')=='valid' for k in ('agent_roles','knowledge','assembly')) else 'invalid'
    return report

def repair_one(candidate,plan,*,replay=False,gateway=None):
    cid=candidate['case_id']+'_ownershiprepair_v1';root=ROOT/'results/raw/wp5_extension/ownership_repair'/cid
    final=root/'repair_result.json'
    if final.exists():
        prior=read(final)
        if prior['plan_sha256']!=digest(PLAN_PATH) or prior['candidate']!=candidate:raise RuntimeError('Retained repair identity changed')
        return prior
    for rel,key in ((candidate['run_result_path'],'run_result_sha256'),(candidate['candidate_path'],'candidate_sha256')):
        if digest(safe_path(rel))!=candidate[key]:raise RuntimeError('Original candidate changed')
    source_case=ROOT/'results/raw/wp5/cases'/candidate['case_id'];original_run=read(safe_path(candidate['run_result_path']))
    inputs={name:source_case/'intermediate'/filename for name,filename in
        (('roles','agent_roles.generated.json'),('semantics','scene_semantics.json'),('normalized','scene_graph.normalized.json'),('knowledge','knowledge.generated.json'))}
    for path in inputs.values():
        if original_run['artifact_sha256'].get(path.relative_to(ROOT).as_posix())!=digest(path):raise RuntimeError('Retained original authoring artifact changed')
    values={name:read(path) for name,path in inputs.items()};before=authoring_report(**values)
    write_once(root/'before/agent_roles.generated.json',values['roles']);write_once(root/'before/validation.json',before)
    result={'schema':'wp5-natural-ownership-repair-v1','plan_sha256':digest(PLAN_PATH),'candidate':candidate,
            'status':'failed','before_report':before,'generation_request_attempts':0,'before_native_project':None,
            'before_native_absence_reason':'Original assembly rejected the authoring candidate; no before-native model is fabricated.'}
    if before['status']=='valid':
        result['error_code']='REGISTERED_FAILURE_NOT_REPRODUCED';write_once(final,result);return result
    schema=agent_roles_schema([z['zone_id'] for z in values['semantics']['semantic_zones']],
        [o['object_id'] for o in values['normalized']['objects']])
    payload={'model':candidate['source']['model'],'instructions':safe_path(plan['ownership_repair']['prompt_path']).read_text(encoding='utf-8'),
        'input':json.dumps({'candidate':values['roles'],'source_objects':[{'object_id':o['object_id'],'group':o.get('group')} for o in values['normalized']['objects']],
          'semantic_zones':values['semantics']['semantic_zones'],'validation':before},ensure_ascii=False),
        'temperature':plan['temperature'],'max_output_tokens':plan['ownership_repair']['output_cap'],
        'text':{'format':{'type':'json_schema','name':'ownership_repair','strict':True,'schema':schema}}}
    write_once(root/'request.json',sanitize(payload));gateway=gateway or Gateway(ROOT,replay=replay,count_input_tokens=True)
    try:
        result['generation_request_attempts']=1
        response=gateway.responses(payload,experiment_id='WP5.extension.ownership_repair',item_id=candidate['source']['scene_id'],
            repetition_id=cid,share='WP5',max_input_tokens=plan['ownership_repair']['input_ceiling'])
        write_once(root/'response.json',sanitize(response))
        if response.get('status')!='completed':raise ValueError('Incomplete registered repair response')
        repaired=json.loads(output_text(response));write_once(root/'after/agent_roles.generated.json',repaired)
        preservation=preservation_report(values['roles'],repaired);after=authoring_report(repaired,values['semantics'],values['normalized'],values['knowledge'])
        result.update(preservation=preservation,after_report=after)
        write_once(root/'after/validation.json',after)
        if preservation['status']!='valid' or after['status']!='valid':
            result['error_code']='REPAIRED_CANDIDATE_INVALID';write_once(final,result);return result
    except Exception as exc:
        result['error_code']=getattr(exc,'code',type(exc).__name__);result['budget_stop']=budget_stop_record(result)
        write_once(final,result);return result
    row={**candidate['source'],'case_id':cid,'phase':'ownership_repair','arm':'ownership_repair','family':'original_repair','external_generation_attempts':1}
    seeds={'scene_semantics.json':inputs['semantics'],'knowledge.generated.json':inputs['knowledge'],
           'agent_roles.generated.json':root/'after/agent_roles.generated.json'}
    repair_plan={**plan,'stage_order':[s for s in plan['stage_order'] if s not in plan['llm_stages']]}
    run=run_case(row,repair_plan,replay=replay,seed_artifacts=seeds)
    result.update(status=run['status'],run_result_path=(root/'run_result.json').relative_to(ROOT).as_posix(),
                  run_result_sha256=digest(root/'run_result.json'),after_native_project=run.get('project_dir'))
    write_once(final,result);return result

def run_repairs(plan,*,replay=False):
    results=[]
    for candidate in plan['targeted_repair_candidates']:
        result=repair_one(candidate,plan,replay=replay);results.append(result)
        print(json.dumps({'repair':candidate['case_id'],'status':result['status']}),flush=True)
        if result.get('budget_stop'):break
    write_once(ROOT/'results/raw/wp5_extension/ownership_repair_terminal_v1.json',{'terminal':True,'plan_sha256':digest(PLAN_PATH),'registered_candidates':len(plan['targeted_repair_candidates']),'attempted_candidates':len(results),'results':results})
    return results

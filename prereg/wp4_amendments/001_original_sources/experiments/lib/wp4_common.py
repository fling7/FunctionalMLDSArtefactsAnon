"""WP4 shared immutable artifacts, public data adapters, and budgeted calls."""
from __future__ import annotations
import copy, hashlib, json, os, sys, time
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
BACKEND=ROOT/'app/backend_root/agent_backend'
for p in (ROOT,BACKEND):
    if str(p) not in sys.path: sys.path.insert(0,str(p))
from repro.llm import Gateway, GatewayError, canonical_bytes, sanitize
from repro.budget import BudgetError
MODELS=('gpt-4.1-mini-2025-04-14','gpt-4.1-2025-04-14')
SEED=20261015
ROUTER_INPUT_LIMITS={"B0":1500,"B1":7000}
HTTP_INPUT_LIMIT=3000
PROMPTS=ROOT/'experiments/prompts/wp4'
PLAN=ROOT/'prereg/wp4_plan.json'
CLASSES=('local','direct','multi_hop','unreachable','ambiguous','unowned','other_reject')

def read_json(path): return json.loads(Path(path).read_text(encoding='utf-8-sig'))
def write_json(path,obj):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(sanitize(obj),indent=2,ensure_ascii=False,sort_keys=True)+'\n',encoding='utf-8')
def digest(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def stable_key(value): return hashlib.sha256(canonical_bytes([SEED,value])).hexdigest()
def prompt(name): return (PROMPTS/name).read_text(encoding='utf-8').strip()
def output_text(response):
    return '\n'.join(str(c.get('text','')) for m in response.get('output',[]) if m.get('type')=='message' for c in m.get('content',[]) if c.get('type')=='output_text').strip()
def parsed_output(response):
    try: return json.loads(output_text(response))
    except (TypeError,ValueError): return None

def verify_freeze():
    frozen=ROOT/'prereg/wp4_plan.sha256'
    if not frozen.exists() or digest(PLAN)!=frozen.read_text(encoding='utf-8').split()[0]:
        raise RuntimeError('WP4 plan is not frozen or its digest differs; no paid evaluation allowed.')
    plan=read_json(PLAN)
    for path,expected in plan['source_sha256'].items():
        if digest(ROOT/path)!=expected: raise RuntimeError('Frozen WP4 source changed: '+path)
    return plan

def cost_ceiling(model,inputs,outputs):
    price=read_json(ROOT/'repro/prices.json')['models'][model]
    return (Decimal(price['input_per_million'])*inputs+Decimal(price['output_per_million'])*outputs)/Decimal(1000000)

def remaining(gateway,share='WP4'):
    state=gateway.budget.summary()
    if state['halted']: return Decimal(0)
    allocation=state['allocations'][share]
    return min(Decimal(allocation['stop_usd'])-Decimal(allocation['accounted_usd']),Decimal(state['cap_usd'])-Decimal(state['accounted_usd']))

def guarded_call(gateway,payload,*,experiment,item,repetition,share,limit):
    start=time.perf_counter()
    row={'experiment_id':experiment,'item_id':item,'repetition_id':str(repetition),'model':payload['model'],'payload_sha256':hashlib.sha256(canonical_bytes(payload)).hexdigest(),'temperature':payload.get('temperature'),'input_limit':limit,'output_limit':payload['max_output_tokens']}
    try:
        response=gateway.responses(payload,experiment_id=experiment,item_id=item,repetition_id=str(repetition),share=share,max_input_tokens=limit)
        row.update(status='SUCCESS',response=response,parsed=parsed_output(response),usage=response.get('usage',{}))
        usage=row['usage'];row['nominal_token_cost_usd']=str(cost_ceiling(payload['model'],usage.get('input_tokens',0),usage.get('output_tokens',0)))
    except (GatewayError,BudgetError) as exc:
        row.update(status=getattr(exc,'code','BUDGET_STOP'),error_type=type(exc).__name__)
    row['latency_seconds']=time.perf_counter()-start
    return sanitize(row)

def archive_sources(out,extra=()):
    plan=verify_freeze();names=list(plan['source_sha256'])+['prereg/wp4_plan.json','prereg/wp4_plan.sha256',*extra]
    for name in dict.fromkeys(names):
        path=out/'source'/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes((ROOT/name).read_bytes())
    write_json(out/'provenance.json',{'utc':datetime.now(timezone.utc).isoformat(),'source_sha256':{n:digest(ROOT/n) for n in names},'seed':SEED,'real_models':True})

def ownership_view(instance):
    objects=instance['objects'];by_id={x['id']:x for x in objects};agents=[x for x in objects if x.get('type')=='Agent']
    wire=lambda ref: by_id.get(ref,{}).get('sourceAgentId',ref)
    return {'agents':[{'id':x['sourceAgentId'],'objects':sorted(x.get('groundedAsset',[])),'groups':sorted(x.get('groundedObjectGroup',[])),'zones':sorted(x.get('responsibleZone',[])),'handoff_targets':sorted(wire(y) for y in x.get('handoffTarget',[]))} for x in sorted(agents,key=lambda x:x['sourceAgentId'])],
            'objects':[{'id':x['id'],'source_id':x.get('sourceId'),'name':x.get('name'),'groups':x.get('objectGroup',[])} for x in sorted(objects,key=lambda x:x['id']) if x.get('entityRole')=='sceneObject'],
            'groups':[{'id':x['id'],'name':x.get('name'),'members':x.get('sourceObjectId',[])} for x in sorted(objects,key=lambda x:x['id']) if x.get('entityRole')=='objectGroup'],
            'zones':[{'id':x['id'],'name':x.get('name'),'members':x.get('sourceObjectId',[])} for x in sorted(objects,key=lambda x:x['id']) if x.get('entityRole')=='semanticZone']}

def profiles(project):
    data=read_json(Path(project)/'agents.json')
    return [{k:x.get(k,[] if k=='expertise' else '') for k in ('id','display_name','persona','expertise')} for x in sorted(data['agents'],key=lambda x:x['id'])]

def selected_view(instance,target):
    zones=[x for x in instance['objects'] if x.get('entityRole')=='semanticZone' and target.get('sourceId') in x.get('sourceObjectId',[])]
    return {'id':target['id'],'source_id':target.get('sourceId'),'name':target.get('name') or target.get('sourceId'),'type':target.get('objectType') or target.get('sourceType') or target.get('assetType') or target.get('name'),'group_label':target.get('sourceGroup'),'zone_names':[x.get('name') or x.get('sourceId') for x in zones]}

def routing_class(verdict):
    if verdict.get('decision')=='ANSWER_LOCAL': return 'local'
    if verdict.get('decision')=='ANSWER_AFTER_HANDOFF': return 'direct'
    reason=str(verdict.get('reason','')).upper()
    if any(x in reason for x in ('AMBIGU','MULTIPLE')): return 'ambiguous'
    if any(x in reason for x in ('NO_OWNER','UNOWNED','NO_PROVIDER','NO_RESPONSIBLE')): return 'unowned'
    if any(x in reason for x in ('HOP_LIMIT','MULTI_HOP','TOO_MANY_HOPS')): return 'multi_hop'
    if any(x in reason for x in ('UNREACHABLE','NO_ROUTE','REACHABILITY')): return 'unreachable'
    return 'other_reject'

def classified_probe(verdict,instance,start,target):
    base=routing_class(verdict)
    if verdict.get('reason')!='E_NO_HANDOFF_PATH':return base
    # This graph-derived label only subdivides the independent rejection verdict;
    # it does not override either implementation's ground-truth decision.
    objects=instance['objects'];by_id={x['id']:x for x in objects};agents=[x for x in objects if x.get('type')=='Agent']
    groups=set(target.get('objectGroup',[]));zones={x['id'] for x in objects if x.get('entityRole')=='semanticZone' and target.get('sourceId') in x.get('sourceObjectId',[])}
    candidates=[]
    for field,refs in (('groundedAsset',{target['id']}),('groundedObjectGroup',groups),('responsibleZone',zones)):
        candidates=[a['sourceAgentId'] for a in agents if refs.intersection(a.get(field,[]))]
        if candidates:break
    if len(candidates)!=1:return 'other_reject'
    graph={a['sourceAgentId']:[by_id.get(x,{}).get('sourceAgentId',x) for x in a.get('handoffTarget',[])] for a in agents};seen={start};queue=[start]
    while queue:
        current=queue.pop(0)
        for other in graph.get(current,[]):
            if other==candidates[0]:return 'multi_hop'
            if other not in seen:seen.add(other);queue.append(other)
    return 'unreachable'

def stratified(probes,limit=48):
    buckets={c:sorted([p for p in probes if p['class']==c],key=lambda p:stable_key([p['start_agent'],p['target']['id']])) for c in CLASSES}
    result=[]
    while len(result)<limit and any(buckets.values()):
        for c in CLASSES:
            if buckets[c] and len(result)<limit: result.append(buckets[c].pop(0))
    return result

def native_admission(driver,request):
    """Run native chat through preflight, stop before generation/history mutation.

    This instrumentation never supplies a model response. It observes the native
    preselected provider and action at the private chat-method boundary.
    """
    from unittest.mock import patch
    class AtGeneration(Exception):pass
    observed={};store=driver.store;original=store._preflight_v2_interaction_action
    snapshot=store.snapshot_session_mutation(request['session_id'])
    def preflight(**kwargs):
        result=original(**kwargs)
        if kwargs['action_kind']=='chat':observed['action']=(result.get('action') or {}).get('runtime_action_id')
        return result
    def stop(st,session_id,agent,*args,**kwargs):
        observed['provider']=agent.id
        raise AtGeneration()
    try:
        with patch.object(store,'_preflight_v2_interaction_action',preflight),patch.object(store,'_chat_shared',stop),patch.object(store,'_chat_agent_private',stop):
            store.chat(request,include_runtime_actions=True)
        raise AssertionError('Native routing reached response without generation boundary')
    except AtGeneration:
        verdict={'decision':'ANSWER_LOCAL' if observed['provider']==request['active_agent_id'] else 'ANSWER_AFTER_HANDOFF','reason':None,'provider':observed['provider'],'action':observed.get('action')}
    except Exception as exc:
        verdict={'decision':'REJECT','reason':getattr(exc,'code','HARNESS_ERROR'),'provider':None,'action':None,'exception_type':type(exc).__name__}
    verdict['state_unchanged']=store.snapshot_session_mutation(request['session_id'])==snapshot
    verdict['model_calls']=0
    if not verdict['state_unchanged']:store.restore_session_mutation(request['session_id'],snapshot)
    return verdict

def project_probes(project):
    # Public evaluator interfaces only. The harness never reads their implementations.
    from verification.impl_a.reference import evaluate as i1
    from verification.impl_b.policy_adapter import evaluate as i2
    from experiments.lib.backend_driver import Driver
    class NoGeneration:
        api_key=''
        def create_structured_json(self,**kwargs):raise RuntimeError('B2 must stop before model invocation')
        def create_json_object(self,**kwargs):raise RuntimeError('B2 must stop before model invocation')
    driver=Driver(project,client=NoGeneration())
    try:
        instance=driver.contract['instance'];trace=read_json(Path(project)/'trace_map.v2.json');session={'model_sha256':driver.setup['model_sha256'],'active_agent_mode':'client'}
        rows=[]
        for agent in sorted(driver.setup['agents'],key=lambda x:x['id']):
            for target in sorted(driver.targets,key=lambda x:x['id']):
                request=driver.request(agent['id'],target);a=i1(instance,trace,request,session);b=i2(instance,trace,request,session)
                if hasattr(a,'as_dict'): a=a.as_dict()
                if hasattr(b,'as_dict'): b=b.as_dict()
                agree=all(a.get(k)==b.get(k) for k in ('decision','reason','provider','action'))
                native=native_admission(driver,request)
                rows.append({'start_agent':agent['id'],'target':target,'request':request,'I1':a,'I2':b,'B2':native,'backend_agreement':all(native.get(k)==a.get(k) for k in ('decision','reason','provider','action')),'agreement':agree,'class':classified_probe(a,instance,agent['id'],target)})
        return driver.contract,rows
    finally: driver.close()

def choose_rooms(summary_path):
    plan=read_json(ROOT/'prereg/wp5_plan.json');data=read_json(summary_path);rows=data.get('rows',[]) if isinstance(data,dict) else data
    # Prefer public eligibility manifest; retain compatibility with raw run_result rows.
    normalized=[]
    for r in rows:
        source=r.get('source',{})
        normalized.append({'sid':r.get('source_room_id',source.get('scene_id')),'model':r.get('pipeline_model',source.get('model')),'split':r.get('split',source.get('phase')),'eligible':r.get('eligible_native_success',r.get('status')=='success'),'project':r.get('project_path',r.get('project_dir'))})
    selected=[];seen=set();omitted=[]
    for expected in plan['evaluation']:
        sid=expected['scene_id']
        if sid in seen:continue
        seen.add(sid)
        model_order=[x['model'] for x in plan['evaluation'] if x['scene_id']==sid]
        candidates=sorted([x for x in normalized if x['sid']==sid and x['split']=='evaluation' and x['eligible']],key=lambda x:model_order.index(x['model']))
        if not candidates:omitted.append({'source_room_id':sid,'reason':'no_successful_registered_project'});continue
        chosen=candidates[0];selected.append({'source_room_id':sid,'project_path':chosen['project'],'author_model':chosen['model'],'split':'evaluation'})
        if len(selected)==20:break
    return selected,omitted

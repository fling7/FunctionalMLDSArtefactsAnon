"""Preregistered B0/B1 routing experiment; all paid calls use repro.llm."""
from __future__ import annotations
import argparse, itertools, json, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from experiments.lib.wp4_common import *

def router_payload(room,item,question,baseline,abstain,phrasing,model,temperature=.3):
    context={'agents':room['agent_profiles'],'selected_object':selected_view(room['instance'],item['target']),'active_agent_id':item['start_agent'],'visitor_question':question}
    if baseline=='B1':context['ownership_and_handoffs']=ownership_view(room['instance'])
    agent_ids=[a['id'] for a in room['agent_profiles']]
    schema={'type':'object','additionalProperties':False,'required':['answering_agent_id','abstain'],'properties':{'answering_agent_id':{'type':['string','null'] if abstain else 'string','enum':agent_ids+[None] if abstain else agent_ids},'abstain':{'type':'boolean','enum':[False,True] if abstain else [False]}}}
    instructions=prompt('router_'+str(phrasing)+'.txt').format(abstention=prompt('abstain.txt' if abstain else 'forced_choice.txt'))
    return {'model':model,'temperature':temperature,'max_output_tokens':96,'input':[{'role':'developer','content':instructions},{'role':'user','content':json.dumps(context,ensure_ascii=False,separators=(',',':'))}],'text':{'format':{'type':'json_schema','name':'routing_decision','strict':True,'schema':schema}}}

def classify(parsed,verdict,agent_ids,abstain_allowed):
    if not isinstance(parsed,dict) or set(parsed)!={'answering_agent_id','abstain'} or type(parsed.get('abstain')) is not bool:return 'FORMAT_ERROR'
    agent=parsed['answering_agent_id'];abstain=parsed['abstain']
    if abstain:
        if not abstain_allowed or agent is not None:return 'FORMAT_ERROR'
        return 'ABSTAIN_OK' if verdict['decision']=='REJECT' else 'WRONG_PROVIDER'
    if agent not in agent_ids:return 'FORMAT_ERROR'
    if verdict['decision']=='REJECT':return 'SILENT_VIOLATION'
    return 'CORRECT' if agent==verdict.get('provider') else 'WRONG_PROVIDER'

def prepare(summary,out,allow_insufficient=False):
    verify_freeze();out=Path(out);out.mkdir(parents=True,exist_ok=False);archive_sources(out)
    selected,omitted=choose_rooms(summary)
    if len(selected)<20 and not allow_insufficient:raise RuntimeError('Fewer than twenty eligible evaluation sources; wait for the completed WP5 sequence or explicitly record an insufficient corpus.')
    selected.append({'source_room_id':'authored_example','project_path':str((BACKEND/'projects/classroom_dinosaur').relative_to(ROOT)),'author_model':None,'split':'example'})
    index={'rooms':[],'omitted_sources':omitted,'question_objects':[],'disagreements':[]}
    for ri,metadata in enumerate(selected):
        project=ROOT/metadata['project_path'];contract,probes=project_probes(project);agreed=[p for p in probes if p['agreement']]
        disagreements=[p for p in probes if not p['agreement'] or not p['backend_agreement']]
        index['disagreements'].extend({'source_room_id':metadata['source_room_id'],**p} for p in disagreements)
        candidates=stratified(agreed);admitted=[p for p in candidates if p['I1']['decision']!='REJECT']
        if not candidates or not admitted:
            index['omitted_sources'].append({**metadata,'reason':'no_agreed_probe_or_admitted_probe','probe_count':len(probes),'disagreement_count':len(disagreements)});continue
        classes=CLASSES[ri%len(CLASSES):]+CLASSES[:ri%len(CLASSES)]
        primary=next(p for c in classes for p in candidates if p['class']==c)
        # Fifteen predefined attempts per source; cycle finite admitted pairs transparently.
        turns=[admitted[i%len(admitted)] for i in range(15)]
        owner_by_object={p['target']['id']:p['I1'].get('provider') for p in agreed if p['I1']['decision']!='REJECT'}
        all_targets=sorted({p['target']['id']:p['target'] for p in agreed}.values(),key=lambda x:stable_key(x['id']))
        def mismatch_for(p):
            own=owner_by_object.get(p['target']['id'])
            return next((t for t in all_targets if own and owner_by_object.get(t['id']) and owner_by_object[t['id']]!=own),None)
        room={**metadata,'instance':contract['instance'],'agent_profiles':profiles(project),'probes':probes,'stratified_candidates':candidates,'primary':primary,'turn_pairs':turns,'mismatch_target':mismatch_for(primary),'turn_mismatch_target':mismatch_for(turns[12]),'owner_by_object':owner_by_object,'projection_sha256':{path.relative_to(project).as_posix():digest(path) for path in [project/'agents.json',project/'room_plan.json',project/'trace_map.v2.json',project/Path(contract['instance_path']).name,*sorted((project/'kb').rglob('*.txt'))]},'model_sha256':contract.get('model_sha256')}
        needed={p['target']['id']:p['target'] for p in [primary,*turns]}
        for target in (room['mismatch_target'],room['turn_mismatch_target']):
            if target:needed[target['id']]=target
        room['question_targets']=list(needed.values())
        filename=metadata['source_room_id']+'.json';write_json(out/'rooms'/filename,room)
        index['rooms'].append({**metadata,'file':'rooms/'+filename,'sha256':digest(out/'rooms'/filename),'probe_count':len(probes),'agreement_count':len(agreed),'class_counts':{c:sum(p['class']==c for p in probes) for c in CLASSES}})
        index['question_objects'].extend({'source_room_id':metadata['source_room_id'],'target_id':t['id']} for t in needed.values())
    write_json(out/'manifest.json',index);(out/'manifest.sha256').write_text(digest(out/'manifest.json')+'\n',encoding='utf-8')
    print(json.dumps({'corpus':str(out),'rooms':len(index['rooms']),'disagreements':len(index['disagreements'])}))

def load_corpus(path):
    path=Path(path);manifest=read_json(path/'manifest.json')
    if digest(path/'manifest.json')!=(path/'manifest.sha256').read_text().strip():raise RuntimeError('Corpus manifest changed')
    rooms=[]
    for m in manifest['rooms']:
        if digest(path/m['file'])!=m['sha256']:raise RuntimeError('Corpus room changed')
        room=read_json(path/m['file'])
        for relative,expected in room['projection_sha256'].items():
            if digest(ROOT/room['project_path']/relative)!=expected:raise RuntimeError('Source project changed after corpus freeze: '+room['source_room_id'])
        rooms.append(room)
    return rooms

def question_key(room,target):return room['source_room_id']+'.'+target['id']
def question_for(room,pair,kind,questions):
    if kind=='neutral':return 'What can you tell me about this selected object?'
    target=room.get('mismatch_target') if kind=='mismatch' else pair['target']
    if not target:return None
    q=questions.get(question_key(room,target),{})
    if q.get('status')!='SUCCESS':return None
    return q['parsed'].get('question_2' if kind=='natural_2' else 'question_1')

def generate_questions(corpus,out,replay=False):
    verify_freeze()
    qplan=ROOT/'prereg/wp4_questions_plan.json';qhash=ROOT/'prereg/wp4_questions_plan.sha256'
    if not qhash.exists() or digest(qplan)!=qhash.read_text().split()[0]:raise RuntimeError('Question generation preregistration is not frozen')
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    if (out/'questions.json').exists():
        if digest(out/'questions.json')!=(out/'questions.sha256').read_text().strip():raise RuntimeError('Existing frozen questions changed')
        return
    gateway=Gateway(ROOT,replay=replay,count_input_tokens=True)
    from backend.kb import KnowledgeBase
    for room in load_corpus(corpus):
        project=ROOT/room['project_path'];kb=KnowledgeBase(project/'kb')
        source=read_json(project/'room_plan.json')['scene'];source_objects={x['objectId']:x for x in source['objects']}
        for target in room['question_targets']:
            key=question_key(room,target);path=out/(stable_key(key)+'.json')
            if path.exists():continue
            description=source_objects.get(target['sourceId'],{})
            snippets=kb.search(query=str(target.get('name',''))+' '+str(target.get('sourceId','')),tags=[],k=4)
            data={'object':selected_view(room['instance'],target),'description':description.get('specification',''),'knowledge_excerpts':snippets}
            schema={'type':'object','additionalProperties':False,'required':['question_1','question_2'],'properties':{x:{'type':'string'} for x in ('question_1','question_2')}}
            payload={'model':MODELS[0],'temperature':.3,'max_output_tokens':256,'input':[{'role':'developer','content':prompt('questions.txt')},{'role':'user','content':json.dumps(data,ensure_ascii=False)}],'text':{'format':{'type':'json_schema','name':'visitor_questions','strict':True,'schema':schema}}}
            row=guarded_call(gateway,payload,experiment='WP4.questions',item=key,repetition=0,share='judges',limit=6000);row['key']=key
            if row['status']=='SUCCESS' and (not isinstance(row['parsed'],dict) or not all(isinstance(row['parsed'].get(x),str) and row['parsed'][x].strip() for x in ('question_1','question_2'))):row['status']='FORMAT_ERROR'
            if row['status']=='SUCCESS':
                values=[row['parsed']['question_1'],row['parsed']['question_2']]
                names=[str(target.get('name') or ''),str(target.get('sourceId') or '')]
                if values[0].strip()==values[1].strip() or any(not any(name and name.casefold() in value.casefold() for name in names) for value in values):row['status']='QUESTION_REFERENCE_OR_DISTINCTNESS_ERROR'
            write_json(path,row)
            if row['status']=='BUDGET_STOP':break
    frozen={r['key']:r for p in sorted(out.glob('*.json')) if p.name!='questions.json' for r in [read_json(p)] if 'key' in r}
    write_json(out/'questions.json',frozen);(out/'questions.sha256').write_text(digest(out/'questions.json')+'\n',encoding='utf-8')

def make_blocks(rooms,stage):
    evaluations=[r for r in rooms if r['split']=='evaluation'];example=[r for r in rooms if r['split']=='example']
    if stage=='primary':return [('primary.'+r['source_room_id'],[(r,'neutral',.3,0)]) for r in evaluations]+[('example',[(r,'neutral',.3,0) for r in example])]
    # Two distinct classes where possible, selected without seeing any model output.
    reps=[]
    for r in evaluations:
        if not reps or r['primary']['class'] not in {x['primary']['class'] for x in reps}:reps.append(r)
        if len(reps)==2:break
    for r in evaluations:
        if len(reps)<2 and r not in reps:reps.append(r)
    blocks=[('repeats',[(r,'neutral',temp,rep) for r in reps for temp,rep in ((.3,1),(.3,2),(0,3))])]
    for kind in ('mismatch','natural_1','natural_2'):
        blocks.extend((kind+'.'+r['source_room_id'],[(r,kind,.3,0)]) for r in evaluations)
    return blocks

def run(corpus,questions_path,out,stage='primary',replay=False):
    verify_freeze();out=Path(out);out.mkdir(parents=True,exist_ok=True)
    if not (out/'provenance.json').exists():archive_sources(out)
    rooms=load_corpus(corpus);questions=read_json(questions_path) if questions_path else {};gateway=Gateway(ROOT,replay=replay,count_input_tokens=True)
    if questions_path and digest(questions_path)!=Path(questions_path).with_suffix('.sha256').read_text().strip():raise RuntimeError('Questions changed after freeze')
    if stage=='primary':
        for room in rooms:
            pair=room['primary'];native=pair['B2'];native_parsed={'answering_agent_id':native.get('provider'),'abstain':native['decision']=='REJECT'}
            path=out/'rows'/(room['source_room_id']+'.B2.json')
            if not path.exists():write_json(path,{'source_room_id':room['source_room_id'],'split':room['split'],'baseline':'B2','abstain_allowed':True,'phrasing':0,'question_kind':'neutral','fault_class':pair['class'],'I1':pair['I1'],'I2':pair['I2'],'native':native,'target_id':pair['target']['id'],'start_agent':pair['start_agent'],'model':'deterministic_native_guard','temperature':0,'repetition':0,'status':'NATIVE_HARNESS_ERROR' if native.get('reason')=='HARNESS_ERROR' else 'SUCCESS','outcome':'NATIVE_HARNESS_ERROR' if native.get('reason')=='HARNESS_ERROR' else classify(native_parsed,pair['I1'],[a['id'] for a in room['agent_profiles']],True),'model_calls':0,'interpretation':'Native preflight observed at generation boundary; no model response supplied.'})
    for block_id,items in make_blocks(rooms,stage):
        count=len(items)*12
        expected=[]
        for room,kind,temp,rep in items:
            for model,baseline,abstain,phrasing in itertools.product(MODELS,('B0','B1'),(False,True),(1,2,3)):
                identity='.'.join([room['source_room_id'],baseline,'abstain' if abstain else 'forced','p'+str(phrasing),kind,'mini' if model==MODELS[0] else 'full','t'+str(temp),'r'+str(rep)])
                expected.append((identity,room,kind,temp,rep,model,baseline,abstain,phrasing))
        pending=[x for x in expected if not (out/'rows'/(x[0]+'.json')).exists()]
        pending_bound=sum(cost_ceiling(x[5],ROUTER_INPUT_LIMITS[x[6]],96) for x in pending)
        if not replay and remaining(gateway)<pending_bound:
            write_json(out/'stop.json',{'block_id':block_id,'reason':'INSUFFICIENT_FOR_COMPLETE_BALANCED_BLOCK','pending_ceiling_usd':str(pending_bound),'remaining_usd':str(remaining(gateway))});break
        for identity,room,kind,temp,rep,model,baseline,abstain,phrasing in sorted(pending,key=lambda x:stable_key(x[0])):
            pair=room['primary'];question=question_for(room,pair,kind,questions)
            meta={'source_room_id':room['source_room_id'],'split':room['split'],'baseline':baseline,'abstain_allowed':abstain,'phrasing':phrasing,'question_kind':kind,'fault_class':pair['class'],'I1':pair['I1'],'I2':pair['I2'],'target_id':pair['target']['id'],'start_agent':pair['start_agent'],'model':model,'temperature':temp,'repetition':rep,'block_id':block_id}
            if question is None:row={**meta,'status':'QUESTION_UNAVAILABLE','outcome':'QUESTION_UNAVAILABLE'}
            else:
                payload=router_payload(room,pair,question,baseline,abstain,phrasing,model,temp)
                row={**meta,**guarded_call(gateway,payload,experiment='WP4.routing',item=identity,repetition=rep,share='WP4',limit=ROUTER_INPUT_LIMITS[baseline])}
                row['outcome']=(classify(row.get('parsed'),pair['I1'],[a['id'] for a in room['agent_profiles']],abstain) if row.get('response',{}).get('status')=='completed' else 'FORMAT_ERROR') if row['status']=='SUCCESS' else row['status']
                row['question']=question
            write_json(out/'rows'/(identity+'.json'),row)
    write_json(out/('complete_'+stage+'.json'),{'stage':stage,'planned_blocks':len(make_blocks(rooms,stage)),'rows_on_disk':len(list((out/'rows').glob('*.json'))) if (out/'rows').exists() else 0,'stopped':(out/'stop.json').exists()})

def main():
    p=argparse.ArgumentParser();s=p.add_subparsers(dest='command',required=True)
    a=s.add_parser('prepare');a.add_argument('--summary',default='results/processed/wp5_projects.json');a.add_argument('--out',required=True);a.add_argument('--allow-insufficient',action='store_true')
    a=s.add_parser('questions');a.add_argument('--corpus',required=True);a.add_argument('--out',required=True);a.add_argument('--replay',action='store_true')
    a=s.add_parser('run');a.add_argument('--corpus',required=True);a.add_argument('--questions');a.add_argument('--out',required=True);a.add_argument('--stage',choices=['primary','extras'],default='primary');a.add_argument('--replay',action='store_true')
    args=vars(p.parse_args());command=args.pop('command')
    if command=='prepare':prepare(**args)
    elif command=='questions':generate_questions(**args)
    else:args['questions_path']=args.pop('questions');run(**args)
if __name__=='__main__':main()

"""NOT RUN during A1 timing. Offline candidate preparation only; never freezes or calls APIs."""
from pathlib import Path
from collections import Counter,defaultdict
import argparse,copy,hashlib,json,socket,sys
R=Path(__file__).resolve().parents[3];sys.path.insert(0,str(R));S=Path(__file__).relative_to(R).as_posix()
def deny(*a,**k):raise RuntimeError('Stage C draft is offline; live calls forbidden')
socket.create_connection=deny;socket.socket.connect=deny
PINS={}
def read(p):
 b=p.read_bytes();PINS[p.relative_to(R).as_posix()]=hashlib.sha256(b).hexdigest();return json.loads(b.decode('utf-8-sig'))
def save(p,x):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(x,sort_keys=True,indent=2)+'\n',encoding='utf-8')
def main(out):
 if out.exists():raise RuntimeError('Choose a new output path; preserve any prior draft')
 from experiments.lib.wp4_common import ownership_view
 from experiments.natural_faults import request_for
 from tools.routing_verifier import NativeRoutingIndex,verify_routing,serialization_digest
 from verification.impl_a import reference as I1
 from verification.impl_b import policy_adapter as I2
 design=read(R/'prereg/go_sprint_20261019/w3/design.json');requests_path=R/'prereg/go_sprint_20261019/w3/requests.json';requests=read(requests_path)
 assert PINS[requests_path.relative_to(R).as_posix()]==design['requests_sha256']
 blocks=defaultdict(list)
 for row in requests:blocks[(row['room'],row['variant'],row['pair_index'],row['target_id'],row['start_agent'])].append(row)
 for block in blocks.values():assert len(block)==6 and len({(r['baseline'],r['model']) for r in block})==6
 reference=[next(r for r in block if r['baseline']=='B1' and r['model']==design['models'][0]) for block in blocks.values()]
 counts=Counter(r['fault_class'] for r in reference);controls=[r for r in reference if r['I1']['decision']!='REJECT'];faultsource={r['room'] for r in reference if r['fault_class'] in ('duplicate_asset_owner','remove_all_owners')}
 numbers={'retained_calls':len(requests),'distinct_item_blocks':len(blocks),'distinct_controls_per_model_arm':len(controls),'pooled_controls_per_arm_two_models':len(controls)*len(design['models']),'fault_items_by_class_per_model_arm':dict(counts),'distinct_injected_base_sources':len(faultsource),'injected_source_fault_variants':len({(r['room'],r['fault_class']) for r in reference if r['I1']['decision']=='REJECT'}),'status':'DRAFT_NOT_FROZEN','extra_spend_usd':0}
 comparisons=[]
 for k,v in numbers.items():
  if isinstance(v,(int,float)):
   prior={'retained_calls':270,'distinct_item_blocks':45,'pooled_controls_per_arm_two_models':40}.get(k);x={'key':k,'old':prior,'new':v,'script':S,'flag':'NEW_METRIC' if prior is None else 'UNCHANGED' if prior==v else 'CHANGED'};comparisons.append(x);print(json.dumps(x))
 P=R/'app/backend_root/agent_backend/projects/classroom_dinosaur';base=read(P/'roomcontract.v2.instance.json');trace=read(P/'trace_map.v2.json');m=copy.deepcopy(base);idx=NativeRoutingIndex(m,trace);target='ENT-ASSET-DINOSAUR_SKELETON';assert target in idx.objects
 selected=('exhibit_interpreter','teacher_agent');aids=[a for a in idx.agents if idx.wire[a] in selected];assert len(aids)==2
 for a in idx.agents.values():a['groundedAsset']=[x for x in a.get('groundedAsset',[]) if x!=target]
 for aid in aids:idx.agents[aid].setdefault('groundedAsset',[]).append(target)
 raw=(json.dumps(m,sort_keys=True,indent=2)+'\n').encode();digest=serialization_digest(raw);g=verify_routing(m,trace,model_sha256=digest);req=request_for(selected[0],idx.objects[target],digest,session_id='heldout-example');session={'model_sha256':digest,'active_agent_mode':'client'}
 verdicts={'Gate0':g['routing_table'][selected[0]][target],'I1':I1.evaluate(m,trace,req,session),'I2':I2.evaluate(m,trace,req,session)}
 assert all(x.get('reason')=='E_AMBIGUOUS_OWNER' for x in verdicts.values());assert 'authored_example' not in {r['room'] for r in reference}
 example={'source_room_id':'authored_example','counterfactual':'Duplicate direct ownership of dinosaur between exhibit_interpreter and teacher_agent; no study outcome used to select example','ownership_and_handoffs':ownership_view(m),'selected_object_id':target,'active_agent_id':selected[0],'answer':{'answering_agent_id':None,'abstain':True,'reason':'E_AMBIGUOUS_OWNER'},'oracle_proof':verdicts,'model_sha256':digest}
 promptpath=Path(__file__).with_name('B1s_prompt.txt');prompt=promptpath.read_text(encoding='utf-8-sig');PINS[promptpath.relative_to(R).as_posix()]=hashlib.sha256(promptpath.read_bytes()).hexdigest()
 compact_example={'source_room_id':'authored_example','synthetic_counterfactual':True,'selected_object_id':target,'active_agent_id':selected[0],'direct_object_owner_declarations':[{'agent_id':agent,'object_id':target} for agent in selected],'correct_output':example['answer'],'explanation':'Two distinct direct object owners make the deciding level ambiguous; do not fall back to group or zone ownership.'}
 candidates=[]
 for row in requests:
  if row['baseline']!='B1':continue
  payload=copy.deepcopy(row['payload']);payload['input'][0]['content']+='\n'+prompt+'\nHELD-OUT WORKED EXAMPLE:\n'+json.dumps(compact_example,sort_keys=True,separators=(',',':'))
  payload['max_output_tokens']=128
  schema=payload['text']['format']['schema'];schema['required'].append('reason');schema['properties']['reason']={'type':['string','null'],'enum':[None,'E_UNOWNED','E_AMBIGUOUS_OWNER','E_NO_HANDOFF_PATH']}
  candidates.append({'source_item_id':row['item_id'],'room':row['room'],'variant':row['variant'],'pair_index':row['pair_index'],'target_id':row['target_id'],'start_agent':row['start_agent'],'I1':row['I1'],'baseline':'B1s','payload':payload,'input_limit':10000,'status':'CANDIDATE_ONLY_NOT_FROZEN'})
 out.mkdir(parents=True)
 (out/'heldout_full_model.instance.json').write_bytes(raw)
 save(out/'heldout_compact_prompt_example.json',compact_example)
 save(out/'denominator_audit.json',numbers);save(out/'comparisons.json',comparisons);save(out/'heldout_example.json',example);save(out/'b1s_existing_models_candidates.json',candidates);save(out/'input_pins.json',PINS)
 save(out/'execution_block.json',{'live_enabled':False,'plan_frozen':False,'models_for_new_arms':'PENDING authorized discovery and official price verification','budget':'Shared authoritative WP4 remaining; supplied1.143924USD must be reread. No reallocations.','baseline_schema_difference':'B1s adds reason and128 outputtokens vs96 old; primary classifier projects answering_agent_id/abstain, reason checked separately','gateway':'See DRAFT_STAGE_C.md; newlogs/cache sharedoldledger','heldout_output_oracle_verified':True,'prompt_example_scope':'Only selected dinosaur, two direct owners, active agent, correct answer and explanation. Full heldout model/table/oracle proof retained separately, excluded from prompt. Evaluated-room full B1 ownership context unchanged.','log_export':'Gateway Budget.record exports full ledger history to redirected local log; package a separate filtered export of delta2 experiment events only, without editing authoritative ledger or old logs.'})
 print('DRAFT_PREPARATION_COMPLETE_NO_API')
if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,default=R/'results/raw/delta2/stage_C/draft_preparation_v1');a=p.parse_args();main(a.output)

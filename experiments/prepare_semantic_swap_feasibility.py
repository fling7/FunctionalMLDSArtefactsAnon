"""Bounded unpaid token/readiness snapshot for two already completed fixed swaps."""
from pathlib import Path
from datetime import datetime,timezone
import hashlib,importlib.metadata,json,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from experiments.semantic_judge_draft import grounding,payload,MODELS,INPUT_CAP,canonical
from experiments.lib.wp4_common import profiles
import tiktoken

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def read(path):return json.loads(Path(path).read_text(encoding='utf-8-sig'))
def save(path,value):
 path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
 with path.open('x',encoding='utf8') as stream:json.dump(value,stream,indent=2,ensure_ascii=False);stream.write('\n')

def main():
 out=ROOT/'results/raw/wp6_semantic_swap_feasibility_v2';out.mkdir(exist_ok=False)
 gp=ROOT/'results/raw/wp6_swap_geometry_snapshot_004/geometry.json';geometry=read(gp);measured=[r for r in geometry['records'] if r['analysis_status']=='measured']
 assert [r['source_project'] for r in measured]==['classroom_dinosaur','scene_041_archaeology_gallery_mini_r0']
 for path,expected in geometry['code_hashes'].items():assert sha(ROOT/path)==expected,path
 enc=tiktoken.get_encoding('o200k_base');items=[];cases=[]
 for record in measured:
  case=record['source_project'];source_row=record['source_provenance'];base=ROOT/source_row['project_path'];run=ROOT/record['run_dir'];manifest=read(run/'mutation_manifest.json');meta=next(m for m in manifest['models'] if m['id']==record['model']);mutant=run/'models'/meta['storage_id']/base.name
  source_path=ROOT/source_row['case_path']/'input/source_rdl.json';assert sha(source_path)==record['source_geometry_sha256'];assert sha(base/'roomcontract.v2.instance.json')==record['baseline_model_sha256'];assert sha(mutant/'roomcontract.v2.instance.json')==record['mutant_model_sha256']
  outcome=run/'outcomes'/(meta['storage_id']+'.json');assert sha(outcome)==record['outcome_sha256'];assert read(outcome)['independent_disagreements']==[]
  source=read(source_path);before_profiles=profiles(base);after_profiles=profiles(mutant);assert before_profiles==after_profiles
  native=read(base/'roomcontract.v2.instance.json');by_id={o['id']:o for o in native['objects']};source_count=len(source['scene']['objects'])
  provenance={p.relative_to(ROOT).as_posix():sha(p) for p in [source_path,base/'agents.json',mutant/'agents.json',base/'roomcontract.v2.instance.json',mutant/'roomcontract.v2.instance.json',outcome,run/'mutation_manifest.json']}
  source_copy=out/'inputs'/case/'source_rdl.json';source_copy.parent.mkdir(parents=True,exist_ok=True)
  with source_copy.open('xb') as stream:stream.write(source_path.read_bytes())
  assert sha(source_copy)==sha(source_path)
  save(out/'inputs'/case/'before_profiles.json',before_profiles);save(out/'inputs'/case/'after_profiles.json',after_profiles)
  case_rows=[]
  for n,change in enumerate(record['lint']['changed_targets'],1):
   target=change['target'];original_id=by_id[target]['sourceId']
   for condition,owner,agent_profiles in [('before',change['before_owner'],before_profiles),('after',change['after_owner'],after_profiles)]:
    evidence=grounding(source,original_id,agent_profiles,owner);assert len(evidence['complete_room_inventory'])==source_count
    assert evidence['selected_original_object']==next(o for o in source['scene']['objects'] if o['objectId']==original_id)
    requests=[payload(evidence,model) for model in MODELS];assert requests[0]['input']==requests[1]['input']
    key=f'{case}/object{n}/{condition}';save(out/'items'/key/'grounding.json',evidence);row={'case_id':case,'target':target,'original_source_object_id':original_id,'condition':condition,'owner':owner,'source_inventory_objects':source_count,'private_readiness_key':key,'grounding_sha256':hashlib.sha256(canonical(evidence)).hexdigest(),'models':[]}
    for model,request in zip(MODELS,requests):
     file=out/'items'/key/(model+'.json');save(file,request);count=len(enc.encode(canonical(request).decode()))
     row['models'].append({'model':model,'payload_path':file.relative_to(ROOT).as_posix(),'payload_sha256':sha(file),'local_serialized_request_tokens':count,'local_estimate_exceeds_5000':count>INPUT_CAP})
    items.append(row);case_rows.append(row)
  assert len(case_rows)==4;cases.append({'case_id':case,'source_room_id':source_row['source_room_id'],'profiles_identical_before_after':True,'source_inventory_objects':source_count,'input_sha256':provenance})
 pins=['experiments/prepare_semantic_swap_feasibility.py','experiments/semantic_judge_draft.py','experiments/prompts/semantic_judges/assignment_plausibility.txt','experiments/lib/wp4_common.py','prereg/wp6_amendments/006_semantic_judges.DRAFT.md','results/raw/wp6_swap_geometry_snapshot_004/geometry.json']
 report={'utc':datetime.now(timezone.utc).isoformat(),'status':'DRAFT_FEASIBILITY_ONLY_NO_PROVIDER_CALLS_NO_FINAL_ITEM_FREEZE','fixed_swap_cases':5,'ready_cases':2,'pending_cases':[r['source_project'] for r in geometry['records'] if r['analysis_status']!='measured'],'planned_swap_items':20,'prepared_items':len(items),'prepared_two_model_requests':2*len(items),'provider_calls':0,'tokenizer':'tiktoken','tokenizer_version':importlib.metadata.version('tiktoken'),'encoding':'o200k_base','count_method':'Tokenize the complete canonical serialized request, including JSON envelope/schema. This is a local diagnostic; provider framing/schema conversion is not reproduced and this is not an authoritative input cap check.','selection_note':'The exact two completed fixed swap cases from snapshot004 only; every before/after target and both registered models preserved. No natural-item selection or final blinded ordering is performed. No prompt, source, profile, cap, budget or study selection changed.','cases':cases,'items':items,'input_sha256':{p:sha(ROOT/p) for p in pins}}
 save(out/'report.json',report);counts=[m['local_serialized_request_tokens'] for item in items for m in item['models']]
 print(json.dumps({'items':len(items),'requests':len(counts),'provider_calls':0,'local_min':min(counts),'local_max':max(counts),'local_over5000':sum(n>5000 for n in counts),'pending_cases':report['pending_cases']}),flush=True)
if __name__=='__main__':main()

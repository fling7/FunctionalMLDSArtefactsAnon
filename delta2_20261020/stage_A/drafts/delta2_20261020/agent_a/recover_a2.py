"""Recover retained deterministic assembler exceptions without model/API calls."""
import json,csv,hashlib,sys,re,socket,datetime,collections
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT))
# Fail closed if any imported dependency unexpectedly attempts a network connection.
def denied(*a,**k):raise RuntimeError('NETWORK_FORBIDDEN_STAGE_A2')
socket.create_connection=denied;socket.socket.connect=denied;socket.socket.connect_ex=denied
from tools.case_study_pipeline.roomcontract_assembler import assemble_roomcontract_instance
OUT=ROOT/'deliverables/delta2_20261020/stage_A';RAW=ROOT/'results/raw/delta2/stage_A/a2';SCRIPT='drafts/delta2_20261020/agent_a/recover_a2.py'
def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,x):assert not p.exists(),str(p);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(x,indent=2,sort_keys=True)+'\n',encoding='utf-8')
def table(p,rows):
 assert not p.exists()
 with p.open('w',encoding='utf-8',newline='')as f:w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
started=datetime.datetime.now(datetime.timezone.utc).isoformat();pins=[]
for planpath in ['prereg/wp5_plan.json','prereg/wp5_extension_v1/plan.json']:
 p=ROOT/planpath;plan=read(p)
 for rel in ['tools/case_study_pipeline/roomcontract_assembler.py','tools/case_study_pipeline/common.py','tools/case_study_pipeline/agent_roles.py']:
  current=sha(ROOT/rel);expected=plan['implementation_sha256'][rel];assert current==expected,(rel,current,expected);pins.append({'plan':planpath,'plan_sha256':sha(p),'path':rel,'historical_expected_sha256':expected,'current_sha256':current,'match':True})
rows=[];input_manifest=[]
for p in sorted((ROOT/'data/go_sprint/pipeline_runs').glob('*.jsonl')):
 input_manifest.append({'path':p.relative_to(ROOT).as_posix(),'sha256':sha(p)})
 for line,l in enumerate(p.read_text().splitlines(),1):rows.append((json.loads(l),p.relative_to(ROOT).as_posix(),line))
all_results=[]
required={'normalized_scene':'scene_graph.normalized.json','scene_semantics':'scene_semantics.json','agent_roles':'agent_roles.generated.json'}
for r,sourcefile,line in rows:
 if r.get('failure_stage')!='roomcontract_assembly':continue
 cid=r['case_id'];phase=r.get('source',{}).get('phase','unknown');cohort='drift'if phase=='drift'else'guided'if cid.startswith('guided_llm_')else'other'
 inputs={};evidence=[];missing=[];avail={}
 for filename in [*required.values(),'knowledge.generated.json','agent_placements.json','handoff_matrix.json']:
  candidates=[(rel,h)for rel,h in r.get('artifact_sha256',{}).items()if '/roomcontract_assembly/after_stage/intermediate/'in rel and rel.endswith('/'+filename)]
  valid=[]
  for rel,h in candidates:
   p=ROOT/rel
   if p.exists()and sha(p)==h:valid.append((rel,h))
  avail[filename]=bool(valid)
  if valid:
   rel,h=valid[0];evidence.append({'path':rel,'sha256':h,'filename':filename});inputs[filename]=read(ROOT/rel)
  elif filename in required.values():missing.append(filename)
 result={'case_id':cid,'source_phase':phase,'cohort':cohort,'source_record':sourcefile,'source_line':line,'original_error_code':'ValueError','input_availability':avail,'inputs':evidence,'missing_required_inputs':missing,'assembler_scope':'Exact historically pinned pure assemble_roomcontract_instance; same three JSON inputs used by the case wrapper. Knowledge and placements retention checked, but pure assembler does not consume them. No new native validator/pipeline/model runs.'}
 if missing:result.update(status='UNRECOVERABLE',category='UNRECOVERABLE',exception_type=None,exception_text=None)
 else:
  try:
   instance=assemble_roomcontract_instance(case_id=cid,**{key:inputs[name]for key,name in required.items()});result.update(status='REPLAY_DID_NOT_REPRODUCE',category='other',exception_type=None,exception_text=None,assembled_instance_sha256=hashlib.sha256(json.dumps(instance,sort_keys=True).encode()).hexdigest())
  except Exception as exc:
   text=str(exc);assert str(ROOT)not in text and ('C:'+chr(92)+'Users'+chr(92))not in text,text
   category='duplicate_asset_owner'if re.search(r'ambiguous asset owners|duplicate.*owner|multiple.*owner',text,re.I)else'unowned_object'if re.search(r'unowned|no explicitly grounded scene object|no owner|without.*owner',text,re.I)else'dangling_handoff'if re.search(r'handoff.*(?:missing|unknown|dangling|not found)|(?:missing|unknown|dangling).*handoff',text,re.I)else'schema_format'if isinstance(exc,(KeyError,TypeError,json.JSONDecodeError))or re.search(r'schema|format|collapse to interaction token',text,re.I)else'other'
   result.update(status='RECOVERED_EXCEPTION',category=category,exception_type=type(exc).__name__,exception_text=text)
 save(RAW/(cid+'.json'),result);all_results.append(result);print(cid,result['status'],result['category'],flush=True)
nums={};changes=[]
def num(k,v,old='NOT_REPORTED'):
 nums[k]=v;x={'key':k,'old':old,'new':v,'changed':old!=v,'script':SCRIPT};changes.append(x);print(json.dumps(x),flush=True)
num('pipeline_attempt_records',len(rows),296);num('pipeline_attempted_failures',sum(r.get('status')=='failed'and r.get('failure_stage')!='not_attempted'for r,_,_ in rows),118);num('pipeline_not_attempted_records',sum(r.get('failure_stage')=='not_attempted'for r,_,_ in rows),37);num('pipeline_success_records',sum(r.get('status')=='success'for r,_,_ in rows),141);num('assembly_failures_total',len(all_results),86)
summary=[]
for cohort in ['all','drift','guided','other']:
 rr=[r for r in all_results if cohort=='all'or r['cohort']==cohort]
 for cat in ['duplicate_asset_owner','unowned_object','dangling_handoff','schema_format','other','UNRECOVERABLE']:
  n=sum(r['category']==cat for r in rr);summary.append({'cohort':cohort,'category':cat,'count':n,'cohort_assembly_failures':len(rr),'overall_assembly_failures':len(all_results),'all_attempted_pipeline_failures':nums['pipeline_attempted_failures'],'all_pipeline_records':len(rows)});num('assembly_'+cohort+'_'+cat,n)
for status in ['RECOVERED_EXCEPTION','UNRECOVERABLE','REPLAY_DID_NOT_REPRODUCE']:num('assembly_status_'+status,sum(r['status']==status for r in all_results),86 if status=='UNRECOVERABLE'else'NOT_REPORTED')
for filename in [*required.values(),'knowledge.generated.json','agent_placements.json','handoff_matrix.json']:num('assembly_retained_'+filename.replace('.','_'),sum(r['input_availability'][filename]for r in all_results))
flat=[{k:r.get(k)for k in ['case_id','source_phase','cohort','status','category','exception_type','exception_text','source_record','source_line']}for r in all_results]
table(OUT/'tables/A2_assembly_failure_recovery.csv',flat);table(OUT/'tables/A2_assembly_failure_counts.csv',summary)
phase=[]
for ph in sorted({r['source_phase']for r in all_results}):
 for cat in sorted({r['category']for r in all_results}):phase.append({'source_phase':ph,'category':cat,'count':sum(r['source_phase']==ph and r['category']==cat for r in all_results)})
table(OUT/'tables/A2_assembly_failure_by_source_phase.csv',phase)
save(OUT/'numbers_a2.json',nums);save(OUT/'review/changes_a2.json',changes);save(OUT/'review/a2_recovery_proof.json',{'started_utc':started,'finished_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'script':SCRIPT,'script_sha256':sha(ROOT/SCRIPT),'historical_implementation_pins':pins,'input_manifest':input_manifest,'raw_result_manifest':[{'path':p.relative_to(ROOT).as_posix(),'sha256':sha(p)}for p in sorted(RAW.glob('*.json'))],'network':'forbidden by socket guards; no model or API calls','extra_spend_usd':0})
notes='''# A2 Deterministic assembly recovery\n\nDONE. Replayed only the pure deterministic historical assembler on retained, hash-verified normalized scene, scene semantics and agent roles. Knowledge, placements and handoff-file availability were also checked; those are not inputs consumed by this pure function. The assembler, common helper and agent-role helper SHA256 match both the original WP5 and extension preregistered implementation pins. No contemporary replacement was substituted; no model/API calls or optimization occurred.\n\nThe 296 retained pipeline records comprise141 success records,118 attempted failures and37 not-attempted records. The 86 assembly failures are a subset of the118 attempted failures; remaining attempted failures are29 scene-semantics and3 agent-role failures. Drift and guided cohorts are subsets of those86, not additional failed attempts. Guided cohort is selected by guided_llm case-ID lineage (including completion runs); drift by source.phase=drift. Exact cases and source phases are tabulated. Recovered semantic faults are observed in retained pipeline outputs, not injected mutations, but these source scenes are synthetic and authoring attempts are dependent; this is not a deployment-prevalence estimate. The captured exception is the first assembler refusal, not an exhaustive inventory of every fault.\n\n'''+ '\n'.join(f'- {k}: {v}'for k,v in nums.items())+'\n'
p=OUT/'item_notes_a2.md';assert not p.exists();p.write_text(notes,encoding='utf-8')

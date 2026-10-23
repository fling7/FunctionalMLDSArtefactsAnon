"""Offline addendum C/D: retained failure messages and source provenance only."""
import json,csv,re,hashlib,collections
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];OUT=ROOT/'deliverables/delta_20261020';SCRIPT='drafts/delta_20261020/agent_a/addendum_cd.py'
def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def save(rel,x):
 p=OUT/rel;assert not p.exists();p.write_text(json.dumps(x,indent=2,sort_keys=True)+'\n',encoding='utf-8')
def table(rel,rows):
 p=OUT/rel;assert not p.exists()
 with p.open('w',encoding='utf-8',newline='')as f:w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
nums={};changes=[]
def num(k,v,old='NOT_REPORTED'):
 nums[k]=v;x={'key':k,'old':old,'new':v,'changed':old!=v,'script':SCRIPT};changes.append(x);print(json.dumps(x),flush=True)
phases={'roomcontract_assembly':86,'scene_semantics':29,'agent_roles':3}
patterns={'duplicate_asset_owner':r'duplicate[_ -]asset[_ -]owner|multiple\s+owners|more than one\s+owner|ambiguous\s+owner|owned by (?:multiple|more than one)', 'unowned_object':r'unowned|no\s+owner|without\s+(?:an?\s+)?owner|missing\s+owner', 'dangling_handoff':r'dangling[_ -]handoff|(?:handoff.{0,60}(?:unresolved|unknown|missing|nonexistent|not found))|(?:unresolved.{0,60}handoff)'}
rr=[]
for p in sorted((ROOT/'data/go_sprint/pipeline_runs').glob('*.jsonl')):
 for i,l in enumerate(p.read_text().splitlines(),1):
  r=json.loads(l)
  if r.get('failure_stage')not in phases:continue
  phase=r['failure_stage'];st=[s for s in r.get('stages',[])if s.get('stage')==phase];messages=[];codes=[]
  for s in st:
   if s.get('error_code'):codes.append(s['error_code'])
   val=s.get('result',{}).get('validation',{})
   for e in val.get('errors',[]):messages.append(e if isinstance(e,str)else json.dumps(e,ensure_ascii=False,sort_keys=True))
   for key in ('error','error_message','message','reason'):
    if isinstance(s.get('result',{}).get(key),str):messages.append(s['result'][key])
  text='\n'.join(messages);matched=[k for k,pat in patterns.items()if re.search(pat,text,re.I)];categories=matched or(['other']if text else['unclassified'])
  # Preserve exact harmless messages; only local absolute root could be redacted.
  safe=text.replace(str(ROOT),'[WORKSPACE]').replace(ROOT.as_posix(),'[WORKSPACE]')
  rr.append({'case_id':r['case_id'],'phase':phase,'categories':';'.join(categories),'error_codes':';'.join(codes),'retained_messages':safe,'message_redacted':safe!=text,'message_available':bool(messages),'evidence_path':p.relative_to(ROOT).as_posix(),'evidence_line':i,'interpretation':'Exception type retained without refusal message; no semantic attribution possible'if not messages else'Regex classification of retained final-stage messages only'})
summary=[]
for phase,expected in phases.items():
 subset=[r for r in rr if r['phase']==phase];assert len(subset)==expected;num('pipeline_failure_attempts_'+phase,len(subset),expected)
 for cat in [*patterns,'other','unclassified']:
  count=sum(cat in r['categories'].split(';')for r in subset);summary.append({'phase':phase,'category':cat,'attempts':count,'phase_attempts':len(subset),'counting_unit':'pipeline attempt; semantic categories may overlap; other/unclassified exclusive'});num('pipeline_failure_'+phase+'_'+cat,count)
table('tables/T3d_pipeline_failure_reasons.csv',summary);table('tables/T3d_pipeline_failure_messages.csv',rr);save('review/addendum_cd_regex.json',{'patterns':patterns,'other':'Detailed retained message does not match specified semantic patterns (includes infrastructure and output-format failures).','unclassified':'No detailed retained message; an exception name is insufficient.','extraction':'Only terminal failed stage validation.errors/error/error_message/message/reason; no inference from intermediate data or a new assembly run.'})
lineage=list(csv.DictReader((OUT/'tables/T3b_source_lineage.csv').open(encoding='utf-8')));base=sorted({r['base_source']for r in lineage});raw={r['raw_source_id']for r in lineage};num('confirmed_native_models',len(lineage),134);num('confirmed_raw_native_source_ids',len(raw),59);num('confirmed_native_base_sources',len(base),56);num('confirmed_edit_source_variants',len(raw)-len(base),3)
scene={r['scene_id']:r for r in read(ROOT/'experiments/scenes/sources/manifest.json')['scenes']};ext={r['source_id']:r for r in read(ROOT/'prereg/wp5_extension_v1/accepted_sources.json')['slots']};sources=[]
for b in base:
 if b in scene:
  r=scene[b];assert r['provenance']=='deterministic_synthetic_generator';origin='deterministic';family=r['provenance'];evidence='experiments/scenes/sources/manifest.json';sourcepath=r['path'];sha=r['sha256'];scope='Deterministically generated source geometry/content; downstream native pipeline uses retained LLM generations.'
 elif b in ext:
  r=ext[b];assert r['status']=='accepted';family=r['family'];origin='deterministic'if family=='extension_deterministic'else'LLM_written';evidence='prereg/wp5_extension_v1/accepted_sources.json';sourcepath=r['source_path'];sha=r['source_sha256'];scope='Registered extension source authoring family; downstream native pipeline uses retained LLM generations.'
 else:
  evidence='results/raw/wp5_guided_source_authoring_v2/'+b+'/result.json';r=read(ROOT/evidence);assert r['status']=='accepted'and r['family']=='guided_llm_source_v2';origin='LLM_written';family=r['family'];scope=r['guidance'];sourcepath=r.get('source_path',r.get('accepted_source_path'));sha=r.get('source_sha256')
  if not sourcepath:sourcepath='results/raw/wp5_guided_source_authoring_v2/'+b+'/accepted_source.json'
  if not sha:sha=r['artifact_sha256'][sourcepath]
 assert hashlib.sha256((ROOT/sourcepath).read_bytes()).hexdigest()==sha,(b,sourcepath)
 sources.append({'base_source':b,'source_origin':origin,'family':family,'native_models':sum(r['base_source']==b for r in lineage),'source_id_labels':len({r['raw_source_id']for r in lineage if r['base_source']==b}),'provenance_record':evidence,'source_path':sourcepath,'source_sha256':sha,'scope':scope})
table('tables/T3e_native_source_provenance.csv',sources)
for origin in('deterministic','LLM_written'):
 num('native_base_sources_'+origin,sum(r['source_origin']==origin for r in sources));num('native_models_from_'+origin+'_sources',sum(r['native_models']for r in sources if r['source_origin']==origin))
num('pipeline_failure_message_redactions',sum(r['message_redacted']for r in rr));save('numbers_addendum_cd.json',nums);save('review/changes_addendum_cd.json',changes)
notes='''# Addendum C/D\n\nC DONE with retained-evidence limitation. The requested 86 assembly +29 scene-semantics +3 agent-role failed attempts are all accounted for in T3d. Classification applies conservative regexes to retained terminal-stage messages only; category counts may overlap if a message has multiple semantic faults. Other includes explicit infrastructure/JSON/schema failures; unclassified means no detailed refusal message was retained. All 86 assembly checkpoints store only error_code ValueError, not the exception text (the original pipeline catch handler retained the exception class only); consequently all 86 remain unclassified rather than being guessed as duplicate ownership. Exact safe messages/codes are preserved in the row-level table, with input file/line provenance. No new assembly or model run was attempted.\n\nD DONE. 134 audited native model records map to59 literal source IDs and56 base sources; three additional edit IDs derive from the astronomy-gallery base. The source-level provenance table joins retained registries and verifies each source file hash. Source authoring must be distinguished from downstream native pipeline authoring: deterministic source scenes can still feed LLM-driven native generation. Guided LLM sources use a fixed geometric scaffold, with model-written full source JSON/domain content; they are not unconstrained natural scenes.\n\n'''+ '\n'.join(f'- {k}: {v}'for k,v in nums.items())+'\n'
p=OUT/'item_notes_addendum_cd.md';assert not p.exists();p.write_text(notes,encoding='utf-8')

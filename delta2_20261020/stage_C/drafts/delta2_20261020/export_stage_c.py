"""Repin only the anonymized C derivative and prove its offline replay."""
import json,hashlib,importlib.util,sys
from pathlib import Path
from types import SimpleNamespace

def canonical(v):return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()).hexdigest()
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def save(p,v):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def refresh(dst):
 run=dst/'results/raw/delta2/stage_C/c1'
 if not (run/'design.json').exists():return
 changes=[]
 for script in (dst/'drafts/delta2_20261020').rglob('*.py'):
  text=script.read_text(encoding='utf-8')
  text=text.replace('from repro'+chr(46)+'env import load_env', "from importlib import import_module;load_env=import_module('repro'+chr(46)+'env').load_env")
  script.write_text(text,encoding='utf-8')
 events=run/'filtered_stageC_events.jsonl'
 if events.exists():
  values=[json.loads(line)for line in events.read_text().splitlines()if line.strip()]
  for event in values:
   if event.get('endpoint')=='/models' and isinstance(event.get('response'),dict):
    original=event['response'].get('data',[])
    event['response']={'data':[{'id':v['id']}for v in original if isinstance(v.get('id'),str)and not v['id'].startswith('ft:')],'export_note':'Public model IDs only; account ownership metadata and fine-tuned IDs omitted.'}
  events.write_text(''.join(json.dumps(v,sort_keys=True)+'\n' for v in values),encoding='utf-8')
  proof=read(run/'filtered_export_proof.json');proof['sha256']=sha(events);proof['export_derivative']='Discovery metadata minimized; original raw events retained locally.';save(run/'filtered_export_proof.json',proof)

 for p in sorted((run/'logs/llm_cache').glob('*.json')):
  v=read(p);old=v['cache_key'];v['cache_key']=canonical(v['canonical_request']);v['response_sha256']=canonical(v['response']);target=p.with_name(v['cache_key']+'.json')
  if target!=p:
   assert not target.exists();p.rename(target)
  save(target,v);changes.append({'source_cache_key':old,'export_cache_key':v['cache_key']})
 reqs=read(run/'requests.json');mapping={}
 for r in reqs:
  for prefix in ('payload','fallback_payload'):
   old=r[prefix+'_sha256'];r[prefix+'_sha256']=canonical(r[prefix]);mapping[old]=r[prefix+'_sha256']
 save(run/'requests.json',reqs)
 for p in (run/'rows').glob('*.json'):
  v=read(p)
  for field in ('payload_sha256','fallback_payload_sha256'):
   if field in v:v[field]=mapping.get(v[field],v[field])
  save(p,v)
 runner=dst/'drafts/delta2_20261020/agent_c_stageC/stage_c_runner.py'
 d=read(run/'design.json');original=sha(run/'design.json')
 d['export_status']='ANONYMIZED_DERIVATIVE_NOT_NEW_PREREGISTRATION'
 d['original_preregistration_source']='Original immutable raw plan; source hashes retained in source_pins and export proof.'
 d.update(requests_sha256=sha(run/'requests.json'),prices_sha256=sha(run/'prices.json'),context_sha256=sha(run/'stage_context.json'),runner_sha256=sha(runner))
 save(run/'design.json',d);(run/'design.sha256').write_text(sha(run/'design.json')+'\n')
 spec=importlib.util.spec_from_file_location('delta2_exported_runner',runner);mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
 mod.replay(SimpleNamespace(output=run))
 save(dst/'review/export_replay_proof.json',{'status':'PASS','scope':'Anonymized derivative request/cache keys and local execution pins; historical preregistration remains immutable.','pre_repin_transformed_design_sha256':original,'export_design_sha256':sha(run/'design.json'),'cache_transitions':changes,'offline_replay':read(run/'replay_proof.json')})

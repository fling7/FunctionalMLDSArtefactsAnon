"""Bounded read-only corpus audit and authored CR fallback reproduction; no campaign edits."""
from pathlib import Path
from types import SimpleNamespace
from datetime import datetime,timezone
import copy,hashlib,importlib,json,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from experiments.static_policy_compilation import static_policy_compilation
from verification.impl_b.compiled_policy import compile_model
from verification.impl_b.policy_adapter import evaluate as reference

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def read(path):return json.loads(Path(path).read_text(encoding='utf-8-sig'))
def replace(value,old,new):
 if isinstance(value,str):return new if value==old else value
 if isinstance(value,list):return [replace(x,old,new) for x in value]
 if isinstance(value,dict):return {replace(k,old,new):replace(v,old,new) for k,v in value.items()}
 return value

def main():
 out=ROOT/'results/raw/wp6_control_character_audit_v2';out.mkdir(exist_ok=False)
 fixture=ROOT/'results/raw/wp6_unit/fresh_batch_tmp_v1/fresh-authored0/projects/fresh_engineering'
 instance=read(fixture/'roomcontract.v2.instance.json');trace=read(fixture/'trace_map.v2.json')
 objects=instance['objects'];target=next(x for x in objects if x.get('entityRole')=='sceneObject');agent=next(x for x in objects if x.get('entityRole')=='interactiveAgent')
 request={'session_id':'control-character-engineering','active_agent_id':agent['sourceId'],'user_text':'Describe this object.','interaction_mode':'deictic','spatial_context':{'model_sha256':trace['model_sha256'],'state':'resolved','entity_id':target['id'],'source_object_id':target['sourceId'],'hit_position':{'x':0,'y':0,'z':0},'distance_m':1,'selection_modality':'programmatic'}}
 session={'model_sha256':trace['model_sha256'],'active_agent_mode':'client'}
 rows=[]
 for label,old in [('agent_native_id',agent['id']),('target_native_id',target['id']),('model_native_id',objects[0]['id'])]:
  new=old+'\rBOUND';i=replace(instance,old,new);t=replace(trace,old,new);r=replace(request,old,new)
  expected=reference(i,t,r,session);compile_error=None
  try:compile_model(i,t)
  except Exception as exc:compile_error={'type':type(exc).__name__,'message':str(exc)}
  matrix=SimpleNamespace(importlib=importlib);original=matrix.importlib
  with static_policy_compilation(matrix) as stats:
   fn=matrix.importlib.import_module('verification.impl_b.policy_adapter').evaluate
   actual=[fn(copy.deepcopy(i),copy.deepcopy(t),copy.deepcopy(r),copy.deepcopy(session)) for _ in range(2)]
  row={'label':label,'expected':expected,'actual_repeated':actual,'compile_error':compile_error,'bridge_diagnostics':stats,'equal':all(x==expected for x in actual),'binding_restored':matrix.importlib is original}
  rows.append(row)
  (out/(label+'.json')).write_text(json.dumps({'instance':i,'trace':t,'request':r,'session':session,'result':row},indent=2,ensure_ascii=True)+'\n',encoding='utf8')
  assert row['equal'] and row['binding_restored']
  if compile_error:assert stats['compile_fallbacks']==2 and stats['compilations']==0
 inventory=read(ROOT/'results/raw/wp6_corpus_original_terminal_v3.json')
 projects=[ROOT/row['project_path'] for row in inventory['rows'] if row.get('wp6_intake_status')=='native_artifacts_available']
 projects.append(ROOT/'app/backend_root/agent_backend/projects/classroom_dinosaur')
 for kind in ['example','generated']:
  projects+=sorted(p.parent for p in (ROOT/f'results/raw/wp6_{kind}_combined_recovery_v1/models').rglob('roomcontract.v2.instance.json'))
 controls=set('\r\v\f\x1c\x1d\x1e\x85\u2028\u2029');files=[];hits=[]
 def scan(value,pointer,path):
  if isinstance(value,str):
   found=sorted({f'U+{ord(c):04X}' for c in value if c in controls})
   if found:hits.append({'path':path,'pointer':pointer,'characters':found,'value_sha256':hashlib.sha256(value.encode()).hexdigest()})
  elif isinstance(value,list):
   for n,v in enumerate(value):scan(v,pointer+'/'+str(n),path)
  elif isinstance(value,dict):
   for k,v in value.items():scan(k,pointer+'/[key]',path);scan(v,pointer+'/'+k.replace('~','~0').replace('/','~1'),path)
 for project in projects:
  for name in ['roomcontract.v2.instance.json','trace_map.v2.json']:
   path=project/name;relative=path.relative_to(ROOT).as_posix();raw=path.read_bytes();value=json.loads(raw.decode('utf-8-sig'))
   scan(value,'',relative);assert raw==path.read_bytes();files.append({'path':relative,'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw)})
 pins=['experiments/audit_wp6_control_character_fallback.py','experiments/static_policy_compilation.py','verification/impl_b/compiled_policy.py','verification/impl_b/policy_adapter.py','verification/impl_b/admission.lp','results/raw/wp6_corpus_original_terminal_v3.json']
 report={'utc':datetime.now(timezone.utc).isoformat(),'scope':'Decoded keys and string values in native+trace of21 registered original/example baselines and759 current prepared mutant projects; excludes future extension inputs. No campaign inputs changed. No source-code inspection of independent original implementation.','engineering_rows':rows,'projects':len(projects),'files':files,'control_characters_examined':sorted(f'U+{ord(c):04X}' for c in controls),'hits':hits,'dependency_sha256':{p:sha(ROOT/p) for p in pins}}
 (out/'report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
 print(json.dumps({'projects':len(projects),'files':len(files),'hits':len(hits),'engineering':[{'label':r['label'],'compile_error':r['compile_error'],'equal':r['equal'],'fallbacks':r['bridge_diagnostics']['compile_fallbacks']} for r in rows]}),flush=True)
if __name__=='__main__':main()

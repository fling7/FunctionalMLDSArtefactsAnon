"""Reconstruct first-match and shrink a G2 counterexample; no reference is the property oracle."""
from pathlib import Path
import json,sys,random,tempfile,hashlib
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from hypothesis import find,settings,strategies as st
from experiments.lib.model_builder import build_room
from experiments.lib.backend_driver import Driver
from verification.properties import assert_admitted,commit_properties
from verification.differential import load
from backend.guard_config import GuardConfig
from tools.dynamic_functional_rdl_v2_model import MODEL
from tools.validate_dynamic_functional_rdl_v2 import validate_instance
OUT=ROOT/'results/raw/properties/firstmatch-counterexample-v1'
def base(owners):
 return {'case_id':'firstmatch_property','agents':['a0','a1'],'objects':[{'id':'o0'},{'id':'o1'}],
 'owners':{'asset':{'o0':owners,'o1':['a1']},'group':{},'zone':{}},
 'handoffs':[['a0','a1'],['a1','a0']],
 'actions':[{'target':'o0','provider':owners[0],'count':1},{'target':'o1','provider':'a1','count':1}]}
def run(owners,final=False):
 spec=base(owners)
 folder=OUT/'minimal_project' if final else Path(tempfile.mkdtemp(dir=ROOT/'results/tmp',prefix='firstmatch-'))
 built=build_room(spec,folder,allow_invalid=True);d=Driver(built.project_dir)
 try:
  target=next(t for t in d.targets if t['sourceId']=='o0');request=d.request(owners[0],target)
  d.store.guard_config=GuardConfig(routing_mode='firstmatch');bad=d.probe(request)
  caught=None
  if bad['decision']!='REJECT':
   try:assert_admitted(built.instance,built.trace,request,bad,target)
   except AssertionError as e:caught=str(e)
  row={'owners':owners,'spec':spec,'firstmatch':bad,'property_caught':caught}
  if final:
   row['structural_validator']=validate_instance(MODEL,built.instance,'First-match property counterexample').to_dict()
   d.store.guard_config=GuardConfig();row['packet']=d.probe(request)
   session={'model_sha256':d.setup['model_sha256'],'active_agent_mode':'client'}
   for name,file in [('I1','verification/impl_a/reference.py'),('I2','verification/impl_b/policy_adapter.py')]:
    module=load('property_demo_'+name,ROOT/file);row[name]=module.evaluate(built.instance,built.trace,request,session)
   (OUT/'counterexample.json').write_text(json.dumps(row,indent=2),encoding='utf-8')
  with (OUT/'search_observations.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(row)+'\n')
  return caught is not None
 finally:
  d.close()
  if not final:
   import shutil
   if not folder.resolve().is_relative_to((ROOT/"results/tmp").resolve()):raise RuntimeError("Unsafe temporary cleanup target")
   shutil.rmtree(folder)
def main():
 OUT.mkdir(parents=True,exist_ok=False)
 (OUT/'harness.py').write_bytes(Path(__file__).read_bytes())
 minimal=find(st.lists(st.sampled_from(['a0','a1']),min_size=1,max_size=2,unique=True),
              run,settings=settings(max_examples=50,deadline=None,database=None),random=random.Random(20261015))
 assert run(minimal,True)
 row=json.loads((OUT/'counterexample.json').read_text(encoding='utf-8'))
 assert row['structural_validator']['ok']
 assert row['packet']['decision']=='REJECT'
 assert row['I1']['decision']=='REJECT' and row['I2']['decision']=='REJECT'
 print(json.dumps({'minimal_owners':minimal,'structural_ok':row['structural_validator']['ok'],
  'property_detected':True,'packet_reason':row['packet']['reason'],'independents_agree':row['I1']==row['I2']}))
if __name__=='__main__':main()

"""Engineering equivalence checks for a proposed WP6 performance amendment."""
from __future__ import annotations
import copy,json
from pathlib import Path
import sys
import pytest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from experiments.mutations import Bundle,OPERATORS,mutate,refresh_projections,digest
from experiments.detection_matrix import validators,materialize,VARIANTS
from experiments.lib.model_builder import build_room
from experiments.lib.backend_driver import Driver
from experiments.static_model_memoization import static_model_memoization
from backend.guard_config import GuardConfig
from backend import roomcontract_v2_runtime as runtime


def normalized(value):
 if isinstance(value,dict):return {k:normalized(v) for k,v in value.items() if k not in {'generated_at','elapsed_ms'}}
 if isinstance(value,(list,tuple)):return [normalized(v) for v in value]
 return value


@pytest.fixture(scope='module')
def room(tmp_path_factory):
 built=build_room({'case_id':'memo_unit','agents':['a','b','c'],'objects':['one','two','three'],'owners':{'asset':{'one':['a'],'two':['b'],'three':['c']},'group':{'group_a':['a']},'zone':{'zone_a':['a']}},'handoffs':[['a','b'],['b','a'],['b','c'],['c','b']]},tmp_path_factory.mktemp('memo-room'))
 return Bundle.load(built.project_dir)


@pytest.mark.parametrize('operator',['baseline',*OPERATORS])
def test_every_checker_report_equivalent(room,operator):
 bundle=room if operator=='baseline' else refresh_projections(mutate(room,operator,20261015)[0])
 before=copy.deepcopy(bundle)
 baseline=validators(bundle)
 with static_model_memoization() as stats:
  accelerated=validators(bundle)
  repeated=validators(bundle)
 assert normalized(baseline)==normalized(accelerated)==normalized(repeated)
 assert bundle==before
 assert stats['subtype_hits']>0


def test_cache_keys_cover_trace_native_index_and_digest(room):
 args=[copy.deepcopy(room.trace),{o['id']:copy.deepcopy(o) for o in room.instance['objects']},digest(room.instance),copy.deepcopy(room.instance)]
 with static_model_memoization() as stats:
  runtime._validate_v2_trace(*args);runtime._validate_v2_trace(*copy.deepcopy(args));assert stats['trace_hits']==1
  for index in range(4):
   changed=copy.deepcopy(args)
   if index==0:changed[0]['case_id']='wrong'
   elif index==1:changed[1].pop(next(k for k,v in changed[1].items() if v.get('type')=='CapabilityUse'))
   elif index==2:changed[2]='0'*64
   else:changed[3]['caseId']='wrong'
   misses=stats['trace_misses'];hits=stats['trace_hits']
   try:runtime._validate_v2_trace(*changed)
   except Exception:pass
   assert stats['trace_misses']==misses+1 and stats['trace_hits']==hits


def test_context_restores_original_functions_on_error():
 from tools import validate_dynamic_functional_rdl_v2 as structural
 originals=(structural.ModelIndex.is_subclass,structural.InstanceValidator._of_type,runtime._validate_v2_trace)
 with pytest.raises(RuntimeError):
  with static_model_memoization():raise RuntimeError('test')
 assert originals==(structural.ModelIndex.is_subclass,structural.InstanceValidator._of_type,runtime._validate_v2_trace)


@pytest.mark.parametrize('operator',['baseline','move_owner_without_path','duplicate_asset_owner','remove_all_owners','duplicate_action','rename_agent_dangling'])
def test_backend_every_pair_and_variant_equivalent(room,operator,tmp_path):
 bundle=room if operator=='baseline' else refresh_projections(mutate(room,operator,20261015)[0])
 project=tmp_path/'projects'/'memo_unit';materialize(Path(room.source),bundle,project)
 def execute():
  try:driver=Driver(project)
  except Exception as exc:return {'setup_exception':type(exc).__name__,'reason':getattr(exc,'code',None),'message':str(exc)}
  try:
   outcomes=[]
   for agent in [o['sourceAgentId'] for o in bundle.instance['objects'] if o.get('type')=='Agent']:
    for target in driver.targets:
     for config in VARIANTS.values():
      driver.store.guard_config=GuardConfig(**config)
      outcomes.append(driver.probe(driver.request(agent,target)))
     for config in [{},{'digest_check':False}]:
      driver.store.guard_config=GuardConfig(**config)
      outcomes.append(driver.probe(driver.request(agent,target,'stale_digest')))
   return outcomes
  finally:driver.close()
 baseline=execute()
 with static_model_memoization():accelerated=execute()
 assert baseline==accelerated

"""Cache invalidation and fresh-publication-read checks for draft acceleration."""
from __future__ import annotations
import copy,json
from pathlib import Path
import sys
import pytest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from experiments.lib.model_builder import build_room
from experiments.mutations import Bundle,digest
from experiments.static_model_memoization import static_model_memoization
from experiments.lib.backend_driver import Driver
from backend import roomcontract_v2_runtime as runtime


@pytest.fixture(scope='module')
def room(tmp_path_factory):
 built=build_room({'case_id':'memo_freshness','agents':['a','b'],'objects':['one','two'],'owners':{'asset':{'one':['a'],'two':['b']}},'handoffs':[['a','b'],['b','a']]},tmp_path_factory.mktemp('memo-freshness'))
 return Bundle.load(built.project_dir)


def result(fn,args):
 try:return ('return',fn(*copy.deepcopy(args)))
 except Exception as exc:return ('raise',type(exc).__name__,getattr(exc,'code',None),str(exc))


@pytest.mark.parametrize('argument',['trace','by_id','digest','instance'])
def test_invalid_valid_transitions_match_original_and_never_cache_failures(room,argument):
 valid=[room.trace,{o['id']:o for o in room.instance['objects']},digest(room.instance),room.instance]
 invalid=copy.deepcopy(valid)
 if argument=='trace':invalid[0]['case_id']='wrong'
 elif argument=='by_id':invalid[1].pop(next(k for k,v in invalid[1].items() if v.get('type')=='CapabilityUse'))
 elif argument=='digest':invalid[2]='0'*64
 else:invalid[3]['caseId']='wrong'
 original=runtime._validate_v2_trace
 expected_invalid=result(original,invalid);expected_valid=result(original,valid)
 assert expected_invalid[0]=='raise' and expected_valid==('return',None)
 with static_model_memoization() as stats:
  # Invalid -> invalid -> valid -> valid -> invalid -> valid.
  for args,expected in [(invalid,expected_invalid),(invalid,expected_invalid),(valid,expected_valid),(valid,expected_valid),(invalid,expected_invalid),(valid,expected_valid)]:
   assert result(runtime._validate_v2_trace,args)==expected
  assert stats['trace_misses']==4 and stats['trace_hits']==2 and stats['trace_failures_not_cached']==3


def test_loader_rereads_changed_trace_and_native_files(room):
 with static_model_memoization() as stats:
  driver=Driver(Path(room.source))
  try:
   runtime.load_project_contract(driver.project)
   trace=driver.project/'trace_map.v2.json';instance=driver.project/'roomcontract.v2.instance.json'
   trace_before=trace.read_bytes();instance_before=instance.read_bytes()
   try:
    changed=json.loads(trace_before);changed['case_id']='wrong';trace.write_text(json.dumps(changed),encoding='utf-8')
    with pytest.raises(Exception):runtime.load_project_contract(driver.project)
    trace.write_bytes(trace_before);runtime.load_project_contract(driver.project)
    changed=json.loads(instance_before);changed['caseId']='wrong';instance.write_text(json.dumps(changed),encoding='utf-8')
    with pytest.raises(Exception):runtime.load_project_contract(driver.project)
    instance.write_bytes(instance_before);runtime.load_project_contract(driver.project)
   finally:trace.write_bytes(trace_before);instance.write_bytes(instance_before)
   assert stats['trace_hits']>0 and stats['trace_failures_not_cached']>0
  finally:driver.close()

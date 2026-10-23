"""WP4 harness unit tests only. No network/model evaluation or model evidence."""
import copy,json
import pytest
from experiments.routing_baselines import router_payload,classify
from experiments.guarded_llm_turns import ExperimentalClient,serving,valid_model_answer
from experiments.lib.backend_driver import Driver,http_json
from experiments.lib.wp4_common import ownership_view,profiles,classified_probe,BACKEND
from backend.guard_config import GuardConfig
from experiments.analyze_wp4 import cluster_rate,exact_mcnemar

@pytest.fixture
def driver():
    d=Driver()
    try:yield d
    finally:d.close()

def room_item(d):
    t=d.targets[0];owner=next(a['sourceAgentId'] for a in d.contract['instance']['objects'] if a.get('type')=='Agent' and t['id'] in a.get('groundedAsset',[]))
    return {'instance':d.contract['instance'],'agent_profiles':profiles(d.project)},{'target':t,'start_agent':owner}

@pytest.mark.parametrize('abstain',[False,True])
@pytest.mark.parametrize('phrasing',[1,2,3])
def test_complete_information_difference_only(driver,abstain,phrasing):
    room,item=room_item(driver)
    b0=router_payload(room,item,'Question','B0',abstain,phrasing,'gpt-4.1-mini-2025-04-14')
    b1=router_payload(room,item,'Question','B1',abstain,phrasing,'gpt-4.1-mini-2025-04-14')
    c0=json.loads(b0['input'][1]['content']);c1=json.loads(b1['input'][1]['content'])
    view=c1.pop('ownership_and_handoffs');assert c0==c1
    assert len(view['objects'])==len(driver.targets)
    assert len(view['agents'])==len(driver.setup['agents'])
    assert b0['input'][0]==b1['input'][0] and b0['text']==b1['text']
    assert not any('grounded' in k or 'responsib' in k or 'handoff' in k for p in c0['agents'] for k in p)

@pytest.mark.parametrize('parsed,verdict,allowed,expected',[
 ({'answering_agent_id':'a','abstain':False},{'decision':'ANSWER_LOCAL','provider':'a'},True,'CORRECT'),
 ({'answering_agent_id':'b','abstain':False},{'decision':'ANSWER_LOCAL','provider':'a'},True,'WRONG_PROVIDER'),
 ({'answering_agent_id':None,'abstain':True},{'decision':'ANSWER_LOCAL','provider':'a'},True,'WRONG_PROVIDER'),
 ({'answering_agent_id':None,'abstain':True},{'decision':'REJECT'},True,'ABSTAIN_OK'),
 ({'answering_agent_id':'a','abstain':False},{'decision':'REJECT'},False,'SILENT_VIOLATION'),
 ({'answering_agent_id':None,'abstain':True},{'decision':'REJECT'},False,'FORMAT_ERROR'),
 ({'answering_agent_id':'unknown','abstain':False},{'decision':'REJECT'},True,'FORMAT_ERROR'),
 ({'answering_agent_id':'a','abstain':'false'},{'decision':'REJECT'},True,'FORMAT_ERROR'),
 (None,{'decision':'REJECT'},True,'FORMAT_ERROR')])
def test_outcomes(parsed,verdict,allowed,expected):assert classify(parsed,verdict,['a','b'],allowed)==expected

class UnitGateway:
    def __init__(self,proposal=None,error=None):self.requests=[];self.proposal=proposal;self.error=error
    def responses(self,payload,**kwargs):
        self.requests.append(copy.deepcopy(payload))
        if self.error:
            from repro.llm import GatewayError
            raise GatewayError(self.error,'Unit test only')
        answer={'say':'Unit test answer','handoff_to':self.proposal,'handoff_reason':None,'handoff_brief':None,'confidence':.5}
        return {'id':'unit-stub','model':payload['model'],'status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':json.dumps(answer)}]}],'usage':{'input_tokens':0,'output_tokens':0}}

@pytest.mark.parametrize('mode',['abort','drop_log'])
def test_actual_http_fallback_channel_and_policy(driver,mode):
    room,item=room_item(driver);gateway=UnitGateway('unmodeled_target');client=ExperimentalClient(gateway)
    client.configure({'model':'gpt-4.1-mini-2025-04-14','channel':'fallback','temperature':0,'identity':'unit.http','agents':room['agent_profiles']})
    driver.store.openai=client;driver.store.guard_config=GuardConfig(proposal_mode=mode)
    snapshot=driver.store.snapshot_session_mutation(driver.session.session_id)
    with serving(driver.store) as url:status,out=http_json(url,'/chat',driver.request(item['start_agent'],item['target']))
    assert client.forced_schema_bypass==1 and len(gateway.requests)==1 and gateway.requests[0]['text']['format']['type']=='json_object'
    assert valid_model_answer(client.calls[0])
    if mode=='abort':assert status==400 and out['code']=='E_HANDOFF_PROPOSAL' and snapshot==driver.store.snapshot_session_mutation(driver.session.session_id)
    else:assert status==200


def test_api_error_committed_fallback_is_not_real_generation(driver):
    room,item=room_item(driver);client=ExperimentalClient(UnitGateway(error='INPUT_TOKEN_LIMIT'))
    client.configure({'model':'gpt-4.1-mini-2025-04-14','channel':'constrained','temperature':.3,'identity':'unit.error','agents':room['agent_profiles']})
    driver.store.openai=client
    with serving(driver.store) as url:status,out=http_json(url,'/chat',driver.request(item['start_agent'],item['target']))
    assert status==200 and client.calls[0]['status']=='INPUT_TOKEN_LIMIT' and not valid_model_answer(client.calls[0])


def test_room_cluster_not_probe_pool():
    rows=[{'source_room_id':'a','bad':True}]*10+[{'source_room_id':'b','bad':False}]
    r=cluster_rate(rows,'bad');assert r['rooms']==2 and r['rate']==.5
    assert exact_mcnemar(0,0)==1 and exact_mcnemar(0,5)==.0625


def test_native_B2_stops_before_generation_without_stub_response(driver):
    from experiments.lib.wp4_common import native_admission
    room,item=room_item(driver)
    verdict=native_admission(driver,driver.request(item['start_agent'],item['target']))
    assert verdict['decision']=='ANSWER_LOCAL' and verdict['provider']==item['start_agent']
    assert verdict['state_unchanged'] and driver.client.calls==0 and verdict['action']


def test_loopback_timeout_covers_registered_gateway_attempts():
    from experiments.guarded_llm_turns import HTTP_TIMEOUT_SECONDS
    assert HTTP_TIMEOUT_SECONDS > 5*60+sum((1,2,4,8))


def test_no_valid_calls_cannot_count_as_complete_room():
    from experiments.analyze_wp4 import routing_coverage,tex
    rows=[{'source_room_id':'r','split':'evaluation','baseline':'B2','model':'deterministic_native_guard','question_kind':'neutral','repetition':0,'status':'SUCCESS','outcome':'CORRECT'}]
    coverage=routing_coverage(rows)
    assert len(coverage)==2 and all(r['missing_cells']==12 and not r['complete_valid_block'] for r in coverage)


def test_tex_uses_literal_booktabs_rules(tmp_path):
    from experiments.analyze_wp4 import tex
    path=tmp_path/'table.tex';tex(path,[{'model':'gpt-4.1-mini-2025-04-14','rooms':2}],('model','rooms'),'Unit-only table')
    text=path.read_text();assert all(chr(92)+s in text for s in ('toprule','midrule','bottomrule'))
    assert chr(8) not in text and chr(9) not in text

import pytest
from experiments.lib.backend_driver import Driver
from backend.roomcontract_v2_runtime import RoomContractContractError,select_runtime_action
@pytest.fixture(scope='module')
def driver():
    d=Driver();yield d;d.close()
@pytest.mark.parametrize('variant,code',[('stale_digest','E_STALE_DIGEST'),('unknown_entity','E_UNKNOWN_ENTITY'),('mismatch_source','E_ID_MISMATCH'),('none','E_SELECTION_STATE'),('ambiguous','E_SELECTION_STATE'),('ambiguity_flag','E_SELECTION_STATE'),('candidate_conflict','E_SELECTION_STATE')])
def test_identity_reasons_without_side_effects(driver,variant,code):
    row=driver.probe(driver.request(driver.setup['agents'][0]['id'],driver.targets[0],variant))
    assert row['reason']==code
    assert row['model_calls']==0
    assert row['unchanged_before_restore']
def test_unknown_active_agent(driver):
    row=driver.probe(driver.request('missing',driver.targets[0]))
    assert row['reason']=='E_ACTIVE_AGENT_UNKNOWN'
    assert row['model_calls']==0 and row['unchanged_before_restore']
def test_action_cardinality_codes():
    with pytest.raises(RoomContractContractError) as exc:select_runtime_action({'runtime_actions':[]},'chat')
    assert exc.value.code=='E_NO_DECLARED_ACTION'
    with pytest.raises(RoomContractContractError) as exc:select_runtime_action({'runtime_actions':[{'action_kind':'chat'},{'action_kind':'chat'}]},'chat')
    assert exc.value.code=='E_ACTION_AMBIGUOUS'

import json
import pytest
from experiments.lib.backend_driver import Driver,ScriptedClient
from backend.guard_config import GuardConfig
from backend.roomcontract_v2_runtime import RoomContractContractError
def test_strict_active_requires_explicit_logged_switch():
    d=Driver()
    try:
        d.store.guard_config=GuardConfig(active_agent_mode='server_strict')
        other=next(a['id'] for a in d.setup['agents'] if a['id']!=d.session.server_active_agent_id)
        request=d.request(other,d.targets[0])
        row=d.probe(request)
        assert row['reason']=='E_ACTIVE_AGENT_MISMATCH'
        assert row['model_calls']==0 and row['unchanged_before_restore']
        result=d.store.switch_agent({'session_id':d.session.session_id,'active_agent_id':other})
        assert result['active_agent_id']==other and d.session.server_active_agent_id==other
        audit=[json.loads(s) for s in (d.project/'runtime_guard_audit.jsonl').read_text().splitlines()]
        assert audit[-1]['event_type']=='switch_agent' and audit[-1]['to']==other
        assert d.probe(request)['reason']!='E_ACTIVE_AGENT_MISMATCH'
    finally:d.close()
@pytest.mark.parametrize('fallback',[False,True])
@pytest.mark.parametrize('mode',['abort','drop_log'])
def test_proposal_modes_have_explicit_outcomes(mode,fallback):
    d=Driver(client=ScriptedClient(proposal='invented_target',fallback=fallback))
    try:
        d.store.guard_config=GuardConfig(proposal_mode=mode)
        target=d.targets[0]
        owner=next(x['sourceAgentId'] for x in d.contract['instance']['objects'] if x.get('type')=='Agent' and target['id'] in x.get('groundedAsset',[]))
        snapshot=d.store.snapshot_session_mutation(d.session.session_id)
        request=d.request(owner,target)
        if mode=='abort':
            with pytest.raises(RoomContractContractError) as exc:d.store.chat(request)
            assert exc.value.code=='E_HANDOFF_PROPOSAL'
            d.store.restore_session_mutation(d.session.session_id,snapshot)
            assert d.store.snapshot_session_mutation(d.session.session_id)==snapshot
        else:
            out=d.store.chat(request)
            assert out['active_agent_id']==owner and not out['handoff']
            assert out['_guard_ignored_proposals'][0]['proposed_target']=='invented_target'
        assert d.client.calls==1
    finally:d.close()
def test_no_digest_variant_is_opt_in():
    d=Driver()
    try:
        target=d.targets[0];owner=next(x['sourceAgentId'] for x in d.contract['instance']['objects'] if x.get('type')=='Agent' and target['id'] in x.get('groundedAsset',[]))
        req=d.request(owner,target,'stale_digest')
        assert d.probe(req)['reason']=='E_STALE_DIGEST'
        d.store.guard_config=GuardConfig(digest_check=False)
        assert d.probe(req)['decision']=='ANSWER_LOCAL'
    finally:d.close()

def test_table_lookup_matches_real_runtime_on_every_example_pair():
    d=Driver()
    try:
        for agent in d.setup['agents']:
            for target in d.targets:
                request=d.request(agent['id'],target)
                d.store.guard_config=GuardConfig()
                runtime=d.probe(request)
                d.store.guard_config=GuardConfig(routing_mode='table')
                table=d.probe(request)
                assert {k:runtime[k] for k in ('decision','reason','provider','action')} == {k:table[k] for k in ('decision','reason','provider','action')}
        assert d.session.routing_table is not None
    finally:d.close()

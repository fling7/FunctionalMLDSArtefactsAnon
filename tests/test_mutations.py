"""Unit fixtures validate mutation mechanics; not preregistered corpus results."""
from __future__ import annotations
import copy
import json
from pathlib import Path
import sys
import pytest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from experiments.mutations import Bundle,OPERATORS,mutate,refresh_projections,digest,mutation_plan
from experiments.detection_matrix import legacy_validation_view,validators
from experiments.lib.model_builder import build_room
from tools.routing_verifier import verify_routing
from tools.case_study_pipeline.validators.roomcontract_invariants import validate_roomcontract_invariants


@pytest.fixture(scope='module')
def room(tmp_path_factory):
    built=build_room({'case_id':'mutation_unit','agents':['a','b','c'],'objects':['one','two','three'],
      'owners':{'asset':{'one':['a'],'two':['b'],'three':['c']},'group':{'group_a':['a']},'zone':{'zone_a':['a']}},
      'handoffs':[['a','b'],['b','a'],['b','c'],['c','b']]},tmp_path_factory.mktemp('mutation-room'))
    return Bundle.load(built.project_dir)


@pytest.mark.parametrize('operator',OPERATORS)
def test_each_operator_changes_native_model(room,operator):
    changed,meta=mutate(room,operator,20261015)
    assert meta['changed']
    assert digest(changed.instance)!=digest(room.instance)
    again,second=mutate(room,operator,20261015)
    assert changed.instance==again.instance
    assert meta==second
    refreshed=refresh_projections(changed)
    assert refreshed.trace['model_sha256']==digest(refreshed.instance)
    assert refreshed.project['roomcontract_model_sha256']==digest(refreshed.instance)


def test_consistent_swap_preserves_declared_paths(room):
    changed,_=mutate(room,'swap_owners_consistently',20261015)
    refreshed=refresh_projections(changed)
    report=verify_routing(refreshed.instance,refreshed.trace,model_sha256=digest(refreshed.instance))
    assert report['ok']
    before=verify_routing(room.instance,room.trace,model_sha256=digest(room.instance))
    assert before['routing_table']!=report['routing_table']


def test_missing_action_is_not_repaired(room):
    changed,_=mutate(room,'remove_action',20261015)
    refreshed=refresh_projections(changed)
    report=verify_routing(refreshed.instance,refreshed.trace,model_sha256=digest(refreshed.instance))
    assert any(i['code']=='ROUTE077' for i in report['issues'])


def test_legacy_validation_view_preserves_known_failure(room):
    passing=validate_roomcontract_invariants(legacy_validation_view(room.instance))
    assert passing['status']=='valid'
    assert passing['metrics']['checked_element_count']>0
    changed,_=mutate(room,'remove_action',20261015)
    failure=validate_roomcontract_invariants(legacy_validation_view(changed.instance))
    assert failure['status']=='invalid'
    assert any(c['invariant_id']=='RUNTIME_BINDING_HAS_RUNTIME_ACTION' and c['status']=='invalid' for c in failure['invariants'])


def test_all_pairs_have_a_record_without_false_coverage(room):
    planned=list(mutation_plan(room))
    pairs={meta['pair_id'] for meta,_ in planned if 'pair_id' in meta}
    assert len(pairs)==len(OPERATORS)*(len(OPERATORS)-1)//2
    assert all(len(meta['changes'])==2 and all(c['changed'] for c in meta['changes']) for meta,_ in planned if meta['status']=='changed' and 'pair_id' in meta)


def test_validator_adapter_accepts_synthetic_baseline(room):
    results,_=validators(room)
    for key in ['Va_structural','Vb_native_schema','Vb_native_domain','Vb_trace_schema','Vb_legacy_invariants_view','Vb_handoff_metrics','Vc_instance','Vc_trace','Gate0']:
        assert results[key]['status']=='pass',(key,results[key])

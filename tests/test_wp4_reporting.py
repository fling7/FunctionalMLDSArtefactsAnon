"""Offline report QA only. Every input is an explicitly fabricated engineering fixture."""
from decimal import Decimal
from pathlib import Path
import json
import socket
import pytest
from experiments.wp4_report_engineering import make_fixture
from experiments.analyze_wp4 import replay,read_rows,summarize_routing
from experiments.lib.wp4_reporting import ENGINEERING,attach_costs,cost_summary,denominators,question_summary,read,retained_accounting

@pytest.fixture
def fixture(tmp_path):return make_fixture(tmp_path/'ENGINEERING_INPUTS')


def test_wholly_missing_room_remains_in_expected_coverage(fixture):
    rows=read_rows(fixture/'routing');http=read_rows(fixture/'http')
    result=denominators(rows,http,read(fixture/'corpus/manifest.json'))
    missing=[r for r in result['coverage'] if r['source_room_id']=='engineering_room_2']
    assert len(missing)==2
    assert all(r['missing_primary_routing_cells']==12 and r['missing_core_http_slots']==15 for r in missing)
    assert result['routing_observed_rows']==5 and result['routing_valid_scored_rows']==2


def test_attempt_admission_generation_and_commit_denominators_are_distinct(fixture):
    result=denominators(read_rows(fixture/'routing'),read_rows(fixture/'http'),read(fixture/'corpus/manifest.json'))
    assert result['http_observed_rows']==5
    assert result['http_chat_requests_attempted']==4
    assert result['http_admitted_at_precall']==3
    assert result['http_completed_real_responses']==result['http_valid_real_generations']==2
    assert result['http_committed_real_generations']==1
    assert result['http_committed_without_valid_generation']==1


def test_unsettled_and_orphan_log_reservations_are_not_free(fixture):
    items,summary=retained_accounting(fixture/'gateway.jsonl')
    routing=next(x for x in summary['experiments'] if x['experiment_id']=='WP4.routing')
    assert Decimal(routing['accounted_cost_usd'])==Decimal('.15')
    assert Decimal(routing['unsettled_reserved_usd'])==Decimal('.05')
    assert routing['unsettled_attempts']==1
    rows=read_rows(fixture/'routing');attach_costs(rows,[],fixture/'gateway.jsonl')
    assert Decimal(cost_summary(rows)['accounted_cost_usd'])==Decimal('.10')
    assert sum(r['generation_api_attempts'] for r in rows)==4


def test_missing_log_coverage_is_unknown_not_zero(fixture):
    rows=read_rows(fixture/'routing');http=read_rows(fixture/'http')
    summary=attach_costs(rows,http,fixture/'does_not_exist.jsonl')
    assert not summary['available']
    assert all(r['accounted_cost_usd'] is None for r in rows)
    assert cost_summary(rows)['accounted_cost_usd'] is None
    assert cost_summary(rows)['rows_with_unknown_cost']==5
    assert [r['accounted_cost_usd'] for r in http if not r['calls']]==['0','0']


def test_question_errors_and_absent_objects_remain_separate(fixture):
    summary=question_summary(fixture/'questions',read(fixture/'corpus/manifest.json'))
    assert summary['expected_object_rows']==3
    assert summary['observed_object_rows']==2
    assert summary['missing_object_rows']==1
    assert summary['valid_question_pairs']==1 and summary['valid_questions']==2
    assert summary['error_object_rows']==1
    assert summary['statuses']=={'FORMAT_ERROR':1,'SUCCESS':1}


def test_error_rows_do_not_dilute_conditional_valid_rate():
    common={'source_room_id':'ENGINEERING','split':'evaluation','model':'unit','baseline':'B0','abstain_allowed':True,'phrasing':1,'question_kind':'neutral','temperature':.3,'fault_class':'unit'}
    rows=[{**common,'status':'SUCCESS','outcome':'WRONG_PROVIDER'},{**common,'status':'API_ERROR','outcome':'API_ERROR'}]
    summary=summarize_routing(rows)[0]
    assert summary['attempts']==2 and summary['valid_scored_decisions']==1 and summary['unscored_failures']==1
    assert summary['misroute_valid_scored_room_rate']==1 and summary['misroute_room_rate']==.5


def test_replay_is_offline_and_labels_each_artifact(fixture,tmp_path,monkeypatch):
    def forbidden(*args,**kwargs):raise AssertionError('Report attempted network access')
    monkeypatch.setattr(socket,'create_connection',forbidden)
    out=tmp_path/'ENGINEERING_OUTPUTS'
    summary=replay(routing=fixture/'routing',http=fixture/'http',questions=fixture/'questions',corpus=fixture/'corpus',gateway_log=fixture/'gateway.jsonl',output_root=out,no_figures=True,engineering_fixture=True)
    assert summary['data_kind']==ENGINEERING
    assert all(ENGINEERING in p.read_text(encoding='utf-8') for p in out.rglob('*.csv'))
    assert 'ENGINEERING FIXTURE' in (out/'docs/WP4_RESULTS.md').read_text(encoding='utf-8')
    assert not list((out/'paper_inputs').rglob('*.pdf'))


def test_engineering_rows_cannot_masquerade_as_model_results(fixture,tmp_path):
    with pytest.raises(RuntimeError,match='explicit engineering flag'):
        replay(routing=fixture/'routing',corpus=fixture/'corpus',output_root=tmp_path/'out',no_figures=True)


def test_changed_questions_rejected_before_report(fixture,tmp_path):
    path=fixture/'questions/questions.json';data=read(path);data['extra']={};path.write_text(json.dumps(data))
    with pytest.raises(RuntimeError,match='Frozen questions changed'):
        replay(routing=fixture/'routing',questions=fixture/'questions',corpus=fixture/'corpus',output_root=tmp_path/'out',no_figures=True,engineering_fixture=True)

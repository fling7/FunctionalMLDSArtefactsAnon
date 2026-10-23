"""Offline reporting tests: missing native labels and source-cluster units."""
from experiments import report_wp5 as report

def analysis(source,objects=None,unowned=0):
    row={'room':source+'_mini','source':{'scene_id':source,'model':'unit_mini'},'original_pipeline_status':'failed' if objects is None else 'success','candidate_reports':[],'repair_attempts':0}
    if objects is not None:
        row.update(model_sha256='UNIT',object_faults={'objects':objects,'unowned':unowned,'ambiguous_deciding_level':0,'without_declared_action':0,'latent_group_ambiguities':1,'latent_zone_ambiguities':0},
          graph={'agent_count':2,'density':.5,'isolated_agents':[],'directed_diameter':None,'unreachable_agent_pairs':1},pair_counts={'all':objects*2,'more_than_one_handoff':0,'no_path_to_unique_owner':objects,'disagreements':0})
    return row

def test_failed_generation_is_missing_not_zero_faults():
    row=report.fault_row(analysis('missing'))
    assert not row['native_fault_labels_available']
    assert row['unowned'] is None and row['unowned_rate'] is None
    assert row['latent_group_ambiguities'] is None and row['objects'] is None
    assert row['before_native_available'] is False

def test_pooled_object_ratio_and_equal_source_mean_have_distinct_denominators():
    rows=[report.fault_row(analysis('small',1,1)),report.fault_row(analysis('large',100,0)),report.fault_row(analysis('missing'))]
    value=next(r for r in report.pooled_faults(rows) if r['metric']=='unowned')
    assert value['registered_model_runs']==3 and value['available_model_runs']==2 and value['missing_model_runs']==1
    assert value['pooled_numerator']==1 and value['pooled_denominator']==101
    assert value['pooled_rate_or_mean']==1/101 and value['source_cluster_mean']==.5
    assert value['source_clusters']==2 and value['pooled_ci_low']==0 and value['pooled_ci_high']==1

def test_latent_ambiguities_are_per_room_counts_not_object_rates():
    rows=[report.fault_row(analysis('small',1)),report.fault_row(analysis('large',100))]
    value=next(r for r in report.pooled_faults(rows) if r['metric']=='latent_group_ambiguities')
    assert value['pooled_denominator']==2 and value['pooled_rate_or_mean']==1
    assert value['observational_unit']=='groups per room'
    diameter=next(r for r in report.pooled_faults(rows) if r['metric']=='directed_diameter')
    assert diameter['missing_model_runs']==2 and diameter['pooled_rate_or_mean'] is None

def test_corpus_table_keeps_model_variants_and_unexecuted_source_separate(tmp_path,monkeypatch):
    import json
    monkeypatch.setattr(report,'ROOT',tmp_path);monkeypatch.setattr(report,'BACKEND',tmp_path/'backend')
    path=tmp_path/'experiments/scenes/sources/manifest.json';path.parent.mkdir(parents=True)
    path.write_text(json.dumps({'scenes':[{'scene_id':sid,'domain':'unit_domain','object_count':15,'split':'evaluation','sha256':sid} for sid in ('same_source','unselected_source')]}),encoding='utf-8')
    original={'rows':[{'source_room_id':'same_source','case_id':'case_'+tag,'pipeline_model':tag,'project_produced':tag=='mini','run_result_sha256':tag} for tag in ('mini','full')]}
    natural=[{'room':'case_mini','graph':{'agent_count':3}},{'room':'case_full'}]
    rows=report.corpus_room_rows(original,natural)
    assert len(rows)==3 and len({r['room'] for r in rows})==2
    variants=[r for r in rows if r['room']=='same_source']
    assert {r['pipeline_model'] for r in variants}=={'mini','full'}
    assert next(r for r in variants if r['pipeline_model']=='full')['agents'] is None
    assert next(r for r in rows if r['room']=='unselected_source')['pipeline_model'] is None

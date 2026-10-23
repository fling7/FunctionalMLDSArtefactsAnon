"""Small offline provenance and identifier tests; not experimental model output."""
import copy,json
from pathlib import Path
import pytest
from experiments import source_native_coverage as audit

def native(ids):
    return {'objects':[{'type':'Entity','kind':'asset','entityRole':'sceneObject','id':'entity_'+str(i),'sourceId':v} for i,v in enumerate(ids)]}
def normalized(ids):return {'objects':[{'object_id':v} for v in ids]}

def test_missing_native_targets_are_coverage_omissions_not_unowned_faults():
    result=audit.id_join(normalized(['a','b','c']),native(['a','c']))
    assert result['coverage_fraction']==pytest.approx(2/3) and result['source_objects_absent_from_native_routing_target_set']==['b']
    assert result['normalized_source_object_ids']==['a','b','c'] and result['native_source_ids']==['a','c']
    assert 'unowned' not in result


def test_duplicate_and_missing_source_ids_leave_fraction_undefined():
    result=audit.id_join(normalized(['a','a',None]),native(['a']))
    assert result['source_object_records']==3 and result['source_unique_objects']==1
    assert result['source_duplicate_ids']==['a'] and result['source_missing_id_record_indices']==[2]
    assert not result['identifier_join_defined'] and result['coverage_fraction'] is None


def test_duplicate_missing_and_extra_native_source_ids_remain_explicit():
    result=audit.id_join(normalized(['a','b']),native(['a','a',None,'extra']))
    assert result['native_duplicate_source_ids']==['a'] and result['native_missing_source_id_entities']==['entity_2']
    assert result['extra_native_source_ids']==['extra'] and result['extra_native_source_objects']==1
    assert result['source_objects_absent_from_native_routing_target_set']==['b'] and result['coverage_fraction'] is None
    extra=audit.id_join(normalized(['a']),native(['a','extra']))
    assert extra['coverage_fraction']==1 and extra['extra_native_source_ids']==['extra']


def test_duplicate_native_entity_ids_make_identifier_join_undefined():
    instance=native(['a','b']);instance['objects'][1]['id']=instance['objects'][0]['id']
    result=audit.id_join(normalized(['a','b']),instance)
    assert result['native_duplicate_entity_ids']==['entity_0'] and not result['identifier_join_defined']


def test_failed_generation_has_no_invented_native_coverage():
    result=audit.id_join(normalized(['a','b']),None)
    assert not result['native_materialized'] and result['native_target_records'] is None
    assert result['coverage_fraction'] is None and result['source_objects_absent_from_native_routing_target_set'] is None


def inputs(tmp_path):
    def write(relative,value):
        path=tmp_path/relative;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value),encoding='utf-8');return path
    source=write('source.json',{'scene':{'objects':[{'objectId':'a'},{'objectId':'b'}]}})
    norm=write('case/intermediate/scene_graph.normalized.json',normalized(['a','b']))
    model=write('project/roomcontract.v2.instance.json',native(['a']))
    selection={'scene_id':'unit','model':'unit-model','repetition':0,'source_path':'source.json','source_sha256':audit.sha(source)}
    run=write('run.json',{'case_id':'unit_case','source':selection,'status':'success','project_dir':'project','case_dir':'case',
        'artifact_sha256':{p.relative_to(tmp_path).as_posix():audit.sha(p) for p in (norm,model)}})
    return selection,run,{'source':source,'normalized':norm,'native':model,'run':run}


@pytest.mark.parametrize('changed',['source','normalized','native','run'])
def test_changed_retained_input_fails_pin_check(tmp_path,changed):
    selection,run,paths=inputs(tmp_path);expected=audit.sha(run)
    before=audit.audit_run(tmp_path,selection,'run.json',expected)
    assert before['coverage_fraction']==.5 and before['absent_source_objects']==1
    paths[changed].write_text('{"changed":true}',encoding='utf-8')
    with pytest.raises(RuntimeError,match='input pin changed'):audit.audit_run(tmp_path,selection,'run.json',expected)


def test_frozen_source_model_identity_mismatch_fails_closed(tmp_path):
    selection,run,paths=inputs(tmp_path);selection=copy.deepcopy(selection);selection['model']='another-model'
    with pytest.raises(RuntimeError,match='frozen source/model selection'):audit.audit_run(tmp_path,selection,'run.json',audit.sha(run))


def test_real_retained_source_and_native_fixture_preserves_distinct_counts():
    root=Path(__file__).parent/'fixtures/source_native_retained'
    fixture=audit.read(root/'fixture.json')
    result=audit.audit_run(root,fixture['selection'],fixture['run_result_path'],fixture['run_result_sha256'])
    assert result['source_object_records']==40 and result['native_target_records']==28
    assert result['absent_source_objects']==12 and result['coverage_fraction']==.7
    assert result['identifier_join_defined'] and result['extra_native_source_ids']==[]

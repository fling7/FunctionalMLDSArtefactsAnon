"""Post-freeze descriptive audit of source objects and native routing targets.

This is not a routing fault classifier. Native omission never implies an unowned
fault, and failed generation has no measured native coverage denominator.
"""
from __future__ import annotations
from collections import Counter
import hashlib,json
from pathlib import Path


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def read(path):return json.loads(Path(path).read_text(encoding='utf-8-sig'))
def pinned(root,relative,expected):
    path=(root/relative).resolve()
    if not path.is_relative_to(root.resolve()) or sha(path)!=expected:raise RuntimeError('Source/native audit input pin changed')
    return path


def id_join(normalized,instance):
    objects=normalized.get('objects')
    if not isinstance(objects,list):raise ValueError('Normalized source object records are unavailable')
    source=[o.get('object_id') if isinstance(o,dict) else None for o in objects]
    source_missing=[i for i,value in enumerate(source) if not isinstance(value,str) or not value.strip()]
    source_valid=[v for v in source if isinstance(v,str) and v.strip()];source_set=set(source_valid)
    result={'source_object_records':len(source),'normalized_source_object_ids':source,
        'source_unique_object_ids':sorted(source_set),'source_duplicate_ids':sorted(v for v,n in Counter(source_valid).items() if n>1),
        'source_missing_id_record_indices':source_missing,'source_unique_objects':len(source_set),
        'native_materialized':instance is not None,'native_target_records':None,'native_entity_ids':None,'native_source_ids':None,
        'native_unique_source_ids':None,'native_duplicate_source_ids':None,'native_duplicate_entity_ids':None,
        'native_missing_source_id_entities':None,'native_missing_entity_id_record_indices':None,
        'matched_source_ids':None,'source_objects_absent_from_native_routing_target_set':None,'extra_native_source_ids':None,
        'matched_source_objects':None,'absent_source_objects':None,'extra_native_source_objects':None,
        'identifier_join_defined':False,'coverage_fraction':None,'undefined_reason':'no_native_model',
        'scope':'Post-freeze descriptive source/native coverage audit; absence is not an inferred unowned fault or a verified zero fault.'}
    if instance is None:return result
    if not isinstance(instance,dict) or not isinstance(instance.get('objects'),list):result['undefined_reason']='native_object_records_unavailable';return result
    native=[o for o in instance['objects'] if isinstance(o,dict) and o.get('type')=='Entity' and o.get('kind')=='asset' and o.get('entityRole')=='sceneObject']
    native_ids=[o.get('sourceId') for o in native];entities=[o.get('id') for o in native]
    missing=[entities[i] for i,value in enumerate(native_ids) if not isinstance(value,str) or not value.strip()]
    missing_entities=[i for i,value in enumerate(entities) if not isinstance(value,str) or not value.strip()]
    valid=[v for v in native_ids if isinstance(v,str) and v.strip()];native_set=set(valid)
    valid_entities=[v for v in entities if isinstance(v,str) and v.strip()]
    duplicates=sorted(v for v,n in Counter(valid).items() if n>1);duplicate_entities=sorted(v for v,n in Counter(valid_entities).items() if n>1)
    matched=sorted(source_set&native_set);absent=sorted(source_set-native_set);extra=sorted(native_set-source_set)
    reasons=[]
    for condition,label in ((source_missing,'missing_source_object_id'),(result['source_duplicate_ids'],'duplicate_source_object_id'),
        (missing,'missing_native_source_id'),(duplicates,'duplicate_native_source_id'),(missing_entities,'missing_native_entity_id'),(duplicate_entities,'duplicate_native_entity_id')):
        if condition:reasons.append(label)
    defined=not reasons and bool(source_set)
    if not source_set:reasons.append('empty_source_object_set')
    result.update(native_target_records=len(native),native_entity_ids=entities,native_source_ids=native_ids,native_unique_source_ids=sorted(native_set),
        native_duplicate_source_ids=duplicates,native_duplicate_entity_ids=duplicate_entities,native_missing_source_id_entities=missing,
        native_missing_entity_id_record_indices=missing_entities,matched_source_ids=matched,source_objects_absent_from_native_routing_target_set=absent,
        extra_native_source_ids=extra,matched_source_objects=len(matched),absent_source_objects=len(absent),extra_native_source_objects=len(extra),
        identifier_join_defined=defined,coverage_fraction=len(matched)/len(source_set) if defined else None,undefined_reason=';'.join(reasons) if reasons else None)
    return result


def audit_run(root,selection,run_path,run_sha256):
    root=Path(root).resolve();path=pinned(root,run_path,run_sha256);run=read(path)
    if run['source']!=selection:raise RuntimeError('Coverage run differs from frozen source/model selection')
    source=pinned(root,selection['source_path'],selection['source_sha256']);raw=read(source)
    case_dir=run.get('case_dir','results/raw/wp5/cases/'+run['case_id'])
    normalized=(Path(case_dir)/'intermediate/scene_graph.normalized.json').as_posix()
    result={'case_id':run['case_id'],'source_id':selection['scene_id'],'pipeline_model':selection['model'],'repetition':selection['repetition'],
        'pipeline_status':run['status'],'source_path':selection['source_path'],'source_sha256':selection['source_sha256'],
        'run_result_path':run_path,'run_result_sha256':run_sha256,'raw_source_object_ids':[o.get('objectId') for o in raw['scene']['objects']],
        'normalized_path':None,'normalized_sha256':None,'native_model_path':None,'native_model_sha256':None,
        'audit_timing':'Post-freeze descriptive audit motivated by observed source/native denominator differences.'}
    if normalized not in run['artifact_sha256']:
        if (root/normalized).exists():raise RuntimeError('Unregistered normalized source appeared after run')
        result.update(native_materialized=False,identifier_join_defined=False,coverage_fraction=None,undefined_reason='normalized_source_not_produced');return result
    norm=pinned(root,normalized,run['artifact_sha256'][normalized])
    model=root/run['project_dir']/'roomcontract.v2.instance.json' if run.get('project_dir') else None
    instance=None
    if model and model.exists():
        relative=model.relative_to(root).as_posix()
        if relative not in run['artifact_sha256']:raise RuntimeError('Unregistered native model appeared after run')
        pinned(root,relative,run['artifact_sha256'][relative]);instance=read(model)
        result.update(native_model_path=relative,native_model_sha256=sha(model))
    elif model and model.relative_to(root).as_posix() in run['artifact_sha256']:raise RuntimeError('Retained native model disappeared')
    result.update(id_join(read(norm),instance),normalized_path=normalized,normalized_sha256=sha(norm))
    return result


def audit_original(root):
    root=Path(root).resolve();plan_path=root/'prereg/wp5_plan.json';side=plan_path.with_suffix('.sha256')
    if not side.exists() or side.read_text(encoding='ascii').split()[0]!=sha(plan_path):raise RuntimeError('Original plan source freeze changed')
    plan=read(plan_path)
    assembler='tools/case_study_pipeline/roomcontract_assembler.py'
    pinned(root,assembler,plan['implementation_sha256'][assembler])
    terminal_path=root/'results/raw/wp5/evaluation_terminal_v1.json';terminal=read(terminal_path)
    if not terminal.get('terminal') or terminal.get('completed_runs')!=50 or terminal.get('artifact_hash_mismatches'):raise RuntimeError('Original generation is not terminal')
    records={r['case_id']:r for r in terminal['row_records']}
    if len(records)!=len(terminal['row_records']):raise RuntimeError('Duplicate terminal run identity')
    rows=[]
    for selection in plan['evaluation']:
        tag='mini' if 'mini' in selection['model'] else 'full';cid=selection['scene_id']+'_'+tag+'_r'+str(selection['repetition'])
        row=records[cid];rows.append(audit_run(root,selection,row['run_result_path'],row['run_result_sha256']))
    return {'schema':'wp5-source-native-coverage-v1','audit_timing':'Post-freeze descriptive audit; primary native fault labels unchanged.',
        'original_plan_sha256':sha(plan_path),'original_terminal_sha256':sha(terminal_path),'audit_script_sha256':sha(Path(__file__)),
        'assembler_source_path':assembler,'assembler_source_sha256':plan['implementation_sha256'][assembler],
        'registered_model_runs':len(rows),'registered_source_rooms':len({r['source_id'] for r in rows}),'rows':rows,
        'mechanism':'The pinned assembler _interaction_targets retains normalized objects only when object_id occurs in an agent grounded_object_ids list (roomcontract_assembler.py lines360-402). Native sceneObject targets therefore need not cover every normalized source object.',
        'limits':'Coverage joins normalized object_id to native Entity(kind=asset,entityRole=sceneObject).sourceId. Missing/duplicate identifiers make coverage fractions undefined; extra native source IDs remain explicit. Failed/no-native runs have no measured native coverage. Omitted source objects are not classified as unowned native faults.'}

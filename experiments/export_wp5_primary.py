"""Derived primary corpus exporter; excludes downstream repairs and drift arms."""
from pathlib import Path
import json
from experiments.export_wp5_projects import export as export_original
from experiments.wp5_extension import ROOT,PLAN_PATH,SOURCE_PATH,read,digest,load_plan,load_sources

def registered_identity(plan_hash,family,source,model,repetition,arm):
    return {'plan_sha256':plan_hash,'family':family,'source_id':source,'pipeline_model':model,'repetition':repetition,'arm':arm}
def export(destination=None):
    plan=load_plan(replay=True);accepted=load_sources(plan);plan_hash=digest(PLAN_PATH);source_hash=digest(SOURCE_PATH)
    original=export_original();original_hash=digest(ROOT/'prereg/wp5_plan.json')
    original_plan=read(ROOT/'prereg/wp5_plan.json');original_terminal_path=ROOT/'results/raw/wp5/evaluation_terminal_v1.json'
    original_terminal=original_terminal_path.exists() and read(original_terminal_path).get('terminal') is True and len(original['rows'])==len(original_plan['evaluation'])
    rows=[]
    for r in original['rows']:
        r=dict(r);r.update(corpus_family='original',arm='original_frozen',source_family_order=r['source_priority'],source_valid=True,
            source_authoring_attempt_count=0,source_authoring_repaired=False,source_authoring_result_path=None,source_authoring_result_sha256=None,source_freeze_sha256=None,
            terminal_status='completed' if r['pipeline_success'] else 'failed',
            registered_identity=registered_identity(original_hash,'original',r['source_room_id'],r['pipeline_model'],r['repetition'],'original_frozen'))
        r['eligible_native_success']=all(r[k] is True for k in ('pipeline_success','project_produced','canonical_valid','schema_valid','gate0_ok','source_valid'))
        rows.append(r)
    slots={r['source_id']:r for r in accepted['slots']};all_initial=True
    for ordinal,selection in enumerate(plan['initial_baselines'],1):
        slot=slots[selection['source_id']];path=ROOT/'results/raw/wp5_extension/initial'/selection['case_id']/'run_result.json'
        if not path.exists():all_initial=False;continue
        run=read(path)
        expected={'scene_id':selection['source_id'],'model':selection['model'],'repetition':selection['repetition'],
            'source_path':slot['source_path'],'source_sha256':slot['source_sha256']}
        if any(run['source'].get(k)!=v for k,v in expected.items()) or run['case_id']!=selection['case_id'] or run['plan_sha256']!=plan_hash:
            raise RuntimeError('Extension terminal record differs from frozen selection')
        project=ROOT/run['project_dir'] if run.get('project_dir') else None
        model=project/'roomcontract.v2.instance.json' if project else None
        model_exists=bool(model and model.exists());gate_path=path.parent/'routing_verifier.json'
        stages={r['stage']:r for r in run['stages']}
        if model_exists and run['artifact_sha256'].get(model.relative_to(ROOT).as_posix())!=digest(model):raise RuntimeError('Extension native artifact changed')
        row={'source_room_id':selection['source_id'],'source_priority':selection['source_priority'],'run_ordinal':ordinal,
            'case_id':selection['case_id'],'project_path':run.get('project_dir'),'split':'evaluation',
            'pipeline_model':selection['model'],'repetition':selection['repetition'],'pipeline_success':run['status']=='success',
            'failure_stage':run.get('failure_stage'),'project_produced':model_exists,
            'canonical_valid':stages.get('roomcontract_v2_assembly',{}).get('status')=='success',
            'schema_valid':stages.get('schema_validation',{}).get('status')=='success',
            'gate0_ok':read(gate_path).get('ok') is True if gate_path.exists() else False,
            'source_path':slot['source_path'],'source_sha256':slot['source_sha256'],'run_result_path':path.relative_to(ROOT).as_posix(),
            'run_result_sha256':digest(path),'model_sha256':__import__('hashlib').sha256(model.read_bytes().replace(b'\r\n',b'\n')).hexdigest().upper() if model_exists else None,
            'corpus_family':selection['family'],'arm':'initial_baseline','source_family_order':selection['source_family_order'],
            'source_valid':slot['status']=='accepted','source_authoring_attempt_count':slot['source_authoring_attempt_count'],
            'source_authoring_repaired':slot['source_authoring_repaired'],'source_authoring_result_path':slot['source_authoring_result_path'],
            'source_authoring_result_sha256':slot['source_authoring_result_sha256'],'source_freeze_sha256':source_hash,
            'terminal_status':run['terminal_status'],
            'registered_identity':registered_identity(plan_hash,selection['family'],selection['source_id'],selection['model'],selection['repetition'],'initial_baseline')}
        row['eligible_native_success']=all(row[k] is True for k in ('pipeline_success','project_produced','canonical_valid','schema_valid','gate0_ok','source_valid'))
        rows.append(row)
    terminal_path=ROOT/'results/raw/wp5_extension/initial_terminal_v1.json'
    initial_terminal=all_initial and terminal_path.exists() and read(terminal_path).get('terminal') is True
    report={'schema':'wp5-combined-primary-provenance-v1','original_terminal':bool(original_terminal),'initial_block_terminal':bool(initial_terminal),
        'manifest_is_complete':bool(original_terminal and initial_terminal),'original_manifest_path':'results/processed/wp5_projects.json',
        'extension_plan_path':PLAN_PATH.relative_to(ROOT).as_posix(),'extension_plan_sha256':plan_hash,
        'source_freeze_manifest_path':SOURCE_PATH.relative_to(ROOT).as_posix(),'source_freeze_manifest_sha256':source_hash,
        'registered_original_count':len(original_plan['evaluation']),'registered_initial_count':len(plan['initial_baselines']),
        'eligible_distinct_sources':len({r['source_room_id'] for r in rows if r['eligible_native_success']}),
        'rows':rows,'gate0_disagreements':[r['case_id'] for r in rows if r['pipeline_success'] and r['project_produced'] and r['canonical_valid'] and r['schema_valid'] and not r['gate0_ok']]}
    destination=destination or ROOT/'results/processed/wp5_primary_projects.json';destination.parent.mkdir(parents=True,exist_ok=True)
    destination.write_text(json.dumps(report,sort_keys=True,indent=2)+'\n',encoding='utf-8',newline='\n')
    return report
if __name__=='__main__':
    report=export();print(json.dumps({k:v for k,v in report.items() if k!='rows'}))

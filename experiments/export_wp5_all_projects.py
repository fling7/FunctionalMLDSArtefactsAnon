"""Offline exhaustive project inventory; never deduplicate sources or model variants."""
from __future__ import annotations
import argparse,hashlib,json
from pathlib import Path
from experiments.pipeline_runs import ROOT

def read(path):return json.loads(Path(path).read_text(encoding='utf-8-sig'))
def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def pin(path):return {'path':path.relative_to(ROOT).as_posix(),'sha256':digest(path)}
def frozen(path):
    side=path.with_suffix('.sha256')
    if not side.exists() or side.read_text(encoding='ascii').split()[0]!=digest(path):raise RuntimeError('Unfrozen input: '+str(path))
    return read(path)

def inventory_row(identity,run_path,terminal_record=None,terminal_status=None):
    row={**identity,'terminal_status':'pending','pipeline_success':False,'native_materialized':False,
        'project_path':None,'model_file_sha256':None,'model_sha256':None,'trace_path':None,'trace_sha256':None,
        'canonical_valid':None,'schema_valid':None,'gate0_ok':None,'runtime_adoption_eligible':None,
        'run_result_path':None,'run_result_sha256':None,'terminal_record_path':None,'terminal_record_sha256':None}
    if not run_path.exists():
        if terminal_record and terminal_record.exists():
            row.update(terminal_status=terminal_status,terminal_record_path=terminal_record.relative_to(ROOT).as_posix(),terminal_record_sha256=digest(terminal_record))
        return row
    run=read(run_path);source=run['source']
    if run['case_id']!=identity['case_id'] or any(source[k]!=identity[v] for k,v in (('scene_id','source_id'),('model','pipeline_model'),('repetition','repetition'))):raise RuntimeError('Registered project identity differs')
    if run.get('plan_sha256') and run['plan_sha256']!=identity['plan_sha256']:raise RuntimeError('Run belongs to another plan')
    row.update(terminal_status=run.get('terminal_status','completed' if run['status']=='success' else 'failed'),pipeline_success=run['status']=='success',
        source_path=source.get('source_path'),source_sha256=source.get('source_sha256'),project_path=run.get('project_dir'),
        run_result_path=run_path.relative_to(ROOT).as_posix(),run_result_sha256=digest(run_path),
        terminal_record_path=run_path.relative_to(ROOT).as_posix(),terminal_record_sha256=digest(run_path),failure_stage=run.get('failure_stage'),error_code=run.get('error_code'))
    stages={r['stage']:r for r in run['stages']}
    row['canonical_valid']=stages.get('roomcontract_v2_assembly',{}).get('status')=='success'
    row['schema_valid']=stages.get('schema_validation',{}).get('status')=='success'
    gate=run_path.parent/'routing_verifier.json'
    if gate.exists():row['gate0_ok']=read(gate).get('ok')
    project=ROOT/run['project_dir'] if run.get('project_dir') else None
    model=project/'roomcontract.v2.instance.json' if project else None
    if model and model.exists():
        if run['artifact_sha256'].get(model.relative_to(ROOT).as_posix())!=digest(model):raise RuntimeError('Native project file differs from retained run')
        row.update(native_materialized=True,model_file_sha256=digest(model),model_sha256=hashlib.sha256(model.read_bytes().replace(b'\r\n',b'\n')).hexdigest().upper())
        trace=project/'trace_map.v2.json'
        if trace.exists():
            if run['artifact_sha256'].get(trace.relative_to(ROOT).as_posix())!=digest(trace):raise RuntimeError('Native trace differs from retained run')
            row.update(trace_path=trace.relative_to(ROOT).as_posix(),trace_sha256=digest(trace))
    # Loader eligibility is deliberately not inferred from generation success.
    return row

def registered_rows(original_plan,extension_plan=None):
    rows=[]
    for selection in original_plan['evaluation']:
        tag='mini' if 'mini' in selection['model'] else 'full';case=selection['scene_id']+'_'+tag+'_r'+str(selection['repetition'])
        rows.append({'phase':'original','arm':'original_frozen','case_id':case,'source_id':selection['scene_id'],'pipeline_model':selection['model'],'repetition':selection['repetition']})
    if extension_plan:
        for phase,key in (('initial','initial_baselines'),('drift','fresh_drift_runs'),('source_edit','source_edits')):
            for r in extension_plan[key]:rows.append({'phase':phase,'arm':r['arm'],'case_id':r['case_id'],'source_id':r['source_id'],'pipeline_model':r['model'],'repetition':r['repetition']})
        for r in extension_plan['targeted_repair_candidates']:
            rows.append({'phase':'ownership_repair','arm':'ownership_repair','case_id':r['case_id']+'_ownershiprepair_v1','source_id':r['source']['scene_id'],'pipeline_model':r['source']['model'],'repetition':r['source']['repetition']})
        for r in extension_plan['recovery']['rows']:rows.append({'phase':'cap_recovery','arm':r['arm'],'case_id':r['case_id'],'source_id':r['source_id'],'pipeline_model':r['model'],'repetition':r['repetition']})
        base=next(r for r in extension_plan['initial_baselines'] if r['case_id']==extension_plan['zone_rename']['base_case_id'])
        rows.append({'phase':'zone_rename','arm':'scripted_zone_rename','case_id':base['case_id']+'_zone_rename_v1','source_id':base['source_id'],'pipeline_model':base['model'],'repetition':base['repetition']})
    priority={name:i for i,name in enumerate(('original','initial','ownership_repair','cap_recovery','drift','source_edit','zone_rename'))}
    return sorted(rows,key=lambda r:priority[r['phase']])

def export(output,extension_plan_path=None):
    original_path=ROOT/'prereg/wp5_plan.json';original=frozen(original_path)
    extension=frozen(extension_plan_path) if extension_plan_path else None
    base=ROOT/'results/raw/wp5_extension'
    phase_paths={'original':ROOT/'results/raw/wp5/evaluation_terminal_v1.json',
        'initial':base/'initial_terminal_v1.json','ownership_repair':base/'ownership_repair_terminal_v1.json',
        'cap_recovery':base/'recovery_terminal_v1.json','drift':base/'drift_terminal_v1.json','source_edit':base/'source_edits_terminal_v1.json'}
    markers={phase:read(path) for phase,path in phase_paths.items() if path.exists()}
    if extension:
        for phase,marker in markers.items():
            if phase!='original' and marker.get('plan_sha256')!=digest(extension_plan_path):raise RuntimeError('Phase terminal marker belongs to another plan')
    rows=[]
    for identity in registered_rows(original,extension):
        phase=identity['phase'];identity['plan_sha256']=digest(original_path if phase=='original' else extension_plan_path)
        folder=ROOT/'results/raw/wp5/evaluation'/identity['case_id'] if phase=='original' else base/phase/identity['case_id']
        terminal=None;status=None
        if phase=='ownership_repair':
            if (folder/'repair_result.json').exists():terminal=folder/'repair_result.json';status='failed'
            elif markers.get(phase,{}).get('terminal') and any(r.get('budget_stop') for r in markers[phase].get('results',[])):
                terminal=phase_paths[phase];status='unexecuted_budget_stop'
        if phase=='zone_rename' and (folder/'edit_result.json').exists():
            terminal=folder/'edit_result.json';status='unexecuted_preselected_baseline_failed' if read(terminal)['status']=='not_executed' else 'failed'
        rows.append(inventory_row(identity,folder/'run_result.json',terminal,status))
    phases={phase:{'terminal':all(r['terminal_status']!='pending' for r in rows if r['phase']==phase) and (phase=='zone_rename' or markers.get(phase,{}).get('terminal') is True),
        'registered_rows':sum(r['phase']==phase for r in rows),'terminal_record':pin(phase_paths[phase]) if phase in markers else None} for phase in dict.fromkeys(r['phase'] for r in rows)}
    materialized=[r for r in rows if r['native_materialized']]
    report={'schema':'wp5-all-projects-v1','selection':'Every registered project identity; no source/model deduplication or eligibility filter.',
        'original_plan':pin(original_path),'extension_plan':pin(extension_plan_path) if extension_plan_path else None,
        'extension_inventory_registered':extension is not None,'extension_status':'registered' if extension else 'not_yet_frozen','all_registered_identities_terminal':all(p['terminal'] for p in phases.values()),
        'phase_status':phases,'registered_rows':len(rows),'native_model_runs':len(materialized),'native_source_rooms':len({r['source_id'] for r in materialized}),
        'pending_rows':sum(r['terminal_status']=='pending' for r in rows),'rows':rows,'exporter_sha256':digest(Path(__file__)),
        'limitations':'runtime_adoption_eligible remains null unless separately measured; native materialization never implies adoption or fault freedom.'}
    text=json.dumps(report,sort_keys=True,indent=2)+'\n';output=Path(output)
    if output.exists() and output.read_text(encoding='utf-8-sig')!=text:raise RuntimeError('Choose a new versioned manifest; preserve prior snapshot')
    output.parent.mkdir(parents=True,exist_ok=True);output.write_text(text,encoding='utf-8',newline='\n');return report

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True);parser.add_argument('--extension-plan',type=Path)
    args=parser.parse_args();result=export(args.output,args.extension_plan);print(json.dumps({k:v for k,v in result.items() if k not in ('rows','phase_status')}))

"""Unpaid draft: fixed missing source/model identities, unchanged pipeline core."""
from __future__ import annotations
import argparse, copy, hashlib, json, stat
from collections import Counter
from pathlib import Path
from experiments import wp5_extension as core
ROOT=core.ROOT
PLAN_REL='prereg/wp5_completion_v1/plan.json'
OUTPUT_REL='results/raw/wp5_completion_v1'
PHASE='completion_v1'
DESIGN_MUTABLE=('status','cache_identity','implementation_status')
PRIOR_PHASES=('initial','ownership_repair','cap_recovery','drift','source_edit','zone_rename','guided_initial')

def value_sha(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()

def pinned(relative, expected):
    path=(ROOT/relative).resolve()
    if not path.is_relative_to(ROOT.resolve()) or not path.is_file() or core.digest(path)!=expected:
        raise RuntimeError('Completion evidence pin changed: '+relative)
    return path

def exact_tree(directory, declared):
    base=ROOT/directory
    if not base.resolve().is_relative_to(ROOT.resolve()):raise RuntimeError('Completion input directory escapes workspace')
    actual=set();pending=[base] if base.exists() else []
    while pending:
        current=pending.pop();meta=current.lstat()
        if current.is_symlink() or getattr(meta,'st_file_attributes',0)&getattr(stat,'FILE_ATTRIBUTE_REPARSE_POINT',0x400):raise RuntimeError('Linked completion input refused')
        if not current.resolve().is_relative_to(base.resolve()):raise RuntimeError('Completion input escapes directory')
        if current.is_dir():pending.extend(current.iterdir())
        elif stat.S_ISREG(meta.st_mode):actual.add(current.relative_to(base).as_posix())
        else:raise RuntimeError('Nonregular completion input refused')
    if actual!=declared:raise RuntimeError('Complete completion input file set changed: '+directory)

def verify_result(relative, expected, source):
    path=pinned(relative,expected);run=core.read(path)
    if run['source']!=source or run['case_id']!=source['case_id'] or run['plan_sha256']!=core.digest(core.PLAN_PATH):raise RuntimeError('Retained completion identity differs')
    artifacts=run['artifact_sha256']
    for name,pin in artifacts.items():pinned(name,pin)
    directories=[path.parent.relative_to(ROOT).as_posix(),run.get('case_dir') or 'results/raw/wp5_extension/cases/'+run['case_id']]
    if run.get('project_dir'):directories.append(run['project_dir'])
    for directory in directories:
        prefix=directory+'/';declared={name[len(prefix):] for name in artifacts if name.startswith(prefix)}
        if directory==path.parent.relative_to(ROOT).as_posix():declared.add(path.name)
        exact_tree(directory,declared)
    return run

def verify_static(plan):
    for name,pin in plan['implementation_sha256'].items():pinned(name,pin)
    for name,pin in plan['pipeline_prompt_sha256'].items():pinned(name,pin)
    for row in plan['rows']:
        pinned(row['source_path'],row['source_sha256'])
        provenance=plan['authoring_provenance'][row['source_id']]
        if provenance['source_authoring_result_path']:pinned(provenance['source_authoring_result_path'],provenance['source_authoring_result_sha256'])

def load_plan(*,replay=False):
    path=ROOT/PLAN_REL;core.verify_freeze(path);plan=core.read(path)
    if plan.get('status')!='FROZEN' or not plan.get('implementation_sha256') or plan.get('wrapper_sha256')!=core.digest(Path(__file__)):raise RuntimeError('Completion protocol is not frozen')
    ref=plan['approved_design'];design=core.read(pinned(ref['path'],ref['sha256']))
    for key,value in design.items():
        if key not in DESIGN_MUTABLE and plan.get(key)!=value:raise RuntimeError('Approved completion design changed: '+key)
    if plan['execution_phase']!=PHASE or plan['gateway_experiment_id']!='WP5.extension.'+PHASE:raise RuntimeError('Completion namespace changed')
    base=core.load_plan(replay=replay)
    original=core.read(pinned('prereg/wp5_plan.json',plan['stage_profiles']['original_ordinary']['source_plan_sha256']))
    pinned('prereg/wp5_extension_v1/plan.json',plan['stage_profiles']['extension_ordinary']['source_plan_sha256'])
    for label,origin in [('original_ordinary',original),('extension_ordinary',base)]:
        if plan['stage_profiles'][label]['llm_stages']!=origin['llm_stages']:raise RuntimeError('Completion settings profile changed')
        if plan['stage_order']!=origin['stage_order'] or plan['temperature']!=origin['temperature']:raise RuntimeError('Completion stage order or temperature changed')
    if plan['pipeline_prompt_sha256']!=original['prompt_sha256'] or plan['pipeline_prompt_sha256']!=base['original_pipeline_prompt_sha256']:raise RuntimeError('Completion prompt registry changed')
    verify_static(plan)
    audit=core.read(pinned(plan['scope_audit']['manifest_path'],plan['scope_audit']['manifest_sha256']))
    for relative,expected in audit['input_sha256'].items():pinned(relative,expected)
    pinned(plan['scope_audit']['csv_path'],plan['scope_audit']['csv_sha256'])
    rows=plan['rows']
    if plan['authoring_provenance']!={row['source_id']:authoring_provenance(row,audit) for row in rows}:raise RuntimeError('Completion authoring provenance registry changed')
    if len(rows)!=57 or len({(r['source_id'],r['pipeline_model']) for r in rows})!=57 or len({r['case_id'] for r in rows})!=57:raise RuntimeError('Completion requires all57 distinct fixed identities')
    if [r['ordinal'] for r in rows]!=list(range(1,58)):raise RuntimeError('Completion order changed')
    if [r['source_family'] for r in rows]!=['original_evaluation']*40+['extension_llm']*2+['guided_llm_source_v2']*12+['original_dev']*3:raise RuntimeError('Completion priority partition changed')
    for row in rows:
        tag='mini' if 'mini' in row['pipeline_model'] else 'full'
        profile='original_ordinary' if row['source_family'].startswith('original_') else 'extension_ordinary'
        if row['pipeline_model'] not in base['models'] or row['repetition']!=0 or row['stage_profile']!=profile or row['case_id']!=row['source_id']+'_completion_'+tag+'_r0' or row['evaluation_unit']!=(row['source_family']!='original_dev'):raise RuntimeError('Completion row identity/profile/split changed')
    refs=plan['preceding_terminal_pins']
    if [r['phase'] for r in refs]!=list(PRIOR_PHASES):raise RuntimeError('Completion terminal prerequisites incomplete')
    for ref in refs:
        prior=core.read(pinned(ref['path'],ref['sha256']));phase=ref['phase']
        if phase=='zone_rename':
            if prior.get('status') not in ('success','failed','not_executed'):raise RuntimeError('Zone rename not terminal')
        else:
            if prior.get('terminal') is not True:raise RuntimeError('Earlier completion prerequisite not terminal')
            count=3 if phase=='ownership_repair' else {'initial':24,'cap_recovery':27,'drift':120,'source_edit':3,'guided_initial':12}[phase]
            collection='results' if phase=='ownership_repair' else 'rows'
            if len(prior.get(collection,[]))!=count:raise RuntimeError('Earlier terminal has incomplete identity count')
    ref=plan['settled_budget_authorization'];approval=core.read(pinned(ref['path'],ref['sha256']))
    expected={'execution_authorized':True,'global_cap_usd':'20.000000000','wp5_stop_usd':'7.200000000','pending_claims':0,'in_flight_reservations':0}
    expected.update(approved_design_sha256=plan['approved_design']['sha256'],implementation_registry_sha256=value_sha(plan['implementation_sha256']))
    if any(approval.get(k)!=v for k,v in expected.items()):raise RuntimeError('Completion has no settled budget authorization')
    return plan,base

def authoring_provenance(slot, audit):
    family=slot['source_family']
    if family.startswith('original_'):
        return {'source_authoring_result_path':None,'source_authoring_result_sha256':None,'source_authoring_attempt_count':0,'source_authoring_repaired':False}
    rel=audit['accepted_extension_sources'] if family=='extension_llm' else audit['guided_sources_terminal']
    record=core.read(pinned(rel,audit['input_sha256'][rel]));entries=record['slots'] if family=='extension_llm' else record['rows']
    matching=[r for r in entries if r['source_id']==slot['source_id']]
    if len(matching)!=1:raise RuntimeError('Completion source authoring identity missing')
    row=matching[0]
    if row.get('status')!='accepted':raise RuntimeError('Completion authoring source was not accepted')
    if row['source_path']!=slot['source_path'] or row['source_sha256']!=slot['source_sha256']:raise RuntimeError('Completion authoring source differs')
    result={key:row[key] for key in ('source_authoring_result_path','source_authoring_result_sha256','source_authoring_attempt_count','source_authoring_repaired')}
    pinned(result['source_authoring_result_path'],result['source_authoring_result_sha256'])
    return result

def execution_source(slot,plan_hash,plan):
    profile=plan['stage_profiles'][slot['stage_profile']]
    return {'scene_id':slot['source_id'],'model':slot['pipeline_model'],'repetition':slot['repetition'],'source_path':slot['source_path'],'source_sha256':slot['source_sha256'],'case_id':slot['case_id'],'family':slot['source_family'],'arm':slot['arm'],'phase':PHASE,'split':'development' if slot['source_family']=='original_dev' else 'evaluation','evaluation_unit':slot['evaluation_unit'],'source_object_count':slot['source_object_count'],'external_execution_plan_path':PLAN_REL,'external_execution_plan_sha256':plan_hash,'stage_settings_profile':slot['stage_profile'],'stage_settings_profile_sha256':value_sha(profile),'settings_source_plan_path':profile['source_plan'],'settings_source_plan_sha256':profile['source_plan_sha256'],'completion_ordinal':slot['ordinal'],'completion_scope_audit_sha256':plan['scope_audit']['manifest_sha256'],'gateway_experiment_id':plan['gateway_experiment_id'],**plan['authoring_provenance'][slot['source_id']]}

def profiled_base(slot,plan,base):
    settings=copy.deepcopy(base)
    settings['llm_stages']=copy.deepcopy(plan['stage_profiles'][slot['stage_profile']]['llm_stages'])
    return settings

def execute(plan,base,*,replay=False):
    plan_path=ROOT/PLAN_REL;plan_hash=core.digest(plan_path)
    if core.read(plan_path)!=plan:raise RuntimeError('Completion plan changed after loading')
    output=ROOT/OUTPUT_REL;receipts=output/'receipts';results=[];stopped=False;new_started=False
    allowed={r['case_id']+'.json' for r in plan['rows']}
    if receipts.exists() and {p.name for p in receipts.iterdir()}-allowed:raise RuntimeError('Unregistered completion receipt')
    retained=[(receipts/(r['case_id']+'.json')).exists() for r in plan['rows']]
    if retained!=sorted(retained,reverse=True):raise RuntimeError('Completion resume contains a non-prefix retained identity')
    phase_root=ROOT/'results/raw/wp5_extension'/PHASE
    if phase_root.exists() and {p.name for p in phase_root.iterdir()}-{r['case_id'] for r in plan['rows']}:raise RuntimeError('Unregistered completion run directory')
    for slot,exists in zip(plan['rows'],retained):
        if not exists and any((ROOT/rel).exists() for rel in ('results/raw/wp5_extension/'+PHASE+'/'+slot['case_id'],'results/raw/wp5_extension/cases/'+slot['case_id'],'results/wp5_extension_runtime/projects/'+slot['case_id'])):
            raise RuntimeError('Completion has unreceipted retained evidence; explicit review required, no regeneration')
    for slot in plan['rows']:
        if core.digest(plan_path)!=plan_hash:raise RuntimeError('Completion plan changed during execution')
        verify_static(plan)
        source=execution_source(slot,plan_hash,plan);relative='results/raw/wp5_extension/'+PHASE+'/'+slot['case_id']+'/run_result.json';path=ROOT/relative;receipt=receipts/(slot['case_id']+'.json')
        if receipt.exists():
            if new_started:raise RuntimeError('Completion resume contains a non-prefix retained identity')
            saved=core.read(receipt)
            if saved['external_execution_plan_sha256']!=plan_hash or saved['run_result_path']!=relative or saved['ordinal']!=slot['ordinal']:raise RuntimeError('Completion receipt identity changed')
            result=verify_result(relative,saved['run_result_sha256'],source)
            if stopped and result.get('terminal_status')!='unexecuted_budget_stop':raise RuntimeError('Retained completion executed after a prior budget stop')
        else:
            if path.exists() or path.parent.exists():raise RuntimeError('Completion has unreceipted retained evidence; explicit review required, no regeneration')
            new_started=True
            settings=profiled_base(slot,plan,base)
            result=core.skipped_run(source,'BUDGET_STOP') if stopped else core.run_case(source,settings,replay=replay)
            verify_static(plan)
            pin=core.digest(path);verify_result(relative,pin,source)
            saved={'schema':'wp5-completion-retained-result-receipt-v1','ordinal':slot['ordinal'],'case_id':slot['case_id'],'external_execution_plan_sha256':plan_hash,'run_result_path':relative,'run_result_sha256':pin}
            core.write_once(receipt,saved)
        stopped=stopped or core.budget_stop_record(result)
        terminal_status=result.get('terminal_status') or ('completed' if result['status']=='success' else 'failed')
        results.append({'ordinal':slot['ordinal'],'source_id':slot['source_id'],'source_family':slot['source_family'],'pipeline_model':slot['pipeline_model'],'split':source['split'],'evaluation_unit':source['evaluation_unit'],'case_id':slot['case_id'],'status':result['status'],'terminal_status':terminal_status,'failure_stage':result.get('failure_stage'),'run_result_path':relative,'run_result_sha256':saved['run_result_sha256'],'receipt_path':receipt.relative_to(ROOT).as_posix(),'receipt_sha256':core.digest(receipt)})
        print(json.dumps(results[-1]),flush=True)
    terminal={'schema':'wp5-missing-source-model-completion-terminal-v1','terminal':True,'plan_sha256':plan_hash,'registered_rows':57,'rows':results,'budget_stopped':stopped,'split_counts':dict(Counter(r['split'] for r in results)),'primary_denominators_changed':False,'wp4_primary_selection_changed':False,'interpretation':plan['interpretation']}
    core.write_once(output/'terminal.json',terminal);return terminal

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--replay',action='store_true');args=parser.parse_args()
    plan,base=load_plan(replay=args.replay);execute(plan,base,replay=args.replay)
if __name__=='__main__':main()

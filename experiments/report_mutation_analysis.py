"""Generate descriptive WP6 documentation from immutable raw runs.

This reporting layer does not alter the preregistered model classifications,
confusion cells, or admission aggregate. The finer admission breakdown is labelled
exploratory because it was requested after the preregistered metric was frozen.
"""
from __future__ import annotations
import argparse
from collections import Counter
import csv
import hashlib
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from experiments.wp6_provenance import join_mutants,load_source_manifests,checker_source_intervals


def read(path): return json.loads(Path(path).read_text(encoding='utf-8'))
def key(value): return tuple(value.get(k) for k in ('decision','reason','provider','action'))
def admitted(value): return value.get('decision') in {'ANSWER_LOCAL','ANSWER_AFTER_HANDOFF'}
def fmt_interval(value): return 'NA' if value is None else '['+', '.join(f'{x:.3f}' for x in value)+']'


def diagnostics(value):
    result=[]
    if isinstance(value,dict):
        if value.get('severity')=='error' or value.get('exception') or value.get('status')=='invalid':
            result.append({k:value[k] for k in ('code','reason','exception','message','invariant_id','description') if k in value})
        for k,v in value.items():
            if k in {'errors','issues'} and isinstance(v,list):
                result.extend(v)
            elif isinstance(v,(dict,list)): result.extend(diagnostics(v))
    elif isinstance(value,list):
        for v in value: result.extend(diagnostics(v))
    seen={json.dumps(x,sort_keys=True,ensure_ascii=False):x for x in result if x}
    return list(seen.values())


def csv_file(path,rows,fields):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('w',encoding='utf-8',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader();writer.writerows(rows)


def analyze(run,source_rows=()):
    manifest=read(run/'mutation_manifest.json')
    summary=read(run/'summary.json')
    records=[read(p) for p in sorted((run/'outcomes').glob('*.json'))]
    discrepancies=[];concordant_rejections=[];agreement=Counter({k:0 for k in ['independent_agreed_pairs','independent_unresolved_pairs','Gate0_agreed_pairs','Gate0_disagreements','runtime_agreed_pairs','runtime_disagreements','runtime_setup_refused_pairs','table_executed_pairs','table_agreed_pairs','table_disagreements']});breakdown={};properties=Counter()
    for record in records:
        truth=record['groundtruth']['routing_faulty']
        reasons=Counter(p['I1'].get('reason') for p in record['probes'] if p['I1'].get('reason'))
        for name,outcome in record['checkers'].items():
            if not name.startswith(('Va_','Vb_','Vc_')) or truth is None:continue
            status=outcome['status']
            if status not in {'pass','reject'}:continue
            cell='TP' if truth and status=='reject' else 'FN' if truth else 'FP' if status=='reject' else 'TN'
            row={'run':run.name,'model':record['metadata']['id'],'room':record['metadata']['room'],'operators':' + '.join(record['metadata']['operators']),'checker':name,'cell':cell,'authoritative_spec':'SPEC.md with A001/A002/A003','routing_reasons':json.dumps(dict(reasons),sort_keys=True),'checker_evidence':json.dumps(diagnostics(outcome),sort_keys=True,ensure_ascii=False),'interpretation':('Checker accepted a model with an agreed ownership/action fault; its executed scope did not reject this fault.' if cell=='FN' else 'Checker rejected although every agreed routing verdict lacks an ownership/action fault. Its publication/authoring constraint is additional to the narrow routing-fault endpoint.' if cell=='FP' else 'Both reject. The raw checker diagnostic is retained; co-occurrence does not establish that it detected the routing fault rather than an additional structural defect.')}
            if cell in {'FP','FN'}:discrepancies.append(row)
            if cell=='TP':concordant_rejections.append(row)
        for probe in record['probes']:
            oracle_agrees=key(probe['I1'])==key(probe['I2']) and not probe['I1'].get('evaluation_error') and not probe['I2'].get('evaluation_error')
            if not oracle_agrees:agreement['independent_unresolved_pairs']+=1
            else:
                agreement['independent_agreed_pairs']+=1
                if key(probe['Gate0'])!=key(probe['I1']):agreement['Gate0_disagreements']+=1
                else:agreement['Gate0_agreed_pairs']+=1
                default=probe['variants']['runtime']
                if default.get('status')=='not_run_setup_refused':agreement['runtime_setup_refused_pairs']+=1
                elif key(default)!=key(probe['I1']):agreement['runtime_disagreements']+=1
                else:agreement['runtime_agreed_pairs']+=1
                table=probe['variants']['table']
                if table.get('status')!='not_run_setup_refused':
                    agreement['table_executed_pairs']+=1
                    if key(table)!=key(probe['I1']):agreement['table_disagreements']+=1
                    else:agreement['table_agreed_pairs']+=1
            default=probe['variants']['runtime']
            if default.get('decision')=='REJECT':
                properties['rejected_normal_requests_checked']+=1
                if default.get('model_calls',0)!=0 or not default.get('unchanged_before_restore',False):properties['rejected_normal_request_violations']+=1
            for variant,outcome in probe['variants'].items():
                count=breakdown.setdefault(variant,Counter())
                if outcome.get('status')=='not_run_setup_refused':count['setup_refused']+=1;continue
                count['executed']+=1
                if not oracle_agrees:count['unresolved_oracle']+=1;continue
                if not admitted(outcome):continue
                if probe['I1'].get('decision')=='REJECT':count['oracle_rejection_admitted']+=1
                elif (outcome.get('decision'),outcome.get('provider'))!=(probe['I1'].get('decision'),probe['I1'].get('provider')):count['decision_or_provider_mismatch']+=1
                elif outcome.get('action')!=probe['I1'].get('action'):count['action_binding_mismatch']+=1
                else:count['fully_agreed_admission']+=1
    completed_ids={r['metadata']['id'] for r in records}
    single_eligibility=[{'room':m['room'],'operator':m['operators'][0],'model':m['id'],'status':m['status'],'completed':m['id'] in completed_ids,'reason':m.get('reason','')} for m in manifest['models'] if len(m.get('operators',[]))==1]
    pair_groups={}
    for m in manifest['models']:
        if m.get('pair_id'):pair_groups.setdefault((m['room'],m['pair_id']),[]).append(m)
    pair_coverage=[]
    for (room,pair_id),attempts in sorted(pair_groups.items()):
        pair_coverage.append({'room':room,'pair_id':pair_id,'attempts':len(attempts),'planned_changed_models':sum(m['status']=='changed' for m in attempts),'evaluated_changed_models':sum(m['status']=='changed' and m['id'] in completed_ids for m in attempts),'incomplete_evaluated_models':sum(m['status']=='incomplete' and m['id'] in completed_ids for m in attempts),'no_op_attempts':sum(m['status']=='no_op' for m in attempts),'not_applicable_attempts':sum(m['status']=='not_applicable' for m in attempts),'attempt_evidence':json.dumps([{k:m.get(k) for k in ['id','operators','status','reason','changes']} for m in attempts],sort_keys=True)})
    covered={m['pair_id'] for m in manifest['models'] if m.get('pair_id') and m['status']=='changed'}
    attempted={m['pair_id'] for m in manifest['models'] if m.get('pair_id')}
    evaluated_pairs=[r['metadata'] for r in records if r['metadata'].get('pair_id') and r['metadata']['status']=='changed']
    evaluated_identities={m['pair_id'] for m in evaluated_pairs}
    singles=[r for r in records if len(r['metadata']['operators'])==1]
    swaps=[r for r in singles if r['metadata']['operators']==['swap_owners_consistently']]
    source_accounting=join_mutants(records,source_rows)
    intervals=checker_source_intervals(records,source_accounting)
    return {'source_accounting':source_accounting,'exploratory_source_cluster_intervals':intervals,'run':run.relative_to(ROOT).as_posix(),'summary':summary,'records':records,'discrepancies':discrepancies,'concordant_rejections':concordant_rejections,'agreement':dict(agreement),'properties':dict(properties),'breakdown':{k:dict(v) for k,v in breakdown.items()},'pair_coverage':pair_coverage,'single_operator_eligibility':single_eligibility,'attempted_operator_pairs':len(attempted),'covered_operator_pairs':len(covered),'evaluated_operator_pair_identities':len(evaluated_identities),'evaluated_realized_pair_models':len(evaluated_pairs),'planned_realized_pair_models':sum(bool(m.get('pair_id')) and m['status']=='changed' for m in manifest['models']),'uncovered_operator_pairs':sorted(attempted-covered),'single_mutants':len(singles),'swap_models':len(swaps),'swap_routing_faulty':sum(r['groundtruth']['routing_faulty'] is True for r in swaps),'swap_groundtruth_unresolved':sum(r['groundtruth']['routing_faulty'] is None for r in swaps),'natural_models':sum('natural_diff' in r['metadata']['operators'] for r in records),'snapshot_case_ids':sorted({r['metadata']['room'] for r in records})}


def generate(runs,report,processed,paper,geometry_reports=(),source_manifests=(),retained_progress_tables=None):
    source_rows,source_pins=load_source_manifests(source_manifests)
    all_records=[]
    sections=['# Mutation analysis','', 'Generated by `experiments/report_mutation_analysis.py` from preserved raw WP6 runs. The preregistered endpoint classifies ownership/action faults relative to SPEC and its amendments. Reachability restrictions and consistent changes in ownership are separate outcomes. Each mutant is a unit; probes within it are correlated. No mutant is counted as a new room.', '', '## Scope and authority','', 'The authoritative routing contract is `docs/SPEC.md` with `SPEC_AMENDMENT_A001.md`, `A002.md`, and `A003.md`. I1 defines the candidate label and I2 must agree on every normal verdict. Unresolved models are excluded explicitly. The structural and authoring validators enforce additional publication constraints; disagreement with the narrow routing endpoint is not automatically a validator bug. A publish-time table can implement the same routing decisions, while digest, request schema and commit obligations remain runtime concerns.','', 'V-b includes direct native schema/domain checks and a separately labelled legacy validation view with retained checked-element counts. Placement and knowledge traceability metrics lack their original authoring inputs and remain not applicable. Strict unions cannot claim a pass through unavailable constituents.','', 'The real SessionStore admission path executes with a ScriptedClient. These results measure deterministic admission and rejection atomicity. They do not measure language-model quality, latency, HTTP commit/evidence behavior or a deployed Unity client.','']
    exported=[]
    fields=['run','model','room','operators','checker','cell','authoritative_spec','routing_reasons','checker_evidence','interpretation']
    for run in runs:
        analysis=analyze(run,source_rows);all_records.extend(analysis['records']);s=analysis['summary'];prefix=processed/run.name
        if not s['evaluation_complete']:
            sections += ['> **Incomplete progress snapshot.** The exhaustive run is still in progress. The cells below describe completed outcomes only and must not be cited as the final mutation evaluation.', '']
        discrepancy_path=prefix/'authoring_contract_disagreements.csv'
        concordant_path=prefix/'concordant_rejections.csv'
        csv_file(discrepancy_path,analysis['discrepancies'],fields)
        csv_file(concordant_path,analysis['concordant_rejections'],fields)
        single_path=prefix/'single_operator_eligibility.csv'
        if analysis['single_operator_eligibility']:csv_file(single_path,analysis['single_operator_eligibility'],list(analysis['single_operator_eligibility'][0]))
        pair_path=prefix/'operator_pair_coverage.csv'
        if analysis['pair_coverage']:csv_file(pair_path,analysis['pair_coverage'],list(analysis['pair_coverage'][0]))
        compact={k:v for k,v in analysis.items() if k not in {'records','discrepancies','concordant_rejections','summary','pair_coverage','single_operator_eligibility'}}
        compact['operator_pair_coverage_path']=pair_path.relative_to(ROOT).as_posix()
        compact['single_operator_eligibility_path']=single_path.relative_to(ROOT).as_posix()
        compact.update(summary_path=(run/'summary.json').relative_to(ROOT).as_posix(),discrepancy_cells=len(analysis['discrepancies']),concordant_rejections=len(analysis['concordant_rejections']))
        (prefix/'reporting_summary.json').write_text(json.dumps(compact,indent=2,sort_keys=True)+'\n',encoding='utf-8')
        source_run=run
        if (run/'snapshot_provenance.json').exists():source_run=ROOT/read(run/'snapshot_provenance.json')['source_run'].replace('\\','/')
        if (source_run/'recovery_manifest.json').exists():
            recovery=read(source_run/'recovery_manifest.json')
            compact['recovery_provenance']={'source_run':recovery['source_run'].replace('\\','/'),'reused_completed_outcomes':len(recovery['reused_completed_outcomes']),'counting':'Recovery rows only; original copied outcomes are not additional observations.'}
            source_run=ROOT/recovery['source_run'].replace('\\','/')
        dependency_path=source_run.with_name(source_run.name+'_dependencies.json')
        if dependency_path.exists():
            dependency=read(dependency_path)
            compact['wp5_source_provenance']=[{k:r.get(k) for k in ['case_id','source_room_id','source_priority','pipeline_model','source_sha256','model_sha256']} for r in dependency.get('selected_projects',[])]
        exported.append(compact)
        sections += ['## '+run.name,'',f"Evaluated {s['models_evaluated']} of {s['planned_model_evaluations']} planned changed/incomplete models from {analysis['source_accounting']['counts']['snapshots']} native snapshot(s), joined to {analysis['source_accounting']['counts']['resolved_source_rooms']} source room(s), with {analysis['source_accounting']['counts']['unresolved_mutants']} mutant provenance join(s) unresolved; evaluation complete: **{s['evaluation_complete']}**. There are {analysis['single_mutants']} evaluated single mutants. Completed realized pair models: {analysis['evaluated_realized_pair_models']} of {analysis['planned_realized_pair_models']} planned; {analysis['evaluated_operator_pair_identities']} distinct operator-pair identities have completed. The full manifest realizes {analysis['covered_operator_pairs']} of {analysis['attempted_operator_pairs']} attempted identities across its source projects. Worker failures: {s['worker_failures']}; independent-disagreement models: {s['independent_disagreement_models']}.",'', 'Eligibility: `'+json.dumps(s['eligibility_counts'],sort_keys=True)+'`. Incomplete and no-op attempts are never credited as realized two-fault combinations. Single-operator statuses and inapplicability reasons are in `'+single_path.relative_to(ROOT).as_posix()+'`. Per-source pair attempts, completed/remaining realization counts, cancellation and target evidence are in `'+pair_path.relative_to(ROOT).as_posix()+'`.','', '| Checker | TP | FP | FN | TN | Unresolved | NA | Sensitivity Wilson 95% | FP proportion Wilson 95% |','| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |']
        for row in s['matrix']:
            if row['group']=='all':sections.append('| '+' | '.join(str(v) for v in [row['checker'],row['tp'],row['fp'],row['fn'],row['tn'],row['excluded_groundtruth'],row['not_applicable'],fmt_interval(row['sensitivity_wilson95']),fmt_interval(row['false_positive_wilson95'])])+' |')
        sections += ['',f"The full per-snapshot, per-operator and per-fault-class cells are in `{run.relative_to(ROOT).as_posix()}/detection_matrix.csv`. Every authoring/contract FP or FN is explained in `{discrepancy_path.relative_to(ROOT).as_posix()}` ({len(analysis['discrepancies'])} checker/model cells), with raw diagnostics and agreed routing reasons. `{concordant_path.relative_to(ROOT).as_posix()}` retains {len(analysis['concordant_rejections'])} concordant rejections so accidental structural co-detection is visible; co-occurrence alone is not evidence of causal fault detection.",'','### Executed admission ablations','', '| Variant | Executed probes | Setup-refused probes | Preregistered wrong admissions | Models with wrong admission |','| --- | ---: | ---: | ---: | ---: |']
        for r in s['admission_ablations']:sections.append('| '+' | '.join(str(r[k]) for k in ['variant','executed_probes','setup_refused_probes','wrongly_admitted_probes','models_with_wrong_admission'])+' |')
        sections += ['', 'The preregistered aggregate compares decision, provider and action. Reach-only intentionally returns an unbound action, so its aggregate includes action-binding disagreement even when provider selection agrees. The following **exploratory descriptive decomposition** was added after the endpoint freeze; it does not replace the aggregate. Oracle-rejection admissions identify actual acceptance of a request rejected by the agreed contract.','', '| Variant | Oracle rejection admitted | Decision/provider mismatch | Action-binding mismatch | Fully agreed admission |','| --- | ---: | ---: | ---: | ---: |']
        for name,counts in analysis['breakdown'].items():sections.append('| '+' | '.join(str(x) for x in [name]+[counts.get(k,0) for k in ['oracle_rejection_admitted','decision_or_provider_mismatch','action_binding_mismatch','fully_agreed_admission']])+' |')
        sections += ['', 'Stale-digest request ablation: `'+json.dumps(s['stale_digest_ablations'],sort_keys=True)+'`. These request variants are not additional mutant models.','', 'All-pairs agreement counts: `'+json.dumps(analysis['agreement'],sort_keys=True)+'`.','', 'Rejection-atomicity observations: `'+json.dumps(analysis['properties'],sort_keys=True)+'`; model-level property statuses: `'+json.dumps(s['behavior_properties'],sort_keys=True)+'`. The explicit rejected-request count prevents treating an unexercised implication as affirmative fault-test coverage.','', f"Consistent-swap single mutants evaluated: {analysis['swap_models']}; agreed routing-faulty: {analysis['swap_routing_faulty']}; unresolved: {analysis['swap_groundtruth_unresolved']}. Such a model may encode an undesirable ownership choice yet satisfy the declared routing contract. This is a limit on semantic assurance, not evidence that the new choice is semantically correct. Natural-diff models in this run: {analysis['natural_models']}.",'']
    combined_source_accounting=join_mutants(all_records,source_rows)
    combined_intervals=checker_source_intervals(all_records,combined_source_accounting)
    sections += ['## Source accounting and exploratory uncertainty','', 'Source-accounting counts: `'+json.dumps(combined_source_accounting['counts'],sort_keys=True)+'`. All supplied manifests are verified against explicit SHA256 pins. Missing or conflicting joins are reported, never inferred as new rooms. The paper-input JSON retains every join and separate source-cluster bootstrap intervals by checker. Original Wilson cells above remain unchanged.','']
    geometry_inventory=[]
    for geometry_path in map(Path,geometry_reports):
        geometry=read(geometry_path)
        geometry_inventory.append({'path':geometry_path.relative_to(ROOT).as_posix(),'sha256':hashlib.sha256(geometry_path.read_bytes()).hexdigest(),**{k:v for k,v in geometry.items() if k not in {'records','code_hashes'}}})
        sections += ['## Indicative geometry: '+geometry_path.parent.name,'',f"Measured {geometry['models_measured']} completed consistent-swap model(s); {geometry['models_pending']} listed swaps await routing evaluation. Complete paired geometry is available for {geometry['models_with_complete_paired_geometry']} model(s), covering {geometry['paired_changed_targets']} changed targets; {geometry['unavailable_changed_targets']} changed targets are unavailable. Baseline outside: {geometry['baseline_outside_targets']}; after swap outside: {geometry['mutant_outside_targets']}; newly outside: {geometry['newly_outside_targets']}. Models newly flagged: {geometry['models_newly_flagged']}.",'', 'The unchanged WP5 lint derives axis-aligned boxes from zone members and ignores footprint rotation. These are responses to constructed swaps, not semantic sensitivity or specificity. Whole-scene and changed-target rows, model/source/outcome hashes and source-case provenance are retained in `'+geometry_path.relative_to(ROOT).as_posix()+'`. LLM judge agreement remains unavailable. The classroom auxiliary-case view preserves original source geometry bytes; the earlier missing-normalized-input failure remains archived in snapshot001.','']
    sections += ['## Remaining evidence and interpretation','', 'B0/B1 language-model routing on a stratified mutant subset and independent language-model judgments of consistent swaps are not executed by this harness. Geometric evidence is reported only for explicitly supplied separate snapshots above. Missing outcomes cannot be inferred from ScriptedClient results. Generated-room and natural-evolution coverage is present only when it appears in the raw run inventory above. The supplied classroom alone does not support population-level generalization to generated rooms. Native case IDs identify snapshots; cross-model counterparts and repeated snapshots of one source room are not distinct rooms. Every mutant-to-source join and supplied manifest hash is retained in the paper-input inventory; unresolved joins never create a room. Preregistered Wilson intervals describe mutant units and do not remove source dependence. Separate exploratory percentile bootstrap intervals resample whole resolved sources with all their snapshots/mutants together; fewer than two source clusters is undefined.','', 'The first-match and reach-only comparisons are real executions through the same backend configuration points. Loader refusal prevents a session from existing and is kept separate. Table/runtime equality is an equivalence finding for executed pairs, not a claim that runtime routing checks outperform a table.','', 'Reproduce this document with `python experiments/report_mutation_analysis.py --run-dir <raw-run> [--run-dir <another-run>] --source-manifest <path>=<sha256> [--source-manifest <another-path>=<sha256>] [--geometry <geometry-json>]` using the exact manifest paths and hashes in the paper-input source_manifest_pins array. The immutable raw files and preregistered summary remain authoritative. Reporting metadata is exported to `paper_inputs/wp6_mutation_summary.json`; all generated tables are referenced here and in that inventory. Superseded progress-snapshot tables remain explicitly indexed as audit history, not final evidence.','']
    report.parent.mkdir(parents=True,exist_ok=True);report.write_text('\n'.join(sections),encoding='utf-8')
    paper.parent.mkdir(parents=True,exist_ok=True)
    paper.write_text(json.dumps({'generator':'experiments/report_mutation_analysis.py','generator_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'source_manifest_pins':source_pins,'source_accounting':combined_source_accounting,'exploratory_source_cluster_intervals':combined_intervals,'runs':exported,'geometric_lint_snapshots':geometry_inventory,'report':report.relative_to(ROOT).as_posix(),'retained_progress_snapshot_tables':[p.relative_to(ROOT).as_posix() for p in (sorted((ROOT/'results/processed').glob('wp6*_progress_*/detection_matrix.csv')) if retained_progress_tables is None else [Path(p) for p in retained_progress_tables])]},indent=2,sort_keys=True)+'\n',encoding='utf-8')
    return exported


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run-dir',type=Path,action='append',required=True);p.add_argument('--source-manifest',action='append',default=[],help='Explicit provenance path=SHA256; absent joins remain unresolved');p.add_argument('--geometry',type=Path,action='append',default=[]);p.add_argument('--report',type=Path,default=ROOT/'docs/MUTATION_ANALYSIS.md');p.add_argument('--processed',type=Path,default=ROOT/'results/processed/wp6');p.add_argument('--paper',type=Path,default=ROOT/'paper_inputs/wp6_mutation_summary.json');a=p.parse_args()
    result=generate([r.resolve() for r in a.run_dir],a.report.resolve(),a.processed.resolve(),a.paper.resolve(),[g.resolve() for g in a.geometry],a.source_manifest)
    print(json.dumps({'runs':len(result),'report':str(a.report)}))
if __name__=='__main__':main()

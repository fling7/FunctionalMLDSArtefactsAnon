"""Terminal accounting and immutable evidence for the original registered WP5 runs."""
from collections import Counter
from decimal import Decimal
import json
from pathlib import Path
import sqlite3
from experiments.pipeline_runs import ROOT,load_frozen_plan,digest,write_once
from experiments.export_wp5_projects import export
from repro.budget import Budget

def main():
    plan=load_frozen_plan();manifest=export();rows=[];mismatches=[]
    if manifest['completed_runs']!=len(plan['evaluation']):raise RuntimeError('Original sequence is not terminal')
    for row in manifest['rows']:
        path=ROOT/row['run_result_path'];run=json.loads(path.read_text(encoding='utf-8-sig'))
        for rel,expected in run['artifact_sha256'].items():
            artifact=ROOT/rel
            if not artifact.exists() or digest(artifact)!=expected:mismatches.append({'case_id':row['case_id'],'path':rel,'expected':expected,'actual':digest(artifact) if artifact.exists() else None})
        rows.append({'case_id':row['case_id'],'source_id':row['source_room_id'],'model':row['pipeline_model'],
                     'run_result_path':row['run_result_path'],'run_result_sha256':row['run_result_sha256'],
                     'status':run['status'],'failure_stage':run.get('failure_stage'),'artifact_count':len(run['artifact_sha256'])})
    budget=Budget(ROOT/'logs/api_budget.sqlite3','20');summary=budget.summary()
    if summary['in_flight_usd']!='0.000000000':raise RuntimeError('Calls remain in flight')
    with sqlite3.connect(ROOT/'logs/api_budget.sqlite3') as c:
        events=[json.loads(r[0]) for r in c.execute('SELECT record FROM events ORDER BY id')]
        reservations=[dict(zip(('id','share','experiment','reserved','charged','status','created'),r)) for r in c.execute('SELECT * FROM reservations ORDER BY id')]
        pending=c.execute("SELECT COUNT(*) FROM claims WHERE status='pending'").fetchone()[0]
    if pending:raise RuntimeError('Request claims remain pending')
    by_experiment={}
    for r in reservations:
        e=by_experiment.setdefault(r['experiment'],{'reservations':0,'charged_nanos':0,'unknown_outcomes':0})
        e['reservations']+=1;e['charged_nanos']+=r['charged'];e['unknown_outcomes']+=r['status'] not in ('completed','success')
    for value in by_experiment.values():value['charged_usd']=format(Decimal(value['charged_nanos'])/1_000_000_000,'.9f')
    result={'schema':'wp5-original-terminal-v1','base_plan_sha256':digest(ROOT/'prereg/wp5_plan.json'),
      'execution_amendments':plan.get('_execution_amendments',[]),'terminal':True,'registered_runs':len(plan['evaluation']),
      'completed_runs':len(rows),'status_counts':dict(Counter(r['status'] for r in rows)),
      'failure_stages':dict(Counter(r['failure_stage'] for r in rows if r['status']!='success')),
      'eligible_native_runs':manifest['eligible_runs'],'eligible_distinct_sources':manifest['eligible_distinct_sources'],
      'artifact_hash_mismatches':mismatches,'row_records':rows,'budget':summary,'reservation_costs_by_experiment':by_experiment,
      'retained_unknown_events':[e for e in events if e.get('status') in ('NETWORK_ERROR','UNKNOWN_OUTCOME')],
      'pending_claims':pending,'natural_analysis_terminal':False,'extension_authorized':False}
    write_once(ROOT/'results/raw/wp5/evaluation_terminal_v1.json',result)
    write_once(ROOT/'results/raw/wp5/evaluation_final_manifest_v1.json',manifest)
    write_once(ROOT/'results/raw/wp5/evaluation_budget_after_v1.json',summary)
    budget.export_log(ROOT/'logs/api_calls.jsonl')
    print(json.dumps({k:result[k] for k in ('terminal','registered_runs','status_counts','failure_stages','eligible_native_runs','eligible_distinct_sources','artifact_hash_mismatches','budget')}))
    if mismatches:raise RuntimeError('Retained artifact hashes differ; preserve discrepancy for review')
if __name__=='__main__':main()

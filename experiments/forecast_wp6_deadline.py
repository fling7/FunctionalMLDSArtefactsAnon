"""Read-only, non-WP8 operational deadline sensitivity analysis."""
from pathlib import Path
from datetime import datetime,timezone,timedelta
from collections import Counter
import json,hashlib
ROOT=Path(__file__).resolve().parents[1]
def read(name):return json.loads((ROOT/name).read_text(encoding='utf-8-sig'))
def main():
 process=read('results/raw/wp6_throughput_process_snapshot_002.json');outcomes=read('results/raw/wp6_throughput_outcome_snapshot_002.json');sizes=read('results/raw/wp6_throughput_sizes_v1.json')['rows'];end=datetime.fromisoformat(process['utc']);measured={}
 for kind in ['example','generated']:
  parents={r['process_id'] for r in process['processes'] if f'--run-dir results/raw/wp6_{kind}_combined_recovery_v1' in r['command_line']}
  workers=[r for r in process['processes'] if r['parent_process_id'] in parents and 'spawn_main' in r['command_line']];done=[r for r in outcomes['rows'] if r['kind']==kind and not r['reused']]
  if not workers:measured[kind]={'workers':0,'new_evaluated_models':0,'status':'Still preparing; no generated-campaign throughput estimate.'};continue
  start=min(datetime.fromisoformat(r['creation_utc']) for r in workers);wall=(end-start).total_seconds();cpu=sum(r['cpu_seconds'] for r in workers);pairs=sum(r['pairs'] for r in done)
  measured[kind]={'workers':len(workers),'worker_start_utc':start.isoformat(),'end_utc':end.isoformat(),'wall_seconds':wall,'cpu_seconds_including_inflight':cpu,'new_evaluated_models':len(done),'new_evaluated_pairs':pairs,'setup_refused_models':sum(r['setup']=='reject' for r in done),'models_per_wall_hour':len(done)*3600/wall,'pairs_per_wall_second':pairs/wall,'effective_cores':cpu/wall,'cpu_seconds_per_completed_pair_including_inflight':cpu/pairs}
 planned=Counter()
 for kind in ['example','generated']:
  for row in read(f'results/raw/wp6_{kind}_recovery_v1/mutation_manifest.json')['models']:
   if row['status'] in {'changed','incomplete'}:planned[row['room']]+=1
 completed=Counter(read(row['path'])['metadata']['room'] for row in outcomes['rows']);remaining=[]
 for row in sizes:
  case=row['case_id'];n=planned.get(case,153);remaining.append(dict(row,planned_mutants=n,planning_count_exact=case in planned,completed_once=completed[case],remaining_mutants=n-completed[case]))
 assert sum(planned.values())==759
 plan=read('prereg/wp5_extension_v1/plan.DRAFT.json');evolution=read('prereg/wp5_extension_v1/evolution_registry.DRAFT.json');natural=evolution['registered_pairs']['total'];assert natural==103
 phases={'initial':len(plan['initial_baselines']),'ownership_repair':len(plan['targeted_repair_candidates']),'drift':len(plan['fresh_drift_runs']),'source_edit':len(plan['source_edits']),'zone_rename':1};assert sum(phases.values())==151
 def objects(path):return len(read(path)['scene']['objects'])
 repairs=[objects(row['source']['source_path']) for row in plan['targeted_repair_candidates']];edits=[row['validation']['object_count'] for row in plan['source_edits']]
 ext_sizes=[15]*144+repairs+edits+[15];assert len(ext_sizes)==151
 recovery_max=plan['recovery']['maximum_room_attempts'];recovery_sizes=sorted([objects(row['source_path']) for row in plan['recovery']['rows'] if row.get('source_path') and (ROOT/row['source_path']).exists()],reverse=True)[:recovery_max]
 phases_used={'I2_warm','runtime','firstmatch','reach_only','table','no_digest','I2_compiled_stale','runtime_stale','no_digest_stale'};cpu_per_pair=sum(row['cpu_seconds'] for row in read('results/raw/wp6_combined_probe_benchmark_v1/progress.json') if row['phase'] in phases_used);assert cpu_per_pair==3.1875
 fraction=measured['example']['effective_cores']/measured['example']['workers'];scenarios=[]
 for scale in ['constant80_reference','linear_native_records_unvalidated']:
  def cost(agents,objects,records,mutants):return cpu_per_pair*(records/3117 if scale.startswith('linear') else 1)*agents*objects*mutants
  original=sum(cost(r['agents'],r['scene_objects'],r['native_records'],r['remaining_mutants']) for r in remaining)
  extension=sum(cost(3,n,237+36*n,153) for n in ext_sizes);recovery=sum(cost(3,n,237+36*n,153) for n in recovery_sizes);natural_cost=cost(3,15,777,natural*2)
  for label,cpu in [('remaining_original',original),('all_unconditional_extension',original+extension+natural_cost),('independent_phase_ceiling_with8recovery',original+extension+recovery+natural_cost)]:
   r={'scaling':scale,'workload':label,'cpu_hours':cpu/3600}
   for workers in [8,12]:r[f'hours_at{workers}_ideal_cores']=cpu/3600/workers;r[f'hours_at{workers}_workers_observed_cpu_fraction']=cpu/3600/(workers*fraction)
   scenarios.append(r)
 deadlines={}
 for day in [18,20]:
  for boundary,extra in [('start',0),('end',1)]:
   date=datetime(2026,10,day+extra,tzinfo=timezone(timedelta(hours=2)));deadlines[f'Oct{day}_{boundary}_Europe_Berlin']={'utc':date.astimezone(timezone.utc).isoformat(),'remaining_hours':(date-end).total_seconds()/3600}
 files=['experiments/forecast_wp6_deadline.py','results/raw/wp6_throughput_process_snapshot_002.json','results/raw/wp6_throughput_outcome_snapshot_002.json','results/raw/wp6_throughput_sizes_v1.json','results/raw/wp6_combined_probe_benchmark_v1/progress.json','prereg/wp5_extension_v1/plan.DRAFT.json','prereg/wp5_extension_v1/evolution_registry.DRAFT.json','results/raw/wp6_corpus_original_terminal_v3.json']
 report={'utc':end.isoformat(),'kind':'Operational sensitivity, not WP8 performance evidence; no scope/tuning/cutover change','measured':measured,'actual_baseline_sizes':remaining,'original_native_wp5_snapshots':20,'original_native_source_rooms':18,'supplied_example_snapshots':1,'remaining_original_mutants_estimate':sum(r['remaining_mutants'] for r in remaining),'extension_unconditional_snapshot_slots':phases,'extension_maximum_unconditional_materializations':151,'conditional_recovery_registered_rows':len(plan['recovery']['rows']),'conditional_recovery_maximum_attempts':recovery_max,'natural_pair_registry':evolution['registered_pairs'],'remaining_mutants_if_unconditional_materializes':sum(r['remaining_mutants'] for r in remaining)+151*153,'remaining_mutants_independent_phase_ceiling':sum(r['remaining_mutants'] for r in remaining)+(151+8)*153,'nominal_mutants_per_future_snapshot':153,'pair_cpu_reference':cpu_per_pair,'observed_per_worker_cpu_fraction':fraction,'repair_source_objects':repairs,'edit_source_objects':edits,'largest8conditional_recovery_sizes':recovery_sizes,'deadline_windows':deadlines,'scenarios':scenarios,'assumptions':['Only10 new classroom rows measured, with2 setup refusals; first scheduled mutants are nonrandom. CPU includes in-flight work and initialization. No individual latency or confidence interval is inferred.','Generated campaign is still preparing. No80-object or15-object full combined campaign throughput is measured.','Compute scenarios apply one retained80-object engineering pair cost. Constant cost is not a proven upper bound; linear scaling with native records is an unvalidated sensitivity assumption.','Future15-object scenes assume3agents/777native records as observed in existing15-object projects. Actual native sizes may differ.','153 per future snapshot is nominal. Exact planner keeps all inapplicable/no-op/reverse attempts, so counts can differ; current759 counts are exact.','Natural-diff cost includes2 full15-object endpoint evaluations per each of103registered pairs; missing endpoints stay unavailable and exact future adapter scope remains pending.','Generation, setup/compilation, model preparation, storage verification, reporting, pauses, failure adjudication and contention add time. These are compute-only scenarios.','Current execution remains4classroom+8generated;12-worker long-run capacity is only a sensitivity, not a new worker authorization.8-worker scenario reflects the bounded generated pool.','All151 unconditional materializations plus8recoveries may not jointly occur because recovery is conditional on a distinct-source target; independent-phase ceiling deliberately overstates joint feasibility.','No failing generation is silently excluded to promise completion. No model/operator/validator scope is sampled away.','Initial forecast script assumed registered_pairs was a list; it is a count mapping. The failed assertion produced no forecast artifact and did not affect campaign data.'],'input_sha256':{p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in files}}
 path=ROOT/'results/raw/wp6_deadline_forecast_v1.json';assert not path.exists();path.write_text(json.dumps(report,indent=2)+'\n',encoding='utf8');print(json.dumps({'measured':measured,'remaining_original':report['remaining_original_mutants_estimate'],'remaining_full':report['remaining_mutants_if_unconditional_materializes'],'scenarios':scenarios,'deadlines':deadlines},indent=2),flush=True)
if __name__=='__main__':main()

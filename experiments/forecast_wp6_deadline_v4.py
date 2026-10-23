"""Read-only operational forecast update; preserves v1 and its omission correction."""
from pathlib import Path
from datetime import datetime,timedelta,timezone
from collections import Counter
import hashlib,json
ROOT=Path(__file__).resolve().parents[1]
def read(path):return json.loads((ROOT/path).read_text(encoding='utf-8-sig'))
def sha(path):return hashlib.sha256((ROOT/path).read_bytes()).hexdigest()
def main():
 old=read('results/raw/wp6_deadline_forecast_v1.json');snapshot=read('results/raw/wp6_throughput_outcome_snapshot_006.json');cutoff=datetime.fromisoformat(snapshot['utc']);old_sizes=old['actual_baseline_sizes'];counts=Counter()
 for row in snapshot['rows']:
  matches=[s['case_id'] for s in old_sizes if row['id'].startswith(s['case_id']+'__')]
  assert len(matches)==1,(row['id'],matches)
  counts[matches[0]]+=1
 remaining=[dict(s,completed_once=counts[s['case_id']],remaining_mutants=s['planned_mutants']-counts[s['case_id']]) for s in old_sizes]
 assert len(snapshot['rows'])==sum(counts.values())==sum(r['complete_rows'] for r in snapshot['summaries'])
 phases=old['extension_unconditional_snapshot_slots'];extension_sizes=[15]*144+old['repair_source_objects']+old['edit_source_objects']+[15];assert len(extension_sizes)==sum(phases.values())==151
 natural_count=old['natural_pair_registry']['total'];assert natural_count==103
 cpu_reference=old['pair_cpu_reference'];assert cpu_reference==3.1875
 summary={r['kind']:r for r in snapshot['summaries']};capacity={k:r['effective_cores']/r['workers'] for k,r in summary.items()};capacity['pooled_current_worker_windows']=sum(r['effective_cores'] for r in summary.values())/sum(r['workers'] for r in summary.values())
 scenarios=[]
 for scale in ['constant80_reference','linear_native_records_unvalidated']:
  def cost(agents,objects,records,mutants):return cpu_reference*(records/3117 if scale.startswith('linear') else 1)*agents*objects*mutants
  original=sum(cost(r['agents'],r['scene_objects'],r['native_records'],r['remaining_mutants']) for r in remaining)
  extension=sum(cost(3,n,237+36*n,153) for n in extension_sizes);recovery=sum(cost(3,n,237+36*n,153) for n in old['largest8conditional_recovery_sizes']);natural=cost(3,15,777,natural_count*2)
  for label,cpu in [('remaining_original',original),('all_unconditional_extension',original+extension+natural),('independent_phase_ceiling_with8recovery',original+extension+recovery+natural)]:
   row={'scaling':scale,'workload':label,'partial_reference_cpu_hours':cpu/3600,'omits_measured_unknown_I1_and_other_work':True,'hours_at12_ideal_cores':cpu/3600/12}
   for name,fraction in capacity.items():
    for workers in [8,12]:row[f'hours_at{workers}_workers_{name}_cpu_fraction']=cpu/3600/(workers*fraction)
   scenarios.append(row)
 windows={}
 for day in [18,20]:
  for boundary,extra in [('start',0),('end',1)]:
   date=datetime(2026,10,day+extra,tzinfo=timezone(timedelta(hours=2)));windows[f'Oct{day}_{boundary}_Europe_Berlin']={'utc':date.astimezone(timezone.utc).isoformat(),'remaining_hours':(date-cutoff).total_seconds()/3600}
 generated_remaining=606-summary['generated']['complete_rows'];class_remaining=153-summary['example']['complete_rows']
 extrapolation={'classroom_remaining_models':class_remaining,'classroom_hours_if_first_window_rate_persists':class_remaining/summary['example']['models_per_wall_hour'],'current_four_project_batch_remaining_models':generated_remaining,'generated_hours_if_first_window_rate_persists_at8workers':generated_remaining/summary['generated']['models_per_wall_hour'],'interpretation':'Early nonrandom completion windows; exact setup strata and reduced-pair outcomes are retained in the measurement rows. Remaining batch includes different model sizes. This is a conditional operational sensitivity, not an individual latency, confidence interval or completion guarantee.'}
 prior=read('results/raw/wp6_throughput_outcome_snapshot_005.json');prior_by={r['kind']:r for r in prior['summaries']};interval_wall=(cutoff-datetime.fromisoformat(prior['utc'])).total_seconds();interval={}
 for kind,current in summary.items():
  previous=prior_by[kind];n=current['new_rows']-previous['new_rows'];interval[kind]={'wall_seconds':interval_wall,'new_models':n,'new_setup_pass':current['new_setup_pass']-previous['new_setup_pass'],'new_pairs':current['new_pairs']-previous['new_pairs'],'worker_cpu_seconds_including_inflight':current['worker_cpu_seconds_including_inflight']-previous['worker_cpu_seconds_including_inflight'],'models_per_wall_hour':n*3600/interval_wall,'limitation':'Completion bursts and in-flight work; not individual latency or a steady-state rate.'}
 files=['results/raw/wp6_throughput_outcome_snapshot_005.json','results/raw/wp6_deadline_forecast_v3.json','experiments/forecast_wp6_deadline_v4.py','results/raw/wp6_deadline_forecast_v1.json','results/raw/wp6_deadline_forecast_v1_cost_correction.json','results/raw/wp6_throughput_process_snapshot_006.json','results/raw/wp6_throughput_outcome_snapshot_006.json','results/raw/wp6_throughput_sizes_v1.json','results/raw/wp6_corpus_original_terminal_v3.json']
 report={'utc':snapshot['utc'],'kind':'Operational conditional sensitivity; notWP8 or a predictive confidence interval; no source/scope/worker change','measured':summary,'late_window_since_snapshot005':interval,'per_worker_cpu_fraction':capacity,'early_window_extrapolation':extrapolation,'actual_baseline_sizes':remaining,'remaining_original_mutants_estimate':sum(r['remaining_mutants'] for r in remaining),'extension_unconditional_snapshot_slots':phases,'remaining_mutants_if_unconditional_materializes':sum(r['remaining_mutants'] for r in remaining)+151*153,'natural_pair_registry':old['natural_pair_registry'],'conditional_recovery_registered_rows':old['conditional_recovery_registered_rows'],'conditional_recovery_maximum_attempts':8,'deadline_windows':windows,'partial_pair_cpu_reference':cpu_reference,'explicit_reference_omissions':['I1normal','I1stale','modelsetupandpublication','validators','initialcompilation','materialization','generation','reporting','archiving','pausesandfailureadjudication'],'scenarios':scenarios,'assumptions':['Preservesv1anditsadditiveI1omissioncorrection. The3.1875CPUreference measures7backend probes plusnormal/staleI2 only; omittedI1cost is unknown,neverzero.','Observed completed-row windows include actual I1 and all executed checks. Worker CPU also includes in-flight evaluations/startup and cannot be assigned to completed rows as individual latency.','All49reused observations and all preparation are excluded from new-throughput counts. The generated window now contains both160-pair and240-pair setup-pass models, including a two-fault model. No15-object campaign throughput is measured at this cutoff.','Pooled per-worker CPU fraction combines two differently sized/start-timed windows and is only an explicit sensitivity. Future contention and worker occupancy may change; speedup is not assumed.','Actual current759planned models are exact;153perfuture snapshot is nominal and unchanged original planner may retain inapplicable/no-op/reverse cases. Allrequiredcases/checkersstay.','Every produced project variant remains in008scope;151extension slots and103naturaladjacencies are planned conditional inputs,notobserved generated models. Prior draft-extension design pins remain attached throughv1; no revised scope is inferred.','Natural cost assumes2full15object endpoint evaluations per103pairs; missing endpoints stayunavailable and exactintake remains pending.','The total authorizedworker ceiling is12 afterclassroom completion;010permits ordered freshbatchesonly. No new tuning/cutover is adopted.','No cProfile overhead time is substituted for campaign throughput. Oct20completion remains at substantial risk; these compute-only scenarios do not establish a safe deadline.'],'input_sha256':{p:sha(p) for p in files},'extension_design_input_sha256_retained_from_v1':{k:v for k,v in old['input_sha256'].items() if k.startswith('prereg/wp5_extension')}}
 path=ROOT/'results/raw/wp6_deadline_forecast_v4.json';assert not path.exists();path.write_text(json.dumps(report,indent=2)+'\n',encoding='utf8');print(json.dumps({'utc':report['utc'],'remaining_original':report['remaining_original_mutants_estimate'],'remaining_full':report['remaining_mutants_if_unconditional_materializes'],'capacity':capacity,'early_window':extrapolation,'pooled12_full':[r for r in scenarios if r['workload']=='all_unconditional_extension'],'deadlines':windows},indent=2))
if __name__=='__main__':main()

"""Resume only unmeasured scale1000 after the user P0 addendum; preserve prior cells."""
import sys,json,csv,time,subprocess,statistics,hashlib
from pathlib import Path
from datetime import datetime,timezone
from timing_delta import ROOT,OUT,RAW,CELLS,write

def main():
 interruption=json.loads((OUT/'review/timing_interruption.json').read_text());budget=interruption['remaining_seconds'];start=time.time();deadline=start+budget
 assert not (RAW/'1000/samples.jsonl').exists(),'Do not overwrite measurements'
 hardware=json.loads((OUT/'exports/delta_hardware.json').read_text())
 write(OUT/'exports/delta_hardware_resume.json',{'utc_start':datetime.now(timezone.utc).isoformat(),'remaining_budget_seconds':budget,'power_plan':subprocess.check_output(['powercfg','/getactivescheme'],text=True,errors='replace').strip(),'measurement_script':'drafts/delta_20261020/timing_delta.py','reason':'P0 addendum completed before resume; previously complete18cells are preserved, not remeasured'})
 with (RAW/'1000_resume.log').open('x',encoding='utf-8') as log:
  proc=subprocess.Popen([sys.executable,'-B',str(Path(__file__).with_name('timing_delta.py')),'--worker','1000',str(deadline)],stdout=log,stderr=log)
  try:
   code=proc.wait(timeout=max(0,deadline-time.time()))
   if code:write(RAW/'1000_resume_stop.json',{'reason':'worker execution error','exit_code':code})
  except subprocess.TimeoutExpired:
   subprocess.run(['taskkill','/PID',str(proc.pid),'/T','/F'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);proc.wait(timeout=20)
   write(RAW/'1000_resume_stop.json',{'reason':'remaining25minute active-compute budget exhausted; owned worker tree stopped'})
 rows=[];raw=[]
 for p in RAW.glob('*/samples.jsonl'):
  for line in p.read_text().splitlines():
   try:raw.append(json.loads(line))
   except json.JSONDecodeError:assert not line.endswith('}'),'Unexpected corrupted complete sample'
 old=list(csv.DictReader((ROOT/'exports/cost_scale.csv').open(encoding='utf-8-sig')))
 numeric=[]
 for size in ['classroom','300','1000']:
  for cell in CELLS:
   selected=[r for r in raw if r['size']==size and r['cell']==cell];vals=[r['elapsed_ns']/1e6 for r in selected if not r['discard'] and r['error'] is None];previous=next((r for r in old if r['size']==size and r['cell']==cell),{})
   q=statistics.quantiles(vals,n=4,method='inclusive') if len(vals)>=2 else [None]*3
   r={'size':size,'cell':cell,'status':'DONE' if len(vals)>=10 else 'NOT DONE','warmups_discarded':sum(x['discard'] for x in selected),'repetitions':len(vals),'median_ms':statistics.median(vals) if len(vals)>=10 else None,'q1_ms':q[0] if len(vals)>=10 else None,'q3_ms':q[2] if len(vals)>=10 else None,'iqr_ms':q[2]-q[0] if len(vals)>=10 else None,'failures':sum(x['error'] is not None for x in selected),'old_p50_ms':previous.get('p50_ms'),'old_status':'INVALID_TIMER' if previous else 'NOT PREVIOUSLY MEASURED','comparison':'NEW_WALL_CLOCK_NOT_COMPARABLE_TO_OLD_CPU_CLOCK','script':'drafts/delta_20261020/timing_resume.py'}
   rows.append(r)
   for key,value in r.items():
    if isinstance(value,(int,float)) or key in ['median_ms','q1_ms','q3_ms','iqr_ms']:
     ov=previous.get({'warmups_discarded':'discarded','repetitions':'measured','median_ms':'p50_ms'}.get(key,key));ov=float(ov) if ov not in (None,'') else None
     record={'size':size,'cell':cell,'key':key,'old':ov,'new':value,'flag':'CHANGED' if ov is not None and ov!=value else 'UNCHANGED' if ov is not None else 'NEW_ESTIMATE' if value is not None else 'NOT_DONE','script':r['script']};numeric.append(record);print(json.dumps(record),flush=True)
 for name,data in [('exports/cost_scale.csv',rows),('tables/T8_cost_scale_delta.csv',rows),('tables/T8_cost_scale_legacy_invalid.csv',[dict(r,original_status=r['status'],status='INVALID_TIMER') for r in old])]:
  p=OUT/name;p.parent.mkdir(parents=True,exist_ok=True)
  with p.open('x',newline='',encoding='utf-8') as f:w=csv.DictWriter(f,fieldnames=list(data[0]));w.writeheader();w.writerows(data)
 write(OUT/'review/timing_numeric_changes.json',numeric);write(OUT/'review/timing_samples.json',raw)
 write(OUT/'exports/delta_timing_fixtures.json',[json.loads(p.read_text()) for p in RAW.glob('*/fixture_metadata.json')])
 write(OUT/'review/timing_retained_fixture_pins.json',{p.parent.name:json.loads(p.read_text()) for p in RAW.glob('*/retained_fixture_pins.json')})
 write(OUT/'review/timing_worker_stops.json',[json.loads(p.read_text()) for p in RAW.glob('*_stop.json')])
 terminal={'utc_start':hardware['utc_start'],'utc_end':datetime.now(timezone.utc).isoformat(),'elapsed_seconds':time.time()-start+interruption['elapsed_before_interruption_seconds'],'resume_elapsed_seconds':time.time()-start,'interrupted_for_user_addendum':True,'cells_done':sum(r['status']=='DONE' for r in rows),'cells_total':len(rows),'original_cells':24,'added_gate4_protocol_cells':3,'legacy_status':'INVALID_TIMER','zero_external_calls':True,'old_done':8,'new_done_original_grid':sum(r['status']=='DONE' and r['cell']!='gate4_commit_protocol' for r in rows),'error_samples':[r for r in raw if r['error']]}
 write(OUT/'review/timing_terminal.json',terminal);print(json.dumps(terminal))
if __name__=='__main__':main()

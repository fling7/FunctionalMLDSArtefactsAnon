import json,hashlib,subprocess,time,os
from pathlib import Path
from datetime import datetime,timezone
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'repro/sprint_report.py').exists())
def snapshot():
 cmd="Get-Process | Where-Object { $_.ProcessName -match 'python|pytest|rg$' } | Select-Object Id,ProcessName,CPU | ConvertTo-Json -Compress"
 text=subprocess.check_output(['powershell.exe','-NoProfile','-Command',cmd],text=True).strip()
 v=json.loads(text) if text else [];return v if isinstance(v,list) else [v]
a=snapshot();time.sleep(2);b=snapshot();old={r['Id']:r for r in a}
unexpected=[r for r in b if r['Id'] not in {os.getpid(),os.getppid(),30708}]
assert not unexpected, ('Other computation processes still present',unexpected)
record={'utc':datetime.now(timezone.utc).isoformat(),'scope':'After all P0 worker processes ended; sequential timing only. Windows services and unrelated user applications remain running. No machine-exclusive latency claim.','known_unrelated_server_pid':30708,'snapshots':[a,b],'cpu_seconds_during_two_second_precheck':{str(r['Id']):r['CPU']-old[r['Id']]['CPU'] for r in b if r['Id'] in old and r['CPU'] is not None and old[r['Id']]['CPU'] is not None},'other_research_workers':[],'own_precheck_pid':os.getpid(),'all_p0_agents_finished':True,'timing_launch_mode':'single controller plus one sequential child; controller blocks while child measures'}
p=ROOT/'deliverables/delta_20261020/review/timing_isolation_resume.json';p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(record,indent=2)+'\n');print(json.dumps(record))

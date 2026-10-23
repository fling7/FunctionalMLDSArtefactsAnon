"""Documented throughput-only amendment; unchanged scientific cases and hard deadline."""
import importlib.util,sys,json,hashlib
from pathlib import Path
from datetime import datetime,timezone
R=Path(__file__).resolve().parents[3];sys.path.insert(0,str(R))
p=Path(__file__).with_name('stage_b_v5.py');spec=importlib.util.spec_from_file_location('stage_b_original',p);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
a=m.read(m.RAW/'execution_amendment.json');assert m.sha(p)==a['original_script_sha256'];assert m.sha(m.RAW/'preregistration_v5.json')==a['original_preregistration_sha256']
for name,digest in a['preserved_completed_hashes'].items():assert m.sha(R/name)==digest
remaining=(datetime.fromisoformat(a['original_deadline_utc'])-datetime.now(timezone.utc)).total_seconds();assert remaining>0
oldread=m.read
def read(path):
 value=oldread(path)
 if Path(path).name=='preregistration_v5.json':value={**value,'worker_limit':a['worker_limit'],'budget_seconds':remaining}
 return value
m.read=read
# taskkill can report255 when its killed child makes the launcher exit first.
# Confirm actual launcher termination before accepting that race; never ignore
# a still-running owned process.
import subprocess
def stop_owned(proc):
 if proc.poll() is not None:proc.wait(timeout=10);return
 result=subprocess.run(['taskkill','/PID',str(proc.pid),'/T','/F'],capture_output=True)
 try:proc.wait(timeout=10)
 except subprocess.TimeoutExpired:raise RuntimeError('OWNED_WORKER_STILL_RUNNING_AFTER_TASKKILL_'+str(result.returncode))
m.stop_owned_tree=stop_owned
m.execute()
for name,digest in a['preserved_completed_hashes'].items():assert m.sha(R/name)==digest
m.save(m.RAW/'execution_amendment_completion_v2.json',{'status':'TERMINATED','original_deadline_utc':a['original_deadline_utc'],'finished_utc':datetime.now(timezone.utc).isoformat(),'preserved_completed_hashes_verified':True,'wrapper_sha256':m.sha(Path(__file__)),'scientific_cases_and_checkers_unchanged':True})

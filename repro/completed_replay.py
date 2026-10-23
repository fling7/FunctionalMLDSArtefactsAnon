"""Bounded offline report replay of retained checkpoints plus current closeout."""
from __future__ import annotations
import argparse,contextlib,hashlib,importlib.util,io,json,os,shutil,subprocess,sys,uuid
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
BUNDLE='drafts/artifact_release/composite_subset_v1/input_root'
SELECTOR='repro/run_all.py'
SELECTOR_SHA256='8762beb0da06d9694959bbe5b8f35de09bb11006d1ae68737e4f24f2890e3d07'
GROUPS=('WP1','WP2','WP5','WP6','WP7')
SCOPES={
 'WP1':'Frozen metamodel/architecture report inputs; 21 outputs.',
 'WP2':'Closed differential and historical property-prefix report inputs; 7 outputs. Not the final six-shard aggregate.',
 'WP5':'Original generation/natural cohort only; 24 outputs. Extensions and final evolution excluded.',
 'WP6':'Historical 130-mutant closed snapshot across two sources; 12 outputs. Not the final mutation campaign.',
 'WP7':'Completed offline synthetic protocol evidence; 14 outputs. No natural-evolution inference.',
 'CLOSEOUT':'Current retained closeout aggregation; report-only, no new evaluators or model calls.'}
MISSING=[
 {'scope':'current_WP4_router_HTTP_full_report','status':'not_registered_in_sealed_report_bundle','note':'Current closeout summary is separate from a full routing/HTTP table and figure replay.'},
 {'scope':'current_WP5_all_cohorts_evolution','status':'incomplete_or_unregistered'},
 {'scope':'current_WP6_full_mutation_campaign','status':'incomplete'},
 {'scope':'global_numbers_and_handover','status':'intentionally_not_regenerated','note':'Historical global numbers and make_handover would overwrite truthful current closeout.'},
 {'scope':'all_scope_G9_anonymous_Linux_certification','status':'not_established'}]

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def save(path,value):path.write_text(json.dumps(value,sort_keys=True,indent=2)+'\n',encoding='utf-8')
def destination(root,value):
 root=Path(root).resolve();path=Path(value)
 if not path.is_absolute():path=root/path
 path=path.absolute()
 if not path.resolve().is_relative_to(root/'results/replay'):raise ValueError('Output must stay under results/replay in this repository')
 for item in (path,*path.parents):
  if item==root:break
  if item.is_symlink() or (item.exists() and getattr(item.lstat(),'st_file_attributes',0)&0x400):raise ValueError('Linked output path refused')
 if path.exists():raise ValueError('Output already exists; previous results are preserved')
 return path

def load_bundle(root):
 bundle=root/BUNDLE;path=bundle/SELECTOR
 if not path.is_file():raise ValueError('Missing sealed replay bundle: '+BUNDLE+'; restore its registered inputs, not live replacements')
 if sha(path)!=SELECTOR_SHA256:raise ValueError('Sealed replay selector pin mismatch')
 spec=importlib.util.spec_from_file_location('_retained_completed_replay_selector',path)
 selector=importlib.util.module_from_spec(spec);spec.loader.exec_module(selector)
 minor,full,index=selector.select(bundle)
 _,subsets=selector.select_subsets(bundle,index)
 executor=selector.load_executor(bundle,index)
 return bundle,minor,subsets,executor

def run_group(root,output,group,prepared):
 bundle,minor,subsets,executor=prepared;registry=subsets[(group,minor)]
 # The unchanged executor validates every source/raw/runtime pin before staging.
 inner=bundle/'results/replay'/('resume_'+uuid.uuid4().hex)/group
 result=executor.execute(bundle,registry,inner,False)
 if result['status']!='complete':raise ValueError('Sealed report did not complete: '+group)
 copied={};target=output/'reports'/group
 for command in result['commands']:
  for rel,expected in command['outputs'].items():
   source=inner/'workspace'/rel
   if sha(source)!=expected:raise ValueError('Generated report changed before copy')
   dest=target/rel;dest.parent.mkdir(parents=True,exist_ok=True)
   with dest.open('xb') as stream:stream.write(source.read_bytes())
   if sha(dest)!=expected:raise ValueError('Copied report hash mismatch')
   copied[dest.relative_to(output).as_posix()]=expected
 return {'status':'complete','scope':SCOPES[group],'profile':minor,'outputs':copied,
  'sealed_run':inner.relative_to(root).as_posix(),'sealed_status_sha256':sha(inner/'run_status.json'),
  'registry_sha256':sha(inner/'registry.json'),'global_numbers_selected':False}

def run_closeout(root,output):
 script=root/'repro/report_closeout.py'
 if not script.is_file():raise ValueError('Current closeout report command is unavailable; no substitute used')
 source_hash=sha(script);target=output/'closeout'
 env={k:os.environ[k] for k in ('SystemRoot','WINDIR','TEMP','TMP') if k in os.environ}
 env['PYTHONDONTWRITEBYTECODE']='1'
 command=[sys.executable,'-I','-B',str(script),'--output',str(target)]
 result=subprocess.run(command,cwd=root,env=env,capture_output=True,timeout=120)
 (output/'closeout.stdout.txt').write_bytes(result.stdout);(output/'closeout.stderr.txt').write_bytes(result.stderr)
 if result.returncode:raise ValueError('Closeout report refused; see retained stderr')
 if sha(script)!=source_hash:raise ValueError('Closeout report source changed during execution')
 names=('summary.json','evidence_table.csv','number_sources.json')
 return {'status':'complete','scope':SCOPES['CLOSEOUT'],'source_sha256':source_hash,
  'outputs':{(target/name).relative_to(output).as_posix():sha(target/name) for name in names}}

def replay(root,output,groups,include_closeout=True):
 output=destination(root,output);output.mkdir(parents=True)
 status={'schema':'bounded-completed-scope-replay-v1','status':'running','started_utc':datetime.now(timezone.utc).isoformat(),
  'selected_groups':list(groups),'selected_closeout':include_closeout,'research_complete':False,'all_scope_G9':False,
  'kind':'offline_report_regeneration_only','no_global_numbers_or_handover_mutation':True,'reports':{},
  'missing_scope':MISSING,'replay_cli_sha256':sha(Path(__file__))}
 save(output/'missing_scope.json',{'missing':MISSING,'scientific_completeness':False})
 save(output/'manifest.json',status)
 try:
  prepared=load_bundle(root) if groups else None
  if prepared:
   for group in groups:prepared[3].validate(prepared[0],prepared[2][(group,prepared[1])],False)
  if include_closeout and not(root/'repro/report_closeout.py').is_file():raise ValueError('Missing current closeout report implementation')
  for group in groups:
   status['reports'][group]={'status':'running','scope':SCOPES[group]};save(output/'manifest.json',status)
   status['reports'][group]=run_group(root,output,group,prepared);save(output/'manifest.json',status)
  if include_closeout:
   status['reports']['CLOSEOUT']=run_closeout(root,output)
  status['status']='complete_declared_scope_only';status['finished_utc']=datetime.now(timezone.utc).isoformat()
  save(output/'manifest.json',status)
  return status
 except BaseException as exc:
  status['status']='failed';status['error']={'type':type(exc).__name__,'message':str(exc)}
  save(output/'manifest.json',status);raise

def main(argv=None):
 parser=argparse.ArgumentParser(description=__doc__)
 mode=parser.add_mutually_exclusive_group(required=True)
 mode.add_argument('--replay',action='store_true');mode.add_argument('--offline',action='store_true',help='Alias for report replay; does not run the historical test suite')
 mode.add_argument('--llm',action='store_true')
 parser.add_argument('--only',choices=(*GROUPS,'CLOSEOUT'))
 parser.add_argument('--output','--run-dir',dest='output')
 args=parser.parse_args(argv)
 if args.llm:parser.error('Paid calls are not authorized or implemented by this entry point')
 groups=GROUPS if args.only is None else (() if args.only=='CLOSEOUT' else (args.only,))
 include_closeout=args.only in (None,'CLOSEOUT')
 value=args.output or 'results/replay/completed_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'_'+uuid.uuid4().hex[:8]
 try:status=replay(ROOT,value,groups,include_closeout)
 except Exception as exc:
  print('Replay refused/failed: '+str(exc),file=sys.stderr);return 1
 print(json.dumps({'status':status['status'],'output':str(Path(value)),'all_scope_G9':False,'missing_scope':'missing_scope.json'},sort_keys=True))
 return 0
if __name__=='__main__':raise SystemExit(main())

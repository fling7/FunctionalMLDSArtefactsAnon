"""Draft sealed offline report replay. No evaluator execution or release certification."""
from __future__ import annotations
import argparse, hashlib, importlib.metadata, json, os, platform, re, shutil, subprocess, sys
from pathlib import Path, PurePosixPath

SCHEMA='sealed-report-replay-DRAFT-v4'
BAD_PARTS={'.git','.venv','independent','excluded_client','.aws','.codex','logs'}
BAD_FILES={'config.json','fragebogen-antworten-2026-08-17-vollstaendig-imputiert.json'}
SHA=re.compile('^[0-9a-f]{64}$')
WP1_ROUTING_OUTPUTS=frozenset({
 'output/metamodel_v2/figures/routing_slice_single.svg',
 'output/metamodel_v2/figures/routing_slice_single.pdf',
 'output/metamodel_v2/figures/routing_slice_single.png',
 'output/metamodel_v2/figures/routing_slice_double.svg',
 'output/metamodel_v2/figures/routing_slice_double.pdf',
 'output/metamodel_v2/figures/routing_slice_double.png',
 'output/metamodel_v2/figures/routing_figure_manifest.json',
})
SCRIPTS={'wp4':'experiments/analyze_wp4.py','wp5':'experiments/report_wp5.py',
         'wp6':'experiments/report_mutation_analysis.py'}
OPTIONS={'wp4':{'--routing':1,'--http':1,'--questions':1,'--corpus':1,'--gateway-log':1,'--output-root':1,'--no-figures':0},
 'wp5':{'--extension-analysis-manifest':1},
 'wp6':{'--run-dir':1,'--source-manifest':1,'--geometry':1,'--report':1,'--processed':1,'--paper':1}}

def relative(value):
 if not isinstance(value,str) or not value or '\\' in value:raise ValueError('noncanonical path')
 p=PurePosixPath(value)
 if p.is_absolute() or ':' in value or '..' in p.parts or any(c in value for c in '*?[]\0'):
  raise ValueError('absolute/traversal/glob path refused')
 if any(x.lower() in BAD_PARTS|BAD_FILES or x.lower().startswith('\x2eenv') or 'questionnaire' in x.lower() for x in p.parts):
  raise ValueError('excluded/private path')
 if p.suffix.lower() in {'.db','.sqlite','.sqlite3','.pkl','.pickle'}:raise ValueError('database/pickle input refused')
 return p.as_posix()

def safe(root,rel):
 rel=relative(rel); p=root/rel
 if not p.resolve().is_relative_to(root.resolve()):raise ValueError('path escapes root')
 q=p
 while q!=root:
  if q.is_symlink() or (hasattr(q,'is_junction') and q.is_junction()):raise ValueError('linked path refused')
  q=q.parent
 return p

def sha(p):
 h=hashlib.sha256(); before=p.stat()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 after=p.stat()
 if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):raise ValueError('file changed during hash')
 return h.hexdigest()

def exact(obj,required,optional=()):
 if not isinstance(obj,dict) or set(obj)-set(required)-set(optional) or set(required)-set(obj):
  raise ValueError('invalid schema keys')

def overlap(a,b):
 a=a.casefold().rstrip('/'); b=b.casefold().rstrip('/')
 return a=='.' or b=='.' or a==b or a.startswith(b+'/') or b.startswith(a+'/')

def runtime_identity():
 # Interpreter identity is observed provenance, not a platform-specific admission pin.
 return {'implementation':platform.python_implementation(),'python_version':platform.python_version(),
         'executable_sha256':sha(Path(sys.executable)),
         'executor_sha256':sha(Path(__file__)),'guard_sha256':sha(Path(__file__).with_name('replay_guard.py')),
         'platform':platform.system(),'machine':platform.machine()}

def runtime_policy(packages=None,requirements_lock=None):
 observed=runtime_identity()
 policy={'policy':'portable-cpython-minimum-v1','implementation':'CPython','minimum_version':'3.11',
         'executor_sha256':observed['executor_sha256'],'guard_sha256':observed['guard_sha256'],
         'packages':{} if packages is None else dict(packages)}
 if requirements_lock is not None:policy['requirements_lock']=requirements_lock
 return policy

def validate_runtime(runtime,engineering,pins):
 exact(runtime,{'policy','implementation','minimum_version','executor_sha256','guard_sha256','packages'}, {'requirements_lock'})
 if runtime['policy']!='portable-cpython-minimum-v1' or runtime['implementation']!='CPython' or runtime['minimum_version']!='3.11':
  raise ValueError('unsupported portable runtime policy')
 if any(not isinstance(runtime[k],str) or not SHA.fullmatch(runtime[k]) for k in ('executor_sha256','guard_sha256')):
  raise ValueError('invalid runtime/source pin')
 if not isinstance(runtime['packages'],dict) or any(not isinstance(k,str) or not re.fullmatch('[a-zA-Z0-9_.-]+',k) or not isinstance(v,str) for k,v in runtime['packages'].items()):raise ValueError('invalid runtime packages')
 if not engineering:
  lock=runtime.get('requirements_lock')
  if lock not in pins or pins[lock]['role']!='dependency' or not runtime['packages']:raise ValueError('scientific report needs pinned runtime lock and package versions')
 observed=runtime_identity()
 version=re.fullmatch('([0-9]+)\\.([0-9]+)\\.([0-9]+)',observed['python_version'])
 if observed['implementation']!='CPython' or version is None or tuple(map(int,version.groups()))<(3,11,0):
  raise ValueError('unsupported runtime: requires CPython >= 3.11 final release')
 for name in ('executor_sha256','guard_sha256'):
  if runtime[name]!=observed[name]:raise ValueError('runtime/source mismatch: '+name)
 actual_packages={}
 for package,version in runtime['packages'].items():
  actual_packages[package]=importlib.metadata.version(package)
  if actual_packages[package]!=version:raise ValueError('runtime package version mismatch')
 return {**observed,'packages':actual_packages}

def validate(root,data,engineering=False):
 exact(data,{'schema','status','kind','input_state','pins','terminal_witnesses','commands','runtime'}, {'notes'})
 if data['schema']!=SCHEMA or data['status']!='frozen':raise ValueError('registry is not frozen/recognized')
 if data['kind'] not in {'report_regeneration','engineering_fixture'}:raise ValueError('evaluator reexecution refused')
 if (data['kind']=='engineering_fixture') != engineering:raise ValueError('engineering mode must be explicit')
 if data['input_state']!='terminal_or_explicitly_interrupted':raise ValueError('active input refused')
 if not isinstance(data['pins'],dict) or not data['pins']:raise ValueError('missing pins')
 pins={}; canonical=set()
 for name,row in data['pins'].items():
  exact(row,{'sha256','role'})
  rel=relative(name)
  if rel.casefold() in canonical:raise ValueError('duplicate case-insensitive pin')
  canonical.add(rel.casefold())
  if row['role'] not in {'raw','terminal','source','dependency','source_manifest'} or not SHA.fullmatch(row['sha256']):raise ValueError('invalid pin')
  pins[rel]=row
 if not isinstance(data['commands'],list) or not data['commands']:raise ValueError('empty command list')
 outputs=[];ids=set()
 for cmd in data['commands']:
  exact(cmd,{'id','kind','interpreter','script','args','outputs','timeout_seconds'}, {'reviewed_auxiliary','generated_inputs'})
  if not isinstance(cmd['id'],str) or not re.fullmatch('[a-z0-9_-]+',cmd['id']) or cmd['id'] in ids:raise ValueError('invalid command id')
  ids.add(cmd['id'])
  if cmd['interpreter']!='current_python' or cmd['kind']!='report_regeneration':raise ValueError('unsupported interpreter/execution kind')
  script=relative(cmd['script'])
  if script not in pins or pins[script]['role']!='source' or not script.endswith('.py'):raise ValueError('unpinned source script')
  label=next((k for k,v in SCRIPTS.items() if v==script),None)
  fixture=engineering and script.startswith('drafts/artifact_release/replay/fixtures/')
  aux=cmd.get('reviewed_auxiliary')
  if label is None and not fixture:
   if aux is not True or not re.fullmatch('(experiments|repro)/report_[a-z0-9_]+\\.py',script):raise ValueError('unsupported report script')
   # Auxiliary adapters deliberately accept no arbitrary switches/code; explicit
   # manifest API is the only future extension point.
   options={'--manifest':1,'--output-root':1}
  else:options=OPTIONS.get(label,{'--input':1,'--output':1,'--action':1})
  if not isinstance(cmd['args'],list) or any(not isinstance(a,str) for a in cmd['args']):raise ValueError('args must be strings')
  if label=='wp4' and engineering:
   options={**options,'--engineering-fixture':0}
   if '--engineering-fixture' not in cmd['args']:raise ValueError('WP4 synthetic trial requires engineering fixture flag')
  i=0
  while i<len(cmd['args']):
   flag=cmd['args'][i]
   if flag not in options:raise ValueError('unsupported argument')
   if options[flag]:
    i+=1
    if i>=len(cmd['args']):raise ValueError('missing argument value')
    value=cmd['args'][i]
    if fixture and flag=='--action':
     if value not in {'sum','network','database','unlisted','glob','model_api'}:raise ValueError('bad fixture action')
    elif flag=='--source-manifest':
     parts=value.rsplit('=',1)
     if len(parts)!=2 or parts[0] not in pins or parts[1]!=pins[parts[0]]['sha256']:raise ValueError('source manifest pin mismatch')
     relative(parts[0])
    else:relative(value)
   i+=1
  if type(cmd['timeout_seconds']) is not int or not 1<=cmd['timeout_seconds']<=300:raise ValueError('invalid bounded timeout')
  if not isinstance(cmd['outputs'],list) or not cmd['outputs']:raise ValueError('explicit outputs required')
  generated=cmd.get('generated_inputs',[])
  if not isinstance(generated,list) or any(relative(x) not in outputs for x in generated):raise ValueError('generated input must be an earlier declared output')
  for value in cmd['outputs']:
   rel=relative(value)
   if not engineering and not (rel.startswith(('results/processed/','paper_inputs/','docs/')) or rel in WP1_ROUTING_OUTPUTS):raise ValueError('unsupported output root')
   if any(overlap(rel,x) for x in pins) or any(overlap(rel,x) for x in outputs):raise ValueError('output overlaps pinned input or other output')
   outputs.append(rel)
 if not isinstance(data['terminal_witnesses'],list) or not data['terminal_witnesses']:raise ValueError('terminal witnesses required')
 covered=set()
 for witness in data['terminal_witnesses']:
  exact(witness,{'path','equals','covers'})
  rel=relative(witness['path'])
  if rel not in pins or pins[rel]['role']!='terminal' or not isinstance(witness['equals'],dict) or not witness['equals']:raise ValueError('invalid terminal witness')
  terminal_values={'pass','passed','fail','failed','complete','completed','success','interrupted','interrupted_for_protocol_correction'}
  predicates=witness['equals']
  terminal_claim=(predicates.get('terminal') is True or predicates.get('status') in terminal_values or (predicates.get('evaluation_complete') is True and predicates.get('worker_failures') in (0,[],{})))
  if not terminal_claim:raise ValueError('witness does not explicitly assert terminal/interrupted state')
  # Predicates are explicit provenance claims, never inferred from directory names.
  if not isinstance(witness['covers'],list):raise ValueError('invalid witness coverage')
  for name in witness['covers']:
   if name not in pins or pins[name]['role'] not in {'raw','source_manifest'}:raise ValueError('unknown covered input')
   covered.add(name)
 if {n for n,p in pins.items() if p['role'] in {'raw','source_manifest'}}-covered:raise ValueError('unwitnessed raw input')
 validate_runtime(data['runtime'],engineering,pins)
 # All schema/command/path validation completes before any input file is opened.
 for rel,row in pins.items():
  p=safe(root,rel)
  if not p.is_file() or sha(p)!=row['sha256']:raise ValueError('missing/tampered pin: '+rel)
 for witness in data['terminal_witnesses']:
  doc=json.loads(safe(root,witness['path']).read_text(encoding='utf-8-sig'))
  if any(doc.get(k)!=v for k,v in witness['equals'].items()):raise ValueError('terminal predicate mismatch')
 return outputs

def execute(root,data,run_dir,engineering=False):
 root=Path(root).resolve();run_dir=Path(run_dir).resolve()
 validate(root,data,engineering)
 if not run_dir.is_relative_to(root) or run_dir==root:raise ValueError('run directory must remain within root')
 if run_dir.exists():raise ValueError('run directory already exists')
 if any(run_dir==safe(root,n) or run_dir in safe(root,n).parents for n in data['pins']):raise ValueError('run directory overlaps input')
 run_dir.mkdir(parents=True);stage=run_dir/'workspace';stage.mkdir();scratch=run_dir/'scratch';scratch.mkdir()
 registry_bytes=(json.dumps(data,sort_keys=True,separators=(',',':'))+'\n').encode()
 status={'registry_canonical_sha256':hashlib.sha256(registry_bytes).hexdigest(),'schema':'sealed-report-run-DRAFT-v4','kind':data['kind'],'runtime_policy':data['runtime'],'runtime_observed':validate_runtime(data['runtime'],engineering,data['pins']),'certifies_completeness':False,'release_recommendation':'NO-GO','commands':[],'status':'running'}
 def persist(): (run_dir/'run_status.json').write_text(json.dumps(status,indent=2,sort_keys=True)+'\n',encoding='utf-8')
 persist()
 try:
  for rel,row in data['pins'].items():
   source=safe(root,rel);dest=safe(stage,rel);dest.parent.mkdir(parents=True,exist_ok=True)
   if sha(source)!=row['sha256']:raise ValueError('source changed before staging')
   shutil.copyfile(source,dest)
   if sha(dest)!=row['sha256'] or sha(source)!=row['sha256']:raise ValueError('source changed while staging')
  bootstrap=Path(__file__).with_name('replay_guard.py').resolve()
  status['executor_sha256']=sha(Path(__file__));status['guard_sha256']=sha(bootstrap)
  (run_dir/'registry.json').write_text(json.dumps(data,indent=2,sort_keys=True)+'\n',encoding='utf-8')
  runtime_roots=list(dict.fromkeys([sys.base_prefix,sys.prefix]))
  generated_pins={}
  for cmd in data['commands']:
   for rel in cmd.get('generated_inputs',[]):
    if sha(safe(stage,rel))!=generated_pins[rel]:raise ValueError('generated dependency changed')
   # Recheck every pin before each subprocess, including source/dependency pins.
   for rel,pin in data['pins'].items():
    if sha(safe(stage,rel))!=pin['sha256']:raise ValueError('staged input changed')
   # Some unchanged reports expect their declared output directories to exist.
   # Create only validated output parents in the isolated new stage, never files.
   for rel in cmd['outputs']:safe(stage,rel).parent.mkdir(parents=True,exist_ok=True)
   config={'stage':str(stage),'scratch':str(scratch),'runtime_roots':runtime_roots,
           'inputs':list(data['pins'])+cmd.get('generated_inputs',[]),'outputs':cmd['outputs'],'all_outputs':[p for c in data['commands'] for p in c['outputs']],'script':cmd['script'],'args':cmd['args']}
   cfg=run_dir/(cmd['id']+'_bootstrap.json');cfg.write_text(json.dumps(config),encoding='utf-8')
   env={k:os.environ[k] for k in ('SystemRoot','WINDIR') if k in os.environ}
   env.update({'TEMP':str(scratch),'TMP':str(scratch),'HOME':str(scratch),'USERPROFILE':str(scratch),
               'MPLCONFIGDIR':str(scratch/'mpl'),'MPLBACKEND':'Agg','PYTHONDONTWRITEBYTECODE':'1'})
   argv=[sys.executable,'-I','-B',str(bootstrap),str(cfg)]
   result={'id':cmd['id'],'argv':[cmd['script'],*cmd['args']],'kind':'report_regeneration','status':'running'}
   status['commands'].append(result);persist()
   try:
    completed=subprocess.run(argv,cwd=stage,env=env,capture_output=True,timeout=cmd['timeout_seconds'],check=False)
    (run_dir/(cmd['id']+'.stdout.txt')).write_bytes(completed.stdout)
    (run_dir/(cmd['id']+'.stderr.txt')).write_bytes(completed.stderr)
    result['returncode']=completed.returncode
    if completed.returncode:raise ValueError('report subprocess failed: '+cmd['id'])
   except subprocess.TimeoutExpired as exc:
    (run_dir/(cmd['id']+'.stdout.txt')).write_bytes(exc.stdout or b'')
    (run_dir/(cmd['id']+'.stderr.txt')).write_bytes(exc.stderr or b'')
    raise ValueError('bounded report timeout: '+cmd['id']) from exc
   result['outputs']={rel:sha(safe(stage,rel)) for rel in cmd['outputs']}
   for rel,pin in data['pins'].items():
    if sha(safe(stage,rel))!=pin['sha256']:raise ValueError('input mutated by report')
   generated_pins.update(result['outputs'])
   result['status']='complete';persist()
  status['status']='complete';persist();return status
 except BaseException as exc:
  if status['commands'] and status['commands'][-1]['status']=='running':
   status['commands'][-1].update(status='failed',error={'type':type(exc).__name__,'message':str(exc)})
   status['commands'][-1]['partial_outputs']={rel:sha(safe(stage,rel)) for rel in cmd['outputs'] if safe(stage,rel).is_file()}
  status.update(status='failed',error={'type':type(exc).__name__,'message':str(exc)});persist();raise

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,required=True)
 p.add_argument('--registry',type=Path,required=True);p.add_argument('--run-dir',type=Path)
 p.add_argument('--engineering',action='store_true');p.add_argument('--validate-only',action='store_true');a=p.parse_args()
 data=json.loads(a.registry.read_text(encoding='utf-8-sig'))
 if a.validate_only:validate(a.root.resolve(),data,a.engineering);print('Validated; no subprocess executed.');return
 if a.run_dir is None:p.error('--run-dir required for execution')
 execute(a.root,data,a.run_dir,a.engineering)
if __name__=='__main__':main()

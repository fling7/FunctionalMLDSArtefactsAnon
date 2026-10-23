"""Child guard for trusted, reviewed Python report code; not an OS security sandbox."""
from pathlib import Path
import json,os,runpy,sys
# Trusted stdlib initialization only, before adding the staged import path.
# On Windows this initializes kernel32.GetLastError used by NumPy imports.
# The installed audit hook still refuses all later ctypes load/symbol events.
import ctypes

config=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
stage=Path(config['stage']).resolve();scratch=Path(config['scratch']).resolve()
inputs={os.path.normcase(str(stage/p)) for p in config['inputs']}
outputs={os.path.normcase(str(stage/p)) for p in config['outputs']}
all_outputs=[stage/p for p in config['all_outputs']]
runtime=[Path(p).resolve() for p in config['runtime_roots']]
# Runtime libraries may initialize normal caches only in the isolated scratch area.
# Import search ignores user site/PYTHONPATH (-I); only staged project modules are added.
sys.path.insert(0,str(stage));sys.dont_write_bytecode=True
blocked={'config.json','fragebogen-antworten-2026-08-17-vollstaendig-imputiert.json'}
output_parents={os.path.normcase(str(p)) for rel in config['outputs'] for p in (stage/rel).parents if p.is_relative_to(stage)}

def path_of(value):
 if not isinstance(value,(str,bytes,os.PathLike)):raise PermissionError('non-path file descriptor refused')
 p=Path(os.fsdecode(value))
 if not p.is_absolute():p=Path.cwd()/p
 # absolute lexical normalization avoids recursive audit-hook filesystem access.
 return Path(os.path.abspath(p))

def private(p):
 return any(x.lower() in blocked or x.lower().startswith('\x2eenv') or 'questionnaire' in x.lower()
            or x.lower() in {'.aws','.codex','.git','excluded_client','independent'} for x in p.parts)

def writable(p):
 return p.is_relative_to(scratch) or os.path.normcase(str(p)) in outputs

def readable(p):
 if private(p) or p.suffix.lower() in {'.db','.sqlite','.sqlite3'}:return False
 key=os.path.normcase(str(p))
 return key in inputs|outputs or p.is_relative_to(scratch) or any(p.is_relative_to(r) for r in runtime)

def audit(event,args):
 if event.startswith(('socket.','sqlite3.','subprocess.','ctypes.')) or event in {'os.system','os.exec','os.spawn','pty.spawn'}:
  raise PermissionError('offline report guard: external execution/network/database refused')
 if event.startswith('glob.glob'):
  raise PermissionError('glob module expansion refused; use sealed explicit paths')
 if event in {'pathlib.Path.glob','pathlib.Path.rglob'}:
  p=path_of(args[0]);pattern=str(args[1])
  if private(p) or '..' in Path(pattern).parts or Path(pattern).is_absolute():
   raise PermissionError('private/traversing glob refused')
  # These roots already permit reads/enumeration; package style/font discovery
  # and isolated scratch caches gain no host/home or live input permission.
  runtime_or_scratch=p.is_relative_to(scratch) or any(p.is_relative_to(r) for r in runtime)
  if not runtime_or_scratch and (not p.is_relative_to(stage) or any(p==q or p in q.parents or q in p.parents for q in all_outputs)):
   raise PermissionError('glob into mutable/output tree refused')
 if event=='import':
  name=str(args[0])
  if name in {'openai','sqlite3','requests','httpx'} or name.startswith(('openai.','backend','verification.impl_','repro.llm','repro.budget')):
   raise PermissionError('offline report guard: model/evaluator/database import refused')
 if event=='open':
  p=path_of(args[0]);mode=args[1];flags=args[2]
  writing=(isinstance(mode,str) and any(c in mode for c in 'wax+')) or (isinstance(flags,int) and bool(flags&(os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND)))
  if private(p) or not (writable(p) if writing else readable(p)):
   raise PermissionError('offline report guard: undeclared/private file access')
 if event in {'os.remove','os.rmdir'}:
  if not writable(path_of(args[0])):raise PermissionError('undeclared deletion refused')
 if event in {'os.rename','os.replace'}:
  if not writable(path_of(args[0])) or not writable(path_of(args[1])):raise PermissionError('undeclared move refused')
 if event=='os.mkdir':
  p=path_of(args[0]);key=os.path.normcase(str(p))
  if not p.is_relative_to(scratch) and key not in output_parents:raise PermissionError('undeclared directory refused')
 if event in {'os.scandir','os.listdir'}:
  p=path_of(args[0])
  # Enumeration is only of the sealed workspace/runtime; source workspace and
  # private home directories are absent. No mutable live glob can be followed.
  if not (p.is_relative_to(stage) or p.is_relative_to(scratch) or any(p.is_relative_to(r) for r in runtime)):
   raise PermissionError('outside sealed-view enumeration refused')
 if event in {'os.chdir','os.chmod','os.link','os.symlink','os.truncate'}:
  raise PermissionError('report filesystem mutation refused')

runtime_assets=set()
def asset_audit(event,args):
 if event=='open' and isinstance(args[0],(str,bytes,os.PathLike)):
  p=path_of(args[0])
  if any(p.is_relative_to(r) for r in runtime) and p.suffix.lower() in {'.ttf','.otf','.afm','.mplstyle','.dll','.pyd'}:
   runtime_assets.add(str(p))

sys.addaudithook(audit)
sys.addaudithook(asset_audit)
sys.argv=[config['script'],*config['args']]
try:
 runpy.run_path(str(stage/config['script']),run_name='__main__')
finally:
 (scratch/'guard_runtime_assets.json').write_text(json.dumps({'kind':'OBSERVED_RUNTIME_ASSET_PATHS_NOT_A_WHEEL_AUDIT','paths':sorted(runtime_assets)},indent=2)+'\n',encoding='utf-8')

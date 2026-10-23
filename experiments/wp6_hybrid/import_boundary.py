"""Engineering-only normal colocated import boundary; never replaces live modules."""
from pathlib import Path
import hashlib,importlib,sys
HERE=Path(__file__).resolve().parent
PINS={'compiled_policy.py':'80267eb5db84957488d84c95bf44324563345202a8d4edc8d8c5646b72041647','persistent_policy_v3.py':'e08986f04abfaef866ff1cf676268c8f63e25c8335288b99d6416c3bbb058873','policy_adapter.py':'cfa3af7ed9446eefb8b947b889f52d2841db73e3920a18133d37c57c7071dd12','admission.lp':'149e76e157415465f925af7063c1796ce682f4228a5adff4347cb7ff08888fea'}
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def load_candidate(directory=None):
 directory=(HERE/'proposed' if directory is None else Path(directory)).resolve()
 for name,h in PINS.items():
  p=directory/name
  if p.is_symlink() or sha(p)!=h:raise RuntimeError('candidate dependency source mismatch: '+name)
 for name in ['compiled_policy','persistent_policy_v3']:
  prior=sys.modules.get(name)
  if prior is not None:
   if not getattr(prior,'__file__',None) or Path(prior.__file__).resolve()!=directory/(name+'.py'):raise RuntimeError('conflicting module alias: '+name)
 old=list(sys.path);sys.path.insert(0,str(directory))
 try:
  accepted=importlib.import_module('compiled_policy');candidate=importlib.import_module('persistent_policy_v3')
 finally:sys.path[:]=old
 for mod in [accepted,candidate]:
  p=Path(mod.__file__).resolve()
  if p.parent!=directory or sha(p)!=PINS[p.name]:raise RuntimeError('loaded module path/source mismatch')
 if candidate.accepted is not accepted or candidate.ROOT!=directory or accepted.ROOT!=directory:raise RuntimeError('candidate dependency alias mismatch')
 return candidate

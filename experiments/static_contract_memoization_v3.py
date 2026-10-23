"""DRAFT static WP6 contract-construction memo; never a publication protocol.

Every hit re-reads every audited V2 loader dependency and recomputes the native
file digest. Unknown/legacy branches and unsuccessful validations use original
loading. Contract values returned on hits are fresh copies from trusted in-memory
pickle buffers. No request decision, guard, fingerprint, or session is cached.
"""
from contextlib import contextmanager
from collections import OrderedDict
from functools import lru_cache
from pathlib import Path
import hashlib,pickle
from experiments.static_model_memoization import static_model_memoization
AUDITED_PROJECT_FIELDS=frozenset("created_ms description display_name roomcontract_case_dir roomcontract_digest_scheme roomcontract_legacy_path roomcontract_legacy_trace_map_path roomcontract_model_path roomcontract_model_schema roomcontract_model_sha256 roomcontract_model_version roomcontract_profile roomcontract_trace_map_path roomcontract_trace_path roomcontract_trace_schema_version roomcontract_v2_path generation_mode id metamodelVersion placement_algorithm_version placement_artifact_sha256 placement_origin placement_projection_sha256 placement_schema placement_schema_version source_rdl_path updated_ms".split())

@contextmanager
def static_contract_memoization_v3():
 from experiments.lib import backend_driver
 from backend import roomcontract_v2_runtime as runtime
 from tools import validate_dynamic_functional_rdl_v2 as structural
 original=runtime._load_project_contract_unchecked;simple=structural._simple
 stats={k:0 for k in ("contract_hits","contract_misses","contract_failures_not_cached","contract_bypasses","fresh_dependency_reads","fresh_digest_checks","changed_during_load")}
 cache=OrderedDict();cached_bytes=0
 @lru_cache(maxsize=8192)
 def simple_string(value):return simple(value)
 def memo_simple(value):return simple_string(value) if isinstance(value,str) else simple(value)
 def snapshot(project):
  project=Path(project).resolve()
  # This small project metadata is parsed afresh. Unsupported branches bypass.
  meta=runtime._read_json(project/"project.json")
  if set(meta)-AUDITED_PROJECT_FIELDS:return None
  if meta.get("roomcontract_model_version")!=runtime.V2_MODEL_VERSION or meta.get("metamodelVersion")!=runtime.V2_MODEL_VERSION:return None
  generation=str(meta.get("generation_mode") or "").strip().lower()
  if generation and generation!="roomcontract":return None
  def resolve(raw,default):return runtime._resolve_project_file(project,raw,default,required=False)
  native=resolve(meta.get("roomcontract_model_path") or meta.get("roomcontract_v2_path"),"roomcontract.v2.instance.json")
  paths={project/"project.json",project/"agents.json",resolve(meta.get("roomcontract_trace_map_path"),"trace_map.json"),resolve(meta.get("roomcontract_model_path"),"roomcontract.v2.instance.json"),native,resolve(meta.get("roomcontract_trace_map_path"),"trace_map.v2.json")}
  paths={p.resolve() for p in paths}
  # The scope is a closed materialized project. External references fall back.
  if any(not p.is_relative_to(project) for p in paths):return None
  records=[]
  for p in sorted(paths,key=str):
   if p.exists() and not p.is_file():return None
   raw=p.read_bytes() if p.exists() else None
   stats["fresh_dependency_reads"]+=1;records.append((str(p),raw))
  key=hashlib.sha256(pickle.dumps((str(project),records),protocol=5)).digest()
  return key,native,str(meta.get("roomcontract_digest_scheme") or "sha256-raw-v1")
 def load(project):
  nonlocal cached_bytes
  try:state=snapshot(project)
  except Exception:
   stats["contract_bypasses"]+=1;return original(project)
  if state is None:stats["contract_bypasses"]+=1;return original(project)
  key,native,scheme=state
  if key in cache:
   frozen,pin=cache[key]
   # Preserve a fresh actual digest calculation; any mismatch falls back.
   stats["fresh_digest_checks"]+=1
   try:current=runtime._sha256(native,scheme=scheme)
   except Exception:
    stats["contract_bypasses"]+=1;return original(project)
   if current==pin:
    stats["contract_hits"]+=1;cache.move_to_end(key);return pickle.loads(frozen)
  stats["contract_misses"]+=1
  try:result=original(project)
  except BaseException:
   stats["contract_failures_not_cached"]+=1;raise
  try:after=snapshot(project)
  except Exception:after=None
  if result.get("kind")=="v2" and after==state:
   frozen=pickle.dumps(result,protocol=5)
   if len(frozen)<=64*1024*1024:
    if key in cache:cached_bytes-=len(cache.pop(key)[0])
    cache[key]=(frozen,result["model_sha256"]);cached_bytes+=len(frozen)
    while len(cache)>4 or cached_bytes>64*1024*1024:
     _,removed=cache.popitem(last=False);cached_bytes-=len(removed[0])
  else:stats["changed_during_load"]+=1
  return result
 with static_model_memoization() as prior:
  runtime._load_project_contract_unchecked=load;structural._simple=memo_simple
  try:yield stats
  finally:
   runtime._load_project_contract_unchecked=original;structural._simple=simple
   stats["base_memoization"]=dict(prior);stats["simple_cache"]=simple_string.cache_info()._asdict()

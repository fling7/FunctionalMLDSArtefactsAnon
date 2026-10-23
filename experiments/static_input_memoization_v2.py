"""DRAFT engineering scope: exact immutable inputs, fresh file reads, fresh copies.

No production or independent evaluator source is edited. No request outcome is cached.
Pickle buffers are produced only from local in-memory values; no pickle file is read.
"""
from __future__ import annotations
import hashlib,json,pickle
from pathlib import Path
from collections import OrderedDict
from contextlib import contextmanager
from functools import lru_cache
from experiments.static_model_memoization import static_model_memoization

class SuccessMemo:
    def __init__(self,name,stats,limit=8,max_bytes=32*1024*1024):
        self.name=name;self.stats=stats;self.limit=limit;self.max_bytes=max_bytes;self.values=OrderedDict();self.size=0
    def call(self,args,original):
        try:encoded=pickle.dumps(args,protocol=5)
        except (TypeError,pickle.PickleError):return original()
        key=hashlib.sha256(encoded).digest()
        if key in self.values:
            self.stats[self.name+"_hits"]+=1;self.values.move_to_end(key)
            return pickle.loads(self.values[key])
        self.stats[self.name+"_misses"]+=1
        try:value=original()
        except BaseException:
            self.stats[self.name+"_failures_not_cached"]+=1;raise
        try:frozen=pickle.dumps(value,protocol=5)
        except (TypeError,pickle.PickleError):return value
        if len(frozen)<=self.max_bytes:
            self.values[key]=frozen;self.size+=len(frozen)
            while len(self.values)>self.limit or self.size>self.max_bytes:
                _,removed=self.values.popitem(last=False);self.size-=len(removed)
        return value

@contextmanager
def static_input_memoization_v2():
    from experiments.lib import backend_driver
    from backend import roomcontract_v2_runtime as runtime
    from tools import validate_dynamic_functional_rdl_v2 as structural
    originals={name:getattr(runtime,name) for name in ("_read_json","_validate_v2_instance","_build_v2_runtime_context")}
    original_simple=structural._simple
    stats={key+suffix:0 for key in ("json","instance","context") for suffix in ("_hits","_misses","_failures_not_cached")}
    caches={key:SuccessMemo(key,stats,limit=16 if key=="json" else 4) for key in ("json","instance","context")}
    @lru_cache(maxsize=8192)
    def simple_string(value):return original_simple(value)
    def simple(value):return simple_string(value) if isinstance(value,str) else original_simple(value)
    def read_json(path):
        # Always read the current bytes, even on a cache hit. Runtime digest,
        # placement, metadata and pin checks outside this function remain live.
        try:raw=Path(path).read_bytes()
        except FileNotFoundError as exc:raise runtime.RoomContractContractError(f"Required JSON file is missing: {path}") from exc
        except OSError as exc:raise runtime.RoomContractContractError(f"Invalid JSON file {path}: {exc}") from exc
        def parse():
            try:
                text=raw.decode("utf-8-sig").replace("\r\n","\n").replace("\r","\n")
                value=json.loads(text)
            except json.JSONDecodeError as exc:raise runtime.RoomContractContractError(f"Invalid JSON file {path}: {exc}") from exc
            if not isinstance(value,dict):raise runtime.RoomContractContractError(f"JSON root must be an object: {path}")
            return value
        return caches["json"].call((str(Path(path)),raw),parse)
    def instance(value):return caches["instance"].call((value,),lambda:originals["_validate_v2_instance"](value))
    def context(value,trace,digest):return caches["context"].call((value,trace,digest),lambda:originals["_build_v2_runtime_context"](value,trace,digest))
    with static_model_memoization() as prior:
        runtime._read_json=read_json;runtime._validate_v2_instance=instance;runtime._build_v2_runtime_context=context;structural._simple=simple
        try:yield stats
        finally:
            for name,original in originals.items():setattr(runtime,name,original)
            structural._simple=original_simple
            stats["base_memoization"]=dict(prior);stats["simple_cache"]=simple_string.cache_info()._asdict()

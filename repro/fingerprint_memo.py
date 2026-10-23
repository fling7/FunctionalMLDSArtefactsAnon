"""Experimental pure fingerprint memo; fresh loader/dependency reads are unchanged."""
from collections import OrderedDict
from contextlib import contextmanager
import marshal

class Uncacheable(TypeError): pass

def content_key(value):
    # A lossless, type-tagged in-process serialization, never unmarshalled.
    # Unsupported/custom objects raise without running custom reducers.
    return marshal.dumps(value,4)

def plain(value, active=None):
    if type(value) in (str,int,float,bool,type(None)): return True
    if type(value) not in (dict,list,tuple): return False
    active=set() if active is None else active
    if id(value) in active: return False
    active.add(id(value))
    try:
        values=list(value.keys())+list(value.values()) if type(value) is dict else value
        return all(plain(v,active) for v in values)
    finally: active.remove(id(value))
def projection(contract):
    return {**{k:contract.get(k) for k in ('kind','model_version','profile','model_sha256','instance_path','trace_path','trace','runtime_context')},
            'project_contract_paths':{k:(contract.get('project') or {}).get(k) for k in ('roomcontract_model_path','roomcontract_v2_path','roomcontract_trace_map_path','roomcontract_trace_path')}}

class FingerprintMemo:
    def __init__(self,original,max_entries=4,max_bytes=64*1024*1024):
        self.original=original;self.cache=OrderedDict();self.max_entries=max_entries;self.max_bytes=max_bytes;self.bytes=0
        self.stats=dict(hits=0,misses=0,bypasses=0,failures_not_cached=0)
    def __call__(self,contract):
        try:
            if type(contract) is not dict or type(contract.get('project') or {}) is not dict:raise Uncacheable('non-plain contract')
            view=projection(contract);key=content_key(view)
        except (Uncacheable,RecursionError,ValueError):
            self.stats['bypasses']+=1;return self.original(contract)
        if len(key)>self.max_bytes:
            self.stats['bypasses']+=1;return self.original(contract)
        if key in self.cache:
            self.stats['hits']+=1;self.cache.move_to_end(key);return self.cache[key]
        if not plain(view):
            self.stats['bypasses']+=1;return self.original(contract)
        self.stats['misses']+=1
        try:answer=self.original(contract)
        except BaseException:
            self.stats['failures_not_cached']+=1;raise
        self.cache[key]=answer;self.bytes+=len(key)
        while len(self.cache)>self.max_entries or self.bytes>self.max_bytes:
            old,_=self.cache.popitem(last=False);self.bytes-=len(old)
        return answer

@contextmanager
def fingerprint_memo():
    from backend import state,runtime_trace
    original=runtime_trace.contract_runtime_fingerprint
    if state.contract_runtime_fingerprint is not original:raise ValueError('unexpected fingerprint alias')
    memo=FingerprintMemo(original)
    runtime_trace.contract_runtime_fingerprint=memo;state.contract_runtime_fingerprint=memo
    try:yield memo.stats
    finally:runtime_trace.contract_runtime_fingerprint=original;state.contract_runtime_fingerprint=original


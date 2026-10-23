"""Experimental, process-local memoization for static WP6 models only.

This module is NOT imported by the frozen v1 harness or production. A scoped
context restores every original function. No routing outcome is memoized.
"""
from __future__ import annotations
from collections import OrderedDict
from contextlib import contextmanager
import hashlib
import json


@contextmanager
def static_model_memoization():
    from tools import validate_dynamic_functional_rdl_v2 as structural
    from experiments.lib import backend_driver  # Establish the public backend path.
    from backend import roomcontract_v2_runtime as runtime
    original_subtype=structural.ModelIndex.is_subclass
    original_of_type=structural.InstanceValidator._of_type
    original_trace=runtime._validate_v2_trace
    stats={'subtype_hits':0,'subtype_misses':0,'type_scan_hits':0,'type_scan_misses':0,'trace_hits':0,'trace_misses':0,'trace_failures_not_cached':0}
    trace_success=OrderedDict()

    def subtype(index,cls_or_name,base):
        if not isinstance(cls_or_name,str) or not isinstance(base,str):return original_subtype(index,cls_or_name,base)
        cache=index.__dict__.setdefault('_wp6_subtype_cache',{})
        key=(cls_or_name,base)
        if key in cache:stats['subtype_hits']+=1;return cache[key]
        stats['subtype_misses']+=1;value=original_subtype(index,cls_or_name,base);cache[key]=value;return value

    def of_type(validator,name):
        cache=validator.__dict__.setdefault('_wp6_type_cache',{})
        if name in cache:stats['type_scan_hits']+=1;return list(cache[name])
        stats['type_scan_misses']+=1;value=original_of_type(validator,name);cache[name]=tuple(value);return list(value)

    def trace(trace,by_id,model_sha256,instance):
        # All four arguments participate, including the explicit index: no
        # assumptions about index construction or serialization digest equality.
        key=hashlib.sha256(json.dumps([trace,by_id,model_sha256,instance],sort_keys=True,separators=(',',':'),ensure_ascii=False).encode('utf-8')).digest()
        if key in trace_success:
            stats['trace_hits']+=1;trace_success.move_to_end(key);return None
        stats['trace_misses']+=1
        try:result=original_trace(trace,by_id,model_sha256,instance)
        except BaseException:
            stats['trace_failures_not_cached']+=1
            raise
        if result is None:
            trace_success[key]=True
            if len(trace_success)>32:trace_success.popitem(last=False)
        return result

    structural.ModelIndex.is_subclass=subtype
    structural.InstanceValidator._of_type=of_type
    runtime._validate_v2_trace=trace
    try:yield stats
    finally:
        structural.ModelIndex.is_subclass=original_subtype
        structural.InstanceValidator._of_type=original_of_type
        runtime._validate_v2_trace=original_trace

"""Uninstrumented paired benchmark: own approved API versus persistent control reuse."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import statistics
import time

import compiled_policy as backend
import persistent_policy_v3 as persistent
import policy_adapter as original

ROOT=Path(__file__).resolve().parent


def variants(request,session,other_agent):
    values=[]
    for label in ['normal','handoff','stale','selection','schema','identity']:
        r,s=deepcopy(request),deepcopy(session)
        if label=='handoff': r['active_agent_id']=other_agent
        if label=='stale': r['spatial_context']['model_sha256']='B'*64
        if label=='selection': r['spatial_context']['state']='none'
        if label=='schema': r['user_text']=''
        if label=='identity': r['spatial_context']['entity_id']='unknown'
        values.append((label,r,s))
    return values


def main():
    protected=json.loads((ROOT/'persistent-protected-inputs.json').read_text())['protected_sha256']
    fixtures=json.loads((ROOT/'fixtures.json').read_text(encoding='utf-8-sig'))
    fixture=fixtures[0]
    instance=json.loads((ROOT/'example.instance.json').read_text(encoding='utf-8-sig'))
    trace=json.loads((ROOT/'example.trace.json').read_text(encoding='utf-8-sig'))
    full_request=deepcopy(fixture['request']); full_request['active_agent_id']='teacher_agent'
    full_request['spatial_context'].update(model_sha256=trace['model_sha256'],entity_id='ENT-ASSET-CHALKBOARD',source_object_id='chalkboard')
    models=[('small',fixture['instance'],fixture['trace'],fixture['request'],fixture['session'],'b'),
            ('full',instance,trace,full_request,{'model_sha256':trace['model_sha256']},'reading_area_guide')]
    results=[]; diagnostics={}; summary={}
    for name,instance,trace,request,session,other_agent in models:
        base=backend.compile_model(instance,trace,allow_fallback=False)
        candidate=persistent.compile_model(instance,trace,allow_fallback=False)
        requests=variants(request,session,other_agent)
        expected=[original.evaluate(instance,trace,r,s) for _,r,s in requests]
        # Untimed warmup of both implementations. No profiler or tracing is active.
        for index in range(6):
            _,r,s=requests[index]
            assert base.evaluate(r,s)==candidate.evaluate(r,s)==expected[index]
        rows=[]
        for index in range(24):
            request_index=index%len(requests); label,r,s=requests[request_index]
            implementations=[('backend',base),('persistent',candidate)]
            if index%2: implementations.reverse()
            timings={}; outputs={}
            for implementation,policy in implementations:
                started=time.perf_counter()
                outputs[implementation]=policy.evaluate(r,s)
                timings[implementation]=time.perf_counter()-started
            record={'model':name,'pair':index,'request_label':label,'request':deepcopy(r),'session':deepcopy(s),
                    'order':[impl for impl,_ in implementations],'expected_original':expected[request_index],
                    'backend':outputs['backend'],'persistent':outputs['persistent'],'seconds':timings,
                    'equal':outputs['backend']==outputs['persistent']==expected[request_index]}
            rows.append(record); results.append(record)
            if not record['equal']: raise AssertionError(json.dumps(record))
        old_times=[row['seconds']['backend'] for row in rows]; new_times=[row['seconds']['persistent'] for row in rows]
        summary[name]={'pairs':len(rows),'all_equal':all(row['equal'] for row in rows),
                       'backend_median_seconds':statistics.median(old_times),'persistent_median_seconds':statistics.median(new_times),
                       'backend_total_seconds':sum(old_times),'persistent_total_seconds':sum(new_times),
                       'backend_over_persistent_total_ratio':sum(old_times)/sum(new_times),
                       'backend_compile_seconds':base.compile_seconds,'persistent_compile_seconds':candidate.compile_seconds}
        diagnostics[name]={'backend_statistics':base.statistics,'persistent_statistics':candidate.statistics,
                           'persistent_diagnostics':candidate.diagnostics()}
        print(name,json.dumps(summary[name]),flush=True)
    unchanged={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==digest for name,digest in protected.items()}
    assert all(unchanged.values()),unchanged
    source_names=['policy_adapter.py','admission.lp','compiled_policy.py','persistent_policy_v3.py','persistent_benchmark_v3.py']
    output={'benchmark':'uninstrumented alternating-order paired wall-clock timings',
            'models':summary,'diagnostics':diagnostics,'protected_files_unchanged':unchanged,
            'source_hashes':{name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in source_names},
            'scope':'engineering experiment only; not WP8 latency evidence',
            'adoption_condition':'persistent must improve full-model request evaluation before a full equivalence campaign'}
    (ROOT/'persistent-v3-timing-results.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
    (ROOT/'persistent-v3-timing-summary.json').write_text(json.dumps(output,indent=2),encoding='utf-8')
    print('paired comparisons',len(results),'all equal',all(row['equal'] for row in results),flush=True)


if __name__=='__main__': main()

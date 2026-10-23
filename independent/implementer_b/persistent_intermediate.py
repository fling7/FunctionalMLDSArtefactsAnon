"""Fixed own-fixture intermediate-size paired measurements; no dispatch policy."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import statistics
import time
import traceback
import compiled_policy as accepted
import persistent_policy_v3 as persistent
import policy_adapter as original
from persistent_benchmark_v3 import variants

ROOT=Path(__file__).resolve().parent


def rewrite(value,mapping):
    if isinstance(value,str): return mapping.get(value,value)
    if isinstance(value,list): return [rewrite(item,mapping) for item in value]
    if isinstance(value,dict): return {key:rewrite(item,mapping) for key,item in value.items()}
    return value


def replicate(case,count):
    combined=deepcopy(case)
    identifiers={record['id'] for record in case['instance']['objects']}
    for record in case['instance']['objects']:
        for key in ('sourceAgentId','sourceId'):
            if isinstance(record.get(key),str): identifiers.add(record[key])
    for index in range(1,count):
        replica=rewrite(deepcopy(case),{value:value+'::copy'+str(index) for value in identifiers})
        combined['instance']['objects'].extend(replica['instance']['objects'])
        combined['trace']['runtime_actions'].extend(replica['trace']['runtime_actions'])
    return combined


def main():
    fixture=json.loads((ROOT/'fixtures.json').read_text(encoding='utf-8-sig'))[0]
    models={str(count):replicate(fixture,count) for count in (4,12)}
    (ROOT/'persistent-intermediate-models.json').write_text(json.dumps(models,ensure_ascii=True,indent=2),encoding='utf-8')
    records=[]; summaries={}
    for size,case in models.items():
        base=accepted.compile_model(case['instance'],case['trace'],allow_fallback=False)
        new=persistent.compile_model(case['instance'],case['trace'],allow_fallback=False)
        requests=variants(case['request'],case['session'],'b')
        expected=[original.evaluate(case['instance'],case['trace'],r,s) for _,r,s in requests]
        for index,(_,request,session) in enumerate(requests):
            assert base.evaluate(request,session)==new.evaluate(request,session)==expected[index]
        rows=[]
        for index in range(12):
            which=index%len(requests); label,request,session=requests[which]
            order=[('accepted',base),('persistent',new)]
            if index%2: order.reverse()
            outputs={}; times={}
            for name,policy in order:
                started=time.perf_counter(); outputs[name]=policy.evaluate(request,session); times[name]=time.perf_counter()-started
            row={'fixture_copies':int(size),'pair':index,'request_label':label,'request':request,'session':session,
                 'expected_original':expected[which],'outputs':outputs,'seconds':times,'order':[name for name,_ in order],
                 'equal':outputs['accepted']==outputs['persistent']==expected[which]}
            records.append(row); rows.append(row)
            with (ROOT/'persistent-intermediate-progress.jsonl').open('a',encoding='utf-8') as stream:
                stream.write(json.dumps(row,ensure_ascii=True)+'\n')
            assert row['equal']
        old_times=[row['seconds']['accepted'] for row in rows]; new_times=[row['seconds']['persistent'] for row in rows]
        summaries[size]={'object_count':len(case['instance']['objects']),'trace_rows':len(case['trace']['runtime_actions']),
                         'static_input_fact_count':new.statistics['static_input_fact_count'],'boundary_fact_count':new.statistics['boundary_fact_count'],
                         'pairs':len(rows),'all_equal':all(row['equal'] for row in rows),
                         'accepted_total_seconds':sum(old_times),'persistent_total_seconds':sum(new_times),
                         'accepted_median_seconds':statistics.median(old_times),'persistent_median_seconds':statistics.median(new_times),
                         'accepted_over_persistent_total_ratio':sum(old_times)/sum(new_times),
                         'accepted_compile_seconds':base.compile_seconds,'persistent_compile_seconds':new.compile_seconds,
                         'persistent_diagnostics':new.diagnostics()}
        print(size,json.dumps(summaries[size]),flush=True)
    output={'scope':'Fixed own-fixture sizes, engineering only; no dispatch threshold selected or implemented.',
            'sizes_selected_before_timing':[4,12],'summaries':summaries,'records':records,
            'source_sha256':{name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in ('persistent_intermediate.py','persistent_policy_v3.py','compiled_policy.py','policy_adapter.py','admission.lp')}}
    (ROOT/'persistent-intermediate-results.json').write_text(json.dumps(output,ensure_ascii=True,indent=2),encoding='utf-8')


if __name__=='__main__':
    try: main()
    except BaseException:
        (ROOT/'persistent-intermediate-failure.txt').write_text(traceback.format_exc(),encoding='utf-8')
        raise
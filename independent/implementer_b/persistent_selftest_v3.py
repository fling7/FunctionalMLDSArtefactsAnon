"""Performance-only equivalence tests against Implementer-B's unchanged adapter."""
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
import hashlib
import io
import json
from pathlib import Path
import random
import statistics
import time
import unittest

import persistent_policy_v3 as compiled
import policy_adapter as original
import persistent_handwritten as handwritten

ROOT=Path(__file__).resolve().parent
SEED=20261015


def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True)


class Recorder:
    def __init__(self):
        self.models={}; self.compiled={}; self.results=[]; self.label='unspecified'

    def evaluator(self,instance,trace,request,session):
        key=hashlib.sha256(canonical([instance,trace]).encode()).hexdigest()
        if key not in self.compiled:
            self.models[key]={'instance':deepcopy(instance),'trace':deepcopy(trace)}
            with (ROOT/'persistent-v3-model-inputs.jsonl').open('a',encoding='utf-8') as stream:
                stream.write(json.dumps({'model_key':key,**self.models[key]},ensure_ascii=True)+'\n')
            self.compiled[key]=compiled.compile_model(instance,trace,allow_fallback=False)
        cached=self.compiled[key]
        before=deepcopy((instance,trace,request,session))
        started=time.perf_counter(); old=original.evaluate(instance,trace,request,session); old_time=time.perf_counter()-started
        started=time.perf_counter(); new=cached.evaluate(request,session); new_time=time.perf_counter()-started
        record={'label':self.label,'model_key':key,'request':deepcopy(request),'session':deepcopy(session),
                'original':old,'compiled':new,'equal':old==new,'original_seconds':old_time,'compiled_seconds':new_time}
        self.results.append(record)
        with (ROOT/'persistent-v3-progress.jsonl').open('a',encoding='utf-8') as stream:
            stream.write(json.dumps({'completed':len(self.results),'process_cpu_seconds':time.process_time(),'record':record},ensure_ascii=True)+'\n')
        if old!=new: raise AssertionError(canonical(record))
        if (instance,trace,request,session)!=before: raise AssertionError('Input mutated')
        return old


class TrackingResult(unittest.TestResult):
    def __init__(self,recorder):
        super().__init__(); self.recorder=recorder
    def startTest(self,test):
        self.recorder.label='handwritten/'+test.id()
        super().startTest(test)


def random_request(rng,base,session,agent_ids,entity_ids,source_ids):
    request=deepcopy(base); session=deepcopy(session)
    for _ in range(rng.randint(1,4)):
        choice=rng.randrange(14)
        spatial=request.get('spatial_context')
        if not isinstance(spatial,dict): spatial={}; request['spatial_context']=spatial
        if choice==0: spatial['state']=rng.choice(['resolved','none','ambiguous',None,7])
        elif choice==1: spatial['entity_id']=rng.choice(entity_ids+['missing',None,[],{}])
        elif choice==2: spatial['source_object_id']=rng.choice(source_ids+['missing',None,[],{}])
        elif choice==3: spatial['source_id']=rng.choice(source_ids+['missing',None])
        elif choice==4: spatial['candidate_entity_ids']=rng.choice([[],entity_ids[:1],entity_ids[:2],[entity_ids[0]]*2,'invalid',None,[7]])
        elif choice==5: spatial['ambiguity']=rng.choice([True,False,{}, {'reason':'description'}, {'ambiguous':1},{'is_ambiguous':'yes'},'wrong'])
        elif choice==6: spatial['ambiguous']=rng.choice([True,False,None,'wrong'])
        elif choice==7: request['active_agent_id']=rng.choice(agent_ids+['missing',None,7])
        elif choice==8: request['user_text']=rng.choice(['Explain this.','',None,17,'x'*300])
        elif choice==9: request['interaction_mode']=rng.choice(['deictic','non_deictic','unknown',None])
        elif choice==10: spatial['model_sha256']=rng.choice([session.get('model_sha256',''),str(session.get('model_sha256','')).lower(),'B'*64,'x',None])
        elif choice==11: session.update(active_agent_mode=rng.choice(['client','server_strict']),active_agent_id=rng.choice(agent_ids+['missing',None]))
        elif choice==12:
            for key in rng.sample(['entity_id','source_object_id','model_sha256','state'],rng.randint(1,3)): spatial.pop(key,None)
        else:
            spatial['hit_position']=rng.choice([None,{}, {'x':0,'y':0,'z':0},{'x':1e8,'y':0,'z':0}])
    return request,session


def main():
    start=time.perf_counter(); before_hashes=compiled.source_hashes(); recorder=Recorder()
    handwritten.evaluate=recorder.evaluator
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(handwritten.AdmissionTests)
    result=TrackingResult(recorder); suite.run(result)
    if not result.wasSuccessful():
        raise AssertionError(str(result.failures)+str(result.errors))
    print('handwritten methods',result.testsRun,'comparisons',len(recorder.results),flush=True)

    fixtures=json.loads((ROOT/'fixtures.json').read_text(encoding='utf-8-sig'))
    rng=random.Random(SEED)
    for index in range(384):
        case=fixtures[index%len(fixtures)]
        request,session=random_request(rng,case['request'],case['session'],['a','b'],['T'],['object'])
        recorder.label=f'generated-small/{index}'
        recorder.evaluator(case['instance'],case['trace'],request,session)
    print('generated small complete',len(recorder.results),flush=True)

    instance=json.loads((ROOT/'example.instance.json').read_text(encoding='utf-8-sig'))
    trace=json.loads((ROOT/'example.trace.json').read_text(encoding='utf-8-sig'))
    agents=[o['sourceAgentId'] for o in instance['objects'] if o['type']=='Agent']
    targets=[o for o in instance['objects'] if o.get('entityRole')=='sceneObject']
    base=deepcopy(fixtures[0]['request']); base['spatial_context']['model_sha256']=trace['model_sha256']
    session={'model_sha256':trace['model_sha256']}
    for agent in agents:
        for target in targets:
            request=deepcopy(base); request['active_agent_id']=agent
            request['spatial_context'].update(entity_id=target['id'],source_object_id=target['sourceId'])
            recorder.label=f'example-agent-target/{agent}/{target["id"]}'
            recorder.evaluator(instance,trace,request,session)
    print('example all agent-target pairs complete',len(recorder.results),flush=True)

    base['active_agent_id']=agents[0]
    base['spatial_context'].update(entity_id=targets[0]['id'],source_object_id=targets[0]['sourceId'])
    for index in range(64):
        request,request_session=random_request(rng,base,session,agents,
                         [t['id'] for t in targets],[t['sourceId'] for t in targets])
        recorder.label=f'generated-example/{index}'
        recorder.evaluator(instance,trace,request,request_session)
    print('generated example complete',len(recorder.results),flush=True)

    # Revisit cached models and alternate early/late failures with admitted turns.
    pool=deepcopy([r for r in recorder.results if r['label'].startswith('example-agent-target/')][:8])
    pool+=deepcopy([r for r in recorder.results if r['label'].startswith('generated-example/')][:8])
    for index in range(32):
        row=pool[(index*7)%len(pool)]; model=recorder.models[row['model_key']]
        recorder.label=f'alternating-example/{index}'
        recorder.evaluator(model['instance'],model['trace'],row['request'],row['session'])
    small_pool=deepcopy([r for r in recorder.results if r['label'].startswith('generated-small/')][:24])
    for index in range(96):
        row=small_pool[(index*7)%len(small_pool)]; model=recorder.models[row['model_key']]
        recorder.label=f'alternating-small/{index}'
        recorder.evaluator(model['instance'],model['trace'],row['request'],row['session'])
    print('alternating request streams complete',len(recorder.results),flush=True)

    # Direct batch, snapshot isolation, concurrency, and guarded fallback checks.
    fixture=fixtures[0]; c=compiled.compile_model(fixture['instance'],fixture['trace'],allow_fallback=False)
    requests=[(deepcopy(fixture['request']),deepcopy(fixture['session'])) for _ in range(8)]
    requests[1][0]['spatial_context']['state']='none'
    requests[2][0]['active_agent_id']='b'
    requests[3][0]['spatial_context']['entity_id']='missing'
    requests[5][0]['spatial_context']['model_sha256']='B'*64
    expected=[original.evaluate(fixture['instance'],fixture['trace'],r,s) for r,s in requests]
    assert c.evaluate_many(requests)==expected
    assert compiled.evaluate_many(fixture['instance'],fixture['trace'],requests)==expected
    with ThreadPoolExecutor(max_workers=4) as executor:
        assert list(executor.map(lambda pair:c.evaluate(*pair),requests))==expected
    altered_instance=deepcopy(fixture['instance']); altered_trace=deepcopy(fixture['trace'])
    snapshot=compiled.compile_model(altered_instance,altered_trace,allow_fallback=False)
    altered_instance['objects'].clear(); altered_trace['runtime_actions'].clear()
    assert snapshot.evaluate(fixture['request'],fixture['session'])==fixture['expected']
    verdict=snapshot.evaluate(fixture['request'],fixture['session']); verdict['reason']='modified by caller'
    assert snapshot.evaluate(fixture['request'],fixture['session'])==fixture['expected']

    partition=compiled.accepted._partition('''p :- not field("request","x","y").
        q :- #count{X:field("request","x",X)} > 0.
        r :- p. r :- obj(0,"X","Agent").''')
    assert {('p',0),('q',0),('r',0)} <= partition.dynamic
    for unsupported in ['#external changed.', '1 { choice(1);choice(2) } 1.', ':- forbidden.']:
        try: compiled.accepted._partition(unsupported)
        except compiled.UnsupportedPartition: pass
        else: raise AssertionError('Unsupported partition accepted: '+unsupported)
    saved=compiled.accepted.EXPECTED_REFERENCE_HASHES
    try:
        compiled.accepted.EXPECTED_REFERENCE_HASHES={name:'0'*64 for name in saved}
        fallback=compiled.compile_model(fixture['instance'],fixture['trace'])
        assert fallback.mode=='reference_fallback'
        assert fallback.evaluate(fixture['request'],fixture['session'])==fixture['expected']
        try: compiled.compile_model(fixture['instance'],fixture['trace'],allow_fallback=False)
        except compiled.UnsupportedPartition: pass
        else: raise AssertionError('Strict compiler accepted a source-hash mismatch')
    finally:
        compiled.accepted.EXPECTED_REFERENCE_HASHES=saved
    assert compiled.source_hashes()==before_hashes==compiled.accepted.EXPECTED_REFERENCE_HASHES

    categories={}
    for name in sorted({r['label'].split('/')[0] for r in recorder.results}):
        rows=[r for r in recorder.results if r['label'].split('/')[0]==name]
        old=[r['original_seconds'] for r in rows]; new=[r['compiled_seconds'] for r in rows]
        categories[name]={'comparisons':len(rows),'original_total_seconds':sum(old),'compiled_total_seconds':sum(new),
                         'original_median_seconds':statistics.median(old),'compiled_median_seconds':statistics.median(new),
                         'total_speedup':sum(old)/sum(new)}
    summary={'seed':SEED,'handwritten_test_methods':result.testsRun,'exact_output_comparisons':len(recorder.results),
             'all_equal':all(r['equal'] for r in recorder.results),'compiled_model_count':len(recorder.compiled),
             'unexpected_fallback_count':sum(c.mode!='compiled' for c in recorder.compiled.values()),
             'reference_hashes_before':before_hashes,'reference_hashes_after':compiled.source_hashes(),
             'new_source_hashes':{name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
                                  for name in ['persistent_policy_v3.py','persistent_selftest_v3.py','persistent_handwritten.py','compiled_policy.py']},
             'compilation_total_seconds':sum(c.compile_seconds for c in recorder.compiled.values()),
             'categories':categories,'elapsed_seconds':time.perf_counter()-start,
             'extra_checks':['batch API','immutable input snapshot','fresh returned verdict','serialized concurrent callers',
                             'negation dependency','aggregate dependency','same-predicate closure','unsupported partition rejection',
                             'source hash fallback','strict source hash failure','unchanged original byte hashes'],
             'compiled_models':{key:{'compile_seconds':c.compile_seconds,'statistics':c.statistics,'persistent_diagnostics':c.diagnostics()}
                                for key,c in recorder.compiled.items()}}
    (ROOT/'persistent-v3-models.json').write_text(json.dumps(recorder.models,ensure_ascii=True),encoding='utf-8')
    (ROOT/'persistent-v3-equivalence.json').write_text(json.dumps(recorder.results,indent=2,ensure_ascii=True),encoding='utf-8')
    (ROOT/'persistent-v3-summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in summary.items() if k!='compiled_models'},indent=2),flush=True)


if __name__=='__main__':
    import traceback
    try: main()
    except BaseException:
        (ROOT/'persistent-v3-campaign-failure.txt').write_text(traceback.format_exc(),encoding='utf-8')
        raise

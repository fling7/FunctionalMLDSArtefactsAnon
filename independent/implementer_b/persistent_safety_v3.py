"""Bounded own-fixture isolation and failure tests for the persistent API."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import traceback
import clingo
import persistent_policy_v3 as candidate
import policy_adapter as original

ROOT=Path(__file__).resolve().parent
ROWS=[]
CHECKS=[]
EXPECTED_FAILURES=[]


def verdict(policy, case, request, session, label):
    before=deepcopy((request,session))
    expected=original.evaluate(case['instance'],case['trace'],request,session)
    actual=policy.evaluate(request,session)
    row={'label':label,'instance':case['instance'],'trace':case['trace'],'request':deepcopy(request),'session':deepcopy(session),'original':expected,'persistent':actual,'equal':expected==actual}
    ROWS.append(row)
    assert row['equal'],row
    assert (request,session)==before
    return actual


def expect_error(label, function, kind):
    try:
        function()
    except kind as error:
        EXPECTED_FAILURES.append({'label':label,'type':type(error).__name__,'message':str(error)})
    else:
        raise AssertionError('Expected exception: '+label)


def main():
    fixtures=json.loads((ROOT/'fixtures.json').read_text(encoding='utf-8-sig'))
    base=deepcopy(fixtures[0])
    for index,case in enumerate(fixtures):
        policy=candidate.compile_model(case['instance'],case['trace'],allow_fallback=False,max_queries_per_control=2)
        for repeat in range(3): verdict(policy,case,case['request'],case['session'],f'fixture/{index}/{repeat}')
        assert policy.diagnostics()['control_rebuilds']==2
    CHECKS.append('All eight handwritten fixtures repeated across bounded rebuilds')
    requests=[]
    for mode in ['normal','stale','selection','unknown','schema','handoff','strict','candidate','request-null','request-array','session-null','literal']:
        request,session=deepcopy(base['request']),deepcopy(base['session'])
        if mode=='stale': request['spatial_context']['model_sha256']='B'*64
        elif mode=='selection': request['spatial_context']['state']='none'
        elif mode=='unknown': request['spatial_context']['entity_id']='unknown'
        elif mode=='schema': request['user_text']=''
        elif mode=='handoff': request['active_agent_id']='b'
        elif mode=='strict': session.update(active_agent_mode='server_strict',active_agent_id='b')
        elif mode=='candidate': request['spatial_context']['candidate_entity_ids']=['T','T']
        elif mode=='request-null': request=None
        elif mode=='request-array': request=[]
        elif mode=='session-null': session=None
        elif mode=='literal': request['user_text']='quote" backslash\\ line\n tab\t CR\r Unicode ÃŽÂ© Ã°Å¸Â¦â€“'
        requests.append((mode,request,session))
    policy=candidate.compile_model(base['instance'],base['trace'],allow_fallback=False,max_queries_per_control=3)
    for turn,(mode,request,session) in enumerate(requests+list(reversed(requests))+requests):
        verdict(policy,base,request,session,f'order/{turn}/{mode}')
        with policy._control.solve(yield_=True) as handle:
            answers=[list(model.symbols(shown=True)) for model in handle]
        assert answers==[[]],answers
    assert policy.diagnostics()['control_rebuilds']==12
    CHECKS.append('Forward/reverse/repeated requests, malformed data and literals; post-release solves empty; twelve bounded control epochs')
    for document in [False,{'type':'nonsense'},{'$ref':'https://unavailable.invalid/schema'}]:
        case=deepcopy(base)
        next(item for item in case['instance']['objects'] if item['id']=='IS')['text']=json.dumps(document)
        invalid=candidate.compile_model(case['instance'],case['trace'],allow_fallback=False)
        for repeat in range(2): verdict(invalid,case,case['request'],case['session'],'schema-model/'+str(document))
    CHECKS.append('Boolean-false, invalid and unavailable-external-reference schemas')
    other=deepcopy(base)
    next(item for item in other['instance']['objects'] if item['id']=='A')['groundedAsset']=[]
    pair=[(base,candidate.compile_model(base['instance'],base['trace'],allow_fallback=False)),
          (other,candidate.compile_model(other['instance'],other['trace'],allow_fallback=False))]
    for index in range(12):
        case,model=pair[index%2]
        verdict(model,case,case['request'],case['session'],'cross-model/'+str(index))
    before=deepcopy(base)
    snapshot=candidate.compile_model(before['instance'],before['trace'],allow_fallback=False)
    before['instance']['objects'].clear(); before['trace']['runtime_actions'].clear()
    result=verdict(snapshot,base,base['request'],base['session'],'snapshot')
    result['decision']='caller mutation'
    verdict(snapshot,base,base['request'],base['session'],'fresh-output')
    CHECKS.append('Distinct interleaved models, caller model/trace mutation, fresh returned mapping')
    concurrent=candidate.compile_model(base['instance'],base['trace'],allow_fallback=False,max_queries_per_control=5)
    tasks=[requests[index%len(requests)] for index in range(32)]
    expected=[original.evaluate(base['instance'],base['trace'],request,session) for _,request,session in tasks]
    with ThreadPoolExecutor(max_workers=4) as executor:
        actual=list(executor.map(lambda row:concurrent.evaluate(row[1],row[2]),tasks))
    for index,((mode,request,session),old,new) in enumerate(zip(tasks,expected,actual)):
        ROWS.append({'label':'concurrency/'+str(index)+'/'+mode,'instance':base['instance'],'trace':base['trace'],'request':request,'session':session,'original':old,'persistent':new,'equal':old==new})
    assert actual==expected
    CHECKS.append('32 concurrent calls serialized on one object across seven epochs')
    failed=candidate.compile_model(base['instance'],base['trace'],allow_fallback=False)
    solve=failed._solve_query
    def fail_solve(control, query): raise RuntimeError('injected active-query solve failure')
    failed._solve_query=fail_solve
    expect_error('active query failure',lambda:failed.evaluate(base['request'],base['session']),RuntimeError)
    assert failed._control is None
    failed._solve_query=solve
    verdict(failed,base,base['request'],base['session'],'recovery-after-active-failure')
    facts=failed._fresh_query_facts
    failed._fresh_query_facts=lambda request,session:') malformed ASP ('
    expect_error('partial add failure',lambda:failed.evaluate(base['request'],base['session']),RuntimeError)
    assert failed._control is None
    failed._fresh_query_facts=facts
    verdict(failed,base,base['request'],base['session'],'recovery-after-add-failure')
    CHECKS.append('Active-query solve failure and parser failure discard control; later requests recover identically')
    for source in ['{ x }.', ':- x.', '#external x.', '#show x/0.']:
        expect_error('unsupported/'+source,lambda source=source:candidate._query_program(source,{('x',0)}),candidate.UnsupportedPartition)
    saved=candidate.EXPECTED_COMPILED_SHA256
    try:
        candidate.EXPECTED_COMPILED_SHA256='0'*64
        fallback=candidate.compile_model(base['instance'],base['trace'])
        assert fallback.mode=='reference_fallback'
        verdict(fallback,base,base['request'],base['session'],'source-pin-fallback')
        expect_error('source-pin-strict',lambda:candidate.compile_model(base['instance'],base['trace'],allow_fallback=False),candidate.UnsupportedPartition)
    finally: candidate.EXPECTED_COMPILED_SHA256=saved
    CHECKS.append('Unsupported syntax refused; source-pin mismatch fallback and strict error')
    # The inherited static parser limitation is preserved, not repaired.
    control_case=deepcopy(base)
    control_case['instance']['objects'][0]['id'] += '\rcontrol'
    expect_error('inherited CR static literal constructor failure',lambda:candidate.compile_model(control_case['instance'],control_case['trace'],allow_fallback=False),RuntimeError)
    CHECKS.append('Inherited CR static-literal constructor failure retained')


if __name__=='__main__':
    error=None
    try: main()
    except BaseException:
        error=traceback.format_exc()
    protected=json.loads((ROOT/'persistent-protected-inputs.json').read_text())['protected_sha256']
    unchanged={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==value for name,value in protected.items()}
    output={'status':'failed' if error else 'passed','error':error,'comparison_count':len(ROWS),'all_equal':all(row['equal'] for row in ROWS),
            'checks':CHECKS,'expected_failures':EXPECTED_FAILURES,'records':ROWS,'protected_files_unchanged':unchanged,
            'source_sha256':{name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in ['persistent_policy_v3.py','persistent_safety_v3.py','compiled_policy.py','policy_adapter.py','admission.lp']}}
    (ROOT/'persistent-v3-safety.json').write_text(json.dumps(output,ensure_ascii=True,indent=2),encoding='utf-8')
    print(json.dumps({key:value for key,value in output.items() if key not in ('records','protected_files_unchanged')},ensure_ascii=True),flush=True)
    if error or not all(unchanged.values()): raise SystemExit(1)
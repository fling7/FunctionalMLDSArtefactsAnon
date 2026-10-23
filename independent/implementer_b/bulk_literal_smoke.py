"""Bounded literal/snapshot smoke checks; not the unrun full equivalence suite."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import compiled_policy as backend
import compiled_policy_bulk as bulk
import policy_adapter as original

ROOT=Path(__file__).resolve().parent


def rewrite(value,mapping):
    if isinstance(value,str): return mapping.get(value,value)
    if isinstance(value,list): return [rewrite(item,mapping) for item in value]
    if isinstance(value,dict): return {key:rewrite(item,mapping) for key,item in value.items()}
    return value


def main():
    fixture=json.loads((ROOT/'fixtures.json').read_text(encoding='utf-8-sig'))[0]
    identifiers=['A','B','T','G','Z','S','U','C','RB','RA','L','IS','a','b','object']
    payloads=['quote"backslash\\','line\nbreak\ttab\rcarriage','Greek Ω / 中文 / 🦖',
              'x").\nverdict("FORGED",null,null,null).\n%', 'brackets[]{};,:#@!<>', '']
    records=[]
    for index,payload in enumerate(payloads):
        case=rewrite(deepcopy(fixture),{identifier:identifier+'::'+payload for identifier in identifiers})
        candidate=bulk.compile_model(case['instance'],case['trace'],allow_fallback=False)
        base=backend.compile_model(case['instance'],case['trace'],allow_fallback=False)
        for turn in range(3):
            request=deepcopy(case['request'])
            if turn==1: request['spatial_context']['state']='none'
            old=original.evaluate(case['instance'],case['trace'],request,case['session'])
            previous=base.evaluate(request,case['session'])
            new=candidate.evaluate(request,case['session'])
            records.append({'payload_index':index,'payload':payload,'turn':turn,'instance':case['instance'],
                            'trace':case['trace'],'request':request,'session':case['session'],
                            'original':old,'backend':previous,'bulk':new,'equal':old==previous==new})
    protected=json.loads((ROOT/'bulk-protected-inputs.json').read_text())['protected_sha256']
    unchanged={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==digest for name,digest in protected.items()}
    output={'comparisons':len(records),'all_equal':all(row['equal'] for row in records),
            'protected_files_unchanged':unchanged,'scope':'literal escaping and alternating resolved/none/resolved smoke checks only',
            'records':records}
    (ROOT/'bulk-literal-results.json').write_text(json.dumps(output,ensure_ascii=True,indent=2),encoding='utf-8')
    print(json.dumps({key:value for key,value in output.items() if key!='records'}),flush=True)
    assert output['all_equal'] and all(unchanged.values())


if __name__=='__main__': main()

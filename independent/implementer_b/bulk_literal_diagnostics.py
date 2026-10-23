"""Record literal failures without repairing or modifying an existing evaluator."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import clingo
import compiled_policy as backend
import compiled_policy_bulk as bulk
import policy_adapter as original
from bulk_literal_smoke import rewrite

ROOT=Path(__file__).resolve().parent


def attempt(function):
    try: return {'status':'returned','value':function()}
    except Exception as error: return {'status':'error','type':type(error).__name__,'message':str(error)}


def main():
    # Preserve a byte-exact stderr reproduction of the first failed smoke script.
    failed=subprocess.run([sys.executable,'-u','bulk_literal_smoke.py'],cwd=ROOT,text=True,capture_output=True)
    (ROOT/'bulk-literal-attempt1.txt').write_text(failed.stdout+failed.stderr,encoding='utf-8')
    fixture=json.loads((ROOT/'fixtures.json').read_text(encoding='utf-8-sig'))[0]
    identifiers=['A','B','T','G','Z','S','U','C','RB','RA','L','IS','a','b','object']
    payloads=['quote"backslash\\','line\nbreak\ttab\rcarriage','Greek Ω / 中文 / 🦖',
              'x").\nverdict("FORGED",null,null,null).\n%', 'brackets[]{};,:#@!<>', '']
    records=[]; compilation=[]
    for index,payload in enumerate(payloads):
        case=rewrite(deepcopy(fixture),{identifier:identifier+'::'+payload for identifier in identifiers})
        policies={}; compilation_outcomes={}
        for name,module in [('backend',backend),('bulk',bulk)]:
            try:
                policies[name]=module.compile_model(case['instance'],case['trace'],allow_fallback=False)
                compilation_outcomes[name]={'status':'compiled'}
            except Exception as error:
                compilation_outcomes[name]={'status':'error','type':type(error).__name__,'message':str(error)}
        facts=original.load_facts(case['instance'],case['trace'],case['request'],case['session'])
        bad_lines=[]
        for number,line in enumerate(facts.splitlines(),1):
            parsed=attempt(lambda line=line:clingo.parse_term(line[:-1]))
            if parsed['status']=='error': bad_lines.append({'line_number':number,'line':line,'error':parsed})
        compilation.append({'payload_index':index,'payload':payload,'outcomes':compilation_outcomes,
                            'fact_splitlines_count':len(facts.splitlines()),'fact_lf_split_count':len(facts.split('\n')),
                            'first_bad_fact_lines':bad_lines[:3]})
        for turn in range(3):
            request=deepcopy(case['request'])
            if turn==1: request['spatial_context']['state']='none'
            outcomes={'original':attempt(lambda:original.evaluate(case['instance'],case['trace'],request,case['session']))}
            for name in ['backend','bulk']:
                outcomes[name]=(attempt(lambda name=name:policies[name].evaluate(request,case['session']))
                                if name in policies else compilation_outcomes[name])
            returned=all(outcome['status']=='returned' for outcome in outcomes.values())
            equal=returned and outcomes['original']['value']==outcomes['backend']['value']==outcomes['bulk']['value']
            records.append({'payload_index':index,'payload':payload,'turn':turn,'instance':case['instance'],
                            'trace':case['trace'],'request':request,'session':case['session'],
                            'outcomes':outcomes,'all_returned_equal_verdicts':equal})
    protected=json.loads((ROOT/'bulk-protected-inputs.json').read_text())['protected_sha256']
    unchanged={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==digest for name,digest in protected.items()}
    output={'first_smoke_exit_code':failed.returncode,'first_smoke_source_sha256':hashlib.sha256((ROOT/'bulk_literal_smoke.py').read_bytes()).hexdigest(),
            'request_cases':len(records),'all_returned_equal_verdict_cases':sum(r['all_returned_equal_verdicts'] for r in records),
            'compilation':compilation,'protected_files_unchanged':unchanged,'records':records,
            'scope':'diagnostic probes only; no original/approved source repair and no full827 campaign'}
    (ROOT/'bulk-literal-diagnostics.json').write_text(json.dumps(output,ensure_ascii=True,indent=2),encoding='utf-8')
    print(json.dumps({'request_cases':len(records),'all_returned_equal_verdict_cases':output['all_returned_equal_verdict_cases'],
                      'compile_outcomes':[(r['payload_index'],r['outcomes']) for r in compilation],
                      'protected_unchanged':all(unchanged.values())},ensure_ascii=True),flush=True)


if __name__=='__main__': main()

"""Differential admission testing; implementations retain independent provenance."""
from __future__ import annotations
import argparse,copy,hashlib,importlib.util,json,sys
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from experiments.lib.backend_driver import Driver,VARIANTS

def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);sys.modules[name]=module;spec.loader.exec_module(module);return module
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--project',type=Path);ap.add_argument('--extended-only',action='store_true');ap.add_argument('--run-id',default=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'));args=ap.parse_args()
    out=ROOT/'results/raw/differential'/args.run_id
    out.mkdir(parents=True,exist_ok=False)
    a=load('independent_reference',ROOT/'verification/impl_a/reference.py')
    b=load('independent_policy',ROOT/'verification/impl_b/policy_adapter.py')
    driver=Driver(args.project)
    variants=VARIANTS+('forged_active','source_alias_conflict','empty_candidates','ambiguity_reason_only','active_and_digest')
    if args.extended_only:variants=('user_text_number','user_text_empty','extra_top_field','forged_model_binding')
    summary={'unit':'room','rooms':1,'probes':0,'disagreement_probes':0,'decision_disagreement_probes':0,'reason_only_disagreement_probes':0,'variants':{},'implementation_hashes':{}}
    for key,path in [('I1','verification/impl_a/reference.py'),('I2','verification/impl_b/policy_adapter.py'),('ASP','verification/impl_b/admission.lp')]:
        summary['implementation_hashes'][key]=hashlib.sha256((ROOT/path).read_bytes()).hexdigest()
    disagreements=[]
    try:
        with (out/'probes.jsonl').open('w',encoding='utf-8') as stream:
            for agent in driver.setup['agents']:
                for target in driver.targets:
                    for variant in variants:
                        request=driver.request(agent['id'],target,variant)
                        if variant=='forged_active':request['active_agent_id']='unknown'
                        if variant=='source_alias_conflict':request['spatial_context']['source_id']=next(t['sourceId'] for t in driver.targets if t['id']!=target['id'])
                        if variant=='empty_candidates':request['spatial_context']['candidate_entity_ids']=[]
                        if variant=='ambiguity_reason_only':request['spatial_context']['ambiguity']={'reason':'selection uncertain'}
                        if variant=='active_and_digest':request['active_agent_id']='unknown';request['spatial_context']['model_sha256']='0'*64
                        if variant=='user_text_number':request['user_text']=42
                        if variant=='user_text_empty':request['user_text']=''
                        if variant=='extra_top_field':request['unmodeled_parameter']='value'
                        if variant=='forged_model_binding':request['model_binding']={'runtime_action_id':'invented'}
                        session={'model_sha256':driver.setup['model_sha256'],'active_agent_mode':'client'}
                        actual=driver.probe(request)
                        verdicts={'I0':{k:actual[k] for k in ('decision','reason','provider','action')}}
                        for name,module in [('I1',a),('I2',b)]:
                            try:verdicts[name]=module.evaluate(driver.contract['instance'],driver.contract['trace'],request,session)
                            except Exception as e:verdicts[name]={'decision':'HARNESS_ERROR','reason':type(e).__name__,'provider':None,'action':None}
                        keys=('decision','reason','provider','action')
                        canonical={name:tuple(v.get(k) for k in keys) for name,v in verdicts.items()}
                        agrees=len(set(canonical.values()))==1
                        decisions=len({(v.get('decision'),v.get('provider'),v.get('action')) for v in verdicts.values()})==1
                        row={'id':f"{driver.project.name}/{agent['id']}/{target['id']}/{variant}",'room':driver.project.name,'model_sha256':driver.setup['model_sha256'],'variant':variant,'request':request,'session':session,'verdicts':verdicts,'agrees':agrees,'decision_agrees':decisions,'backend_model_calls':actual['model_calls'],'backend_rejection_unchanged':actual['unchanged_before_restore']}
                        stream.write(json.dumps(row,ensure_ascii=False)+'\n')
                        summary['probes']+=1
                        vc=summary['variants'].setdefault(variant,{'probes':0,'disagreements':0,'decision_disagreements':0})
                        vc['probes']+=1
                        if not agrees:
                            summary['disagreement_probes']+=1;vc['disagreements']+=1
                            if not decisions:summary['decision_disagreement_probes']+=1;vc['decision_disagreements']+=1
                            else:summary['reason_only_disagreement_probes']+=1
                            disagreements.append({'probe':row['id'],'model':row['model_sha256'],'implementations':verdicts,'variant':variant,'classification':'pending adjudication','fix_commit':None,'spec_amended':False,'raw_file':(out/'probes.jsonl').relative_to(ROOT).as_posix()})
        (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
        (out/'disagreements.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in disagreements))
        with (ROOT/'results/disagreements.jsonl').open('a',encoding='utf-8') as f:
            for row in disagreements:f.write(json.dumps(row)+'\n')
        print(json.dumps(summary))
    finally:driver.close()
if __name__=='__main__':main()

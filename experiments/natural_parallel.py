"""Orchestration-only resume of unchanged frozen natural_faults.analyze_run.

Completed room files are verified and reused byte-for-byte. Only missing room
identities are scheduled. No model calls or scientific evaluator modifications.
"""
from __future__ import annotations
import argparse
from concurrent.futures import ProcessPoolExecutor,as_completed
import hashlib,json,multiprocessing
from pathlib import Path
from experiments import natural_faults as nf
from experiments.pipeline_runs import ROOT,load_frozen_plan,digest,write_once
EXCLUDED_VOLATILE={'generated_at','timestamp','elapsed_seconds','duration_ms'}
def read(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def semantic(value):
    if isinstance(value,dict):return {k:semantic(v) for k,v in value.items() if k not in EXCLUDED_VOLATILE}
    if isinstance(value,list):return [semantic(v) for v in value]
    return value
def hash_value(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
def volatile(value,path=''):
    rows=[]
    if isinstance(value,dict):
        for key,item in value.items():
            if key in EXCLUDED_VOLATILE:rows.append({'path':path+'/'+key,'value':item})
            else:rows.extend(volatile(item,path+'/'+key))
    elif isinstance(value,list):
        for i,item in enumerate(value):rows.extend(volatile(item,path+'/'+str(i)))
    return rows

def summarize(rows):
    metrics={}
    for model in sorted({r['source']['model'] for r in rows}):
        subset=[r for r in rows if r['source']['model']==model and r['project_produced'] and 'rates' in r]
        metrics[model]={sample:{str(h):nf.clustered_interval(subset,lambda r:r['rates'][sample][str(h)]) for h in (1,2,3)} for sample in ('all_pairs','nearest_agent')}
        metrics[model]['object_fault_rates']={}
        for fault in ('unowned','ambiguous_deciding_level','without_declared_action'):
            interval=nf.clustered_interval(subset,lambda r:r['object_faults'][fault]/r['object_faults']['objects'] if r['object_faults']['objects'] else None)
            denominator=sum(r['object_faults']['objects'] for r in subset)
            interval['pooled_numerator']=sum(r['object_faults'][fault] for r in subset);interval['pooled_denominator']=denominator
            interval['pooled_rate']=interval['pooled_numerator']/denominator if denominator else None
            metrics[model]['object_fault_rates'][fault]=interval
    return {'unit':'source room; model runs nested; probes secondary','phase':'evaluation','rooms':len(rows),
        'projects':sum(r['project_produced'] for r in rows),'source_cluster_intervals':metrics,
        'analysis_sha256':nf.sha(nf.__file__),'runtime_included':True,'status':'PARTIAL',
        'limits':'No native before-repair model is invented. LLM judges and regeneration drift are not funded. Hop2/3 are static graph metrics, not runtime policy changes.'}

def verify_inputs():
    load_frozen_plan();terminal=read(ROOT/'results/raw/wp5/evaluation_terminal_v1.json')
    if not terminal.get('terminal') or terminal['completed_runs']!=50 or terminal['artifact_hash_mismatches']:raise RuntimeError('Original inputs lack terminal integrity evidence')
    for row in terminal['row_records']:
        path=ROOT/row['run_result_path']
        if digest(path)!=row['run_result_sha256']:raise RuntimeError('Original terminal record changed')
        for rel,expected in read(path)['artifact_sha256'].items():
            if digest(ROOT/rel)!=expected:raise RuntimeError('Retained original artifact changed: '+rel)
    return terminal

def equivalence(case_id,output,*,compare_retained_repeat=False):
    output=Path(output).resolve()
    terminal=verify_inputs();row=next(r for r in terminal['row_records'] if r['case_id']==case_id)
    retained=ROOT/'results/raw/wp5/natural_evaluation_v1/rooms'/(case_id+'.json')
    if not retained.exists():raise RuntimeError('Choose an already-completed native room')
    before=read(retained)
    repeat_path=output/(case_id+'.repeat.json')
    if compare_retained_repeat:
        if not repeat_path.exists():raise RuntimeError('Retained equivalence repeat is absent')
        repeat=read(repeat_path)
    else:
        if repeat_path.exists():raise RuntimeError('Repeat already retained; compare its bytes rather than rerunning')
        repeat=nf.analyze_run(ROOT/row['run_result_path'],include_runtime=True)
        write_once(repeat_path,repeat)
    evidence={'schema':'natural-parallel-equivalence-v1','case_id':case_id,
        'retained_path':retained.relative_to(ROOT).as_posix(),'retained_sha256':digest(retained),
        'repeat_path':(output/(case_id+'.repeat.json')).relative_to(ROOT).as_posix(),'repeat_sha256':digest(output/(case_id+'.repeat.json')),
        'exact_json_equal':before==repeat,'semantic_equal':semantic(before)==semantic(repeat),
        'semantic_sha256_original':hash_value(semantic(before)),'semantic_sha256_repeat':hash_value(semantic(repeat)),
        'excluded_volatile_keys':sorted(EXCLUDED_VOLATILE),'original_volatile':volatile(before),'repeat_volatile':volatile(repeat),
        'analysis_sha256':digest(Path(nf.__file__)),'wrapper_sha256':digest(Path(__file__)),
        'original_terminal_sha256':digest(ROOT/'results/raw/wp5/evaluation_terminal_v1.json'),
        'source_and_artifact_hashes_verified':True,'same_frozen_function':True,'compared_retained_repeat_without_rerun':compare_retained_repeat}
    write_once(output/'evidence.json',evidence)
    if not evidence['semantic_equal']:raise RuntimeError('Frozen-function equivalence failed; preserve both outputs')
    print(json.dumps(evidence));return evidence

def worker(path,analysis_sha):
    if digest(Path(nf.__file__))!=analysis_sha:raise RuntimeError('Frozen analysis changed')
    result=nf.analyze_run(Path(path),include_runtime=True)
    if digest(Path(nf.__file__))!=analysis_sha:raise RuntimeError('Frozen analysis changed during evaluation')
    return result

def run(execution_plan,output):
    output=Path(output).resolve()
    execution_plan=Path(execution_plan);side=execution_plan.with_suffix('.sha256')
    if not side.exists() or side.read_text(encoding='ascii').strip().split()[0]!=digest(execution_plan):raise RuntimeError('Orchestration plan is not frozen')
    plan=read(execution_plan)
    if plan.get('status')!='FROZEN' or plan['workers']!=2 or plan['analysis_sha256']!=digest(Path(nf.__file__)) or plan['wrapper_sha256']!=digest(Path(__file__)):raise RuntimeError('Orchestration source or worker count changed')
    eq=ROOT/plan['equivalence_path']
    if digest(eq)!=plan['equivalence_sha256'] or not read(eq)['semantic_equal']:raise RuntimeError('Equivalence evidence changed')
    if digest(ROOT/'results/raw/wp5/evaluation_terminal_v1.json')!=plan['original_terminal_sha256']:raise RuntimeError('Pinned original terminal manifest changed')
    terminal=verify_inputs();ordered=sorted(terminal['row_records'],key=lambda r:r['case_id'])
    missing=[];reused={}
    for row in ordered:
        dest=output/'rooms'/(row['case_id']+'.json')
        if dest.exists():
            old=read(dest)
            if old['room']!=row['case_id'] or old['source']!=read(ROOT/row['run_result_path'])['source']:raise RuntimeError('Completed natural row identity mismatch')
            reused[dest.relative_to(ROOT).as_posix()]=digest(dest)
        else:missing.append(row)
    if reused!=plan['completed_room_sha256']:raise RuntimeError('Completed room files differ from frozen serial cutoff')
    write_once(output/'execution_002_start.json',{'execution_plan_sha256':digest(execution_plan),'reused_completed_files':reused,
        'scheduled_case_ids':[r['case_id'] for r in missing],'terminal_order':[r['case_id'] for r in ordered],
        'original_process_interruption_reason':plan['interruption_reason'],'workers':2,'no_completed_identity_rescheduled':True})
    context=multiprocessing.get_context('spawn')
    with ProcessPoolExecutor(max_workers=2,mp_context=context) as pool:
        futures={pool.submit(worker,str(ROOT/r['run_result_path']),plan['analysis_sha256']):r for r in missing}
        for future in as_completed(futures):
            row=futures[future];result=future.result();write_once(output/'rooms'/(row['case_id']+'.json'),result)
            print(json.dumps({'room':row['case_id'],'project_produced':result['project_produced'],'pairs':result.get('pair_counts',{})}),flush=True)
    for rel,expected in reused.items():
        if digest(ROOT/rel)!=expected:raise RuntimeError('Previously completed natural row was modified')
    verify_inputs();rows=[read(output/'rooms'/(r['case_id']+'.json')) for r in ordered]
    write_once(output/'summary.json',summarize(rows))
    result={'schema':'wp5-natural-terminal-v1','terminal':True,'execution_plan_sha256':digest(execution_plan),
        'rooms':len(rows),'source_rooms':len({r['source']['scene_id'] for r in rows}),
        'native_model_runs':sum('pair_counts' in r for r in rows),'native_source_rooms':len({r['source']['scene_id'] for r in rows if 'pair_counts' in r}),
        'pairs':sum(r.get('pair_counts',{}).get('all',0) for r in rows),'disagreements':sum(r.get('pair_counts',{}).get('disagreements',0) for r in rows),
        'room_sha256':{(output/'rooms'/(r['room']+'.json')).relative_to(ROOT).as_posix():digest(output/'rooms'/(r['room']+'.json')) for r in rows},
        'summary_sha256':digest(output/'summary.json'),'reused_completed_files':reused,
        'analysis_sha256':plan['analysis_sha256'],'wrapper_sha256':plan['wrapper_sha256']}
    write_once(output/'terminal.json',result);print(json.dumps({k:v for k,v in result.items() if k not in ('room_sha256','reused_completed_files')}));return result

def main():
    p=argparse.ArgumentParser();p.add_argument('--check-equivalence');p.add_argument('--compare-retained-repeat',action='store_true');p.add_argument('--execution-plan',type=Path)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if a.check_equivalence:equivalence(a.check_equivalence,a.output,compare_retained_repeat=a.compare_retained_repeat)
    elif a.execution_plan:run(a.execution_plan,a.output)
    else:p.error('Choose equivalence or frozen execution plan')
if __name__=='__main__':main()

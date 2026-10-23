"""Aggregate property campaigns by unique native model, preserving incomplete/failing shards."""
from pathlib import Path
from collections import Counter
import json,csv
ROOT=Path(__file__).resolve().parents[1]
def main(shard_paths=None):
    base=ROOT/'results/raw/properties';models=set();cases=set();counts=Counter();shards=[]
    for folder in (sorted(base.glob('model-properties-v2-shard*')) if shard_paths is None else [Path(p) for p in shard_paths]):
        rows=[]
        raw=folder/'models.jsonl'
        if raw.exists():
            for line in raw.read_text(encoding='utf-8').splitlines():
                try:rows.append(json.loads(line))
                except json.JSONDecodeError:counts['partial_lines_while_running']+=1
        summary=json.loads((folder/'summary.json').read_text(encoding='utf-8')) if (folder/'summary.json').exists() else {}
        counts['completed_observation_rows']+=len(rows)
        for r in rows:
            if r.get('model_sha256'):models.add(r['model_sha256'])
            cases.add(r['case_hash']);counts['status_'+r['status']]+=1
            for request in r.get('requests',[]):
                counts['requests_'+request['result']['decision']]+=1
            if r.get('commit_properties'):counts['g4_http_success_and_drift_pairs']+=1
        shards.append({'directory':folder.relative_to(ROOT).as_posix(),'status':summary.get('status','IN_PROGRESS'),'observations':len(rows),'unique_models':len({r.get('model_sha256') for r in rows if r.get('model_sha256')})})
    complete=bool(shards) and all(r['status']=='pass' for r in shards)
    result={'unit':'unique native model; requests/configurations are secondary','status':'PASS' if complete and len(models)>=5000 else 'FAIL' if any(r['status']=='fail' for r in shards) else 'INCOMPLETE',
       'unique_models':len(models),'unique_configurations':len(cases),'minimum_unique_models':5000,'shards':shards,'counts':dict(counts),
       'excluded_engineering_runs':['model-properties-v1','pilot-initial','v2-pilot-20','v2-stratified-pilot'],
       'scope':'Native G1/G2/G3/G5 assertions and actual HTTP G4 success/drift rollback; no reference implementation supplies expected properties; scripted model only.'}
    out=ROOT/'results/processed';out.mkdir(parents=True,exist_ok=True)
    (out/'properties_summary.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    lines=['# Native property campaign','',f"Status: {result['status']}. Unique native models: {len(models)}. Unique configurations: {len(cases)}.",'',
    'These are Hypothesis configurations, not a uniform probability sample or real-model observations. Incomplete and failed shards cannot satisfy the minimum. Setup refusals are counted separately, not treated as exercised admission guarantees.',
    '',f"Actual HTTP unchanged-commit/drift-rollback pairs observed: {counts['g4_http_success_and_drift_pairs']}.",
    '', 'The first-match reconstruction is separate: results/raw/properties/firstmatch-counterexample-v1/counterexample.json. Hypothesis shrank the ownership list to two owners. The structural validator accepts that model, first-match admits it, and the native G2 assertion detects the violation; packet, I1 and I2 reject ambiguity.',
    '', 'Engineering changes and all retained pilot observations are documented in docs/DEVIATIONS.md. Known original-request schema differences are reported by the differential suite and are not covered up by this generator.']
    (ROOT/'docs/PROPERTY_RESULTS.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    with (ROOT/'paper_inputs/tables/T9_property_shards.csv').open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=['directory','status','observations','unique_models']);w.writeheader();w.writerows(shards)
    print(json.dumps({k:result[k] for k in ('status','unique_models','unique_configurations')}))
if __name__=='__main__':main()

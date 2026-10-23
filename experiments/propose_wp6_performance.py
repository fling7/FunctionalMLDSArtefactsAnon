"""Prepare the draft WP6 performance amendment from engineering evidence."""
from pathlib import Path
import json,hashlib
ROOT=Path(__file__).resolve().parents[1]

def read(path):return json.loads((ROOT/path).read_text(encoding='utf-8-sig'))
def main():
 resources=read('results/raw/wp6_unit/resources.json');profile=read('results/raw/wp6_unit/structural_profile.json');backend=read('results/raw/wp6_unit/backend_profile.json');memo=read('results/raw/wp6_unit/memoized_classroom_throughput.json');original=read('results/raw/wp6_unit/classroom_throughput_probe.json');wp5=read('results/processed/wp5_projects.json');manifest=read('results/raw/wp6_example_v1/mutation_manifest.json')
 logical=resources['hardware']['NumberOfLogicalProcessors'];workers=min(8,max(1,logical-8-4));eligible=[r for r in wp5['rows'] if r['eligible_native_success']]
 rows=[]
 for r in eligible:
  project=ROOT/r['project_path'];model=json.loads((project/'roomcontract.v2.instance.json').read_text());agents=sum(o.get('type')=='Agent' for o in model['objects']);objects=sum(o.get('entityRole')=='sceneObject' for o in model['objects']);size=sum(p.stat().st_size for p in project.rglob('*') if p.is_file() and '__pycache__' not in str(p) and not p.name.endswith('.log') and not p.name.startswith('runtime'))
  rows.append({'case':r['case_id'],'agents':agents,'objects':objects,'pairs':agents*objects,'source_bytes':size,'source_model_sha256':r['model_sha256']})
 planned=sum(m['status'] in {'changed','incomplete'} for m in manifest['models']);pair_s=original['I1']['elapsed_s']+original['I2']['elapsed_s']+sum(v['elapsed_s'] for v in memo['variants'].values())+memo['variants']['no_digest']['elapsed_s']
 for r in rows:r['planning_estimate_serial_hours']=(memo['validators_elapsed_s']+r['pairs']*pair_s)*planned/3600;r['planning_estimate_parallel_hours']=r['planning_estimate_serial_hours']/workers;r['estimated_copy_bytes']=r['source_bytes']*planned
 stats={'condition':'draft resource estimate; extrapolation from engineering probes, not measured generated-run throughput','logical_cpus':logical,'memory_bytes':resources['hardware']['TotalPhysicalMemory'],'free_disk_bytes':resources['disk']['FreeSpace'],'proposed_generated_workers':workers,'classroom_planned_models':planned,'engineering_pair_seconds_proxy':pair_s,'eligible_sources_now':rows}
 out=ROOT/'prereg/wp6_amendments';out.mkdir(parents=True,exist_ok=True)
 (out/'001_performance_only.DRAFT.json').write_text(json.dumps(stats,indent=2,sort_keys=True)+'\n',encoding='utf-8')
 text=f'''# Draft WP6 performance-only amendment

Status: DRAFT; not permission to launch generated-model evaluation. The existing classroom v1 run remains unchanged. This draft is generated from engineering profiles by `experiments/propose_wp6_performance.py` and will be frozen only after equivalence evidence and root review.

## Scope and unchanged semantics

Preserve every operator, target rule, seed, model, validator, independent evaluator call, request, variant, refusal and aggregation formula in the original registered WP6 harness. The new launcher calls the original `evaluate_one` inside an experimental process-local context; the original source hashes remain enforced. No production file changes. No routing outcome is cached. B0/B1, natural evolution and semantic judges remain separate evidence classes.

The context memoizes three pure operations: string-based metamodel subtype lookup within one immutable ModelIndex; type-filter scans within one immutable InstanceValidator (return a fresh list retaining original order); and successful `_validate_v2_trace` results keyed by the complete trace, explicit by_id index, digest and native instance arguments. Failure results are never cached. The trace-success cache is scoped to one model worker, capped at 32 entries, and restored on exceptions. Canonical reports are not reused across distinct checker APIs: all checks still execute, with repeated pure suboperations memoized.

The loader still reads current files and verifies their content digests on every call. Request schema and routing checks execute on every probe, as do real SessionStore state changes and snapshot restoration. This acceleration is confined to static WP6 admission testing. It provides no publication, race, commit, deployment or performance claim. It is forbidden for WP7 concurrency/commit and WP8 timing evidence.

## Engineering evidence

The structural profile attributes repeated work to `_of_type` and subtype/ancestor traversal. On the small engineering fixture, profiled structural elapsed time was {profile['original']['elapsed_profiled_s']:.4f} s originally and {profile['memoized']['elapsed_profiled_s']:.4f} s with memoization; profiler overhead prevents interpreting these as production latency estimates. Full memoized validators on one materialized classroom configuration took {memo['validators_elapsed_s']:.4f} s. Backend profiles identify repeated loader trace validation as a major cost. These are single engineering configurations, not independent repeated trials.

Raw evidence: `results/raw/wp6_unit/structural_profile.json`, `backend_profile.json`, `memoized_classroom_throughput.json`, `resources.json`, and the equivalence test records. The original engineering profile on the unmaterialized example used a serialization hash that differed from the original on-disk digest; those stale rejections are retained and excluded from backend timing comparison. The materialized profiles use Driver.request's pinned digest.

## Required equivalence before freeze

Compare complete checker reports on the baseline and every synthetic operator, ignoring only wall-clock report timestamps and measured elapsed time. Compare every decision, reason, provider, action, call count and pre-restore-state flag for every pair and routing/stale variant on representative ownership/action/refusal fixtures. Test changed trace, native instance, by_id and digest arguments; invalid-to-valid and valid-to-invalid transitions; repeated failures never caching; actual changed trace/native files being reread; and restoration of original functions after an exception. Preserve any failures and fix causes without weakening semantic expectations.

A comparator defect was found before deployment: tuple-contained report timing fields were not normalized. The failure and correction are retained in `results/raw/wp6_unit/memo_comparator_failure.json`. No evaluation outcome was changed in response.

## Resource and execution plan

Measured host resources: {logical} logical CPUs, {resources['hardware']['TotalPhysicalMemory']/1e9:.2f} GB RAM and {resources['disk']['FreeSpace']/1e9:.2f} GB free disk. Proposed generated pool: {workers} processes, leaving capacity for the existing classroom workers, property workers and other tasks. Each worker processes one model and all its pairs; no within-model sampling or probe dropping. Worker count may be lowered for resource pressure without changing model eligibility or outcomes.

The current verified generated inventory contains {len(rows)} eligible source projects. The following are planning extrapolations using measured engineering per-pair costs and the classroom planned model count, not observed generated-run times. Larger models may be slower. Failed generation attempts remain in WP5 and are not silently replaced.

| Source | Agents | Objects | Pairs per model | Estimated copied GB | Planning hours at proposed workers |
| --- | ---: | ---: | ---: | ---: | ---: |
'''
 for r in rows:text+=f"| {r['case']} | {r['agents']} | {r['objects']} | {r['pairs']} | {r['estimated_copy_bytes']/1e9:.3f} | {r['planning_estimate_parallel_hours']:.2f} |\n"
 text+='''
Use fresh versioned generated run directories and save dependency hashes, the amendment hash, per-model memoization counters, full mutation manifests and all outcomes. Retain the unaccelerated classroom run as its own condition. Memoized-run elapsed values are not pooled into latency evidence. Every eligible generated project is processed in manifest priority order as available; consistent cross-model counterparts are not natural evolution pairs. Exclusion and eligibility rules are unchanged.

Before launch the final amendment and exact helper/launcher/test hashes must be committed by root. The accelerated launcher refuses execution without that frozen hash lock. A semantic mismatch halts deployment of acceleration and preserves both outcomes; it is never resolved by majority vote or by dropping the failing fixture.
'''
 (out/'001_performance_only.DRAFT.md').write_text(text,encoding='utf-8')
 print(json.dumps(stats))
if __name__=='__main__':main()

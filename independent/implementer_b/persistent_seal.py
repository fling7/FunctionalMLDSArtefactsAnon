"""Seal the persistent-Control experiment and compact root-review bindings."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import policy_adapter as original

ROOT=Path(__file__).resolve().parent


def read(name): return json.loads((ROOT/name).read_text(encoding='utf-8-sig'))
def digest(name): return hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
def write(name,value): (ROOT/name).write_text(json.dumps(value,ensure_ascii=True,indent=2)+'\n',encoding='utf-8')
def binding(name): return {'path':name,'sha256':digest(name)}


def main():
    protected=read('persistent-protected-inputs.json')['protected_sha256']
    unchanged={name:digest(name)==value for name,value in protected.items()}
    assert all(unchanged.values()),unchanged
    campaign=read('persistent-v3-summary.json')
    safety=read('persistent-v3-safety.json')
    intermediate=read('persistent-intermediate-results.json')
    timing={version:read(name) for version,name in [('v1','persistent-timing-summary.json'),('v2','persistent-v2-timing-summary.json'),('v3','persistent-v3-timing-summary.json')]}
    assert campaign['exact_output_comparisons']==827 and campaign['compiled_model_count']==71 and campaign['all_equal']
    assert safety['comparison_count']==115 and safety['status']=='passed' and safety['all_equal']
    fixture=read('fixtures.json')[0]
    crcase=deepcopy(fixture)
    crcase['instance']['objects'][0]['id'] += '\rcontrol'
    write('persistent-failure-inputs.json',{
        'base_fixture':fixture,
        'static_cr_case':crcase,
        'static_cr_original_verdict':original.evaluate(crcase['instance'],crcase['trace'],crcase['request'],crcase['session']),
        'static_cr_candidate_result':next(x for x in safety['expected_failures'] if x['label']=='inherited CR static literal constructor failure'),
        'solve_failure_injection':'Replace _solve_query with a function raising RuntimeError while the current external is true; discard control, restore method, evaluate the base request.',
        'add_failure_input':') malformed ASP (',
        'source_pin_failure':'Temporarily set the candidate EXPECTED_COMPILED_SHA256 in process to 64 zeroes; no file mutation.',
        'all_expected_failures':safety['expected_failures'],
    })
    models=list(campaign['compiled_models'].values())
    controls=sum(value['persistent_diagnostics']['control_rebuilds'] for value in models)
    epochs=[{'boundary_fact_count':value['statistics']['boundary_fact_count'],'diagnostics':value['persistent_diagnostics']} for value in models if value['persistent_diagnostics']['control_rebuilds']>1]
    main_pins={name:digest(name) for name in ('persistent_policy_v3.py','compiled_policy.py','policy_adapter.py','admission.lp','persistent_selftest_v3.py','persistent_safety_v3.py')}
    bench_rows=[]
    for version,data in timing.items():
        for model,measure in data['models'].items():
            bench_rows.append(f"| {version} | {model} | {measure['backend_total_seconds']:.6f} | {measure['persistent_total_seconds']:.6f} | {measure['backend_over_persistent_total_ratio']:.3f} | {measure['backend_compile_seconds']:.6f} | {measure['persistent_compile_seconds']:.6f} |")
    size_rows=[]
    for size,measure in intermediate['summaries'].items():
        size_rows.append(f"| {size} | {measure['object_count']} | {measure['boundary_fact_count']} | {measure['accepted_total_seconds']:.6f} | {measure['persistent_total_seconds']:.6f} | {measure['accepted_over_persistent_total_ratio']:.3f} | {measure['accepted_compile_seconds']:.6f} | {measure['persistent_compile_seconds']:.6f} |")
    category_rows=[]
    for label,measure in campaign['categories'].items():
        category_rows.append(f"| {label} | {measure['comparisons']} | {measure['original_total_seconds']:.6f} | {measure['compiled_total_seconds']:.6f} | {measure['total_speedup']:.3f} |")
    report='''# Persistent clingo Control: experimental review result

The final separate candidate passes the authorized own-fixture equivalence and isolation checks. It is **not adopted or deployed**. It improves the measured large example but regresses on the small and both intermediate fixtures. No automatic dispatch or threshold is implemented. All observations are engineering evidence, not WP8 latency evidence, and no root corpus or other implementation was used.

## Final candidate and preservation

Use `persistent_policy_v3.py` only as the final experimental candidate. `persistent_policy.py` and `persistent_policy_v2.py` preserve earlier versions. The candidate retains the exact accepted compiler, original adapter, and ASP as dependencies. All 45 files protected at the start of this experiment remain byte-identical, including the original accepted 827 evidence and the sealed bulk non-adoption experiment. The compact `persistent-review-manifest.json` binds the review inputs; `persistent-manifest.json` pins all protected and new artifacts.

Candidate SHA-256: `'''+main_pins['persistent_policy_v3.py']+'''`.
Accepted compiler SHA-256: `'''+main_pins['compiled_policy.py']+'''`.
Original adapter SHA-256: `'''+main_pins['policy_adapter.py']+'''`.
Original ASP SHA-256: `'''+main_pins['admission.lp']+'''`.

## Design and isolation evidence

The API and its calling constraints are documented in `PERSISTENT_API.md`. A private immutable model snapshot is compiled with the accepted conservative dependency partition. Static boundary facts are inserted once per control epoch. Dynamic predicates receive a unique query-id argument through a syntax-aware AST transformation, including negation and aggregate conditions. Every dynamic fact/rule is guarded by a query-specific external. The current query alone is activated; the emitted verdict must carry its id. Release and cleanup run in a finally block. Any failure after solver mutation discards the control. An RLock serializes calls on each object. Controls rebuild after 64 calls by default, with no decision cache.

The first feasibility probe compared 24 toy ASP queries to fresh controls, including aggregate/negation and an empty-output solve after every release. Both v1 and final v3 bounded safety suites passed 115 exact comparisons. Final v3 safety covers all eight supplied fixtures, forward/reverse/repeated streams across bounded epochs, malformed request/session values, schema failures, request literal escaping, separate model instances, snapshot mutation, fresh returned mappings, concurrent calls, activation/parser error recovery, unsupported syntax refusal, source-pin fallback and strict errors. Exact safety inputs/outputs and failures are retained. V2 has paired timing evidence only; its prepared safety script was not run.

The final authorized campaign passed **827 exact original-verdict comparisons across 71 snapshots**, all 83 handwritten test methods, and additional batch/concurrency/snapshot/dependency/fallback checks. It had zero unexpected fallback objects and zero query failures. It used '''+str(controls)+''' control builds across those snapshots, including four epochs each on the repeatedly queried small and large models. Thus the long campaign exercised scheduled rebuilds and kept their cost in request evaluation timing. Exact requests, sessions, model snapshots, verdicts, progress, process CPU counters and source pins are retained in the persistent-v3 campaign artifacts. No original test cases were dropped or changed; the new handwritten copy changes only its CLI output filename.

## Paired timing against the accepted compiled API

These rows compare the previously accepted fresh-control compiled API to the persistent candidate, not to the original adapter. Every version used 24 alternating-order timing pairs per model plus six untimed warmups; all 144 pairs across the three prototypes matched the original oracle. No profiler or tracing was enabled. Ratios above 1 favor persistent. Compilation is separate. Short runs had 30 calls and did not trigger the default 64-call scheduled rebuild.

| Version | Own model | Accepted request total, s | Persistent request total, s | Accepted / persistent | Accepted compile, s | Persistent compile, s |
|---|---|---:|---:|---:|---:|---:|
'''+ '\n'.join(bench_rows)+'''

The final large-example paired ratio is approximately 2.536, while final small-model request time is about 3.05 times the accepted compiler's time. Final large medians are 0.321117 s accepted versus 0.108761 s persistent; small medians are 0.019733 versus 0.089297 s. Higher initial compilation cost must be amortized. These are observations from paired runs on a contended host, not general latency claims.

V1 uses the general AST rule/signature walk for fresh facts. V2 directly updates the single fact head. V3 uses clingo.parse_term for trusted LF-delimited ground facts and constructs a namespaced clingo.Symbol, retaining full AST verification for policy rules. Earlier sources/results remain intact; the diffs and final transformed rule program are saved.

## Fixed intermediate sizes

Four and twelve independent native copies of the supplied small fixture were chosen before timing. IDs, wire IDs and references were renamed consistently for each copy. Exact generated model inputs are retained. Neither size was selected using a route outcome or root corpus. Each row has twelve alternating timing pairs; all 24 pairs matched the original oracle.

| Fixture copies | Objects | Static boundary facts | Accepted request total, s | Persistent request total, s | Accepted / persistent | Accepted compile, s | Persistent compile, s |
|---|---:|---:|---:|---:|---:|---:|---:|
'''+ '\n'.join(size_rows)+'''

Both intermediate sizes regress. These two topology-specific samples do not establish a defensible static-size dispatch threshold. No threshold is chosen or implemented.

## Full campaign timing against the original adapter

The next table has a different comparator: unchanged `policy_adapter.evaluate`, with no model compilation reuse. Do not interpret these ratios as improvements over the accepted compiled API. Original and persistent evaluations were paired in the original harness order. Initial compilation of 71 candidate snapshots took '''+f"{campaign['compilation_total_seconds']:.6f}"+''' seconds separately; campaign elapsed time was '''+f"{campaign['elapsed_seconds']:.6f}"+''' seconds. Later control rebuild costs are included in evaluation totals.

| Category | Exact comparisons | Original adapter total, s | Persistent total, s | Original / persistent |
|---|---:|---:|---:|---:|
'''+ '\n'.join(category_rows)+'''

## Failures and limitations

All deliberate failures are preserved in the v1/v3 safety JSON and console logs: active-query solve failure, parser-add failure, unsupported syntax, strict source-pin failure, and the inherited static CR literal constructor failure. Failed-query tests verify that subsequent calls recover with a new control and match the original. There were no unexpected output mismatches or campaign failures.

The accepted immutable fact loader still uses splitlines; a CR inside a quoted static identifier causes construction RuntimeError before evaluation. This inherited limitation was not repaired. The original adapter returns an admission verdict on the retained static-CR input. Default allow_fallback catches UnsupportedPartition, not this RuntimeError. V3 preserves CR in fresh request literals by LF-only term splitting; this does not alter the inherited static loader.

The API serializes callers rather than adding same-object throughput. Retained request groundings are bounded by a query count, not a byte budget. Its supported tested import arrangement is ordinary module imports with exact sibling source files; arbitrary module-name collisions/importlib arrangements were not audited. This experiment does not establish production-scale memory behavior, a deployment threshold, or a universal performance improvement. Source files and evidence are fixed pending separate root review. All owned jobs are terminal.
'''
    (ROOT/'persistent-investigation.md').write_text(report,encoding='utf-8')
    worklog='''# Persistent experiment access and execution log

All project reads/writes and every shell workdir stayed inside independent/implementer_b. The explicitly permitted project Python interpreter was invoked; only installed standard/dependency APIs were used outside this directory. No network, credentials, Git, shared source edits, backend source, other implementation, harness outcome from another implementation, root scientific result, or root/generated corpus was accessed.

Substantive inputs: own compiled_policy.py, policy_adapter.py, admission.lp, COMPILED_API.md, optimization_selftest.py, selftest.py, fixtures.json, example.instance.json, example.trace.json, instance.schema.json, and own bulk_benchmark.py as a local benchmark-source template. Existing own artifacts were byte-read for preservation hashing. New persistent source/evidence files were read as required for testing and reporting. The full protected hash-read list is in persistent-protected-inputs.json; final accesses/artifacts are enumerated by persistent-manifest.json. No parent project directory was read.

Sequence:
1. Read own accepted compiler, ASP and API guide; proposed query namespaces, activation guards, bounded controls, and strict unsupported-syntax handling to root.
2. Ran persistent_feasibility.py: 24 toy queries including negation/count and empty solves after release, exit 0. Kept exact transformed rules/results.
3. Recorded 45 protected source/evidence file hashes. Created v1 persistent_policy.py without changing originals. One supplied-small smoke evaluate returned the original local-answer verdict. Ran bounded paired small/full benchmark (exit 0) and v1 safety (115 comparisons, exit 0). Deliberate errors were recorded. Performance was weak, especially small inputs.
4. Kept v1 files intact; created v2 with direct AST fact-head updates. Ran only its paired benchmark, exit 0; all 48 pairs equal but small regression remained. Its safety script was prepared, not run. Reported all findings before proceeding.
5. Kept v2 intact; created final v3 with clingo ground-term parsing for LF-delimited fact input. Ran paired benchmark, exit 0, then final 115-comparison safety suite, exit 0. Retained the small-model slowdown and static-CR constructor limitation. Root authorized the full own campaign based on promising large-model measurements only.
6. Copied own original harness to persistent_selftest_v3.py and its handwritten module to persistent_handwritten.py with separate artifact paths and append-only exact records/CPU progress. Kept every original request, seed and fixture. Ran 827 exact original comparisons across 71 models; 83 methods and extra checks passed, exit 0. Sources remained fixed throughout. No integration or root corpus testing occurred.
7. After the campaign terminated, ran persistent_intermediate.py at fixed four/twelve copies of the supplied small fixture, exit 0. All 24 pairs matched; both sizes were slower. No dispatch threshold was chosen or implemented.
8. Saved source diffs and final transformed rule program. Sealed API guide, report, exact failure input record, compact review bindings and comprehensive manifest. Checked all 45 protected hashes unchanged. All jobs terminal.

Current candidate SHA and all prior prototype/test/data/report hashes are in the final manifests. Python imports may create routine __pycache__ files, which are excluded from artifact preservation accounting. No existing source or evidence file was rewritten. These results are engineering observations only, not WP8 evidence.
'''
    (ROOT/'persistent-worklog.md').write_text(worklog,encoding='utf-8')
    review={
        'status':'experimental_review_only_not_adopted',
        'scope':'Isolated own fixtures only; engineering observations, not WP8; no integration or automatic dispatch.',
        'source':binding('persistent_policy_v3.py'),
        'original_and_accepted_sources':{name:binding(name) for name in ('policy_adapter.py','admission.lp','compiled_policy.py')},
        'all_protected_files_unchanged':all(unchanged.values()),'protected_file_count':len(protected),
        'campaign':{'comparisons':827,'model_snapshots':71,'handwritten_methods':83,'all_equal':True,'unexpected_fallbacks':0,
                    'comparator':'unchanged original policy_adapter.evaluate; NOT accepted compiled API',
                    'initial_snapshot_compilation_seconds':campaign['compilation_total_seconds'],'elapsed_seconds':campaign['elapsed_seconds'],
                    'control_builds':controls,'models_crossing_rebuild_boundary':epochs,
                    'artifacts':[binding(name) for name in ('persistent_selftest_v3.py','persistent_handwritten.py','persistent-v3-summary.json','persistent-v3-equivalence.json','persistent-v3-models.json','persistent-v3-progress.jsonl','persistent-v3-model-inputs.jsonl','persistent-v3-campaign-console.txt')]},
        'safety':{'comparisons':115,'status':'passed','expected_failure_count':len(safety['expected_failures']),
                  'artifacts':[binding(name) for name in ('persistent_safety_v3.py','persistent-v3-safety.json','persistent-v3-safety-console.txt','persistent-failure-inputs.json')]},
        'paired_benchmarks':{'comparator':'accepted compiled_policy.py fresh-control API; original adapter is the untimed verdict oracle',
                             'v3_request_and_initial_compile_timings':timing['v3']['models'],
                             'per_version_pairs':48,'all_pairs_equal':True,
                             'scheduled_rebuild_in_short_benchmarks':False,
                             'artifacts':[binding(name) for name in ('persistent_benchmark.py','persistent-timing-summary.json','persistent-timing-results.json','persistent_benchmark_v2.py','persistent-v2-timing-summary.json','persistent-v2-timing-results.json','persistent_benchmark_v3.py','persistent-v3-timing-summary.json','persistent-v3-timing-results.json')]},
        'intermediate_sizes':{'sizes_selected_before_timing':[4,12],'pairs':24,'all_equal':True,'dispatch_threshold':'none selected or implemented','summary':intermediate['summaries'],
                              'artifacts':[binding(name) for name in ('persistent_intermediate.py','persistent-intermediate-results.json','persistent-intermediate-models.json','persistent-intermediate-progress.jsonl','persistent-intermediate-console.txt')]},
        'preserved_prior_versions':[binding('persistent_policy.py'),binding('persistent_policy_v2.py')],
        'review_documents':[binding('PERSISTENT_API.md'),binding('persistent-investigation.md'),binding('persistent-worklog.md'),binding('persistent-v3-transformed-rules.lp')],
        'known_limitations':['Small and both intermediate model sizes regressed versus accepted compiler','Higher initial compilation cost','Inherited CR static literal constructor RuntimeError; not caught by default fallback','Serialized calls per object; request groundings bounded by query count','Normal colocated module imports only tested','No adoption, dispatch or production memory/latency guarantee'],
        'owned_jobs_remaining':0,
    }
    write('persistent-review-manifest.json',review)
    names=sorted(path.name for path in ROOT.iterdir() if path.is_file() and (path.name.startswith('persistent') or path.name=='PERSISTENT_API.md') and path.name!='persistent-manifest.json')
    manifest={'sealed_at_utc':datetime.now(timezone.utc).isoformat(),'status':'experimental_review_only_not_adopted',
              'protected_sha256':{name:digest(name) for name in protected},'protected_files_unchanged':unchanged,
              'new_artifact_sha256':{name:digest(name) for name in names},
              'compact_review_manifest':binding('persistent-review-manifest.json'),
              'excluded':['manifest own hash reported separately','__pycache__ runtime files']}
    write('persistent-manifest.json',manifest)
    print(json.dumps({'protected_files':len(protected),'protected_all_unchanged':all(unchanged.values()),'new_artifacts':len(names),
                      'source_sha256':digest('persistent_policy_v3.py'),'review_manifest_sha256':digest('persistent-review-manifest.json'),
                      'manifest_sha256':digest('persistent-manifest.json'),'owned_jobs_remaining':0},indent=2),flush=True)


if __name__=='__main__': main()
"""Seal the bounded bulk experiment without changing protected inputs."""
import difflib
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(name, value):
    (ROOT / name).write_text(json.dumps(value, ensure_ascii=True, indent=2) + '\n', encoding='utf-8')


def main():
    protected = json.loads((ROOT / 'bulk-protected-inputs.json').read_text())['protected_sha256']
    current = {name: digest(ROOT / name) for name in protected}
    unchanged = {name: current[name] == expected for name, expected in protected.items()}
    assert all(unchanged.values()), unchanged
    timing = json.loads((ROOT / 'bulk-timing-summary.json').read_text())
    literals = json.loads((ROOT / 'bulk-literal-diagnostics.json').read_text())
    api = json.loads((ROOT / 'bulk-public-api-probe.json').read_text())
    diff = ''.join(difflib.unified_diff((ROOT / 'compiled_policy.py').read_text().splitlines(keepends=True),
                                     (ROOT / 'compiled_policy_bulk.py').read_text().splitlines(keepends=True),
                                     fromfile='compiled_policy.py', tofile='compiled_policy_bulk.py'))
    (ROOT / 'bulk-source-diff.patch').write_text(diff, encoding='utf-8')
    report = '''# Bulk immutable-fact loading: not adopted

This bounded engineering prototype is not adoption-ready and is not WP8 latency evidence. It preserves the approved source and records a failed performance gate plus a newly exposed inherited literal-parsing limitation. No original policy, ASP, approved compiled API, original test, or existing evidence file was changed.

## Design and API

`compiled_policy_bulk.py` is a separate copy of `compiled_policy.py`. It renders the precomputed immutable boundary symbols once using clingo.Symbol string rendering, joins complete facts with newlines, and sends that immutable program together with fresh request facts and the unchanged request rules to a fresh clingo.Control for every request. It replaces the prior Python backend.add_atom/add_rule loop. The exact source difference is `bulk-source-diff.patch`.

The copied public API remains `compile_model(instance, trace, *, allow_fallback=True)`, `CompiledAdmissionModel.evaluate(request, session)`, instance and module `evaluate_many`, with the same mode, reference_hashes, statistics, and compile_seconds diagnostics. The copied design retains snapshot deep copies, locking, fresh request/schema evaluation, source pins, dependency partitioning, and no request-result or mutable-solver cache. These are source properties, not a claim that this prototype passed the unrun comprehensive suite.

## Paired measurements

`bulk_benchmark.py` completed with exit 0. It used the supplied small fixture and full example, six request variants per model, unchanged original adapter outputs as an untimed oracle, an untimed warmup, and 24 paired request evaluations per model with alternating implementation order. All 48 timed pairs matched the original verdict exactly. Timing used perf_counter around evaluate without profiler/tracing instrumentation. Compilation was measured separately by each API. These paired timings describe only this run on a contended host.

| Model | Prior compiled median | Bulk median | Prior compiled total | Bulk total | Prior compile | Bulk compile |
|---|---:|---:|---:|---:|---:|---:|
| Small | 0.014711250 s | 0.015680250 s | 1.114865000 s | 1.017492000 s | 0.216645200 s | 0.075372200 s |
| Full example | 0.413066800 s | 0.773998000 s | 10.205499200 s | 17.945175100 s | 3.476439100 s | 3.521208200 s |

The full-example bulk request total was about 1.76 times the prior compiled total; its median was about 1.87 times the prior median. Small-model aggregate and median results disagree in direction and do not establish a useful improvement. The immutable bulk program was 2,245 bytes for the small model and 1,103,442 bytes for the full example. Exact inputs, output verdicts, order, and per-call times are retained in `bulk-timing-results.json`; full summaries and source pins are in `bulk-timing-summary.json`.

Because the performance gate failed, the copied full 827-comparison harness was not executed. `bulk_selftest.py` and `bulk_handwritten.py` are prepared artifacts only. No new comprehensive equivalence, concurrency, or snapshot-isolation validation is claimed. The previously accepted 827-comparison evidence remains unchanged and pertains to its original source and inputs.

## Retained literal failure

The first bounded `bulk_literal_smoke.py` run failed at construction with exit 1. `bulk-literal-attempt1.txt` preserves its reproduced traceback. The diagnostic follow-up completed with exit 0 and records six identifier payloads, each with resolved/none/resolved requests: quotes/backslashes; LF, tab and CR; Unicode; policy-looking text; punctuation; and empty suffix. Fifteen of 18 cases returned identical verdicts in original, approved compiled, and bulk implementations.

For the payload containing LF, tab and CR, both compiled implementations failed before request evaluation with RuntimeError from clingo.parse_term. The unchanged original adapter returned valid ANSWER_LOCAL / E_SELECTION_STATE / ANSWER_LOCAL verdicts. The inherited compiled loader calls splitlines on a fact string; the literal CR inside a quoted identifier is treated as a line boundary. In the diagnostic fixture this yields 294 splitlines chunks versus 152 newline-only chunks. Exact models, traces, request/session data, verdicts, constructor errors, and first broken chunks are in `bulk-literal-diagnostics.json`. No repair or rule change was made.

## Constructor fallback and query-wrapper distinction

`bulk_public_api_probe.py` completed with exit 0. Neither owned compiled module exports an `evaluate_compiled` function. For the failing literal input, both `compile_model` with default allow_fallback=True and strict allow_fallback=False raise RuntimeError. The module convenience `evaluate_many` also raises the same RuntimeError. Constructor fallback catches UnsupportedPartition only, so it does not handle this error. An object is not produced and its evaluate method is never reached. The original adapter returns ANSWER_LOCAL for the same input.

The integration-level query wrapper is outside this isolated directory and was neither read nor invoked. This report makes no claim about its exception handling; the publisher is separately auditing it under root direction. `bulk-public-api-probe.json` retains the exact owned-API probe inputs and results.

## Disposition and pins

Do not adopt or integrate this bulk prototype. Do not repair the fixed approved source or rerun the 827-comparison campaign as part of this bounded task. All owned benchmark/probe processes reached terminal status. All 25 pre-existing protected file hashes match `bulk-protected-inputs.json`. `bulk-manifest.json` pins all protected inputs and every new source, test, report and evidence artifact; it excludes only its own hash and generated Python bytecode caches. No backend, other implementation, differential result, root outcome, network, credentials, or Git was accessed.
'''
    (ROOT / 'bulk-investigation.md').write_text(report, encoding='utf-8')
    worklog = '''# Bulk experiment work log

Scope: original isolated implementer_b directory only. Every shell call used this directory as workdir. The already authorized interpreter at ../../.venv/Scripts/python.exe was invoked without inspecting other project paths. No network, Git, credentials, parent workspace files, backend code, other implementation, other agent results, or outcome reports were consulted. No skill was necessary for this local Python/clingo engineering task.

1. Hashed all 25 pre-existing non-bytecode files into bulk-protected-inputs.json before creating the prototype. Files were read bytewise for preservation checks. Original source/approved API, own earlier worklogs/API documentation/test harness and supplied local fixtures/schema/example inputs were the substantive references. Existing evidence was only own evidence.
2. Copied approved compiled_policy.py to distinct compiled_policy_bulk.py. Changed only its description, one-time rendering of static boundary symbols, and replacement of request-time backend atom insertion with complete fact-program addition. The final diff is retained separately. No declarative rules were edited.
3. Copied own optimization test harness and handwritten tests into bulk_selftest.py and bulk_handwritten.py, with new output paths. These were never executed because the performance gate subsequently failed.
4. Ran bulk_benchmark.py against supplied small and full inputs. It exited 0; exact 48 paired outputs and times were written to new files. Full-model slowdown ruled out adoption and the full campaign was skipped.
5. Ran bulk_literal_smoke.py. It exited 1 on a control-character identifier during compile. Kept the failed source intact. Ran bulk_literal_diagnostics.py (exit 0), which reproduced and captured that failure, continued all six payloads, and retained exact models/requests/results/errors. Both approved compiled and bulk paths fail on CR within a quoted literal before decision evaluation. The original adapter succeeds. This is an inherited compiled parsing limitation; no repair was made.
6. Reported slowdown/failure to root. Root directed preservation of the approved source, no repairs or 827 rerun, API fallback clarification, and a non-adoption seal.
7. Ran bulk_public_api_probe.py (exit 0). Confirmed default and strict compile_model plus module evaluate_many propagate RuntimeError; neither owned module exports evaluate_compiled. No external query wrapper was read. Reported the distinction to root.
8. Sealed this report, source diff, access record, outcome and manifest using bulk_seal.py. Rechecked every protected hash. All owned jobs were terminal before sealing. No existing evidence file was overwritten; Python imports may create normal bytecode cache files, excluded from source/evidence preservation accounting.

Sources and inputs read substantively: own compiled_policy.py, policy_adapter.py, admission.lp, optimization_selftest.py, selftest.py, COMPILED_API.md, OPTIMIZATION_WORKLOG.md, fixtures.json, instance.schema.json, example.instance.json, example.trace.json, and newly created bulk sources/evidence. The preservation hash pass additionally read all filenames enumerated in bulk-protected-inputs.json, including own earlier result files and local docs/amendments. Runtime dependencies were Python standard library, installed clingo and jsonschema with its installed local dependencies. No direct dependency source modification occurred. The interpreter and dependency loading were the only allowed executable accesses outside this directory.

The exact hash-read inventory is in bulk-access-record.json and the final content pins are in bulk-manifest.json. All final new files begin bulk or are compiled_policy_bulk.py. Timing conclusions are restricted to the measured alternating paired run; no broad latency or correctness claim is made for the candidate.
'''
    (ROOT / 'bulk-worklog.md').write_text(worklog, encoding='utf-8')
    output = {
        'status': 'not_adopted',
        'reason': 'Full-example paired request timing regression; retained inherited compiled literal parsing failure.',
        'scope': 'Bounded engineering experiment only; not WP8 latency evidence.',
        'timing_pairs': 48,
        'timing_pairs_all_equal_to_original': all(m['all_equal'] for m in timing['models'].values()),
        'timing_summary': timing['models'],
        'literal_request_cases': literals['request_cases'],
        'literal_equal_verdict_cases': literals['all_returned_equal_verdict_cases'],
        'literal_constructor_failure_cases': 3,
        'public_api_results': api['results'],
        'external_evaluate_compiled_wrapper': 'outside isolation; not read or invoked; publisher audit separate',
        'full_827_candidate_campaign': 'NOT RUN: performance gate failed; root explicitly prohibited rerun',
        'candidate_comprehensive_concurrency_snapshot_checks': 'NOT RUN; no new validation claimed',
        'processes': [
            {'script': 'bulk_benchmark.py', 'exit_code': 0},
            {'script': 'bulk_literal_smoke.py', 'exit_code': 1},
            {'script': 'bulk_literal_diagnostics.py', 'exit_code': 0},
            {'script': 'bulk_public_api_probe.py', 'exit_code': 0},
        ],
        'owned_jobs_remaining': 0,
        'protected_files_unchanged': unchanged,
        'reference_sha256': {name: current[name] for name in ('policy_adapter.py', 'admission.lp', 'compiled_policy.py', 'optimization_selftest.py')},
        'candidate_sha256': digest(ROOT / 'compiled_policy_bulk.py'),
        'remaining_action': 'Root review of non-adoption record; preserve immutable sources and all evidence.',
    }
    write_json('bulk-outcome.json', output)
    new_names = sorted(p.name for p in ROOT.iterdir() if p.is_file() and (p.name.startswith('bulk') or p.name == 'compiled_policy_bulk.py') and p.name not in ('bulk-manifest.json', 'bulk-access-record.json'))
    write_json('bulk-access-record.json', {
        'permitted_project_directory': str(ROOT),
        'protected_files_read_for_preservation_hashes': sorted(protected),
        'new_files_read_or_written_by_experiment': new_names + ['bulk-access-record.json', 'bulk-manifest.json'],
        'external_access': ['Explicitly permitted Python interpreter invocation', 'Python standard library and installed clingo/jsonschema dependency loading'],
        'excluded_access': ['parent project sources', 'backend', 'other implementation', 'other agent findings', 'root outcomes', 'network', 'Git', 'credentials'],
    })
    new_names.append('bulk-access-record.json')
    manifest = {
        'sealed_at_utc': datetime.now(timezone.utc).isoformat(),
        'status': 'not_adopted',
        'protected_sha256': current,
        'protected_all_unchanged': all(unchanged.values()),
        'new_artifact_sha256': {name: digest(ROOT / name) for name in sorted(new_names)},
        'excludes': ['manifest own hash (reported separately)', '__pycache__ runtime files'],
    }
    write_json('bulk-manifest.json', manifest)
    print(json.dumps({'status': output['status'], 'protected_count': len(protected), 'protected_all_unchanged': all(unchanged.values()), 'new_artifact_count': len(new_names), 'candidate_sha256': output['candidate_sha256'], 'manifest_sha256': digest(ROOT / 'bulk-manifest.json')}, indent=2), flush=True)


if __name__ == '__main__':
    main()
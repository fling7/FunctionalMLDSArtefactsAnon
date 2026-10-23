"""Build Stage A narrative exclusively from measured and retained evidence."""
import json
from pathlib import Path
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'repro/sprint_report.py').is_file())
OUT=ROOT/'deliverables/delta2_20261020/stage_A'
def main():
 a1=json.loads((OUT/'numbers_a1.json').read_text())
 a2=json.loads((OUT/'numbers_a2_final.json').read_text())
 a3=json.loads((OUT/'review/numbers_a3.json').read_text())
 a45=json.loads((OUT/'numbers_a4_a5.json').read_text())
 profilepath=OUT/'review/a1_runtime_profile_top15.json'
 profile=json.loads(profilepath.read_text()) if profilepath.exists() else []
 changes=[{'key':f'profile300[{i}].{key}','old':None,'new':value,'flag':'NEW_PROFILE_METRIC','script':'drafts/delta2_20261020/a1_timing.py'} for i,row in enumerate(profile) for key,value in row.items() if isinstance(value,(int,float))]
 (OUT/'review/changes_a1_profile.json').write_text(json.dumps(changes,indent=2)+'\n',encoding='utf-8')
 timings=[]
 for size in ['classroom','100','300','1000']:
  by={r['cell']:r for r in a1['rows'] if r['size']==size}
  t,r=by['gates_1_to_3_table'],by['gates_1_to_3_runtime']
  fmt=lambda x:f"{x['median_ms']:.3f} ms" if x['status']=='DONE' else 'NOT DONE'
  timings.append(f"| {size} | {fmt(t)} | {fmt(r)} |")
 notes=[]
 for name in ['item_notes_a1.md','item_notes_a2_final.md','review/item_notes_a3.md','item_notes_a4_a5.md']:
  notes.append((OUT/name).read_text(encoding='utf-8-sig'))
 text=f"""# DELTA 2 — Stage A

## Five findings that affect the paper

1. Table-mode admission was measured with digest checking, paired with runtime admission on the same local-answer request and session. {a1['cells_done']}/{a1['cells_total']} timing cells completed. The results below include all slow and unfinished cases. This measures the admission pipeline, not just dictionary lookup.
2. All {a2['assembly_failures_total']} historical assembly refusals were reproducible from retained inputs with the historically pinned assembler: {a2['assembly_all_duplicate_asset_owner']} duplicate asset-owner declarations and {a2['assembly_all_other']} owner/zone conflicts. These are retained pipeline-attempt faults, not a representative estimate of fault prevalence.
3. Removing only the object-owner override makes {a45['A5_latent']['any_ambiguous_all3']}/{a45['A5_latent']['entities']} latent cases ambiguous under all three oracles, not the expected twelve. Seven remain resolved by group ownership. The requested twelve span original-natural and ownership-repair cohorts; they are not twelve classroom faults.
4. All-non-oracle misses remain {a45['A4']['generated']['missed_all_nonoracle']} in generated mutants and {a45['A4']['classroom']['missed_all_nonoracle']} in classroom mutants; every miss involves the duplicate-action operator. Per-operator singles and pairs are separated. These results do not establish universal detector coverage.
5. Classroom's {a45['A5_classroom']['outside_one_handoff_limit']} pairs outside one handoff comprise {a45['A5_classroom']['finite_more_than_one_handoff']} finite two-hop pairs and {a45['A5_classroom']['unreachable_pairs']} unreachable pairs. Stored timestamps precede October 15, but the author/tool is unestablished. Drift preserves the ownership partition in {a45['A5_drift']['same_partition']}/{a45['A5_drift']['comparable_fresh_regeneration_pairs']} comparable pairs; partition equality alone does not establish semantic equivalence.

## Paired admission medians

| Scene-object size | table, digest=true | runtime, digest=true |
| --- | ---: | ---: |
{chr(10).join(timings)}

The complete table includes ten repetitions after two discarded warmups, inclusive IQR, minimum and maximum, exact native-element counts and preparation status. One worker ran at a time; desktop applications remained running. One ANSWER_LOCAL query per size is a case measurement, not a representative query mixture. The admission endpoint includes state snapshots and both preflights. The inherited no-guard baseline bypasses admission checks and exercises scripted SessionStore.chat plus snapshot/restore. It does not invoke the outer HTTP endpoint or Gate4 logger, which is measured separately; do not subtract or divide these different endpoints to claim total end-to-end guard overhead.

Cold memory means clearing the routing-table cache, with the verifier already imported. The OS file cache was uncontrolled. Production has no persistent disk-table load implementation; JSON persist/load is separately labelled artifact I/O, and true OS-cold loading is NOT DONE. The production default remains runtime routing; table mode was explicitly selected for its paired measurements. No application optimization was made.

The retained 300-object cProfile run identifies the action preflight/contract-reload path, especially trace validation, as the main cumulative-time consumer. Profiling itself adds overhead; its wall-clock duration is not a replacement timing sample, and nested cumulative times must not be added together.

## Checker provenance

The table has {a3['delta2_A3_component_rows']} component/dependency rows, not that many independent checkers. Seven rows are study-written, eight are inherited files changed for the study, and five are unchanged. Structural V-a functions, V-b schema functions and V-c loader functions remain AST-identical to the retained original implementation even where their containing files changed. The requested August 6 V-a import is verified; local history also retains an earlier July 27 addition. Gate 0, I1, I2 and study adapters must not be described as independent pre-existing tools.

## Detailed item notes

{chr(10).join(notes)}

## Scope, numeric provenance and reproduction

All baseline and DELTA1 artifacts, raw files, caches, claims and gates remain unchanged. No GO decision is re-evaluated in this supplement. Stage A uses no API calls and spends USD 0. New tables, numbers files and old/new/script logs are authoritative only for this supplement. Source hashes pin originals before anonymization; MANIFEST.sha256 pins the delivered transformed payload.

Scripts are supplied under drafts/delta2_20261020, with new raw results under results/raw/delta2/stage_A. Use the existing repository environment and exact retained inputs referenced by proofs; scripts do not download dependencies or call models. Existing result outputs intentionally refuse overwrite where applicable. Preserve this delivery when reproducing in a fresh output tree. The original source registry, model paths and all cohort distinctions remain in the proofs.

Stages B and C are separate deliveries and are not claimed complete here.
"""
 (OUT/'DELTA2.md').write_text(text,encoding='utf-8')
if __name__=='__main__':main()

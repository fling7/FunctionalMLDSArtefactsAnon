"""Summarize the frozen Stage B cohort without modifying earlier stages."""
import json,csv
from pathlib import Path
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'repro/sprint_report.py').is_file())
OUT=ROOT/'deliverables/delta2_20261020/stage_B'
def main():
 n=json.loads((OUT/'review/numbers_b1.json').read_text())
 proof=json.loads((OUT/'review/proof_b1.json').read_text())
 table=list(csv.DictReader((OUT/'tables/T_B1_detection.csv').open(encoding='utf-8-sig')))
 union=next(r for r in table if r['scope']=='pooled' and r['checker']=='nonoracle_union')
 plan=json.loads((ROOT/'results/raw/delta2/stage_B/preregistration_v5.json').read_text())
 note=(OUT/'review/item_notes_b1.md').read_text()
 actual=json.loads((OUT/'actually_started_rooms/analysis_scope.json').read_text())
 coverage='MET' if actual['actually_started_rooms']>=20 else 'NOT MET'
 (OUT/'review/numbers_b_scope.json').write_text(json.dumps({'actually_started_rooms':actual['actually_started_rooms'],'requested_minimum_room_coverage':20,'minimum_coverage_status':coverage,'source':'actually_started_rooms/analysis_scope.json','script':'drafts/delta2_20261020/report_stage_b.py'},indent=2)+'\n',encoding='utf-8')
 text=f"""# DELTA 2 - Stage B

## Five findings and qualifications

1. The new campaign covers {n['stageB_observed_rooms']} observed rooms out of {n['stageB_selected_rooms']} selected rooms, rather than reusing the six generated base cases of the original mutation cohort. Execution status: {proof['status']}.
2. The non-oracle union has TP={union['TP']}, FN={union['FN']}, FP={union['FP']}, TN={union['TN']} on determinate, eligible mutants. Misses and false positives are retained. Wilson and room-cluster intervals are reported alongside counts, not replaced by an unqualified success percentage.
3. There are {n['stageB_groundtruth_eligible']} mutants with determinate ground truth among {n['stageB_planned_slots']} planned operator slots. No-op, inapplicable, technical, unexecuted and oracle-disagreement cases are explicit; they are not silently counted as passes.
4. The subset was fixed before mutant execution: twenty-one native sources selected by source-origin and object-count strata, plus classroom. The full population is fifty-six native base sources plus classroom. This bounded sample does not establish prevalence across that population.
5. Backend setup and model/backend probes were deliberately excluded. The campaign measures offline checker detection, with agreement of Gate 0, I1 and compiled I2 as the truth requirement; it does not replace end-to-end backend validation.

At least twenty rooms actually started: **{coverage}** ({actual['actually_started_rooms']} started). This threshold alone does not establish complete scientific evaluation of all seventeen operators; technical failures remain unresolved.

## Method and reproduction

{note}

Execution amendment: execution_amendment.json increased concurrent workers from two to six, preserving the original absolute one-hour deadline. The original controller and its two active workers were stopped before resumption; completed-file hashes were verified unchanged. The same registered queue, rooms, operators, seeds, validators and truth criteria were used. Only slots without completed outputs, including technical timeouts, were resumed; all earlier failure records remain available. This orchestration amendment was recorded after observing runtime and is not represented as the original preregistration. A later controller recovery handled a Windows taskkill race: only confirmed process termination is accepted. Previously started slots lacking scientific output were retained as explicit technical terminal records, with console/failure provenance, and not retried again. These are not successful mutant evaluations. See execution_recovery_v2.json.

Active preregistration: results/raw/delta2/stage_B/preregistration_v5.json, pinned by review/proof_b1.json. Earlier draft plans/scripts are retained as superseded, not executed studies. Active script: drafts/delta2_20261020/agent_b_stageB/stage_b_v5.py. Execute only in a fresh output workspace; retained checkpoints are never overwritten. The exported original plan preserves pre-anonymization source and script pins for provenance. The separate review/exported_input_manifest.json verifies anonymized model files; direct execution against those renamed copies requires a new, explicitly derivative job with those export hashes, not silent alteration of the original preregistration.

The requested analysis over actually started rooms is in actually_started_rooms/tables/T_B1_detection_machine_readable.csv; analysis_scope.json gives the actual room denominator and the outcome-independent worker-start selection rule. The original all-selected-room analysis remains in tables/T_B1_detection.csv, with JSON interval arrays in tables/T_B1_detection_machine_readable.csv. The derivative conversion changes scalar representation only and retains source/derivative hashes. Neither analysis repairs informative technical censoring or establishes coverage of unstarted rooms.

Room-cluster bootstrap uses seed {plan['seed']} and {plan['bootstrap_resamples']} resamples over all selected rooms, including rooms with zero eligible observations; single-room intervals are descriptive and degenerate. The supplied tables separate checker-specific eligibility and show all room/operator slots. Scientific completion and technical termination are separate.

API calls and extra API cost: zero. Original data, DELTA1, Stage A, claims and gates remain unchanged. This is a separate cohort and must not be pooled into generated 908 or classroom 153. Original source hashes refer to pre-anonymization inputs; MANIFEST.sha256 covers this exported payload.
"""
 (OUT/'DELTA2.md').write_text(text,encoding='utf-8')
if __name__=='__main__':main()

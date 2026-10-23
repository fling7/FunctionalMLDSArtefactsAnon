"""Regenerate disagreement summaries; never modify original probe records."""
from pathlib import Path
import csv,json,collections
ROOT=Path(__file__).resolve().parents[1]
RULES={
 "user_text_number":("backend bug","SPEC 4.3 requires the original request to satisfy its declared schema; numeric text is coerced by the packet."),
 "user_text_empty":("backend bug","The packet checks empty utterance before ownership/reachability, contrary to SPEC first-failing-condition order."),
 "source_alias_conflict":("backend bug","SPEC 4.3 requires consistent supplied identities; A001 explicitly covers both aliases."),
 "empty_candidates":("spec ambiguity","SPEC v1 did not define empty candidate-list semantics; A001 chose exact singleton when supplied."),
 "ambiguity_reason_only":("spec ambiguity","A001 distinguishes boolean ambiguity flags from explanatory text."),
 "active_and_digest":("backend bug","SPEC 4.3 requires stale digest to be the first error, before active-agent membership.")
}
def main():
    raw=ROOT/"results/raw/differential/example-initial/probes.jsonl"
    if not raw.exists():return
    selected=[raw,ROOT/"results/raw/differential/schema-admission-v1/probes.jsonl"]
    rows=[json.loads(l) for p in selected if p.exists() for l in p.read_text(encoding="utf-8").splitlines()]
    disagreements=[r for r in rows if not r["agrees"]]
    independent=sum(r["verdicts"]["I1"]!=r["verdicts"]["I2"] for r in rows)
    counts=collections.Counter(RULES[r["variant"]][0] for r in disagreements)
    out=ROOT/"results/processed";out.mkdir(parents=True,exist_ok=True)
    summary={"unit":"room","rooms":len({r["room"] for r in rows}),"probes":len(rows),"disagreement_probes":len(disagreements),
             "decision_disagreement_probes":sum(not r["decision_agrees"] for r in disagreements),
             "reason_only_disagreement_probes":sum(r["decision_agrees"] for r in disagreements),
             "I1_I2_disagreements":independent,"classifications":dict(counts),"rules":RULES,
             "fix_status":"Unfixed default compatibility findings; no independent implementation changed to obtain agreement.",
             "raw_sources":[p.relative_to(ROOT).as_posix() for p in selected if p.exists()]}
    (out/"differential_summary.json").write_text(json.dumps(summary,indent=2)+"\n",encoding="utf-8")
    lines=["# Differential findings","",
      "One authored example room is the unit of analysis. Probe counts below describe exhaustive configurations within that room, not independent observations.","",
      f"{len(rows)} probes; {len(disagreements)} disagreed. Decision/provider/action disagreements: {summary['decision_disagreement_probes']}; reason-only: {summary['reason_only_disagreement_probes']}. I1 versus I2 disagreements: {independent}.","",
      "| Variant | Classification | Disagreement probes | Decision disagreements | Disposition |","|---|---|---:|---:|---|"]
    table=[]
    for variant,(classification,reason) in RULES.items():
        group=[r for r in disagreements if r["variant"]==variant]
        lines.append(f"| {variant} | {classification} | {len(group)} | {sum(not r['decision_agrees'] for r in group)} | {reason} Default retained; no fix commit. |")
        table.append({"variant":variant,"classification":classification,"probes":len(group),"decision_disagreements":sum(not r["decision_agrees"] for r in group)})
    lines+=["","A001 was frozen before these probes were evaluated. It was not revised in response to this run. All initial pending entries remain in the append-only ledger, followed by adjudication records. Do not add the two event types as separate disagreements.",
      "","Raw verdicts: results/raw/differential/example-initial/probes.jsonl. Processed counts: results/processed/differential_summary.json.",
      "","The extended schema-admission run adds numeric-utterance and empty-utterance precedence findings. The broader corpus, mutant comparison, and property counterexamples remain separate work; this table does not establish general agreement."]
    (ROOT/"docs/DISAGREEMENTS.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
    tables=ROOT/"paper_inputs/tables";tables.mkdir(parents=True,exist_ok=True)
    with (tables/"T9_disagreements.csv").open("w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=list(table[0]));w.writeheader();w.writerows(table)
    latex=["% One authored room; probes are dependent configurations.","\\begin{tabular}{lrr}","\\toprule","Variant & Disagree & Decision \\\\","\\midrule"]
    for r in table:latex.append(r["variant"].replace("_","\\_")+f" & {r['probes']} & {r['decision_disagreements']} \\\\")
    latex+=["\\bottomrule","\\end{tabular}"]
    (tables/"T9_disagreements.tex").write_text("\n".join(latex)+"\n",encoding="utf-8")
if __name__=="__main__":main()

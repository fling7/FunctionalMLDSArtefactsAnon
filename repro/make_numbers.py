"""Generate numbers from saved evidence, with provenance for each value."""
from pathlib import Path
import json,xml.etree.ElementTree as ET
ROOT=Path(__file__).resolve().parents[1]
def read(p):return json.loads((ROOT/p).read_text(encoding="utf-8"))
def write(p,value):
    p=ROOT/p;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(value,sort_keys=True,indent=2)+"\n",encoding="utf-8")
def main(*,sealed_offline=False):
    summary_dir="results/processed/accounting" if sealed_offline else "logs"
    n={};provenance={}
    def add(key,value,source):n[key]=value;provenance[key]=source
    p="results/raw/packet_regression.json"
    if (ROOT/p).exists():add("regressionProbeConfigurations",len(read(p)["probes"]),p)
    p="results/wp1/metamodel_delta.json"
    if (ROOT/p).exists():
        d=read(p)
        for phase in ("baseline","extended"):
            for k,v in d[phase].items():add("metamodel_"+phase+"_"+k,v,p)
        for k,v in d["traceability_status_counts"].items():add("traceability_"+k.replace(" ","_"),v,p)
    p="results/processed/properties_summary.json"
    if (ROOT/p).exists():
        for k,v in read(p).items():
            if type(v) is int:add("properties_"+k,v,p)
    p="results/processed/differential_summary.json"
    if (ROOT/p).exists():
        for k,v in read(p).items():
            if isinstance(v,int):add("differential_"+k,v,p)
    p="results/processed/wp7_index.json"
    if (ROOT/p).exists():
        for k,v in read(p)["numbers"].items():add(k,v,p)
    p="results/processed/pipeline_summary.json"
    if (ROOT/p).exists():
        for k,v in read(p).items():
            if type(v) is int:add("pipeline_"+k,v,p)
    p="results/processed/wp5_paper_summary.json"
    if (ROOT/p).exists():
        d=read(p)
        for key in ("original_source_rooms","original_registered_model_runs","original_successful_native_model_runs","original_successful_native_sources","natural_probe_count"):
            if type(d.get(key)) is int:add("wp5_"+key,d[key],p)
    p="results/raw/api_preflight_status.json"
    if (ROOT/p).exists():
        d=read(p)
        add("apiPreflightInputTokens",d["usage"]["input_tokens"],p);add("apiPreflightOutputTokens",d["usage"]["output_tokens"],p);add("apiPreflightCostUsd",d["generation_cost_usd"],p)
    db=ROOT/"logs/api_budget.sqlite3"
    policy=None;rows=[]
    if not sealed_offline and db.exists():
        import sqlite3
        with sqlite3.connect(db.as_uri()+"?mode=ro",uri=True) as c:
            policy=json.loads(c.execute("select value from settings where name='policy'").fetchone()[0])
            rows=c.execute("select share,experiment,coalesce(charged,reserved),charged is null from reservations").fetchall()
    elif (ROOT/'data/accounting/budget_ledger.json').exists():
        ledger=read('data/accounting/budget_ledger.json')
        if ledger.get('schema')!='artifact-budget-ledger-v1':raise RuntimeError('Unknown offline accounting schema')
        policy=ledger['policy']
        rows=[(r['share'],r['experiment'],r['charged'] if r['charged'] is not None else r['reserved'],r['charged'] is None) for r in ledger['reservations']]
    elif sealed_offline:
        raise RuntimeError('Sealed numbers replay requires offline budget ledger')
    if policy is not None:
        summary={"cap_usd":policy["cap"]/1e9,"accounted_usd":sum(r[2] for r in rows)/1e9,"in_flight_usd":sum(r[2] for r in rows if r[3])/1e9,
            "source":"Authoritative reservation records including corrections and unresolved outcomes",
            "by_experiment":{e:sum(r[2] for r in rows if r[1]==e)/1e9 for e in sorted({r[1] for r in rows})}}
        write(summary_dir+"/budget_summary.json",summary);add("apiBudgetAccountedUsd",summary["accounted_usd"],summary_dir+"/budget_summary.json");add("apiBudgetCapUsd",summary["cap_usd"],summary_dir+"/budget_summary.json")
    calls=ROOT/("data/accounting/generation_events.jsonl" if sealed_offline else "logs/llm_calls.jsonl")
    if not sealed_offline and not calls.exists():calls=ROOT/"data/accounting/generation_events.jsonl"
    if sealed_offline and not calls.exists():raise RuntimeError("Sealed numbers replay requires offline generation events")
    if calls.exists():
        effective={}
        for r in [json.loads(l) for l in calls.read_text(encoding="utf-8").splitlines()]:
            if r.get("usage") and r.get("returned_model") and r.get("status")!="CACHE_HIT":
                key=r.get("cache_key") or r.get("request_hash") or (r.get("experiment_id"),r.get("item_id"),r.get("repetition_id"))
                effective[str(key)]=r
        grouped={}
        for r in effective.values():
            key=r["experiment_id"]+"/"+r["returned_model"]
            g=grouped.setdefault(key,{"calls":0,"input_tokens":0,"output_tokens":0,"estimated_usd":0});g["calls"]+=1
            for token in ("input_tokens","output_tokens"):g[token]+=r["usage"].get(token,0)
            g["estimated_usd"]+=float(r.get("cost_usd",0))
        write(summary_dir+"/llm_summary.json",{"by_experiment_model":grouped,"recorded_generation_outcomes":len(effective),"accounting":"Last terminal/correction per cache key; budget summary also includes unknown outcomes."})
        add("recordedGenerationOutcomes",len(effective),summary_dir+"/llm_summary.json")
    for f,key in [("guard_modes_initial.xml","guardModesRegressionPassed"),("guard_modes_table.xml","guardModesTableTestsPassed")]:
        path=ROOT/"results/raw"/f
        if path.exists():
            suites=ET.parse(path).getroot();tests=sum(int(e.get("tests",0)) for e in suites.findall("testsuite"));fail=sum(int(e.get("failures",0))+int(e.get("errors",0)) for e in suites.findall("testsuite"))
            add(key,tests-fail,path.relative_to(ROOT).as_posix())
    write("paper_inputs/numbers.json",n);write("paper_inputs/number_sources.json",provenance)
    lines=["% Generated only from saved evidence; not a claim of completed evaluation."]
    for key,value in n.items():
        macro="N"+''.join(word[:1].upper()+word[1:] for word in key.split("_")); macro=''.join(("Zero","One","Two","Three","Four","Five","Six","Seven","Eight","Nine")[int(c)] if c.isdigit() else c for c in macro); lines.append("\\newcommand{\\"+macro+"}{"+str(value)+"}")
    (ROOT/"paper_inputs/numbers.tex").write_text("\n".join(lines)+"\n",encoding="utf-8")
if __name__=="__main__":main()

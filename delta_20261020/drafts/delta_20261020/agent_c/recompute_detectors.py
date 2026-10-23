"""Delta items 3,4,5,7. Retained inputs only; no evaluator calls or networking."""
from pathlib import Path
from collections import Counter, defaultdict
import csv, hashlib, json, math, random, socket
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT / "data/go_sprint"
OUT = ROOT / "deliverables/delta_20261020"
SCRIPT = Path(__file__).relative_to(ROOT).as_posix()
SEED, RESAMPLES = 20261015, 10000
START = datetime.now(timezone.utc).isoformat()
def deny(*a, **kw): raise RuntimeError("Network forbidden in retained-data delta")
socket.create_connection = deny
socket.socket.connect = deny
pins, comparisons = {}, []
def read(p):
    b = p.read_bytes()
    pins[p.relative_to(ROOT).as_posix()] = hashlib.sha256(b).hexdigest()
    return json.loads(b.decode("utf-8-sig"))
def readcsv(p):
    pins[p.relative_to(ROOT).as_posix()] = hashlib.sha256(p.read_bytes()).hexdigest()
    with p.open(encoding="utf-8-sig", newline="") as f: return list(csv.DictReader(f))
def savejson(p, v):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(v, indent=2, sort_keys=True) + "\n", encoding="utf-8")
def savecsv(name, rows):
    p = OUT / "tables" / name
    p.parent.mkdir(parents=True, exist_ok=True)
    fields = list(dict.fromkeys(k for r in rows for k in r))
    with p.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows({k:json.dumps(v) if isinstance(v,(list,dict)) else v for k,v in r.items()} for r in rows)
def compare(key, old, new):
    r = dict(key=key, old=old, new=new, script=SCRIPT,
             flag="NEW_METRIC" if old is None else "CHANGED" if old != new else "UNCHANGED")
    comparisons.append(r)
    print(json.dumps(r, sort_keys=True))
def wilson(x,n):
    if not n: return None
    z=1.959963984540054; p=x/n; d=1+z*z/n
    c=(p+z*z/(2*n))/d; h=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/d
    return [max(0,c-h),min(1,c+h)]
def cluster_ci(groups):
    """Ratio of pooled numerator/denominator, sampling source rooms equally.

    Type-7 linearly interpolated percentile endpoints. Same seeded room draws
    are reused across endpoints. Empty denominators are counted and excluded.
    """
    keys=sorted(groups); rng=random.Random(SEED); vals=[]
    for _ in range(RESAMPLES):
        selected=[groups[rng.choice(keys)] for __ in keys]
        den=sum(v[1] for v in selected)
        if den: vals.append(sum(v[0] for v in selected)/den)
    vals.sort()
    def q(p):
        x=(len(vals)-1)*p; i=math.floor(x); j=math.ceil(x)
        return vals[i]*(j-x)+vals[j]*(x-i) if j!=i else vals[i]
    return ([q(.025),q(.975)] if vals else None),len(vals)
def metric(prefix, pairs):
    groups=defaultdict(lambda:[0,0])
    for room,x,n in pairs:
        groups[room][0]+=x; groups[room][1]+=n
    x=sum(v[0] for v in groups.values()); n=sum(v[1] for v in groups.values())
    ci, valid=cluster_ci(groups)
    return {prefix+"_rate":x/n if n else None,prefix+"_wilson95":wilson(x,n),
            prefix+"_room_cluster95":ci,prefix+"_valid_bootstrap":valid}
def verdict_union(statuses):
    if "reject" in statuses: return "reject"
    if statuses and all(s=="pass" for s in statuses): return "pass"
    return "not_applicable"
def checks(r):
    c=r["checkers"]
    d={"Va_structural":c["Va_structural"]["status"],
       "Vb_native_domain":c["Vb_native_domain"]["status"],
       "Vb_backend_setup":c["backend_setup"]["status"],
       "Vc_loader":verdict_union([c[k]["status"] for k in ("Vc_instance","Vc_trace")])}
    d["non_oracle_union"]=verdict_union(list(d.values()))
    d.update({k:c[k]["status"] for k in ("Gate0","I1_reference","I2_policy")})
    return d
def cell(truth,status):
    if truth is None: return "excluded_groundtruth"
    if status not in ("pass","reject"): return "not_applicable"
    return ("tp" if status=="reject" else "fn") if truth else ("fp" if status=="reject" else "tn")

records=defaultdict(list)
for p in sorted((DATA/"wp6/outcomes").glob("*.jsonl")):
    pins[p.relative_to(ROOT).as_posix()]=hashlib.sha256(p.read_bytes()).hexdigest()
    records["generated"].extend(json.loads(s) for s in p.read_text(encoding="utf-8-sig").splitlines() if s.strip())
for p in sorted((DATA/"sprint/w2/completed").glob("*/*.json")): records["generated"].append(read(p))
for p in sorted((DATA/"wp6_classroom").glob("snapshot/*/outcomes/*.json")): records["classroom"].append(read(p))
assert {k:len(v) for k,v in records.items()}=={"generated":908,"classroom":153}
for cohort,rr in records.items():
    assert len({r["metadata"]["id"] for r in rr})==len(rr)
    assert all(r["groundtruth"]["routing_faulty"] is not None for r in rr)
    assert all("MemoryError" not in json.dumps(r["checkers"]["backend_setup"]) for r in rr)
old_t4={(r["cohort"],r["checker"]):r for r in readcsv(ROOT/"tables/T4_detection_matrix.csv") if r["group"]=="all"}
old_t5={(r["cohort"],r["variant"]):r for r in readcsv(ROOT/"tables/T5_executed_ablation.csv")}
oldmap={"Vb_backend_setup":"backend_setup","Vc_loader":"Vc_instance","non_oracle_union":"authoring_loader_union"}
detectors, paired, refusals, refusal_checks, perroom, ablations = [],[],[],[],[],[]
numbers={"bootstrap_seed":SEED,"bootstrap_resamples":RESAMPLES,"detector_truth_definition":
         "Retained routing_faulty label from agreeing I1/I2. Positive means declared routing fault, not generic invalidity. Gate0/I1/I2 are oracle sanity checks only.",
         "cluster_unit":"metadata.room; six generated source rooms, one classroom source room; never treat mutants or probes as independent rooms",
         "loader_definition":"Vc_instance OR Vc_trace rejection; backend setup refusal is recorded rejection, not missing execution",
         "union_definition":"OR of Va_structural, Vb_native_domain, backend_setup, and Vc_instance/Vc_trace; unavailable unrelated metrics do not remove negatives",
         "cluster_caveat":"Classroom has one source room: bootstrap intervals are degenerate and provide no between-room population uncertainty. Generated has six rooms only. Wilson treats models as Bernoulli trials and is descriptive, not dependence-adjusted.",
         "cohorts":{}}
for cohort,rr in sorted(records.items()):
    for r in rr: r["_checks"]=checks(r)
    nrooms=len({r["metadata"]["room"] for r in rr})
    refused=[r for r in rr if r["checkers"]["backend_setup"]["status"]=="reject"]
    nc={"models":len(rr),"source_rooms":nrooms,"routing_faulty":sum(r["groundtruth"]["routing_faulty"] for r in rr),"setup_refused":len(refused)}
    numbers["cohorts"][cohort]=nc
    for mode in ("include_refusals","exclude_refusals"):
        selected=rr if mode=="include_refusals" else [r for r in rr if r not in refused]
        for checker in rr[0]["_checks"]:
            cells=[(r["metadata"]["room"],cell(r["groundtruth"]["routing_faulty"],r["_checks"][checker])) for r in selected]
            cc=Counter(c for _,c in cells); n=sum(cc[k] for k in ("tp","fn","fp","tn"))
            row={"cohort":cohort,"refusal_policy":mode,"block":"oracle sanity check, not independent evidence" if checker in ("Gate0","I1_reference","I2_policy") else "non-oracle detectors",
                 "checker":checker,"retained_models":len(rr),"selected_models":len(selected),"source_rooms":nrooms,"n_models":n,
                 **{k:cc[k] for k in ("tp","fn","fp","tn","excluded_groundtruth","not_applicable")},
                 "cluster_note":"one room: degenerate, no population inference" if nrooms==1 else "six source-room clusters; limited generalizability"}
            for k in ("tp","fn","fp","tn"):
                row.update(metric(k,[(room,int(c==k),int(c in ("tp","fn","fp","tn"))) for room,c in cells]))
            for name,numerator,denominator in (("sensitivity","tp",("tp","fn")),("false_positive","fp",("fp","tn")),("specificity","tn",("fp","tn"))):
                row.update(metric(name,[(room,int(c==numerator),int(c in denominator)) for room,c in cells]))
            detectors.append(row)
            old=old_t4.get((cohort,oldmap.get(checker,checker)),{}) if mode=="include_refusals" else {}
            for k,v in row.items():
                if isinstance(v,(int,float,list)):
                    ov=old.get(k); ov=json.loads(ov) if ov not in (None,"") else None
                    if k=="sensitivity_rate" and old:
                        old_n=int(old["tp"])+int(old["fn"])
                        ov=int(old["tp"])/old_n if old_n else None
                    compare(f"T4b/{cohort}/{mode}/{checker}/{k}",ov,v)
            for room in sorted({x[0] for x in cells}):
                rc=Counter(c for rm,c in cells if rm==room)
                perroom.append({"cohort":cohort,"refusal_policy":mode,"checker":checker,"source_room":room,**{k:rc[k] for k in ("tp","fn","fp","tn")}})
    caught=lambda r: r["groundtruth"]["routing_faulty"] is True and r["_checks"]["Va_structural"]=="pass" and verdict_union([r["_checks"][k] for k in ("Vb_native_domain","Vb_backend_setup","Vc_loader")])=="reject"
    legacy=lambda r:r["groundtruth"]["routing_faulty"] is True and r["checkers"]["Va_structural"]["status"]=="pass" and any(v.get("status")=="reject" for k,v in r["checkers"].items() if k.startswith(("Vb_","Vc_")))
    assert all(caught(r)==legacy(r) for r in rr)
    x=sum(caught(r) for r in rr)
    pr={"cohort":cohort,"count":x,"all_models":len(rr),"source_rooms":nrooms,
        **metric("share_of_all_models",[(r["metadata"]["room"],int(caught(r)),1) for r in rr]),
        **metric("share_of_faulty_models",[(r["metadata"]["room"],int(caught(r)),int(r["groundtruth"]["routing_faulty"])) for r in rr])}
    paired.append(pr); nc["Va_misses_later_catches"]=x
    compare(f"C09/{cohort}/Va_misses_later_catches",252 if cohort=="generated" else None,x)
    for k,v in pr.items():
        if isinstance(v,(int,float,list)) and k!="count": compare(f"C09/{cohort}/{k}",None,v)
    reason_groups=defaultdict(list)
    for r in refused:
        b=r["checkers"]["backend_setup"]; message=b.get("message","")
        reason="runtimeAction_cardinality" if "runtimeAction" in message and "1..*" in message else "unresolved_handoffTarget_reference" if "handoffTarget" in message else "unresolved_provider_reference" if ".provider contains unresolved reference" in message else "other_retained_reason"
        reason_groups[(b.get("reason"),reason)].append(r)
    for (code,reason),sub in sorted(reason_groups.items()):
        row={"cohort":cohort,"code":code,"reason":reason,"models":len(sub),"source_rooms":len({r["metadata"]["room"] for r in sub}),"routing_faulty":sum(r["groundtruth"]["routing_faulty"] for r in sub)}
        refusals.append(row)
        for k,v in row.items():
            if isinstance(v,int): compare(f"refusals/{cohort}/{reason}/{k}",({"runtimeAction_cardinality":96,"unresolved_handoffTarget_reference":102}.get(reason) if cohort=="generated" and k=="models" else None),v)
        for checker in rr[0]["_checks"]:
            c=Counter(r["_checks"][checker] for r in sub)
            refusal_checks.append({"cohort":cohort,"reason":reason,"checker":checker,"models":len(sub),"reject":c["reject"],"pass":c["pass"],"not_applicable":c["not_applicable"]})
    # Same exact wrong-admission predicate as retained report; add room sets.
    acc=defaultdict(Counter); wrong_models=defaultdict(set); wrong_rooms=defaultdict(set); executed_models=defaultdict(set); executed_rooms=defaultdict(set)
    def key(v):return tuple(v.get(k) for k in ("decision","reason","provider","action"))
    for r in rr:
        ident=r["metadata"]["id"]; room=r["metadata"]["room"]
        for p in r["probes"]:
            endpoints=[(v,x,p["I1"],p["I2"]) for v,x in p["variants"].items()]
            s=p["stale_request"]
            endpoints += [("stale_"+v,s[v],s["I1"],s["I2"]) for v in ("runtime","no_digest")]
            for variant,v,i1,i2 in endpoints:
                a=acc[variant];a["probe_slots"]+=1
                if v.get("status")=="not_run_setup_refused": a["setup_refused_probes"]+=1; continue
                a["executed_probes"]+=1;executed_models[variant].add(ident);executed_rooms[variant].add(room)
                wrong=v.get("decision") in ("ANSWER_LOCAL","ANSWER_AFTER_HANDOFF") and key(v)!=key(i1) and key(i1)==key(i2)
                a["wrongly_admitted_probes"]+=int(wrong)
                if wrong: wrong_models[variant].add(ident);wrong_rooms[variant].add(room)
    for variant,a in sorted(acc.items()):
        row={"cohort":cohort,"variant":variant,**{k:a[k] for k in ("probe_slots","executed_probes","setup_refused_probes","wrongly_admitted_probes")},
             "executed_models":len(executed_models[variant]),"models_with_wrong_admission":len(wrong_models[variant]),
             "executed_source_rooms":len(executed_rooms[variant]),"source_rooms_with_wrong_admission":len(wrong_rooms[variant]),
             "affected_source_room_ids":sorted(wrong_rooms[variant]),
             "model_wrong_admission_wilson95":wilson(len(wrong_models[variant]),len(executed_models[variant]))}
        ablations.append(row)
        for k,v in row.items():
            if isinstance(v,(int,float,list)) and k!="affected_source_room_ids":
                old=old_t5[(cohort,variant)].get(k);old=json.loads(old) if old not in ("",None) else None
                compare(f"T5b/{cohort}/{variant}/{k}",old,v)
    nc["ablation_wrong_admissions"]={r["variant"]:{k:r[k] for k in ("wrongly_admitted_probes","models_with_wrong_admission","source_rooms_with_wrong_admission")} for r in ablations if r["cohort"]==cohort}

savecsv("T5b_normalized_ablation.csv",ablations)
savecsv("T4b_nonoracle_detectors.csv",[r for r in detectors if r["block"]=="non-oracle detectors"])
savecsv("T4b_oracle_sanity.csv",[r for r in detectors if r["block"]!="non-oracle detectors"])
savecsv("T4b_Va_missed_later_caught.csv",paired)
savecsv("T4b_detector_per_room.csv",perroom)
for row in perroom:
    for k in ("tp","fn","fp","tn"):
        compare(f"detector_per_room/{row['cohort']}/{row['refusal_policy']}/{row['checker']}/{row['source_room']}/{k}",None,row[k])
savecsv("T4c_setup_refusal_reasons.csv",refusals)
savecsv("T4c_setup_refusal_by_checker.csv",refusal_checks)
side=[]
for inc in [r for r in detectors if r["refusal_policy"]=="include_refusals"]:
    exc=next(r for r in detectors if r["cohort"]==inc["cohort"] and r["checker"]==inc["checker"] and r["refusal_policy"]=="exclude_refusals")
    side.append({"cohort":inc["cohort"],"checker":inc["checker"],"block":inc["block"],
                 **{prefix+"_"+k:r[k] for prefix,r in (("with_refusals",inc),("without_refusals",exc)) for k in ("n_models","tp","fn","fp","tn","sensitivity_rate","sensitivity_wilson95","sensitivity_room_cluster95","false_positive_rate","false_positive_wilson95","false_positive_room_cluster95")}})
savecsv("T4c_refusal_sensitivity_side_by_side.csv",side)
for row in refusal_checks:
    for k,v in row.items():
        if isinstance(v,int):compare(f"refusal_checker/{row['cohort']}/{row['reason']}/{row['checker']}/{k}",None,v)
# F5 only: same retained matrix cells/layout; label all three oracle rows.
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
plt.rcParams.update({"font.size":8,"axes.titlesize":9,"svg.hashsalt":"delta20261020","pdf.fonttype":42,"svg.fonttype":"none"})
rows=[r for (cohort,k),r in old_t4.items() if cohort=="generated"]
fig,ax=plt.subplots(figsize=(17.5/2.54,11/2.54))
im=ax.imshow([[int(r[k]) for k in ("tp","fp","fn","tn")] for r in rows],aspect="auto",cmap="Greys")
ax.set_yticks(range(len(rows)),[r["checker"]+(" (oracle)" if r["checker"].startswith(("I1","I2","Gate0")) else "") for r in rows],fontsize=7)
ax.set_xticks(range(4),["TP","FP","FN","TN"])
ax.set_title("Generated cohort: 908/908 retained mutants")
fig.colorbar(im,ax=ax,label="Mutant count")
caption="Gate0/I1/I2: oracle sanity check, not independent evidence.\nOriginal matrix counts retained; fair union denominators and room CIs: T4b."
fig.text(.5,.015,caption,ha="center",fontsize=7)
fig.tight_layout(rect=(0,.09,1,1))
folder=OUT/"figures";folder.mkdir(parents=True,exist_ok=True)
fig.savefig(folder/"F5_detection_delta.svg",metadata={"Date":None,"Creator":"Research artifact"})
fig.savefig(folder/"F5_detection_delta.pdf",metadata={"CreationDate":None,"ModDate":None,"Creator":"Research artifact","Author":"Anonymous Authors"})
fig.savefig(folder/"F5_detection_delta.png",dpi=180,metadata={"Software":"Research artifact"})
plt.close(fig)
(folder/"F5_detection_delta_caption.txt").write_text(caption+"\n",encoding="utf-8")
numbers["nonoracle_union"]={cohort:{k:r[k] for k in ("n_models","tp","fn","fp","tn","sensitivity_rate","sensitivity_wilson95","sensitivity_room_cluster95")} for cohort in records for r in detectors if r["cohort"]==cohort and r["checker"]=="non_oracle_union" and r["refusal_policy"]=="include_refusals"}
for cohort,rr in records.items():
    for k,v in numbers["cohorts"][cohort].items():
        if isinstance(v,int): compare(f"cohort/{cohort}/{k}",len(rr) if k=="models" else None,v)
savejson(OUT/"numbers_c.json",numbers)
savejson(OUT/"review/agent_c_comparisons.json",comparisons)
savejson(OUT/"review/agent_c_proof.json",{"script":SCRIPT,"started_utc":START,"ended_utc":datetime.now(timezone.utc).isoformat(),"network_forbidden":True,
         "inputs_sha256":pins,"seed":SEED,"bootstrap_resamples":RESAMPLES,"original_files_modified":False,
         "ground_truth_unknown":0,"new_mutants":0,"I3_excluded":True,"figure_rebuilt":"F5 only",
         "counts":{k:len(v) for k,v in records.items()}})
notes="""Items 3,4,5,7 DONE. No evaluators, model calls or network used. Existing retained files unchanged.

T5b uses the exact prior wrong-admission predicate, normalized to probe pairs, mutant models, and distinct metadata.room sources. All old probe/model counts reproduced unchanged; source counts are newly reported. Both normal and stale runtime controls, table, and normal no_digest retained alongside requested variants.

T4b separates generated 908 (6 source rooms) and classroom 153 (1 source room). Ground truth is fully available and is retained I1/I2 routing_faulty agreement; it does not define all generic schema faults. V-c loader means rejection by either Vc_instance or Vc_trace. Backend setup is separately shown. Union is OR of the four specified non-oracle endpoints. I3 atomicity excluded. Gate0/I1/I2 are separately labelled oracle sanity checks, not independent evidence.

IMPORTANT DENOMINATOR CORRECTION: Prior authoring_loader_union treated every non-detection as not_applicable because unrelated placement/traceability metrics were unavailable. Its generated row has TP450 FN0 TN0 n450 (458 not_applicable); corrected union has TP450 FN72 FP0 TN386 n908. Apparent sensitivity 100% becomes 86.2069%. Classroom TP87 FN0 TN0 n87 (66 not_applicable) becomes TP87 FN11 FP0 TN55 n153, sensitivity 88.7755%. These are corrected summary denominators, not new detector outcomes. Original table/claims/gates unchanged.

Wilson 95% intervals are descriptive model-level intervals. Room bootstrap uses seed20261015,10000 resamples, equal-probability source-room sampling with replacement, pooled ratio in each sample, linearly interpolated percentile endpoints. Only six generated rooms; classroom's one-room bootstrap is necessarily degenerate and supports no between-room population inference. Every confusion-cell proportion and sensitivity/FPR/specificity includes both intervals.

Paired V-a misses / later non-oracle catches: generated252/908 unchanged. This predicate matches the prior broader Vb/Vc endpoint predicate for every retained model.

T4c reports setup refusals by reason/checker and side-by-side included vs excluded statistics. These are actual E_PUBLICATION_INCONSISTENT loader rejections, not run failures; no downstream unexecuted probe is fabricated. Generated198 refusals are96runtimeAction cardinality and102unresolved handoffTarget references; classroom33 additional refusals remain separate (16runtimeAction,13handoffTarget,4unresolved provider). All refused models are routing_faulty. Excluding refusals changes the target population and must not be presented as an improved full-cohort result.

F5 only is regenerated as F5_detection_delta.*; all old heatmap counts preserved, Gate0/I1/I2 labelled(oracle), caption directs readers to corrected fair union T4b. No other figure rebuilt. The separate PNG is visual QA.

Every numerical table field has old/new/script comparisons where a prior equivalent exists; genuinely new metrics have old=null (not previously reported). No original raw/caches/tables/claims were edited. All new artifacts stay in delta paths.
"""
(OUT/"item_notes_c.md").write_text(notes,encoding="utf-8")
print("AGENT_C_COMPLETE")

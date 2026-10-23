"""Outcome-blind WP6 project inventory; no evaluator or API calls."""
import argparse,copy,fnmatch,hashlib,json
from pathlib import Path

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def select_rows(manifest,expected_count):
 rows=copy.deepcopy(manifest["rows"])
 if len(rows)!=expected_count or manifest.get("completed_runs")!=expected_count:raise ValueError("Source manifest is not terminal at its registered count")
 rows.sort(key=lambda r:(r["source_priority"],r["run_ordinal"],r["case_id"]))
 if len({r["case_id"] for r in rows})!=len(rows):raise ValueError("Duplicate project/run identity")
 produced=[r for r in rows if r.get("project_produced")]
 paths=[str(Path(r["project_path"]).resolve()) for r in produced]
 if len(set(paths))!=len(paths):raise ValueError("Multiple run identities alias one produced project")
 for r in rows:r["wp6_intake_status"]="produced_project_pending_preparation" if r.get("project_produced") else "no_project_produced"
 return rows

def copied_input(relative):
 # Exactly the frozen materializer's copytree ignore patterns, at any depth.
 return not any(fnmatch.fnmatch(part,pattern) for part in relative.parts for pattern in ("runtime*.jsonl","*.log","__pycache__"))

def audit_project_pins(project,run_result):
 project=Path(project).resolve();mapping=run_result.get("artifact_sha256")
 if not isinstance(mapping,dict) or not mapping:raise ValueError("Pinned run-result has no artifact hash map")
 expected={}
 for name,pin in mapping.items():
  path=Path(name).resolve()
  if path.is_relative_to(project) and copied_input(path.relative_to(project)):
   relative=path.relative_to(project).as_posix()
   if relative in expected and expected[relative]!=pin:raise ValueError("Conflicting registered artifact pins")
   expected[relative]=pin
 actual={f.relative_to(project).as_posix():sha(f) for f in sorted(project.rglob("*")) if f.is_file() and copied_input(f.relative_to(project))}
 records=[{"path":name,"expected_sha256":expected.get(name),"actual_sha256":actual.get(name),"matches":expected.get(name) is not None and expected.get(name)==actual.get(name)} for name in sorted(set(expected)|set(actual))]
 required={"project.json","roomcontract.v2.instance.json","trace_map.v2.json","agents.json"}
 return {"ok":bool(records) and required<=set(actual) and all(r["matches"] for r in records),"files":records,"missing_required":sorted(required-set(actual)),"scope":"All copied project inputs, using original materialize ignore patterns; includes room_plan and KB."}

def catalog(manifest_path,expected_count):
 path=Path(manifest_path);manifest=json.loads(path.read_text(encoding="utf8"));rows=select_rows(manifest,expected_count)
 for row in rows:
  if not row.get("project_produced"):continue
  p=Path(row["project_path"])
  row["project_file_sha256"]={str(f.relative_to(p)).replace("\\","/"):sha(f) for f in sorted(p.rglob("*")) if f.is_file()}
  try:
   run_path=Path(row["run_result_path"])
   if sha(run_path)!=row["run_result_sha256"]:raise ValueError("Run-result hash differs")
   run_result=json.loads(run_path.read_text(encoding="utf8"))
   row["registered_project_input_check"]=audit_project_pins(p,run_result)
   if not row["registered_project_input_check"]["ok"]:raise ValueError("Copied project inputs differ from registered artifact hashes")
   required=[p/"project.json",p/"roomcontract.v2.instance.json",p/"trace_map.v2.json",p/"agents.json"]
   for f in required:
    value=json.loads(f.read_text(encoding="utf-8-sig"))
    if not isinstance(value,dict):raise ValueError("Required native document is not an object: "+str(f))
   native_lf=hashlib.sha256((p/"roomcontract.v2.instance.json").read_bytes().replace(b"\r\n",b"\n")).hexdigest().upper()
   if row.get("model_sha256") and native_lf!=row["model_sha256"].upper():raise ValueError("Native LF digest differs from source manifest")
   if row.get("source_path") and sha(row["source_path"])!=row["source_sha256"]:raise ValueError("Source hash differs")
   if row.get("run_result_path") and sha(row["run_result_path"])!=row["run_result_sha256"]:raise ValueError("Run-result hash differs")
   row["wp6_intake_status"]="native_artifacts_available"
  except Exception as exc:row["wp6_intake_status"]="artifact_or_preparation_refused";row["intake_error"]={"type":type(exc).__name__,"message":str(exc)}
 return {"schema":"wp6-terminal-project-intake-v1","source_manifest":str(path),"source_manifest_sha256":sha(path),"registered_runs":expected_count,"rows":rows,"rule":"Every produced project, preserving model counterparts and repeated source identity; no validator, detector, oracle, or mutation outcome selection.","unit":"Produced project/model snapshot nested in source room; no mutated model is a new room."}

def main():
 p=argparse.ArgumentParser();p.add_argument("--manifest",type=Path,required=True);p.add_argument("--expected-count",type=int,required=True);p.add_argument("--output",type=Path,required=True);a=p.parse_args()
 result=catalog(a.manifest,a.expected_count);a.output.parent.mkdir(parents=True,exist_ok=True)
 with a.output.open("x",encoding="utf8") as f:json.dump(result,f,indent=2,sort_keys=True);f.write("\n")
 print(json.dumps({"rows":len(result["rows"]),"produced":sum(r.get("project_produced",False) for r in result["rows"]),"available":sum(r["wp6_intake_status"]=="native_artifacts_available" for r in result["rows"])}))
if __name__=="__main__":main()

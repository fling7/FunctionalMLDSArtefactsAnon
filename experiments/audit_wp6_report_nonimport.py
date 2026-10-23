"""Engineering-only import audit for an exact report-source overlay."""
import ast,hashlib,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from experiments.lib.model_builder import build_room
from experiments.detection_matrix import evaluate_one,write_new
from experiments.static_contract_memoization_v3 import static_contract_memoization_v3

def main(output):
 output=Path(output);output.mkdir(parents=True,exist_ok=False)
 built=build_room({"case_id":"report_import_audit","agents":["a"],"objects":["one"],"owners":{"asset":{"one":["a"]}},"handoffs":[]},output/"fixture")
 with static_contract_memoization_v3():
  result=evaluate_one({"project":str(built.project_dir),"output":str(output/"engineering_outcome.json"),"metadata":{"id":"report_import_audit","room":"self_authored_fixture","operators":[],"status":"baseline"}})
 records=[];references=[]
 for name,module in sorted(sys.modules.items()):
  file=getattr(module,"__file__",None)
  if not file:continue
  path=Path(file).resolve()
  if not path.is_relative_to(ROOT) or path.suffix!=".py":continue
  relative=path.relative_to(ROOT).as_posix()
  records.append({"module":name,"path":relative,"sha256":hashlib.sha256(path.read_bytes()).hexdigest()})
  # Independent evaluators are observed only as imported modules and byte pins.
  if relative.startswith("verification/impl_"):continue
  for node in ast.walk(ast.parse(path.read_text(encoding="utf-8-sig"))):
   names=[]
   if isinstance(node,ast.Import):names=[a.name for a in node.names]
   elif isinstance(node,ast.ImportFrom):names=[node.module or ""]+[a.name for a in node.names]
   elif isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute) and node.func.attr=="import_module":names=[a.value for a in node.args if isinstance(a,ast.Constant) and isinstance(a.value,str)]
   if any("analyze_wp7" in n for n in names):references.append({"path":relative,"line":node.lineno,"names":names})
 report_loaded=any(r["path"]=="experiments/analyze_wp7.py" for r in records)
 assert result["pairs"]==1 and result["setup"]=="pass"
 assert not report_loaded and not references
 write_new(output/"report_nonimport_audit.json",{"scope":"One self-authored native fixture; all original checkers, independent normal/stale calls and all real admission variants. Engineering only, not corpus or performance evidence.","result":result,"report_module_loaded":report_loaded,"static_import_references":references,"local_loaded_module_hashes":records,"independent_code_policy":"No independent implementation source inspected; its modules are only named and byte-hashed.","limitation":"Static import syntax of observed local dependencies plus runtime evidence; not a theorem about arbitrary dynamic Python."})
 print(json.dumps({"result":result,"report_module_loaded":report_loaded,"static_import_references":len(references),"local_modules":len(records)}))
if __name__=="__main__":main(sys.argv[1])

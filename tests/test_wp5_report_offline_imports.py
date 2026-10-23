"""Report-only imports and preservation of the frozen source-cluster estimator."""
import ast
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]

def test_estimator_ast_matches_frozen_natural_analysis():
    functions=[]
    for relative in ("experiments/natural_faults.py","experiments/lib/wp5_reporting.py"):
        tree=ast.parse((ROOT/relative).read_text(encoding="utf-8"))
        functions.append(next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=="clustered_interval"))
    assert ast.dump(functions[0],include_attributes=False)==ast.dump(functions[1],include_attributes=False)

def test_report_import_does_not_load_generation_or_evaluators():
    source = """import importlib.abc, sys
class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname in {'experiments.pipeline_runs','experiments.natural_faults','repro.llm','repro.budget','openai','sqlite3','requests','httpx'} or fullname.startswith(('backend','verification.impl_')):
            raise RuntimeError('Forbidden offline import: '+fullname)
sys.meta_path.insert(0,Block())
from experiments import report_wp5
from experiments import source_native_coverage
assert report_wp5.clustered_interval([],lambda r: r)=={'estimate':None,'low':None,'high':None,'source_clusters':0}
print('offline import passed')
"""
    result=subprocess.run([sys.executable,"-B","-c",source],cwd=ROOT,text=True,capture_output=True,check=False)
    assert result.returncode==0,result.stdout+result.stderr
    assert result.stdout.strip()=="offline import passed"

"""Run the unchanged differential harness with exact static compilation reuse."""
from pathlib import Path
import sys,pickle,json
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from verification import differential as d
from verification.impl_b.compiled_policy import compile_model
from experiments.static_contract_memoization_v3 import static_contract_memoization_v3
original=d.load
stats={'compilations':0,'compiled_calls':0,'scope':'Static differential model only; all requests and backend probes still executed'}
def load(name,path):
 module=original(name,path)
 if name!='independent_policy':return module
 previous=module.evaluate;cache={};checked=set()
 def evaluate(instance,trace,request,session):
  key=pickle.dumps((instance,trace),protocol=5)
  if key not in cache:cache[key]=compile_model(instance,trace,allow_fallback=False);stats['compilations']+=1
  value=cache[key].evaluate(request,session);stats['compiled_calls']+=1
  # Check the public original evaluator on every distinct decision/reason class.
  outcome=(value.get('decision'),value.get('reason'))
  if outcome not in checked:assert previous(instance,trace,request,session)==value;checked.add(outcome)
  return value
 module.evaluate=evaluate;return module
d.load=load
with static_contract_memoization_v3():d.main()
out=ROOT/'results/raw/differential/closure20';(out/'acceleration.json').write_text(json.dumps(stats,indent=2)+'\n',encoding='utf-8')

"""Full original differential evaluators; content-keyed backend pure-work reuse."""
from pathlib import Path
import sys,json
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from verification import differential as d
from experiments.static_contract_memoization_v3 import static_contract_memoization_v3
from repro.fingerprint_memo import fingerprint_memo
if __name__=='__main__':
 with static_contract_memoization_v3() as contract,fingerprint_memo() as fingerprint:d.main()
 run=sys.argv[sys.argv.index('--run-id')+1]
 (ROOT/'results/raw/differential'/run/'acceleration.json').write_text(json.dumps({'scope':'Every original I1 and I2 evaluator and backend probe executed; pure backend construction/fingerprint work reused by content','contract':contract,'fingerprint':fingerprint},indent=2)+'\n',encoding='utf-8')

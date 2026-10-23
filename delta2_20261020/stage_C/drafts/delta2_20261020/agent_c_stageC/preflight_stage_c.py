"""Authorized Stage C model discovery, with a plan saved before the request."""
import argparse,hashlib,json,sys
from pathlib import Path
from datetime import datetime,timezone
R=Path(__file__).resolve().parents[3];sys.path.insert(0,str(R))
from stage_c_runner import ledger_state,save,sha
def main():
 p=argparse.ArgumentParser();p.add_argument('--live',action='store_true');a=p.parse_args()
 if not a.live:raise SystemExit('No discovery without --live')
 out=R/'results/raw/delta2/stage_C/preflight'
 if out.exists():raise SystemExit('Existing preflight retained; inspect it instead of overwriting or repeating')
 state=ledger_state();out.mkdir(parents=True)
 context={'starting_event_id':state['last_event_id'],'initial_accounted_usd':state['accounted_usd'],'policy_sha256':state['policy_sha256'],'initial_WP4_remaining_usd':state['WP4_remaining_usd'],'policy':state['policy']}
 save(out/'stage_context.json',context)
 plan={'status':'FROZEN_BEFORE_DISCOVERY','utc':datetime.now(timezone.utc).isoformat(),'endpoint':'GET /models through existing gateway','generation_calls':0,'model_selection_rule':'One currently documented OpenAI flagship and one currently documented small model, accessible to the key; prefer exact dated IDs when available. Verify official pricing/context/output limits before any generation. No fine-tuned or third-party models.','next_step':'Separate frozen C1 request plan before generation; original45 items and baseline arms unchanged.','budget':'Extra USD15 or stricter existing policy; no reallocations.','context_sha256':sha(out/'stage_context.json'),'script_sha256':sha(Path(__file__))}
 save(out/'preflight_plan.json',plan);(out/'preflight_plan.sha256').write_text(sha(out/'preflight_plan.json')+'\n')
 from repro.llm import Gateway
 from repro.budget import Budget
 from importlib import import_module;load_env=import_module('repro'+chr(46)+'env').load_env
 load_env(R);g=Gateway(R,replay=True);g.logs=out/'logs';g.cache=g.logs/'llm_cache';g.budget=Budget(R/'logs/api_budget.sqlite3',max_usd='20');g.replay=False
 assert g.budget.policy()['sha256']==state['policy_sha256']
 try:
  response=g.models(max_attempts=1)
  ids=sorted(x['id'] for x in response['data'] if isinstance(x.get('id'),str) and not x['id'].startswith('ft:'))
  save(out/'accessible_models.json',{'model_ids':ids,'private_finetuned_ids_omitted':sum(str(x.get('id','')).startswith('ft:') for x in response['data']),'scope':'Non-fine-tuned IDs returned by gateway discovery; ownership metadata omitted.'})
  print(json.dumps({'status':'DISCOVERY_COMPLETE','model_ids':ids,'WP4_remaining_usd':ledger_state()['WP4_remaining_usd']}))
 except Exception as exc:
  save(out/'terminal_error.json',{'exception':type(exc).__name__,'code':getattr(exc,'code',None),'generation_calls':0})
  raise SystemExit('Discovery failed; inspect retained sanitized evidence')
if __name__=='__main__':main()

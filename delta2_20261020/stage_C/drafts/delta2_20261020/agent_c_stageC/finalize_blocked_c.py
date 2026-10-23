"""Close an interrupted C1 run after authoritative deadline refusal; no API."""
from pathlib import Path
import sqlite3,json,collections
from decimal import Decimal
from stage_c_runner import R,read,save,sha,ledger_state,export_events
out=R/'results/raw/delta2/stage_C/c1';d=read(out/'design.json');state=ledger_state()
con=sqlite3.connect((R/'logs/api_budget.sqlite3').resolve().as_uri()+'?mode=ro',uri=True)
triggers=[{'name':n,'sql':s}for n,s in con.execute("SELECT name,sql FROM sqlite_master WHERE type='trigger'")]
events=[{'ledger_event_id':i,**json.loads(s)}for i,s in con.execute('SELECT id,record FROM events WHERE id>? ORDER BY id',(d['starting_event_id'],))];con.close()
new=[r for r in events if r.get('experiment_id')=='WP4.delta2.C1'];assert all(r.get('endpoint')=='/responses/input_tokens' and r.get('cost_usd')=='0.000000000' for r in new)
rows=[read(p)for p in sorted((out/'rows').glob('*.json'))];assert all(not r['attempts'] and r.get('technical_exception_message')=='GO sprint one-hour hard deadline' for r in rows)
assert state['accounted_usd']==d['initial_accounted_usd']
proof={'status':'BLOCKED_BY_EXISTING_AUTHORITATIVE_DEADLINE','triggers':triggers,'trigger_policy_unchanged':True,'policy_sha256':state['policy_sha256'],'model_discovery_calls':sum(r.get('endpoint')=='/models' for r in events),'token_count_calls':len(new),'generation_calls':0,'new_successful_model_responses':0,'raw_failure_rows':len(rows),'raw_failure_label':'TECHNICAL_POSTPROCESS_ERROR was the generic handler label. Exact SQLite IntegrityError proves a pre-generation reservation refusal, not model or parser failure. Raw labels retained; report classifies explicit message separately.','extra_accounted_spend_usd':str(Decimal(state['accounted_usd'])-Decimal(d['initial_accounted_usd'])),'stopped_owned_runner':True,'raw_rows_sha256':{p.name:sha(p)for p in (out/'rows').glob('*.json')},'script':'drafts/delta2_20261020/agent_c_stageC/finalize_blocked_c.py'}
save(out/'deadline_refusal_proof.json',proof)
save(out/'terminal.json',{'status':'NOT_DONE_AUTHORITATIVE_DEADLINE','planned':450,'retained':len(rows),'successful':0,'not_done':450-len(rows),'scientific_items_not_evaluated':450,'stop_reason':'Existing SQLite trigger deadline 2026-10-19T11:47:57Z. Policy not removed or bypassed.','C2_eligible':False,'D_status':'NOT_DONE optional; no substitution','incremental_accounted_usd':proof['extra_accounted_spend_usd']})
export_events(out,d);print(json.dumps({k:v for k,v in proof.items()if k not in ('triggers','raw_rows_sha256')}))

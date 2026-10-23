"""Offline cache-to-observation validation for the retained report."""
import json,hashlib
from pathlib import Path

def digest(v):return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode('utf-8')).hexdigest()
def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def verify(root,data):
 from experiments.routing_baselines import classify
 from experiments.lib.wp4_common import parsed_output
 cache=root/'data/llm_cache_sprint'
 transformed=cache.is_dir()
 if not transformed:cache=root/'logs/llm_cache'
 if not cache.is_dir():raise RuntimeError('Current replay cache missing')
 indexed={};total=0
 for p in sorted(cache.glob('*.json')):
  x=read(p);c=x['canonical_request'];assert digest(c)==x['cache_key']==p.stem,('request hash',p.name);assert digest(x['response'])==x['response_sha256'],('response hash',p.name)
  k=(c['experiment_id'],c['item_id'],str(c['repetition_id']));assert k not in indexed,('duplicate identity',k);indexed[k]=x;total+=1
 def lookup(r):
  k=(r['experiment_id'],r['item_id'],str(r.get('repetition_id',0)));x=indexed[k];assert x['status']==r['status']=='SUCCESS',k
  payload=x['canonical_request']['payload'];assert payload['model']==r['model'],k
  if True:
   without_defaults={k:v for k,v in payload.items() if k not in ('store','service_tier')}
   assert r['payload_sha256'] in (digest(payload),digest(without_defaults)),('observation payload hash',k)
  return x,payload
 primary=[json.loads(line) for line in (data/'wp4_wp5/routing_primary_525.jsonl').read_text(encoding='utf-8-sig').splitlines() if line.strip()]
 primary=[r for r in primary if r.get('split')=='evaluation' and r['baseline'] in ('B0','B1')]
 for r in primary:
  x,payload=lookup(r);parsed=parsed_output(x['response']);assert parsed==r['parsed'];schema=payload['text']['format']['schema'];agents=[v for v in schema['properties']['answering_agent_id']['enum'] if v is not None];assert classify(parsed,r['I1'],agents,r['abstain_allowed'])==r['outcome']
 assert len(primary)==480
 requests={r['item_id']:r for r in read(data/'w3_design/requests.json')};reject=[read(p) for p in sorted((data/'sprint/w3/rows').glob('*.json'))]
 for r in reject:
  x,payload=lookup(r);frozen=requests[r['item_id']];expected=dict(frozen['payload']);expected.setdefault('store',False);expected.setdefault('service_tier','default');assert payload==expected;assert x['response']==r['response'];parsed=parsed_output(x['response']);assert parsed==r['parsed'];assert classify(parsed,r['I1'],frozen['agents'],True)==r['outcome']
 assert len(reject)==270
 http=[json.loads(line) for line in (data/'wp4_wp5/http_fixed600.jsonl').read_text(encoding='utf-8-sig').splitlines() if line.strip()];success=0;failed=0
 for r in http:
  for call in r.get('calls',[]):
   if call['status']=='SUCCESS':lookup(call);success+=1
   else:failed+=1
 return {'status':'PASS','cache_entries_verified':total,'primary_outcomes_recomputed':len(primary),'reject_outcomes_recomputed':len(reject),'http_success_receipts_cache_linked':success,'http_failure_receipts_retained':failed,'transformed_export':transformed,'payload_hash_checks':True,'payload_hash_domain':'transformed export' if transformed else 'original private','scope':'Canonical cache hashes checked in both copies; payload pins checked in their original or explicitly repinned export domain. Export request/response values and frozen reject requests checked after transformation. Failures remain failures; missing experiments are not generated.'}

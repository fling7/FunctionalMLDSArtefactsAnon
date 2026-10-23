"""Offline local token sizing only. Never sends room inputs or generates answers."""
import itertools,json,sys,copy,importlib.metadata
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from experiments.lib.wp4_common import *
from experiments.routing_baselines import router_payload
from experiments.guarded_llm_turns import ExperimentalClient
from experiments.lib.backend_driver import Driver
from backend.roomcontract_v2_runtime import load_project_contract
import tiktoken
# May download only the public tokenizer vocabulary on first use. No room input
# is passed to a network function; encode() runs locally after loading vocabulary.
os.environ['TIKTOKEN_CACHE_DIR']=str(ROOT/'.tmp/wp4-token-cache')
encoding=tiktoken.get_encoding('o200k_base')
out=ROOT/'results/raw'/('wp4_token_preflight_local_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S'));out.mkdir(parents=True,exist_ok=False)
manifest=read_json(ROOT/'results/processed/wp5_projects.json');eligible=[r for r in manifest['rows'] if r['eligible_native_success']];rows=[]
def measure(payload,metadata):
 text='\n'.join(m['content'] for m in payload['input']);rows.append({**metadata,'text_only_tokens':len(encoding.encode(text)),'serialized_payload_tokens':len(encoding.encode(json.dumps(payload,ensure_ascii=False,separators=(',',':')))),'payload_sha256':hashlib.sha256(canonical_bytes(payload)).hexdigest()})
class CaptureStop(Exception):pass
class CaptureOnly:
 def responses(self,payload,**kwargs):self.payload=payload;raise CaptureStop()
for source in eligible:
 print('Local sizing '+source['source_room_id'],flush=True)
 project=ROOT/source['project_path'];contract=load_project_contract(project);room={'instance':contract['instance'],'agent_profiles':profiles(project)};target=next(x for x in contract['instance']['objects'] if x.get('entityRole')=='sceneObject');pair={'target':target,'start_agent':room['agent_profiles'][0]['id']}
 for model,baseline,abstain,phrasing in itertools.product(MODELS,('B0','B1'),(False,True),(1,2,3)):
  payload=router_payload(room,pair,'What can you tell me about this selected object?',baseline,abstain,phrasing,model)
  measure(payload,{'source_room_id':source['source_room_id'],'kind':baseline,'model':model,'abstain':abstain,'phrasing':phrasing})
 capture=CaptureOnly();client=ExperimentalClient(capture);driver=Driver(project,client=client)
 try:
  for agent in [x for x in contract['instance']['objects'] if x.get('type')=='Agent']:
   owned=next((x for x in driver.targets if x['id'] in agent.get('groundedAsset',[])),None)
   if owned is None:continue
   for model,channel in itertools.product(MODELS,('constrained','fallback')):
    client.configure({'model':model,'channel':channel,'temperature':.3,'identity':'local.token.capture','agents':room['agent_profiles']})
    try:driver.store.chat(driver.request(agent['sourceAgentId'],owned))
    except CaptureStop:measure(capture.payload,{'source_room_id':source['source_room_id'],'kind':'HTTP_'+channel,'model':model,'provider':agent['sourceAgentId']})
 finally:driver.close()
write_json(out/'rows.json',rows)
summary={}
for kind in sorted({r['kind'] for r in rows}):
 counts=[r['serialized_payload_tokens'] for r in rows if r['kind']==kind];summary[kind]={'requests':len(counts),'minimum':min(counts),'maximum':max(counts),'over3000':sum(n>3000 for n in counts),'over4000':sum(n>4000 for n in counts)}
write_json(out/'metadata.json',{'purpose':'Local tokenizer sizing before freeze, not model evaluation','tokenizer':'tiktoken','version':importlib.metadata.version('tiktoken'),'encoding':'o200k_base','provider_counts':False,'caveat':'Local text and serialized request tokenization; provider message framing and structured-schema conversion are not reproduced. Not a hard API input bound.','sources':eligible,'source_sha256':{n:digest(ROOT/n) for n in ['experiments/wp4_token_preflight.py','experiments/routing_baselines.py','experiments/lib/wp4_common.py','experiments/guarded_llm_turns.py']}})
write_json(out/'summary.json',summary);print(json.dumps(summary))

"""Real SessionStore driver. ScriptedClient is ONLY for unit/stress tests."""
from __future__ import annotations
import copy, contextlib, io, json, shutil, sys, tempfile, time, urllib.request, urllib.error
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
BACKEND=ROOT/'app/backend_root/agent_backend'
sys.path.insert(0,str(BACKEND))
from backend.state import SessionStore
from backend.kb import KnowledgeBase
from backend.projects import ProjectManager
from backend.roomcontract_v2_runtime import load_project_contract

class ScriptedClient:
    api_key=''
    def __init__(self, proposal=None, latency=0.0, fallback=False):
        self.calls=0; self.proposal=proposal; self.latency=latency; self.fallback=fallback
    def create_structured_json(self, **kwargs):
        if self.fallback:
            from backend.openai_client import OpenAIHTTPError
            raise OpenAIHTTPError(400,'Unit-test fallback trigger')
        return self.create_json_object(**kwargs)
    def create_json_object(self, **kwargs):
        self.calls+=1
        if self.latency: time.sleep(self.latency)
        answer={'say':'Unit-test scripted answer.','handoff_to':self.proposal,'handoff_reason':None,'handoff_brief':None,'confidence':1.0}
        return answer,{'id':'unit-test-stub','usage':{'input_tokens':0,'output_tokens':0}},json.dumps(answer)

class Driver:
    def __init__(self, project=None, client=None):
        self.temp=tempfile.TemporaryDirectory(prefix='room-contract-')
        self.projects=Path(self.temp.name)/'projects'; self.projects.mkdir()
        source=Path(project or BACKEND/'projects/classroom_dinosaur')
        self.project=self.projects/source.name
        shutil.copytree(source,self.project,ignore=shutil.ignore_patterns('runtime*.jsonl','*.log','__pycache__'))
        self.client=client or ScriptedClient()
        with contextlib.redirect_stdout(io.StringIO()):
            pm=ProjectManager(self.projects,BACKEND/'examples/room_plan.example.json',BACKEND/'examples/agents.example.json')
            self.store=SessionStore(max_history_turns=8,max_handoffs=1,kb=KnowledgeBase(self.project/'kb'),kb_max_snippets=4,model='unit-test-scripted',temperature=0.3,stt_model='',stt_language='',stt_max_audio_bytes=1,openai=self.client,project_manager=pm)
            self.setup=self.store.setup_from_request({'project_id':source.name,'session_id':'regression'})
        self.session=self.store.sessions[self.setup['session_id']]
        self.contract=load_project_contract(self.project)
    def request(self, agent, target, variant='normal'):
        spatial={'model_sha256':self.setup['model_sha256'],'state':'resolved','entity_id':target['id'],'source_object_id':target['sourceId'],'hit_position':{'x':0,'y':0,'z':0},'distance_m':1,'selection_modality':'programmatic'}
        if variant=='stale_digest': spatial['model_sha256']='0'*64
        if variant=='unknown_entity': spatial['entity_id']='UNKNOWN'
        if variant=='mismatch_source':
            other=next(x for x in self.targets if x['id']!=target['id']);spatial['source_object_id']=other['sourceId']
        if variant in {'none','ambiguous'}: spatial['state']=variant
        if variant=='ambiguity_flag': spatial['ambiguous']=True
        if variant=='candidate_conflict': spatial['candidate_entity_ids']=[next(x['id'] for x in self.targets if x['id']!=target['id'])]
        return {'session_id':self.setup['session_id'],'active_agent_id':agent,'user_text':'Describe this object.','interaction_mode':'deictic','spatial_context':spatial}
    @property
    def targets(self):
        return [x for x in self.contract['instance']['objects'] if x.get('entityRole')=='sceneObject']
    def probe(self,request):
        snapshot=self.store.snapshot_session_mutation(self.session.session_id)
        before=json.dumps(snapshot,sort_keys=True,default=str); calls=self.client.calls
        try:
            output=self.store.chat(request,include_runtime_actions=True)
            action=output['_roomcontract_runtime_actions']['chat'].get('runtime_action_id')
            result={'decision':'ANSWER_LOCAL' if output['active_agent_id']==request['active_agent_id'] else 'ANSWER_AFTER_HANDOFF','reason':None,'provider':output['active_agent_id'],'action':action}
        except Exception as e:
            result={'decision':'REJECT','reason':getattr(e,'code',None),'provider':None,'action':None,'exception_type':type(e).__name__,'message':str(e)}
        result['model_calls']=self.client.calls-calls
        result['unchanged_before_restore']=before==json.dumps(self.store.snapshot_session_mutation(self.session.session_id),sort_keys=True,default=str)
        self.store.restore_session_mutation(self.session.session_id,snapshot)
        return result
    def close(self): self.temp.cleanup()

def http_json(base_url,path,payload):
    req=urllib.request.Request(base_url.rstrip('/')+path,data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'},method='POST')
    try:
        with urllib.request.urlopen(req,timeout=120) as response:
            return response.status,json.load(response)
    except urllib.error.HTTPError as e:
        return e.code,json.loads(e.read())

VARIANTS=('normal','stale_digest','unknown_entity','mismatch_source','none','ambiguous','ambiguity_flag','candidate_conflict')

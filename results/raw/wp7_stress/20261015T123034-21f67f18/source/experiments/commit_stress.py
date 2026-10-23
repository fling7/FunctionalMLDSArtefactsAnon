"""Real SessionStore plus production logger, with 50 in-flight scripted calls.

Process cells use five OS processes, each with ten independent session threads.
A barrier starts the publisher only after every session enters its scripted model
call. This is a deliberately stressful workload, not a deployment frequency.
"""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor
import contextlib
import io
import hashlib
import json
import multiprocessing as mp
from pathlib import Path
import random
import shutil
import sys
import threading
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from experiments.lib.wp7_common import ROOT,BACKEND,start_run,finish_run,write_json
from experiments.lib.backend_driver import ScriptedClient
from backend.state import SessionStore
from backend.kb import KnowledgeBase
from backend.projects import ProjectManager
from backend.guard_config import GuardConfig
from backend.roomcontract_v2_runtime import load_project_contract
from backend.runtime_trace import contract_commit_fingerprint,contract_runtime_fingerprint,log_backend_events
from backend.publication import collect_projection_bytes,publish_project,publication_generation,load_consistent_contract,read_evidence_pair
from tools.routing_verifier import verify_routing


class BarrierClient(ScriptedClient):
    def __init__(self,barrier,delay):
        super().__init__();self.barrier=barrier;self.delay=delay;self.generation_ms=0.
    def create_json_object(self,**kwargs):
        self.barrier.wait(timeout=120)
        start=time.perf_counter();time.sleep(self.delay)
        result=super().create_json_object(**kwargs)
        self.generation_ms=(time.perf_counter()-start)*1000
        return result


def create_store(project,protocol,scope,client):
    with contextlib.redirect_stdout(io.StringIO()):
        pm=ProjectManager(project.parent,BACKEND/'examples/room_plan.example.json',BACKEND/'examples/agents.example.json')
    return SessionStore(max_history_turns=8,max_handoffs=1,kb=KnowledgeBase(project/'kb'),kb_max_snippets=4,model='wp7-scripted',temperature=.3,stt_model='',stt_language='',stt_max_audio_bytes=1,openai=client,project_manager=pm,guard_config=GuardConfig(publication_protocol=protocol,commit_variant=scope))


def session_turn(project,protocol,scope,index,barrier,delay):
    project=Path(project);client=BarrierClient(barrier,delay);store=create_store(project,protocol,scope,client)
    setup=store.setup_from_request({'project_id':project.name,'session_id':'stress-'+str(index)})
    st=store.sessions[setup['session_id']]
    contract=load_project_contract(project,publication_protocol=protocol)
    table=verify_routing(contract['instance'],contract['trace'],model_sha256=contract['model_sha256'])['routing_table']
    agent,target=next((a,t) for a,v in table.items() for t,r in v.items() if r['decision']=='ANSWER_LOCAL')
    entity=next(o for o in contract['instance']['objects'] if o['id']==target)
    request={'session_id':st.session_id,'active_agent_id':agent,'user_text':'Describe this object.','interaction_mode':'deictic','spatial_context':{'model_sha256':setup['model_sha256'],'state':'resolved','entity_id':target,'source_object_id':entity['sourceId'],'hit_position':{'x':0,'y':0,'z':0},'distance_m':1,'selection_modality':'programmatic'}}
    snap=store.snapshot_session_mutation(st.session_id);started=time.perf_counter();observed={};code=None;events=[]
    def hook(phase):
        if phase=='after_contract_check':observed['check_generation']=publication_generation(project)
        elif phase in ('before_journal_clear','after_packet_append'):
            try:
                marker=json.loads((project/'.publication.json').read_text(encoding='utf-8'))
                observed['append_generation']=marker['generation']
                observed['append_manifest_consistent']=all(hashlib.sha256((project/name).read_bytes()).hexdigest()==digest for name,digest in marker['files'].items())
                observed['append_manifest_generation_after']=publication_generation(project)
            except Exception as exc:
                # Instrumentation must not turn a completed packet append into
                # an abort when its unlocked observation races a replacement.
                observed['append_monitor_error']=type(exc).__name__
                observed.setdefault('append_manifest_consistent',None)
    try:
        output=store.chat(request,include_runtime_actions=True)
        action=output['_roomcontract_runtime_actions']['chat']
        events=log_backend_events(project_manager=store.project_manager,project_id=project.name,
            entries=[{'action_kind':'chat','event_type':'wp7_stress','session_id':st.session_id,'expected_action':action}],
            expected_contract_fingerprint=contract_commit_fingerprint(contract,scope,project_dir=project),publication_protocol=protocol,
            expected_publication_generation=contract.get('publication_generation'),commit_variant=scope,pinned_contract=contract,fault_hook=hook)
        outcome='committed'
    except Exception as exc:
        store.restore_session_mutation(st.session_id,snap)
        outcome='aborted';code=getattr(exc,'code',type(exc).__name__)
    return {'session':index,'protocol':protocol,'scope':scope,'outcome':outcome,'code':code,'event_ids':[e['event_id'] for e in events],'model_calls':client.calls,'scripted_latency_ms':delay*1000,'generation_elapsed_ms':client.generation_ms,'elapsed_ms':(time.perf_counter()-started)*1000,'snapshot_restored':snap==store.snapshot_session_mutation(st.session_id),'pin_generation':contract.get('publication_generation',1),**observed}


def process_worker(project,protocol,scope,indices,barrier,delays,queue):
    try:
        with ThreadPoolExecutor(max_workers=len(indices)) as pool:
            futures=[pool.submit(session_turn,project,protocol,scope,i,barrier,delays[i]) for i in indices]
            for future in futures:queue.put({'row':future.result()})
    except BaseException as exc:queue.put({'error':repr(exc)})


def prepare(root):
    project=root/'classroom_dinosaur'
    shutil.copytree(BACKEND/'projects/classroom_dinosaur',project,ignore=shutil.ignore_patterns('runtime_logs','__pycache__'))
    meta=json.loads((project/'project.json').read_text());meta['roomcontract_trace_path']='roomcontract.v2.instance.json'
    (project/'project.json').write_text(json.dumps(meta),encoding='utf-8')
    publish_project(project,collect_projection_bytes(project),validate=load_project_contract)
    return project


def run_cell(root,mode,protocol,scope):
    project=prepare(root/(mode+'_'+protocol+'_'+scope));rng=random.Random(20261015)
    delays=[rng.uniform(.010,.050) for _ in range(50)]
    intervals=[rng.uniform(.005,.015) for _ in range(5)]
    publications=[];rows=[]
    if mode=='threads':
        barrier=threading.Barrier(51)
        executor=ThreadPoolExecutor(max_workers=50)
        futures=[executor.submit(session_turn,project,protocol,scope,i,barrier,delays[i]) for i in range(50)]
    else:
        ctx=mp.get_context('spawn');barrier=ctx.Barrier(51);queue=ctx.Queue()
        workers=[ctx.Process(target=process_worker,args=(str(project),protocol,scope,list(range(p*10,p*10+10)),barrier,delays,queue)) for p in range(5)]
        for worker in workers:worker.start()
    barrier.wait(timeout=120)
    publication_start=time.perf_counter()
    files=collect_projection_bytes(project)
    for revision,delay in enumerate(intervals,start=1):
        time.sleep(delay)
        trace=json.loads(files['trace_map.v2.json']);trace['wp7_revision']=revision
        files['trace_map.v2.json']=json.dumps(trace,sort_keys=True).encode()
        start=time.perf_counter();marker=publish_project(project,files,validate=load_project_contract)
        publications.append({'revision':revision,'generation':marker['generation'],'elapsed_since_storm_ms':(time.perf_counter()-publication_start)*1000,'publish_ms':(time.perf_counter()-start)*1000,'routing_change':False,'edit':'trace descriptive top-level revision'})
    if mode=='threads':
        rows=[f.result() for f in futures];executor.shutdown()
    else:
        while len(rows)<50:
            item=queue.get(timeout=120)
            if 'error' in item:raise RuntimeError(item['error'])
            rows.append(item['row'])
        for worker in workers:
            worker.join(30)
            if worker.exitcode!=0:raise RuntimeError('stress child failed')
    for row in rows:row['execution']=mode
    evpath=project/'runtime_logs/events.jsonl';vapath=evpath.with_name('runtime_validation.v2.jsonl')
    if protocol=='cooperative':events,validations=read_evidence_pair(project,evpath,vapath)
    else:
        events=[json.loads(x) for x in evpath.read_text().splitlines()] if evpath.exists() else []
        validations=[json.loads(x) for x in vapath.read_text().splitlines()] if vapath.exists() else []
    event_ids={e['event_id'] for e in events}
    validation_ids={r['runtimeValidationLog']['id'].removesuffix('-LOG') for r in validations}
    # Re-pin after storm measures adoption of this complete current publication.
    adopt_start=time.perf_counter();adopt_store=create_store(project,protocol,scope,ScriptedClient())
    adopted=adopt_store.setup_from_request({'project_id':project.name,'session_id':'adopt'})
    cell={'execution':mode,'protocol':protocol,'scope':scope,'sessions':len(rows),'committed':sum(r['outcome']=='committed' for r in rows),'aborted':sum(r['outcome']=='aborted' for r in rows),'model_calls':sum(r['model_calls'] for r in rows),'generation_check_append_mismatches':sum(r['outcome']=='committed' and r.get('check_generation')!=r.get('append_generation') for r in rows),'torn_reads_accepted':sum(r['outcome']=='committed' and r.get('append_manifest_consistent') is False for r in rows),'torn_read_measurement':'independent manifest-byte hash monitor at append under project lock in cooperative mode; packet observer can race with publication','paired_ids':event_ids==validation_ids,'events':len(events),'validation_records':len(validations),'wasted_generation_ms':sum(r['generation_elapsed_ms'] for r in rows if r['outcome']=='aborted'),'adopt_ms':(time.perf_counter()-adopt_start)*1000,'adopted':bool(adopted.get('session_id')),'publications':publications,'rows':rows}
    write_json(root/(mode+'_'+protocol+'_'+scope+'.json'),cell)
    return cell


def controlled_races(root):
    rows=[]
    for mode in ('packet','cooperative','uncooperative'):
        project=prepare(root/('forced_'+mode));protocol='packet' if mode=='packet' else 'cooperative'
        contract=load_project_contract(project,publication_protocol=protocol)
        action=next(x for x in contract['runtime_context']['runtime_actions'] if x['action_kind']=='setup')
        pm=type('Manager',(),{'root':project.parent})()
        files=collect_projection_bytes(project);trace=json.loads(files['trace_map.v2.json']);trace['wp7_revision']='changed';files['trace_map.v2.json']=json.dumps(trace).encode()
        publisher=None;started=threading.Event();done=threading.Event();observed={}
        def publish():started.set();publish_project(project,files,validate=load_project_contract);done.set()
        def hook(phase):
            nonlocal publisher
            if phase=='after_contract_check':
                observed['check_generation']=publication_generation(project)
                if mode=='packet':publish()
                elif mode=='uncooperative':(project/'trace_map.v2.json').write_bytes(files['trace_map.v2.json'])
                else:
                    publisher=threading.Thread(target=publish);publisher.start();started.wait(1)
                    observed['publisher_blocked']=not done.wait(.025)
            elif phase in ('before_journal_clear','after_packet_append'):
                observed['append_generation']=publication_generation(project)
                observed['raw_trace_changed_at_append']=(project/'trace_map.v2.json').read_bytes()==files['trace_map.v2.json']
        events=log_backend_events(project_manager=pm,project_id=project.name,entries=[{'action_kind':'setup','event_type':'forced_race','expected_action':action}],expected_contract_fingerprint=contract_runtime_fingerprint(contract),publication_protocol=protocol,expected_publication_generation=contract.get('publication_generation'),fault_hook=hook)
        if publisher:publisher.join(10)
        next_refused=False
        try:load_project_contract(project,publication_protocol=protocol)
        except Exception:next_refused=True
        rows.append({'mode':mode,'committed':len(events),'next_snapshot_refused':next_refused,**observed})
    write_json(root/'controlled_races.json',rows)
    return rows


def main():
    root=start_run('stress',['experiments/commit_stress.py','experiments/lib/wp7_common.py'])
    cells=[]
    for mode in ('threads','processes'):
        for protocol in ('packet','cooperative'):
            for scope in ('full','slice'):
                cells.append(run_cell(root,mode,protocol,scope))
    races=controlled_races(root)
    finish_run(root,{'cells':len(cells),'sessions':sum(c['sessions'] for c in cells),'committed':sum(c['committed'] for c in cells),'aborted':sum(c['aborted'] for c in cells),'cooperative_generation_mismatches':sum(c['generation_check_append_mismatches'] for c in cells if c['protocol']=='cooperative'),'cooperative_torn_reads_accepted':sum(c['torn_reads_accepted'] for c in cells if c['protocol']=='cooperative'),'paired_all_cells':all(c['paired_ids'] for c in cells),'cell_summaries':[{k:v for k,v in c.items() if k not in ('rows','publications')} for c in cells],'controlled_races':races,'limits':'scripted latency; explicit-state proof does not imply implementation proof; strict cooperative generation abort applies even for unchanged routing slice'})

if __name__=='__main__':main()

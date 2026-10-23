"""WP7 deterministic append/process-kill, partial-publication and rollback probes."""
from __future__ import annotations
import argparse
import contextlib
import io
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from experiments.lib.wp7_common import ROOT,BACKEND,start_run,finish_run,write_json
from experiments.lib.backend_driver import Driver
from backend.publication import APPEND_PHASES,MARKER,append_evidence_pair,collect_projection_bytes,load_consistent_contract,publish_project,read_evidence_pair,read_publication,recover_evidence
from backend.roomcontract_v2_runtime import load_project_contract
from backend.runtime_trace import contract_runtime_fingerprint,log_backend_events


def emit(root,row):
    with (root/'rows.jsonl').open('a',encoding='utf-8') as out:out.write(json.dumps(row,sort_keys=True)+'\n')
    return row


def paths(root):
    event=root/'runtime_logs/events.jsonl'
    return event,event.with_name('runtime_validation.v2.jsonl')


def append(root,identifier,hook=None):
    event,validation=paths(root)
    payload=(json.dumps({'id':identifier,'text':'partial UTF-8 payload: café'},ensure_ascii=False)+'\n').encode()
    append_evidence_pair(root,event,payload,validation,payload,fault_hook=hook)


def kill_worker(root,phase):
    def pause(actual):
        if actual==phase:
            write_json(root/'fault-ready.json',{'phase':actual,'pid':os.getpid()})
            while True:time.sleep(.01)
    append(root,'new',pause)


def faults(root):
    rows=[]
    for mode in ('exception','process_kill'):
        for phase in APPEND_PHASES:
            cell=root/'evidence'/mode/phase;cell.mkdir(parents=True)
            append(cell,'baseline')
            error=None;exitcode=None
            if mode=='exception':
                def fail(actual):
                    if actual==phase:raise OSError('preregistered append exception')
                try:append(cell,'new',fail)
                except Exception as exc:error=getattr(exc,'code',type(exc).__name__)
            else:
                process=subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'--kill-worker',str(cell),phase],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
                deadline=time.monotonic()+20
                while not (cell/'fault-ready.json').exists() and process.poll() is None and time.monotonic()<deadline:time.sleep(.01)
                if not (cell/'fault-ready.json').exists():
                    process.kill();stdout,stderr=process.communicate();raise RuntimeError('Kill worker did not reach phase: '+stderr.decode(errors='replace'))
                process.kill();process.communicate(timeout=10);exitcode=process.returncode
            before={p.name:p.stat().st_size for p in paths(cell)}
            recovered=recover_evidence(cell)
            ev,va=read_evidence_pair(cell,*paths(cell))
            rows.append(emit(root,{'experiment':'append_fault','mode':mode,'phase':phase,'error_code':error,'exitcode':exitcode,'sizes_before_recovery':before,'recovered':recovered,'parseable':True,'paired':ev==va,'new_present':any(x['id']=='new' for x in ev),'records':len(ev)}))
    return rows


def partial_publications(root):
    rows=[]
    with Driver() if False else contextlib.nullcontext() as _:
        d=Driver()
        try:
            base=collect_projection_bytes(d.project)
            # Explicit placement projection is deployment-only in this experiment.
            base['placement.json']=b'{"revision":0}'
            sequence=['roomcontract.v2.instance.json','trace_map.v2.json','agents.json','project.json','placement.json']
            changed=dict(base)
            for name in sequence:
                # JSON whitespace changes bytes without changing validation semantics.
                changed[name]=base[name]+b'\n'
            digest=hashlib.sha256(changed['roomcontract.v2.instance.json'].replace(b'\r\n',b'\n')).hexdigest().upper()
            trace=json.loads(changed['trace_map.v2.json']);trace['model_sha256']=digest
            changed['trace_map.v2.json']=json.dumps(trace).encode()
            meta=json.loads(changed['project.json']);meta['roomcontract_model_sha256']=digest
            changed['project.json']=json.dumps(meta).encode()
            for prefix in range(len(sequence)+2):
                cell=root/'publication_prefix'/str(prefix)/d.project.name
                cell.mkdir(parents=True)
                publish_project(cell,base,validate=load_project_contract)
                for name in sequence[:min(prefix,len(sequence))]:
                    (cell/name).write_bytes(changed[name])
                if prefix==len(sequence)+1:
                    publish_project(cell,changed,validate=load_project_contract)
                started=time.perf_counter()
                try:
                    loaded=load_consistent_contract(cell,load_project_contract)
                    outcome='loaded';code=None;generation=loaded['publication_generation']
                except Exception as exc:
                    outcome='refused';code=getattr(exc,'code',type(exc).__name__);generation=None
                rows.append(emit(root,{'experiment':'publication_prefix','prefix':prefix,'writes':sequence[:min(prefix,len(sequence))],'marker_flipped':prefix==len(sequence)+1,'outcome':outcome,'code':code,'generation':generation,'load_ms':(time.perf_counter()-started)*1000}))
        finally:d.close()
    return rows


def make_entry(contract):
    action=next(a for a in contract['runtime_context']['runtime_actions'] if a['action_kind']=='setup')
    return {'action_kind':'setup','event_type':'wp7_fault_probe','session_id':'fault-probe','expected_action':action}


def session_rollback_and_effects(root):
    rows=[]
    for ordering in ('before_commit','after_commit_abort','after_commit_success'):
        d=Driver()
        try:
            publish_project(d.project,collect_projection_bytes(d.project),validate=load_project_contract)
            contract=load_consistent_contract(d.project,load_project_contract)
            snapshot=d.store.snapshot_session_mutation(d.session.session_id)
            d.session.history.append({'role':'assistant','content':'uncommitted mutation'})
            sink=root/('sink_'+ordering+'.jsonl')
            effect=lambda: sink.write_text('{"effect":"increment"}\n',encoding='utf-8')
            if ordering=='before_commit':effect()
            expected=contract_runtime_fingerprint(contract) if ordering=='after_commit_success' else 'WRONG-PIN'
            try:
                log_backend_events(project_manager=d.store.project_manager,project_id=d.project.name,entries=[make_entry(contract)],expected_contract_fingerprint=expected,publication_protocol='cooperative',expected_publication_generation=contract['publication_generation'])
                if ordering=='after_commit_success':effect()
                outcome='committed'
            except Exception as exc:
                d.store.restore_session_mutation(d.session.session_id,snapshot)
                outcome=getattr(exc,'code',type(exc).__name__)
            rows.append(emit(root,{'experiment':'external_effect','ordering':ordering,'outcome':outcome,'sink_effects':len(sink.read_text().splitlines()) if sink.exists() else 0,'snapshot_restored':snapshot==d.store.snapshot_session_mutation(d.session.session_id)}))
        finally:d.close()
    # Actual restore method with one-shot injected failures around each assignment.
    d=Driver()
    try:
        fields=('history','agent_histories','updated_ms','server_active_agent_id')
        snapshot=d.store.snapshot_session_mutation(d.session.session_id)
        for field in fields:
            if not hasattr(d.session,field):continue
            for moment in ('before','after'):
                st=d.session
                st.history=[{'role':'user','content':'mutated'}];st.agent_histories={'other':[{'role':'user','content':'mutated'}]};st.updated_ms=snapshot['updated_ms']+1
                if hasattr(st,'server_active_agent_id'):st.server_active_agent_id='mutated'
                class Proxy:
                    def __init__(self):object.__setattr__(self,'fired',False)
                    def __getattr__(self,name):return getattr(st,name)
                    def __setattr__(self,name,value):
                        fail=name==field and not self.fired
                        if fail and moment=='before':object.__setattr__(self,'fired',True);raise OSError('restore before '+field)
                        setattr(st,name,value)
                        if fail and moment=='after':object.__setattr__(self,'fired',True);raise OSError('restore after '+field)
                proxy=Proxy();d.store.sessions[st.session_id]=proxy
                error=None
                try:d.store.restore_session_mutation(st.session_id,snapshot)
                except Exception as exc:error=type(exc).__name__
                first=snapshot==d.store.snapshot_session_mutation(st.session_id)
                d.store.restore_session_mutation(st.session_id,snapshot)
                repaired=snapshot==d.store.snapshot_session_mutation(st.session_id)
                d.store.sessions[st.session_id]=st
                rows.append(emit(root,{'experiment':'restore_fault','field':field,'moment':moment,'exception':error,'complete_after_fault':first,'complete_after_retry':repaired,'fault_triggered':proxy.fired,'scope':'actual restore assignments; in-memory store is not crash durable'}))
    finally:d.close()
    # Real generated chat followed by each failing evidence phase and server-style restore.
    for phase in APPEND_PHASES[:-1]:
        d=Driver()
        try:
            publish_project(d.project,collect_projection_bytes(d.project),validate=load_project_contract)
            contract=load_consistent_contract(d.project,load_project_contract)
            from tools.routing_verifier import verify_routing
            table=verify_routing(contract['instance'],contract['trace'],model_sha256=contract['model_sha256'])['routing_table']
            agent,target=next((a,t) for a,v in table.items() for t,r in v.items() if r['decision']=='ANSWER_LOCAL')
            obj=next(t for t in d.targets if t['id']==target)
            snap=d.store.snapshot_session_mutation(d.session.session_id)
            output=d.store.chat(d.request(agent,obj),include_runtime_actions=True)
            action=output['_roomcontract_runtime_actions']['chat']
            def fail(actual):
                if actual==phase:raise OSError('injected evidence exception')
            try:log_backend_events(project_manager=d.store.project_manager,project_id=d.project.name,entries=[{'action_kind':'chat','event_type':'chat','expected_action':action}],expected_contract_fingerprint=contract_runtime_fingerprint(contract),publication_protocol='cooperative',expected_publication_generation=contract['publication_generation'],fault_hook=fail)
            except Exception as exc:
                d.store.restore_session_mutation(d.session.session_id,snap)
                code=getattr(exc,'code',type(exc).__name__)
            ev,va=read_evidence_pair(d.project,*paths(d.project))
            rows.append(emit(root,{'experiment':'session_append_fault','phase':phase,'code':code,'model_calls':d.client.calls,'snapshot_restored':snap==d.store.snapshot_session_mutation(d.session.session_id),'event_records':len(ev),'validation_records':len(va)}))
        finally:d.close()
    return rows


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--kill-worker',nargs=2);args=parser.parse_args()
    if args.kill_worker:return kill_worker(Path(args.kill_worker[0]),args.kill_worker[1])
    root=start_run('faults',['experiments/commit_faults.py','experiments/lib/wp7_common.py'])
    rows=faults(root)+partial_publications(root)+session_rollback_and_effects(root)
    finish_run(root,{'rows':len(rows),'append_fault_cells':sum(r['experiment']=='append_fault' for r in rows),'unpaired_cells':sum(r.get('paired') is False for r in rows),'publication_prefix_cells':sum(r['experiment']=='publication_prefix' for r in rows),'restore_partial_after_fault':sum(r['experiment']=='restore_fault' and not r['complete_after_fault'] for r in rows),'restore_retry_failures':sum(r['experiment']=='restore_fault' and not r['complete_after_retry'] for r in rows),'session_rollback_failures':sum(r['experiment']=='session_append_fault' and not r['snapshot_restored'] for r in rows),'results':rows})

if __name__=='__main__':main()

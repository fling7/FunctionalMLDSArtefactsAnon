"""Post-fix actual SessionStore restoration fault probes, preserving old raw run."""
from pathlib import Path
import copy
import json
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from experiments.lib.wp7_common import start_run,finish_run
from experiments.lib.backend_driver import Driver


def main():
    root=start_run('restore_atomic',['experiments/commit_restore_faults.py'])
    rows=[]
    for phase in ('prepare_copy_1','prepare_copy_2','before_swap','after_swap'):
        d=Driver()
        try:
            st=d.session;snapshot=d.store.snapshot_session_mutation(st.session_id)
            st.history=[{'role':'user','content':'mutated'}];st.agent_histories={'other':[]};st.updated_ms=snapshot['updated_ms']+1
            if hasattr(st,'server_active_agent_id'):st.server_active_agent_id='mutated'
            before=d.store.snapshot_session_mutation(st.session_id)
            identity=id(st);cls=type(st);original_setattr=cls.__setattr__;original_deepcopy=copy.deepcopy
            calls=[0];fired=[False]
            def fail_copy(obj,*args,**kwargs):
                calls[0]+=1
                if phase=='prepare_copy_'+str(calls[0]):fired[0]=True;raise MemoryError('injected preparation failure')
                return original_deepcopy(obj,*args,**kwargs)
            def fail_swap(self,name,value):
                target=self is st and name=='__dict__'
                if target and phase=='before_swap':fired[0]=True;raise OSError('injected before swap')
                original_setattr(self,name,value)
                if target and phase=='after_swap':fired[0]=True;raise OSError('injected after swap')
            copy.deepcopy=fail_copy;cls.__setattr__=fail_swap;error=None
            try:d.store.restore_session_mutation(st.session_id,snapshot)
            except Exception as exc:error=type(exc).__name__
            finally:copy.deepcopy=original_deepcopy;cls.__setattr__=original_setattr
            actual=d.store.snapshot_session_mutation(st.session_id)
            d.store.restore_session_mutation(st.session_id,snapshot)
            row={'phase':phase,'fault_triggered':fired[0],'exception':error,'atomic_before_or_restored':actual in (before,snapshot),'restored_after_fault':actual==snapshot,'restored_after_retry':d.store.snapshot_session_mutation(st.session_id)==snapshot,'object_identity_preserved':id(d.store.sessions[st.session_id])==identity}
            rows.append(row)
            with (root/'rows.jsonl').open('a',encoding='utf-8') as out:out.write(json.dumps(row)+'\n')
        finally:d.close()
    finish_run(root,{'cells':len(rows),'atomic_cells':sum(r['atomic_before_or_restored'] for r in rows),'all_faults_triggered':all(r['fault_triggered'] for r in rows),'retry_successes':sum(r['restored_after_retry'] for r in rows),'rows':rows,'limits':'Process death still destroys the in-memory store. Python attribute-dictionary replacement assumes cooperating threads and the per-session lock.'})

if __name__=='__main__':main()

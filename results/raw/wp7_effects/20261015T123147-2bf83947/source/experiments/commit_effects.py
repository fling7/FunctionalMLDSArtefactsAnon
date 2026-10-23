"""Non-idempotent local sink: conversation rollback does not undo appends."""
from pathlib import Path
import json
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from experiments.lib.wp7_common import start_run,finish_run
from experiments.lib.backend_driver import Driver
from backend.publication import publish_project,collect_projection_bytes,load_consistent_contract
from backend.roomcontract_v2_runtime import load_project_contract
from backend.runtime_trace import log_backend_events,contract_runtime_fingerprint


def main():
    root=start_run('effects',['experiments/commit_effects.py']);rows=[]
    for mode in ('before_commit_abort','after_commit_abort','after_commit_success','after_commit_duplicate_delivery'):
        d=Driver()
        try:
            publish_project(d.project,collect_projection_bytes(d.project),validate=load_project_contract)
            contract=load_consistent_contract(d.project,load_project_contract)
            action=next(a for a in contract['runtime_context']['runtime_actions'] if a['action_kind']=='setup')
            snapshot=d.store.snapshot_session_mutation(d.session.session_id)
            d.session.history.append({'role':'assistant','content':'uncommitted side-effect probe'})
            sink=root/(mode+'.jsonl')
            def increment():
                with sink.open('a',encoding='utf-8') as out:out.write('{"increment":1}\n')
            if mode=='before_commit_abort':increment()
            commit=mode in ('after_commit_success','after_commit_duplicate_delivery')
            try:
                log_backend_events(project_manager=d.store.project_manager,project_id=d.project.name,
                    entries=[{'action_kind':'setup','event_type':'side_effect_probe','expected_action':action}],
                    expected_contract_fingerprint=contract_runtime_fingerprint(contract) if commit else 'STALE',
                    publication_protocol='cooperative',expected_publication_generation=contract['publication_generation'])
                increment()
                if mode=='after_commit_duplicate_delivery':increment()
                outcome='committed'
            except Exception as exc:
                d.store.restore_session_mutation(d.session.session_id,snapshot);outcome=getattr(exc,'code',type(exc).__name__)
            effects=[json.loads(x) for x in sink.read_text().splitlines()] if sink.exists() else []
            row={'mode':mode,'outcome':outcome,'increments':sum(r['increment'] for r in effects),'records':len(effects),'snapshot_restored':snapshot==d.store.snapshot_session_mutation(d.session.session_id),'sink_semantics':'append-only non-idempotent local increment record'}
            rows.append(row)
            with (root/'rows.jsonl').open('a',encoding='utf-8') as out:out.write(json.dumps(row)+'\n')
        finally:d.close()
    finish_run(root,{'cells':len(rows),'rows':rows,'limits':'No remote effect or transactional outbox; repeated delivery deliberately demonstrates duplication.'})

if __name__=='__main__':main()

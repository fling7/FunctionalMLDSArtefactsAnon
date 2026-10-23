"""Production-path tests for cooperative publication and evidence recovery."""
import json
from pathlib import Path
import sys
import threading
import time

import pytest
from experiments.lib.backend_driver import BACKEND, Driver
from backend.roomcontract_v2_runtime import RoomContractContractError, load_project_contract
from backend.publication import (
    APPEND_PHASES, MARKER, append_evidence_pair, collect_projection_bytes,
    load_consistent_contract, project_lock, publish_project, read_evidence_pair,
    read_publication,
)
from backend.runtime_trace import contract_runtime_fingerprint, log_backend_events


def initialize(project):
    return publish_project(project, collect_projection_bytes(project), validate=load_project_contract)


def test_partial_publication_refuses_and_republish_recovers():
    d=Driver()
    try:
        initial=initialize(d.project)
        files=collect_projection_bytes(d.project)
        agents=json.loads(files['agents.json']); agents['test_revision']=2
        files['agents.json']=json.dumps(agents).encode()
        def stop(phase):
            if phase=='after_write:agents.json': raise RuntimeError('interrupted')
        with pytest.raises(RuntimeError): publish_project(d.project,files,fault_hook=stop)
        with pytest.raises(RoomContractContractError) as caught:
            load_consistent_contract(d.project,load_project_contract)
        assert caught.value.code=='E_PUBLICATION_INCONSISTENT'
        assert read_publication(d.project)['generation']==initial['generation']
        result=publish_project(d.project,files,validate=load_project_contract)
        assert load_consistent_contract(d.project,load_project_contract)['publication_generation']==result['generation']
    finally: d.close()


def test_snapshot_retries_changed_generation():
    d=Driver()
    try:
        initialize(d.project)
        fired=[]
        def edit(phase):
            if phase=='after_projection_read' and not fired:
                fired.append(True)
                publish_project(d.project,collect_projection_bytes(d.project),validate=load_project_contract)
        assert load_consistent_contract(d.project,load_project_contract,fault_hook=edit)['publication_generation']==2
    finally: d.close()


def test_same_generation_kb_addition_refused():
    d=Driver()
    try:
        initialize(d.project)
        (d.project/'kb'/'unexpected.txt').write_text('a new prompt document')
        with pytest.raises(RoomContractContractError): load_consistent_contract(d.project,load_project_contract)
    finally: d.close()


@pytest.mark.parametrize('phase',APPEND_PHASES)
def test_append_exception_is_pairwise(tmp_path,phase):
    event=tmp_path/'runtime_logs'/'events.jsonl'; validation=event.with_name('runtime_validation.v2.jsonl')
    append_evidence_pair(tmp_path,event,b'{"id":"baseline"}\n',validation,b'{"id":"baseline"}\n')
    def fail(actual):
        if actual==phase: raise OSError('test injected failure')
    if phase=='after_journal_clear':
        append_evidence_pair(tmp_path,event,b'{"id":"new"}\n',validation,b'{"id":"new"}\n',fault_hook=fail)
    else:
        with pytest.raises(RoomContractContractError) as caught:
            append_evidence_pair(tmp_path,event,b'{"id":"new"}\n',validation,b'{"id":"new"}\n',fault_hook=fail)
        assert caught.value.code=='E_EVIDENCE_APPEND'
    events,validations=read_evidence_pair(tmp_path,event,validation)
    assert events==validations
    assert len(events)==(2 if phase=='after_journal_clear' else 1)


def test_publisher_blocked_through_commit_append():
    d=Driver()
    try:
        marker=initialize(d.project)
        contract=load_consistent_contract(d.project,load_project_contract)
        action=next(a for a in contract['runtime_context']['runtime_actions'] if a['action_kind']=='setup')
        entered=threading.Event(); finished=threading.Event(); threads=[]
        def publisher():
            entered.set(); publish_project(d.project,collect_projection_bytes(d.project)); finished.set()
        def observer(phase):
            if phase=='after_contract_check':
                thread=threading.Thread(target=publisher); threads.append(thread); thread.start()
                assert entered.wait(1)
                assert not finished.wait(0.03)
        events=log_backend_events(project_manager=d.store.project_manager,project_id=d.project.name,
            entries=[{'action_kind':'setup','event_type':'setup','expected_action':action}],
            expected_contract_fingerprint=contract_runtime_fingerprint(contract),
            publication_protocol='cooperative',expected_publication_generation=marker['generation'],fault_hook=observer)
        for thread in threads: thread.join(3)
        assert finished.is_set()
        assert events[0]['publication_generation']==marker['generation']
        with pytest.raises(RoomContractContractError) as caught:
            log_backend_events(project_manager=d.store.project_manager,project_id=d.project.name,
                entries=[{'action_kind':'setup','event_type':'setup','expected_action':action}],
                expected_contract_fingerprint=contract_runtime_fingerprint(contract),
                publication_protocol='cooperative',expected_publication_generation=marker['generation'])
        assert caught.value.code=='E_CONTRACT_DRIFT'
    finally: d.close()


def test_directory_sync_failure_after_commit_does_not_report_abort(tmp_path,monkeypatch):
    import backend.publication as publication
    def directory_sync(path):
        if not (tmp_path/publication.JOURNAL).exists():
            raise OSError("directory sync failed after the commit point")
    monkeypatch.setattr(publication,"_fsync_dir",directory_sync)
    event=tmp_path/"runtime_logs/events.jsonl";validation=event.with_name("validation.jsonl")
    publication.append_evidence_pair(tmp_path,event,b'{"id":"committed"}\n',validation,b'{"id":"committed"}\n')
    events,validations=publication.read_evidence_pair(tmp_path,event,validation)
    assert events==validations==[{"id":"committed"}]

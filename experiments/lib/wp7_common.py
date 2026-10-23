"""Shared WP7 raw-run provenance. No secret-bearing configuration is inspected."""
from __future__ import annotations
from datetime import datetime, timezone
import hashlib
import json
import platform
from pathlib import Path
import sys
import uuid
ROOT=Path(__file__).resolve().parents[2]
BACKEND=ROOT/'app/backend_root/agent_backend'
if str(BACKEND) not in sys.path: sys.path.insert(0,str(BACKEND))


def write_json(path,data):
    Path(path).parent.mkdir(parents=True,exist_ok=True)
    Path(path).write_text(json.dumps(data,indent=2,sort_keys=True,ensure_ascii=False)+'\n',encoding='utf-8')


def start_run(kind, sources):
    run_id=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')+'-'+uuid.uuid4().hex[:8]
    root=ROOT/'results/raw'/('wp7_'+kind)/run_id
    root.mkdir(parents=True,exist_ok=False)
    names=list(sources)+['prereg/WP7_PLAN.md','app/backend_root/agent_backend/backend/publication.py','app/backend_root/agent_backend/backend/runtime_trace.py','app/backend_root/agent_backend/backend/roomcontract_v2_runtime.py','app/backend_root/agent_backend/backend/state.py']
    hashes={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in names}
    for name in names:
        destination=root/'source'/name
        destination.parent.mkdir(parents=True,exist_ok=True)
        destination.write_bytes((ROOT/name).read_bytes())
    write_json(root/'metadata.json',{'run_id':run_id,'kind':kind,'utc':datetime.now(timezone.utc).isoformat(),'python':sys.version,'platform':platform.platform(),'seed':20261015,'source_sha256':hashes,'scripted_model_only':True})
    return root


def finish_run(root,summary):
    write_json(root/'summary.json',summary)
    out=ROOT/'results/processed'/('wp7_'+root.parent.name.removeprefix('wp7_')+'_'+root.name+'.json')
    write_json(out,{'raw_directory':root.relative_to(ROOT).as_posix(),**summary})
    print(json.dumps({'processed':out.relative_to(ROOT).as_posix(),**summary}))

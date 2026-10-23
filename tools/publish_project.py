"""Cooperative local publisher. Stage a complete project before exposing it."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'app/backend_root/agent_backend'))
sys.path.insert(0,str(ROOT))
from backend.roomcontract_v2_runtime import load_project_contract
from backend.publication import collect_projection_bytes,publish_project
from tools.routing_verifier import verify_routing


def validate(project):
    contract=load_project_contract(project)
    if contract.get('kind')!='v2':raise ValueError('Cooperative CLI currently requires a native V2 project.')
    report=verify_routing(contract['instance'],contract['trace'],model_sha256=contract['model_sha256'],project=contract['project'],model_bytes=Path(contract['instance_path']).read_bytes())
    if not report['ok']:raise ValueError('Gate 0 rejected the staged project: '+json.dumps(report['issues']))
    return contract


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project',type=Path,required=True)
    source=parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--staged-project',type=Path)
    source.add_argument('--initialize',action='store_true')
    args=parser.parse_args()
    staged=args.staged_project or args.project
    validate(staged)
    marker=publish_project(args.project,collect_projection_bytes(staged),validate=validate)
    print(json.dumps({'generation':marker['generation'],'projection_files':len(marker['files'])}))

if __name__=='__main__':main()

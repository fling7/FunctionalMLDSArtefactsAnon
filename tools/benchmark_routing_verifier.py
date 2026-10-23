"""Descriptive Gate 0 timing for one publication (10 warmups + 200 runs)."""
from __future__ import annotations
import argparse
import hashlib
import json
import platform
import sys
import time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools.routing_verifier import load_and_verify


def percentile(values,p):
    values=sorted(values)
    position=(len(values)-1)*p
    lower=int(position)
    return values[lower]+(values[min(lower+1,len(values)-1)]-values[lower])*(position-lower)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-dir',type=Path,default=ROOT/'app/backend_root/agent_backend/projects/classroom_dinosaur')
    parser.add_argument('--output',type=Path,default=ROOT/'results/wp1/gate0_timing.json')
    args=parser.parse_args()
    if args.output.exists():
        base=args.output
        run=2
        while args.output.exists():
            args.output=base.with_name(f'{base.stem}.run-{run}{base.suffix}')
            run+=1
    rows=[]
    for run in range(210):
        begin=time.perf_counter_ns()
        report=load_and_verify(args.project_dir/'roomcontract.v2.instance.json',args.project_dir/'trace_map.v2.json',args.project_dir/'project.json')
        elapsed=(time.perf_counter_ns()-begin)/1e6
        if not report['ok']: raise RuntimeError('Publication is not verified')
        rows.append({'run':run,'warmup':run<10,'milliseconds':elapsed})
    values=[r['milliseconds'] for r in rows if not r['warmup']]
    output={'verifier_sha256':hashlib.sha256((ROOT/'tools/routing_verifier.py').read_bytes()).hexdigest(),'condition':'native Gate 0 including serialized model/trace/project reads, parsing and full routing table construction','unit':'one publication verification','model_sha256':report['model_sha256'],'agents':len(report['routing_table']),'objects':len(report['objects']),'pairs':sum(len(r) for r in report['routing_table'].values()),'warmup_runs':10,'measured_runs':200,'order':'one timing cell, sequential repeated runs; no cross-condition order to randomize','clock':'perf_counter_ns','python':platform.python_version(),'os':platform.platform(),'processor':platform.processor(),'summary_ms':{'p50':percentile(values,.5),'p95':percentile(values,.95),'p99':percentile(values,.99),'min':min(values),'max':max(values)},'limitations':'Single supplied room, local warmed filesystem; no scaling, speedup, or deployment-frequency claim. CPU/RAM inventory is recorded by the shared repro harness.','runs':rows}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(output,indent=2,sort_keys=True)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps({'output':str(args.output),'summary_ms':output['summary_ms']}))

if __name__=='__main__': main()

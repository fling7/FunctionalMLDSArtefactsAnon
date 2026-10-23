"""Freeze an explicitly partial reporting snapshot while a WP6 run continues.

The snapshot preserves byte-identical completed outcomes and the full plan, so
its evaluation_complete flag remains false until every planned model is present.
It never substitutes for the eventual immutable raw-run summary.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from experiments.detection_matrix import aggregate
from experiments.report_mutation_analysis import generate


def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run-dir',type=Path,required=True);p.add_argument('--snapshot-dir',type=Path,required=True);a=p.parse_args()
 source=a.run_dir.resolve();dest=a.snapshot_dir.resolve();dest.mkdir(parents=True,exist_ok=False);(dest/'outcomes').mkdir()
 paths=[source/'mutation_manifest.json',*sorted((source/'outcomes').glob('*.json')),*sorted((source/'worker_failures').glob('*.json'))]
 hashes={}
 for path in paths:
  relative=path.relative_to(source);target=dest/relative;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(path,target);hashes[str(relative).replace('\\','/')]=hashlib.sha256(path.read_bytes()).hexdigest()
 (dest/'snapshot_provenance.json').write_text(json.dumps({'source_run':str(source.relative_to(ROOT)),'snapshot_utc':datetime.now(timezone.utc).isoformat(),'condition':'partial progress snapshot, not a sampled evaluation or final evidence claim','copied_sha256':hashes},indent=2,sort_keys=True)+'\n',encoding='utf-8')
 summary=aggregate(dest)
 generate([dest],ROOT/'docs/MUTATION_ANALYSIS.md',ROOT/'results/processed/wp6',ROOT/'paper_inputs/wp6_mutation_summary.json')
 print(json.dumps({'snapshot':str(dest.relative_to(ROOT)),'completed':summary['models_evaluated'],'planned':summary['planned_model_evaluations'],'evaluation_complete':summary['evaluation_complete']}))
if __name__=='__main__':main()

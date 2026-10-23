"""Preserve source geometry while supplying an unused normalized auxiliary file."""
from __future__ import annotations
import argparse,ast,hashlib,inspect,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from experiments.natural_faults import zone_lint
from tools.case_study_pipeline.rdl_ingestion import normalize_scene

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def verify_unused_normalized_value():
 tree=ast.parse(inspect.getsource(zone_lint))
 loads=[n for n in ast.walk(tree) if isinstance(n,ast.Name) and n.id=='normalized' and isinstance(n.ctx,ast.Load)]
 stores=[n for n in ast.walk(tree) if isinstance(n,ast.Name) and n.id=='normalized' and isinstance(n.ctx,ast.Store)]
 if loads or len(stores)!=1:raise ValueError('Frozen lint no longer treats normalized as unused auxiliary input')
 return {'normalized_stores':len(stores),'normalized_loads':len(loads)}

def make_view(case,destination):
 case=Path(case);destination=Path(destination)
 unused=verify_unused_normalized_value()
 source=case/'input/source_rdl.json';raw=source.read_bytes()
 normalized,report=normalize_scene(json.loads(raw.decode('utf-8-sig')))
 if report.get('status')!='valid':raise ValueError('Source ingestion did not validate; no geometry substituted')
 destination.mkdir(parents=True,exist_ok=False)
 (destination/'input').mkdir();(destination/'intermediate').mkdir()
 (destination/'input/source_rdl.json').write_bytes(raw)
 for relative,value in [('intermediate/scene_graph.normalized.json',normalized),('ingestion_report.json',report)]:
  with (destination/relative).open('x',encoding='utf8') as stream:json.dump(value,stream,indent=2,sort_keys=True)
 paths=['experiments/geometry_case_view.py','experiments/natural_faults.py','tools/case_study_pipeline/rdl_ingestion.py','tools/case_study_pipeline/common.py']
 evidence={'schema':'wp6-geometry-case-view-v1','original_case':str(case),'view':str(destination),
  'purpose':'Auxiliary input compatibility only; original source geometry bytes unchanged.',
  'original_source_sha256':sha(source),'copied_source_sha256':sha(destination/'input/source_rdl.json'),
  'normalized_artifact_sha256':sha(destination/'intermediate/scene_graph.normalized.json'),
  'ingestion_report_sha256':sha(destination/'ingestion_report.json'),'normalizer_function':'tools.case_study_pipeline.rdl_ingestion.normalize_scene',
  'normalized_value_ast_check':unused,'code_hashes':{p:sha(ROOT/p) for p in paths}}
 with (destination/'view_provenance.json').open('x',encoding='utf8') as stream:json.dump(evidence,stream,indent=2)
 return evidence

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--case',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
 lock=json.loads((ROOT/'prereg/wp6_amendments/004_geometry_auxiliary_view.sha256.json').read_text())
 if lock.get('status')!='frozen':raise ValueError('Auxiliary-view protocol is not frozen')
 for name,expected in lock['code_hashes'].items():
  if sha(ROOT/name)!=expected:raise ValueError('Auxiliary-view dependency hash changed: '+name)
 print(json.dumps(make_view(a.case,a.output)))
if __name__=='__main__':main()

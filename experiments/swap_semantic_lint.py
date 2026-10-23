"""Indicative geometry for completed consistent-owner-swap single mutants.

This separate analysis never alters routing ground truth or calls a language model.
"""
from __future__ import annotations
import argparse,hashlib,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from experiments.natural_faults import zone_lint
from tools.routing_verifier import NativeRoutingIndex

def read(path):return json.loads(Path(path).read_text(encoding='utf-8-sig'))
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def index(project):return NativeRoutingIndex(read(project/'roomcontract.v2.instance.json'),read(project/'trace_map.v2.json'))
def changed_targets(before,after):
 if set(before.objects)!=set(after.objects):raise ValueError('Consistent swap unexpectedly changed the object set')
 changes=[]
 for target in sorted(before.objects):
  _,old=before.ownership(target);_,new=after.ownership(target)
  if old!=new:
   if len(old)!=1 or len(new)!=1:raise ValueError('Consistent swap does not have unique before/after owners')
   changes.append({'target':target,'before_owner':before.wire[old[0]],'after_owner':after.wire[new[0]]})
 if len(changes)!=2 or {c['before_owner'] for c in changes}!={c['after_owner'] for c in changes}:
  raise ValueError('Expected exactly two objects with exchanged deciding owners')
 return changes

def measure(case,before,after):
 changes=changed_targets(before,after)
 baseline=zone_lint(case,before);mutant=zone_lint(case,after)
 old={r['target']:r for r in baseline['rows']};new={r['target']:r for r in mutant['rows']}
 rows=[]
 for change in changes:
  target=change['target'];b=old.get(target);m=new.get(target)
  available=bool(b and m and b['zone_box_available'] and m['zone_box_available'])
  rows.append({**change,'baseline':b,'mutant':m,'paired_geometry_available':available,
   'newly_outside':bool(b['inside_owner_zone_box'] and not m['inside_owner_zone_box']) if available else None})
 available=[r for r in rows if r['paired_geometry_available']]
 return {'kind':baseline['kind'],'changed_targets':rows,'n_changed_targets':len(rows),
  'paired_geometry_available':len(available),'unavailable':len(rows)-len(available),
  'baseline_outside':sum(r['baseline']['inside_owner_zone_box'] is False for r in available),
  'mutant_outside':sum(r['mutant']['inside_owner_zone_box'] is False for r in available),
  'newly_outside':sum(r['newly_outside'] is True for r in available),
  'model_flagged_after_swap':any(r['mutant']['inside_owner_zone_box'] is False for r in available) if len(available)==len(rows) else None,
  'model_newly_flagged':any(r['newly_outside'] is True for r in available) if len(available)==len(rows) else None,
  'baseline_all_target_lint':baseline,'mutant_all_target_lint':mutant,
  'semantic_ground_truth':'unavailable; construction alone does not establish semantic inappropriateness',
  'llm_judges':'NOT_RUN; no API calls in this analysis'}

def run(runs,sources,out_dir):
 out_dir=Path(out_dir);out_dir.mkdir(parents=True,exist_ok=False)
 mapping=read(sources)['sources'];records=[];seen=set()
 for run_dir in map(Path,runs):
  manifest=read(run_dir/'mutation_manifest.json')
  for meta in manifest['models']:
   if meta.get('operators')!=['swap_owners_consistently']:continue
   key=meta['id']
   if key in seen:raise ValueError('Duplicate original/recovery observation: '+key)
   seen.add(key)
   row={'model':key,'source_project':meta['room'],'status':meta['status'],'run_dir':str(run_dir)}
   outcome=run_dir/'outcomes'/(meta['storage_id']+'.json')
   if meta['status'] not in {'changed','incomplete'}:row['analysis_status']='operator_not_realized'
   elif not outcome.exists():row['analysis_status']='routing_evaluation_pending'
   else:
    spec=mapping[meta['room']];base=ROOT/spec['project_path'];case=ROOT/spec['case_path']
    project=run_dir/'models'/meta['storage_id']/base.name
    if (project/'ARCHIVED_MODEL.json').exists() and not (project/'roomcontract.v2.instance.json').exists():
     raise ValueError('Restore this completed archived model before lint: '+str(project))
    record=read(outcome)
    if spec.get('model_sha256') and hashlib.sha256((base/'roomcontract.v2.instance.json').read_bytes().replace(b'\r\n',b'\n')).hexdigest().upper()!=spec['model_sha256']:raise ValueError('Baseline source digest changed')
    if record['model_sha256']!=sha(project/'roomcontract.v2.instance.json').upper():raise ValueError('Mutant outcome/model digest mismatch')
    if record['metadata']!=meta:raise ValueError('Outcome/manifest metadata mismatch')
    row.update(analysis_status='measured',source_provenance=spec,outcome_sha256=sha(outcome),
     baseline_model_sha256=sha(base/'roomcontract.v2.instance.json'),mutant_model_sha256=sha(project/'roomcontract.v2.instance.json'),
     source_geometry_sha256=sha(case/'input/source_rdl.json'),routing_groundtruth=record['groundtruth'],
     lint=measure(case,index(base),index(project)))
   records.append(row)
 measured=[r for r in records if r['analysis_status']=='measured']
 summary={'schema':'wp6-consistent-swap-geometry-v1','models':len(records),'models_measured':len(measured),
  'models_pending':sum(r['analysis_status']=='routing_evaluation_pending' for r in records),
  'models_with_complete_paired_geometry':sum(r['lint']['unavailable']==0 for r in measured),
  'paired_changed_targets':sum(r['lint']['paired_geometry_available'] for r in measured),
  'unavailable_changed_targets':sum(r['lint']['unavailable'] for r in measured),
  'baseline_outside_targets':sum(r['lint']['baseline_outside'] for r in measured),
  'mutant_outside_targets':sum(r['lint']['mutant_outside'] for r in measured),
  'newly_outside_targets':sum(r['lint']['newly_outside'] for r in measured),
  'models_newly_flagged':sum(r['lint']['model_newly_flagged'] is True for r in measured),
  'limitation':'Member-derived axis-aligned boxes are indicative. These are construction-response counts, not semantic sensitivity/specificity or judge agreement.',
  'records':records,'sources_sha256':sha(sources),'code_hashes':{p:sha(ROOT/p) for p in ['experiments/swap_semantic_lint.py','experiments/natural_faults.py','tools/routing_verifier.py']}}
 with (out_dir/'geometry.json').open('x',encoding='utf8') as stream:json.dump(summary,stream,indent=2)
 return summary

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run-dir',action='append',type=Path,required=True);p.add_argument('--sources',type=Path,required=True);p.add_argument('--output-dir',type=Path,required=True);a=p.parse_args()
 lock=read(ROOT/'prereg/wp6_amendments/003_swap_geometric_lint.sha256.json')
 if lock.get('status')!='frozen':raise ValueError('Geometric-lint protocol is not frozen')
 for name,expected in lock['code_hashes'].items():
  if sha(ROOT/name)!=expected:raise ValueError('Geometric-lint dependency changed: '+name)
 result=run(a.run_dir,a.sources,a.output_dir)
 print(json.dumps({k:v for k,v in result.items() if k!='records'}))
if __name__=='__main__':main()

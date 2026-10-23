"""Prospective sealed WP6 report adapter; no evaluation or live pool discovery."""
from pathlib import Path, PurePosixPath
import argparse, hashlib, json, re
ROOT=Path(__file__).resolve().parents[1]
SHA=re.compile('^[0-9a-f]{64}$')
BLOCKED={'.git','.venv','.aws','.codex','logs','independent','excluded_client','config.json','fragebogen-antworten-2026-08-17-vollstaendig-imputiert.json'}
def relative(value):
 if not isinstance(value,str) or not value or '\\' in value or any(c in value for c in ':*?[]\0'):raise ValueError('noncanonical path')
 p=PurePosixPath(value)
 if p.is_absolute() or p.as_posix()!=value or '..' in p.parts or '.' in p.parts:raise ValueError('outside/noncanonical path')
 if any(x.lower() in BLOCKED or x.lower().startswith('\x2eenv') or 'questionnaire' in x.lower() for x in p.parts) or p.suffix.lower() in {'.db','.sqlite','.sqlite3','.pkl','.pickle'}:raise ValueError('excluded path')
 return value

def safe(root,value):
 p=root/relative(value)
 if not p.resolve().is_relative_to(root.resolve()):raise ValueError('outside path')
 q=p
 while q!=root:
  if q.is_symlink() or (hasattr(q,'is_junction') and q.is_junction()):raise ValueError('linked path')
  q=q.parent
 return p

def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def overlap(a,b):
 a=a.casefold();b=b.casefold();return a==b or a.startswith(b+'/') or b.startswith(a+'/')
def validate(root,doc):
 required={'schema','runs','geometry','source_manifests','retained_progress_tables','report','processed','paper','outputs','pins'}
 if not isinstance(doc,dict) or set(doc)!=required or doc['schema']!='sealed-wp6-report-manifest-v1':raise ValueError('manifest schema')
 pins=doc['pins']
 if not isinstance(pins,dict) or not pins:raise ValueError('pins required')
 for name,h in pins.items():
  relative(name)
  if not isinstance(h,str) or not SHA.fullmatch(h):raise ValueError('invalid pin')
 if len({x.casefold() for x in pins})!=len(pins):raise ValueError('duplicate pin')
 if not isinstance(doc['runs'],list) or not doc['runs']:raise ValueError('runs required')
 paths=[];run_names=[]
 for run in doc['runs']:
  if not isinstance(run,dict) or set(run)!={'path','outcomes'} or not isinstance(run['outcomes'],list) or not run['outcomes']:raise ValueError('run schema')
  name=relative(run['path']);run_names.append(Path(name).name)
  for suffix in ['summary.json','mutation_manifest.json','snapshot_provenance.json','detection_matrix.csv']:paths.append(name+'/'+suffix)
  for outcome in run['outcomes']:
   relative(outcome)
   if Path(outcome).parent.as_posix()!=name+'/outcomes' or not outcome.endswith('.json'):raise ValueError('outside outcome')
   paths.append(outcome)
  if len(set(run['outcomes']))!=len(run['outcomes']):raise ValueError('duplicate outcome')
 if len(set(run_names))!=len(run_names):raise ValueError('duplicate run identity')
 for field in ['geometry','retained_progress_tables']:
  if not isinstance(doc[field],list) or len(set(doc[field]))!=len(doc[field]):raise ValueError('path list schema')
  paths.extend(doc[field])
 if not isinstance(doc['source_manifests'],list):raise ValueError('source manifest list')
 for row in doc['source_manifests']:
  if not isinstance(row,dict) or set(row)!={'path','sha256'} or pins.get(row['path'])!=row['sha256']:raise ValueError('source manifest pin')
  paths.append(row['path'])
 paths += ['experiments/report_mutation_analysis.py','experiments/wp6_provenance.py','experiments/__init__.py','repro/report_wp6.py']
 for path in paths:
  relative(path)
  if path not in pins:raise ValueError('missing pin: '+path)
 for field in ['report','processed','paper']:relative(doc[field])
 outputs=doc['outputs']
 if not isinstance(outputs,list) or len(outputs)!=len(set(outputs)):raise ValueError('outputs list')
 expected=[doc['report'],doc['paper']]+[doc['processed']+'/'+name+'/'+tail for name in run_names for tail in ['authoring_contract_disagreements.csv','concordant_rejections.csv','single_operator_eligibility.csv','operator_pair_coverage.csv','reporting_summary.json']]
 if sorted(outputs)!=sorted(expected):raise ValueError('exact output list')
 for out in outputs:
  relative(out)
  if not out.startswith(('results/processed/','paper_inputs/','docs/')) or any(overlap(out,x) for x in pins):raise ValueError('output/input overlap or root')
 # No bytes are opened until every path and command-independent field is checked.
 for name,h in pins.items():
  p=safe(root,name)
  if not p.is_file() or digest(p)!=h:raise ValueError('missing/mismatched pin: '+name)
 for run in doc['runs']:
  actual={p.relative_to(root).as_posix() for p in safe(root,run['path']+'/outcomes').iterdir() if p.is_file()}
  if actual!=set(run['outcomes']):raise ValueError('outcome closure mismatch')
 return doc

def execute(manifest,root=ROOT):
 root=Path(root).resolve();manifest=safe(root,manifest)
 doc=validate(root,json.loads(manifest.read_text(encoding='utf-8')))
 from experiments.report_mutation_analysis import generate
 return generate([safe(root,r['path']) for r in doc['runs']],safe(root,doc['report']),safe(root,doc['processed']),safe(root,doc['paper']),[safe(root,p) for p in doc['geometry']],[r['path']+'='+r['sha256'] for r in doc['source_manifests']],retained_progress_tables=[safe(root,p) for p in doc['retained_progress_tables']])
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--manifest',required=True);a=p.parse_args();result=execute(a.manifest);print(json.dumps({'runs':len(result),'report_only':True}))
if __name__=='__main__':main()

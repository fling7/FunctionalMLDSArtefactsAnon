"""Prospective explicit completed-input WP7 report adapter; no evaluation."""
from pathlib import Path,PurePosixPath
import argparse,hashlib,json,re
ROOT=Path(__file__).resolve().parents[1]
KINDS=('interleavings','faults','restore_atomic','scopes','effects','stress')
SHA=re.compile('^[0-9a-f]{64}$')
RUN=re.compile('^results/raw/wp7_(interleavings|faults|restore_atomic|scopes|effects|stress)/[0-9]{8}T[0-9]{6}-[a-f0-9]{8}$')
CELL=re.compile('^(threads|processes)_(packet|cooperative)_(full|slice)\\.json$')
SOURCES=['experiments/analyze_wp7.py','repro/report_wp7.py','experiments/__init__.py','repro/__init__.py']
OUTPUTS=['paper_inputs/tables/T6_commit_protocol.csv','paper_inputs/tables/T6_commit_protocol.tex','paper_inputs/tables/T7_fingerprint_scopes.csv','paper_inputs/tables/T7_fingerprint_scopes.tex','results/processed/wp7_index.json','docs/WP7_RESULTS.md']+[f'paper_inputs/figures/{name}_{size}.{ext}' for name in ('F6_commit_timeline','F7_scope_tradeoff') for size in ('single','double') for ext in ('pdf','svg')]
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
def validate(root,doc):
 if not isinstance(doc,dict) or set(doc)!={'schema','selected','interrupted','stress_cells','selection_index','outputs','pins'} or doc['schema']!='sealed-wp7-report-manifest-v1':raise ValueError('manifest schema')
 pins=doc['pins']
 if not isinstance(pins,dict) or not pins:raise ValueError('pins required')
 for path,h in pins.items():
  relative(path)
  if not isinstance(h,str) or not SHA.fullmatch(h):raise ValueError('invalid pin')
 if len({p.casefold() for p in pins})!=len(pins):raise ValueError('duplicate pin')
 if doc['outputs']!=OUTPUTS:raise ValueError('exact output list required')
 selection=relative(doc['selection_index'])
 if not selection.startswith('data/replay/'):raise ValueError('selection index location')
 selected=doc['selected'];interrupted=doc['interrupted'];cells=doc['stress_cells']
 if not isinstance(selected,dict) or set(selected)!=set(KINDS):raise ValueError('six selected experiment kinds required')
 expected=set(SOURCES+[selection]);folders={};pending=[]
 for kind in KINDS:
  path=relative(selected[kind]);m=RUN.fullmatch(path)
  if not m or m.group(1)!=kind:raise ValueError('selected run/kind mismatch')
  names={'summary.json','metadata.json'}
  if kind!='stress':names.add('scope_rows.jsonl' if kind=='scopes' else 'rows.jsonl')
  folders[path]=names
 if not isinstance(cells,list) or not cells or cells!=sorted(set(cells)):raise ValueError('ordered stress cells required')
 for path in cells:
  relative(path)
  if str(PurePosixPath(path).parent)!=selected['stress'] or not CELL.fullmatch(PurePosixPath(path).name):raise ValueError('stress cell path')
  folders[selected['stress']].add(PurePosixPath(path).name)
 if not isinstance(interrupted,list):raise ValueError('interrupted list')
 for row in interrupted:
  if not isinstance(row,dict) or set(row)!={'path','files'}:raise ValueError('interrupted schema')
  path=relative(row['path']);m=RUN.fullmatch(path);names=row['files']
  if not m or path in folders or not isinstance(names,list) or names!=sorted(set(names)) or 'metadata.json' not in names:raise ValueError('interrupted path/files')
  if any(n not in ('metadata.json','rows.jsonl') and not CELL.fullmatch(n) for n in names):raise ValueError('interrupted file name')
  folders[path]=set(names);pending.append(path)
 if pending!=sorted(set(pending)):raise ValueError('ordered interrupted runs required')
 for path,names in folders.items():expected.update(path+'/'+n for n in names)
 if set(pins)!=expected:raise ValueError('exact input pin set required')
 # Entire schema/path contract is validated before opening any pinned file.
 for path,h in pins.items():
  p=safe(root,path)
  if not p.is_file() or digest(p)!=h:raise ValueError('missing/mismatched pin: '+path)
 index=json.loads(safe(root,selection).read_text(encoding='utf-8-sig'))
 if index.get('selected_raw_runs')!=selected or index.get('interrupted_raw_runs')!=pending:raise ValueError('selection index binding mismatch')
 for kind in KINDS:
  parent=safe(root,'results/raw/wp7_'+kind)
  if {p.name for p in parent.iterdir()}!={PurePosixPath(p).name for p in folders if RUN.fullmatch(p).group(1)==kind}:raise ValueError('extra/missing run')
 for path,names in folders.items():
  if {p.name for p in safe(root,path).iterdir()}!=names:raise ValueError('run file closure mismatch')
 return {'selected':{kind:selected[kind] for kind in KINDS},'interrupted':pending,'stress_cells':cells}
def execute(manifest,root=ROOT):
 root=Path(root).resolve();inputs=validate(root,json.loads(safe(root,manifest).read_text(encoding='utf-8')))
 from experiments import analyze_wp7
 if Path(analyze_wp7.ROOT).resolve()!=root:raise ValueError('reporter root differs from validated root')
 return analyze_wp7.main(explicit_inputs=inputs)
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--manifest',required=True);a=p.parse_args();execute(a.manifest)
if __name__=='__main__':main()

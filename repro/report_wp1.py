"""Fixed-input WP1 report replay using unchanged functions and explicit byte cleanup."""
from pathlib import Path,PurePosixPath
import argparse,hashlib,importlib.util,json,re,shutil,sys
ROOT=Path(__file__).resolve().parents[1]
SOURCES=['repro/analyze_metamodel.py','repro/wp1_paper_inputs.py','tools/generate_routing_figures.py','repro/normalize_figures.py','repro/__init__.py','repro/report_wp1.py']
DATA=['results/wp1/metamodel_delta.json','docs/INVARIANT_TRACEABILITY.csv']
OUTPUTS=['paper_inputs/tables/T1_metamodel_delta.csv','paper_inputs/tables/T1_metamodel_delta.tex','paper_inputs/tables/T10_invariant_traceability.csv','paper_inputs/tables/T10_invariant_traceability.tex','results/processed/invariant_traceability_summary.json']
OUTPUTS += [f'paper_inputs/figures/F1_architecture_{tag}.{fmt}' for tag in ('single','double') for fmt in ('pdf','svg')]+['paper_inputs/figures/F1_architecture_manifest.json']
OUTPUTS += [f'paper_inputs/figures/F2_routing_slice_{tag}.{fmt}' for tag in ('single','double') for fmt in ('pdf','svg')]
OUTPUTS += [f'output/metamodel_v2/figures/routing_slice_{tag}.{fmt}' for tag in ('single','double') for fmt in ('svg','pdf','png')]+['output/metamodel_v2/figures/routing_figure_manifest.json']
NORMALIZED=[p for p in OUTPUTS if PurePosixPath(p).suffix in ('.pdf','.svg','.png')]
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
def validate(root,doc):
 if not isinstance(doc,dict) or set(doc)!={'schema','pins','outputs','normalized_outputs','normalization_policy'} or doc['schema']!='sealed-wp1-report-manifest-v1':raise ValueError('manifest schema')
 if doc['outputs']!=OUTPUTS or doc['normalized_outputs']!=NORMALIZED or doc['normalization_policy']!='declared-pdf-svg-png-byte-helpers-v1':raise ValueError('exact output/normalization contract required')
 pins=doc['pins']
 if not isinstance(pins,dict) or set(pins)!=set(SOURCES+DATA):raise ValueError('exact source/data pin set required')
 for path,h in pins.items():
  relative(path)
  if not isinstance(h,str) or not SHA.fullmatch(h):raise ValueError('invalid pin')
 for path,h in pins.items():
  p=safe(root,path)
  if not p.is_file() or digest(p)!=h:raise ValueError('missing/mismatched pin: '+path)
 data=json.loads(safe(root,DATA[0]).read_text(encoding='utf-8'))
 if data.get('schema')!='metamodel-delta-v1' or data.get('traceability_sha256')!=pins[DATA[1]]:raise ValueError('captured metamodel/traceability binding mismatch')
 return doc

def load_module(root,name,relative_path):
 spec=importlib.util.spec_from_file_location(name,safe(root,relative_path));module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
 if Path(module.ROOT).resolve()!=root:raise ValueError('module root differs from validated root')
 return module

def execute(manifest,root=ROOT):
 root=Path(root).resolve();doc=validate(root,json.loads(safe(root,manifest).read_text(encoding='utf-8')))
 metamodel=load_module(root,'wp1_retained_metamodel_report','repro/analyze_metamodel.py')
 paper=load_module(root,'wp1_retained_paper_report','repro/wp1_paper_inputs.py')
 routing=load_module(root,'wp1_retained_routing_figure','tools/generate_routing_figures.py')
 normalizer=load_module(root,'wp1_retained_figure_normalizer','repro/normalize_figures.py')
 if Path(metamodel.RAW).resolve()!=safe(root,DATA[0]).resolve() or Path(routing.OUT).resolve()!=safe(root,'output/metamodel_v2/figures').resolve():raise ValueError('fixed module data/output paths differ')
 original_argv=sys.argv
 try:
  sys.argv=['repro/analyze_metamodel.py']
  metamodel.main() # --capture is never accepted or forwarded.
 finally:sys.argv=original_argv
 result=paper.traceability();paper.architecture();routing.main()
 for tag in ('single','double'):
  for fmt in ('pdf','svg'):
   shutil.copyfile(safe(root,f'output/metamodel_v2/figures/routing_slice_{tag}.{fmt}'),safe(root,f'paper_inputs/figures/F2_routing_slice_{tag}.{fmt}'))
 print(json.dumps({'table':'T10','invariants':result['invariants'],'figure':'F1','variants':2}))
 helpers={'.pdf':normalizer.pdf_bytes,'.svg':normalizer.svg_bytes,'.png':normalizer.png_bytes}
 for path in doc['normalized_outputs']:
  output=safe(root,path);before=output.read_bytes();after=helpers[output.suffix](before)
  if before!=after:output.write_bytes(after)

def main():
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--manifest',required=True);args=parser.parse_args();execute(args.manifest)
if __name__=='__main__':main()

"""Prospective explicit-input property report adapter; no campaign execution."""
from pathlib import Path, PurePosixPath
import argparse,hashlib,json,re
ROOT=Path(__file__).resolve().parents[1]
SHA=re.compile('^[0-9a-f]{64}$')
SHARD=re.compile('^results/raw/properties/model-properties-v2-shard[0-9]+$')
OUTPUTS=['results/processed/properties_summary.json','docs/PROPERTY_RESULTS.md','paper_inputs/tables/T9_property_shards.csv']
SOURCES=['repro/analyze_properties.py','repro/report_properties.py','repro/__init__.py']
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
 if not isinstance(doc,dict) or set(doc)!={'schema','shards','capture_manifest','outputs','pins'} or doc['schema']!='sealed-property-report-manifest-v1':raise ValueError('manifest schema')
 pins=doc['pins']
 if not isinstance(pins,dict) or not pins:raise ValueError('pins required')
 for path,h in pins.items():
  relative(path)
  if not isinstance(h,str) or not SHA.fullmatch(h):raise ValueError('invalid pin')
 if len({p.casefold() for p in pins})!=len(pins):raise ValueError('duplicate pin')
 if doc['outputs']!=OUTPUTS:raise ValueError('exact output list required')
 capture_path=relative(doc['capture_manifest'])
 if not capture_path.startswith('data/replay/'):raise ValueError('capture manifest location')
 shards=doc['shards'];expected=set(SOURCES+[capture_path]);names=[]
 if not isinstance(shards,list) or not shards:raise ValueError('shards required')
 for row in shards:
  if not isinstance(row,dict) or set(row)!={'path','summary_present'} or type(row['summary_present']) is not bool:raise ValueError('shard schema')
  path=relative(row['path'])
  if not SHARD.fullmatch(path):raise ValueError('shard path')
  names.append(path);expected.add(path+'/models.jsonl')
  if row['summary_present']:expected.add(path+'/summary.json')
  base='data/replay/property_capture/'+Path(path).name
  expected.update([base+'/full_prefix.jsonl',base+'/trailing.bin'])
 if names!=sorted(set(names)):raise ValueError('duplicate or unordered shards')
 if set(pins)!=expected:raise ValueError('exact input pin set required')
 # Validate the complete schema/path/command contract before opening a pin.
 for path,h in pins.items():
  p=safe(root,path)
  if not p.is_file() or digest(p)!=h:raise ValueError('missing/mismatched pin: '+path)
 capture=json.loads(safe(root,capture_path).read_text(encoding='utf-8'))
 if capture.get('schema')!='property-closed-prefix-capture-v1' or capture.get('terminal') is not True or not isinstance(capture.get('shards'),list):raise ValueError('capture schema')
 captured=capture['shards']
 if [r.get('shard') for r in captured]!=[Path(p).name for p in names]:raise ValueError('capture shard set/order')
 parent=safe(root,'results/raw/properties')
 actual={p.name for p in parent.iterdir() if p.name.startswith('model-properties-v2-shard')}
 if actual!={Path(p).name for p in names}:raise ValueError('extra/missing shard')
 for row,record in zip(shards,captured):
  path=row['path'];folder=safe(root,path);model=path+'/models.jsonl';base='data/replay/property_capture/'+folder.name
  expected_files={'models.jsonl'}|({'summary.json'} if row['summary_present'] else set())
  if {p.name for p in folder.iterdir()}!=expected_files:raise ValueError('shard file closure mismatch')
  if record.get('report_sha256')!=pins[model] or record.get('source_summary_present') is not row['summary_present']:raise ValueError('capture model/summary binding')
  if row['summary_present'] and record.get('summary_sha256')!=pins[path+'/summary.json']:raise ValueError('capture summary hash')
  closed=safe(root,model).read_bytes();full=safe(root,base+'/full_prefix.jsonl').read_bytes();tail=safe(root,base+'/trailing.bin').read_bytes()
  if closed+tail!=full or len(closed)!=full.rfind(b'\n')+1:raise ValueError('capture prefix partition')
  if record.get('captured_prefix_sha256')!=pins[base+'/full_prefix.jsonl'] or record.get('retained_tail_sha256')!=pins[base+'/trailing.bin']:raise ValueError('capture byte pins')
  if (record.get('captured_prefix_bytes'),record.get('report_lf_closed_bytes'),record.get('retained_tail_bytes'),record.get('lf_delimited_lines'))!=(len(full),len(closed),len(tail),closed.count(b'\n')):raise ValueError('capture byte counts')
 return doc
def execute(manifest,root=ROOT):
 root=Path(root).resolve();doc=validate(root,json.loads(safe(root,manifest).read_text(encoding='utf-8')))
 from repro import analyze_properties
 if Path(analyze_properties.ROOT).resolve()!=root:raise ValueError('reporter root differs from validated root')
 return analyze_properties.main(shard_paths=[safe(root,row['path']) for row in doc['shards']])
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--manifest',required=True);a=p.parse_args();execute(a.manifest)
if __name__=='__main__':main()

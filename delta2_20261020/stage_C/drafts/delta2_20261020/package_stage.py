"""Create independently scanned, hash-verified DELTA2 stages; preserve old releases."""
import sys,json,hashlib,zipfile
from pathlib import Path
from datetime import datetime,timezone
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'repro/sprint_report.py').is_file())
sys.path.insert(0,str(ROOT));sys.dont_write_bytecode=True
from tools.anonymize.anonymize import transform_text,scan_identity,rename,repin
from repro.scan_secrets import scan
BASE=ROOT/'deliverables/delta2_20261020'
RELEASE=ROOT/'deliverables/delta2_20261020_release'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,x):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(x,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
def pins():
 start=json.loads((ROOT/'drafts/delta2_20261020/start_record.json').read_text())
 for name,h in start['initial_hashes'].items():assert sha(ROOT/name)==h,('baseline changed',name)
 return start['initial_hashes']
def verify_zip(path):
 with zipfile.ZipFile(path) as z:
  assert z.testzip() is None
  for line in z.read('MANIFEST.sha256').decode().splitlines():
   digest,name=line.split('  ',1);assert hashlib.sha256(z.read(name)).hexdigest()==digest
def main(stage):
 initial=pins();src=BASE/('stage_'+stage);dst=RELEASE/('stage_'+stage)
 assert src.is_dir() and not dst.exists()
 dst.mkdir(parents=True)
 fixture_files={};fixture_hashes={}
 exclusions={'item_notes_a2.md','numbers_a2.json','review/changes_a2.json'}
 for p in sorted(src.rglob('*')):
  if not p.is_file() or p.relative_to(src).as_posix() in exclusions:continue
  rel=p.relative_to(src);dest=dst/rename(rel.as_posix());dest.parent.mkdir(parents=True,exist_ok=True)
  data=p.read_bytes()
  if p.suffix in {'.json','.jsonl','.csv','.md','.py','.txt','.svg'}:data=transform_text(data,dest,rel.as_posix())
  dest.write_bytes(data)
 scripts={'A':['a1_timing.py','report_stage_a.py','agent_a/recover_a2.py','agent_a/finalize_a2.py','agent_b/checker_provenance.py','agent_c/a4_a5.py','agent_c/a5_clarify_validate.py'],
          'B':[], 'C':[], 'D':[]}
 scriptroot=ROOT/'drafts/delta2_20261020'
 selected=[scriptroot/x for x in scripts[stage]]
 if stage!='A':selected=list(scriptroot.glob('agent_*_stage'+stage+'/*.py'))
 if stage=='B':selected.append(scriptroot/'report_stage_b.py')
 if stage=='C':
  selected.append(scriptroot/'package_final.py')
  selected.append(scriptroot/'export_stage_c.py')
  selected.extend(scriptroot.glob('agent_c_stageC/B1s_prompt.txt'))
  selected.extend(scriptroot.glob('agent_c_stageC/RUN_COMMANDS.md'))
 selected+=[Path(__file__).resolve(),scriptroot/'start_record.json']
 for p in selected:
  rel=p.relative_to(ROOT);dest=dst/rename(rel.as_posix());dest.parent.mkdir(parents=True,exist_ok=True)
  dest.write_bytes(transform_text(p.read_bytes(),dest,rel.as_posix()))
 rawroot=ROOT/'results/raw/delta2'/('stage_'+stage)
 if rawroot.exists():
  for p in sorted(rawroot.rglob('*')):
   if not p.is_file() or p.suffix in {'.log','.pyc'} or (stage=='C' and p.name=='llm_calls.jsonl'):continue
   rel=p.relative_to(ROOT);dest=dst/rename(rel.as_posix());dest.parent.mkdir(parents=True,exist_ok=True)
   data=p.read_bytes()
   if p.suffix in {'.json','.jsonl','.csv','.md','.txt','.py'}:data=transform_text(data,dest,rel.as_posix())
   dest.write_bytes(data)
   if stage=='A' and 'fixture' in rel.parts and p.suffix in {'.json','.md','.txt'}:
    fixture_files[rel.as_posix()]=dest
    fixture_hashes[rel.as_posix()]={sha(p),hashlib.sha256(p.read_bytes().replace(b'\r\n',b'\n')).hexdigest()}
 if stage=='A':
  for ready in (rawroot/'a1').glob('*/ready.json'):
   for name,digest in json.loads(ready.read_text())['source_pins'].items():
    p=ROOT/name;assert sha(p)==digest
    dest=dst/rename(name);dest.parent.mkdir(parents=True,exist_ok=True)
    data=p.read_bytes()
    if p.suffix in {'.json','.jsonl','.csv','.md','.txt','.py'}:data=transform_text(data,dest,name)
    dest.write_bytes(data)
    if p.suffix in {'.json','.md','.txt'}:
     fixture_files[name]=dest;fixture_hashes[name]={sha(p),hashlib.sha256(p.read_bytes().replace(b'\r\n',b'\n')).hexdigest()}
 if fixture_files:
  transitions=repin(dst,fixture_hashes,fixture_files)
  save(dst/'review/fixture_export_hash_transitions.json',{'scope':'Only exported A1 fixture copies; historical source proofs remain original hashes. No baseline files modified.','script':'drafts/delta2_20261020/package_stage.py','hash_transitions':transitions})
 if stage=='C':
  from export_stage_c import refresh
  refresh(dst)
 numbers={p.relative_to(dst).as_posix():json.loads(p.read_text(encoding='utf-8-sig')) for p in dst.rglob('numbers*.json')}
 save(dst/f'numbers_stage_{stage}.json',{'stage':stage,'source_number_files':numbers,'old_number_files_unchanged':True,'aggregation_script':'drafts/delta2_20261020/package_stage.py'})
 secret=scan([dst]);identity=scan_identity(dst)
 assert not secret and not identity,('scan findings',secret,identity)
 save(dst/'review/release_scan.json',{'secret_findings':secret,'identity_findings':identity})
 payload={p.relative_to(dst).as_posix():sha(p) for p in sorted(dst.rglob('*')) if p.is_file()}
 save(dst/'review/release_proof.json',{'status':'PASS','stage':stage,'utc':datetime.now(timezone.utc).isoformat(),'payload_sha256':payload,'baseline_pins':initial,'excludes':['review/release_proof.json','MANIFEST.sha256'],'baseline_pins_unchanged':True,'gate_statuses_changed':False})
 (dst/'MANIFEST.sha256').write_text(''.join(sha(p)+'  '+p.relative_to(dst).as_posix()+'\n' for p in sorted(dst.rglob('*')) if p.is_file()),encoding='utf-8')
 archive=ROOT/f'deliverables/for_claude_delta2_{stage}.zip';assert not archive.exists()
 with zipfile.ZipFile(archive,'x',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
  for p in sorted(dst.rglob('*')):
   if p.is_file():z.write(p,p.relative_to(dst).as_posix())
 verify_zip(archive);pins()
 receipt={'stage':stage,'path':archive.relative_to(ROOT).as_posix(),'bytes':archive.stat().st_size,'sha256':sha(archive),'manifest_verified':True,'scans_clean':True}
 save(RELEASE/f'receipt_{stage}.json',receipt);print(json.dumps(receipt))
if __name__=='__main__':main(sys.argv[1])

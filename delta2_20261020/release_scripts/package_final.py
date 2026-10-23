"""Append verified DELTA2 supplements to the unchanged DELTA1 anonymous archive."""
import sys,json,hashlib,zipfile,shutil
from pathlib import Path
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'repro/sprint_report.py').is_file())
sys.path.insert(0,str(Path(__file__).parent));sys.dont_write_bytecode=True
from package_stage import pins,sha,save,verify_zip,RELEASE
from tools.anonymize.anonymize import transform_text,scan_identity
from repro.scan_secrets import scan
def main():
 initial=pins()
 stages=[s for s in 'ABCD' if (RELEASE/('stage_'+s)).is_dir()]
 assert stages[:3]==list('ABC'),'Deliver A, B, C before final assembly'
 for stage in stages:
  archive=ROOT/f'deliverables/for_claude_delta2_{stage}.zip';verify_zip(archive)
  receipt=json.loads((RELEASE/f'receipt_{stage}.json').read_text());assert sha(archive)==receipt['sha256'] and receipt['scans_clean']
  folder=RELEASE/('stage_'+stage)
  with zipfile.ZipFile(archive) as z:
   paths={p.relative_to(folder).as_posix():p for p in folder.rglob('*')if p.is_file()}
   assert set(paths)==set(z.namelist())
   for name,path in paths.items():assert sha(path)==hashlib.sha256(z.read(name)).hexdigest()

 overview=RELEASE/'DELTA2.md'
 assert overview.is_file(),'Write final evidence-based overview first'
 overview.write_bytes(transform_text(overview.read_bytes(),overview,'DELTA2.md'))
 # Stage payloads already passed full scans, and exact file equality to sealed
 # ZIPs was checked above. Scan only the newly added overview, avoiding a
 # redundant full scan of hundreds of MB of unchanged verified input traces.
 scripts=RELEASE/'release_scripts';scripts.mkdir(exist_ok=False)
 for name in ('package_final.py','package_stage.py','finish_stage_a.py','report_final.py'):
  source=ROOT/'drafts/delta2_20261020'/name;target=scripts/name
  target.write_bytes(transform_text(source.read_bytes(),target,'release_scripts/'+name))
 assert not scan([overview,scripts]) and not scan_identity(scripts)
 import tempfile
 with tempfile.TemporaryDirectory(prefix='delta2_final_scan_') as tmp:
  check=Path(tmp)/'DELTA2.md';check.write_bytes(overview.read_bytes());assert not scan_identity(Path(tmp))

 final=RELEASE/'anonymous_repo.zip';assert not final.exists()
 baseline=ROOT/'deliverables/delta_20261020_release/anonymous_repo.zip'
 shutil.copyfile(baseline,final)
 additions={overview:'delta2_20261020/DELTA2.md'}
 additions.update({p:'delta2_20261020/release_scripts/'+p.name for p in scripts.iterdir()if p.is_file()})
 for stage in stages:
  folder=RELEASE/('stage_'+stage)
  additions.update({p:'delta2_20261020/stage_'+stage+'/'+p.relative_to(folder).as_posix() for p in folder.rglob('*') if p.is_file()})
 manifest=RELEASE/'DELTA2_MANIFEST.sha256'
 manifest.write_text(''.join(sha(path)+'  '+name+'\n' for path,name in sorted(additions.items(),key=lambda pair:pair[1])),encoding='utf-8')
 additions[manifest]='delta2_20261020/MANIFEST.sha256'
 with zipfile.ZipFile(final,'a',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
  for path,name in additions.items():assert name not in z.namelist();z.write(path,name)
 with zipfile.ZipFile(final) as z,zipfile.ZipFile(baseline) as old:
  assert z.testzip() is None
  assert len(z.namelist())==len(set(z.namelist()))
  for item in old.infolist():
   assert hashlib.sha256(z.read(item.filename)).digest()==hashlib.sha256(old.read(item.filename)).digest()
  for path,name in additions.items():assert hashlib.sha256(z.read(name)).hexdigest()==sha(path)
 pins()
 receipt={'path':final.relative_to(ROOT).as_posix(),'sha256':sha(final),'bytes':final.stat().st_size,'stages':stages,'all_baseline_members_sha256_equal':True,'all_new_members_sha256_verified':True,'prior_archives_unchanged':True,'new_payload_scans_clean':True,'scan_basis':'Every stage payload equals its already fully scanned sealed ZIP; new overview separately scanned.','baseline_pins':initial}
 save(RELEASE/'final_receipt.json',receipt);print(json.dumps(receipt))
if __name__=='__main__':main()

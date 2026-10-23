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
 for stage in stages:verify_zip(ROOT/f'deliverables/for_claude_delta2_{stage}.zip')
 overview=RELEASE/'DELTA2.md'
 assert overview.is_file(),'Write final evidence-based overview first'
 overview.write_bytes(transform_text(overview.read_bytes(),overview,'DELTA2.md'))
 assert not scan([RELEASE]) and not scan_identity(RELEASE)
 final=RELEASE/'anonymous_repo.zip';assert not final.exists()
 baseline=ROOT/'deliverables/delta_20261020_release/anonymous_repo.zip'
 shutil.copyfile(baseline,final)
 additions={overview:'delta2_20261020/DELTA2.md'}
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
 receipt={'path':final.relative_to(ROOT).as_posix(),'sha256':sha(final),'bytes':final.stat().st_size,'stages':stages,'all_baseline_members_sha256_equal':True,'all_new_members_sha256_verified':True,'prior_archives_unchanged':True,'new_payload_scans_clean':True,'baseline_pins':initial}
 save(RELEASE/'final_receipt.json',receipt);print(json.dumps(receipt))
if __name__=='__main__':main()

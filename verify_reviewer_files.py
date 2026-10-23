"""Verify every published file offline; requires a completed Git LFS checkout."""
from pathlib import Path
import hashlib,json,sys
root=Path(__file__).resolve().parent
fail=[];count=0
for line in (root/'REVIEWER_MANIFEST.sha256').read_text(encoding='utf-8').splitlines():
    expected,name=line.split('  ',1);p=root/name
    if not p.is_file():fail.append({'path':name,'error':'missing'});continue
    h=hashlib.sha256()
    with p.open('rb') as f:
        for block in iter(lambda:f.read(4*1024**2),b''):h.update(block)
    if h.hexdigest()!=expected:fail.append({'path':name,'error':'hash mismatch; check Git LFS checkout'})
    count+=1
print(json.dumps({'status':'PASS' if not fail else 'FAIL','files_checked':count,'failures':fail},indent=2))
sys.exit(bool(fail))

"""Read-only canonical cache integrity check; never calls a model."""
from pathlib import Path
import argparse,hashlib,json,collections
def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode('utf-8')
def digest(value):return hashlib.sha256(canonical(value)).hexdigest()
def check(folder):
 counts=collections.Counter();rows=[];errors=[]
 if not folder.is_dir():errors.append('cache_directory_missing')
 for p in sorted(folder.glob('*.json')):
  x=json.loads(p.read_text(encoding='utf-8'))
  key=digest(x['canonical_request']);response=digest(x['response'])
  row={'file':p.name,'status':x['status'],'canonical_key_matches':x['cache_key']==key,
       'filename_matches':p.stem==key,'response_hash_matches':x['response_sha256']==response}
  counts['entries']+=1;counts['status_'+x['status']]+=1
  for k in ('canonical_key_matches','filename_matches','response_hash_matches'):
   if not row[k]:counts[k+'_failures']+=1
  rows.append(row)
 if not rows:errors.append('cache_has_no_entries')
 return {'counts':dict(counts),'rows':rows,'errors':errors,'valid':bool(rows) and not errors and all(r['canonical_key_matches'] and r['filename_matches'] and r['response_hash_matches'] for r in rows)}
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--folder',type=Path,required=True);ap.add_argument('--report',type=Path,required=True);a=ap.parse_args()
 r=check(a.folder);a.report.parent.mkdir(parents=True,exist_ok=True);a.report.write_text(json.dumps(r,indent=2)+'\n',encoding='utf-8')
 print(json.dumps({'counts':r['counts'],'valid':r['valid']}));raise SystemExit(0 if r['valid'] else 1)
if __name__=='__main__':main()

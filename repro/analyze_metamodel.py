"""Generate T1 from frozen model-count evidence and enforcement traceability."""
from pathlib import Path
import argparse,collections,csv,hashlib,json,subprocess,sys
ROOT=Path(__file__).resolve().parents[1]
RAW=ROOT/'results/wp1/metamodel_delta.json'

def counts(model):
 return {key:len(model[key]) for key in ('classes','datatypes','associations','invariants','views')}

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--capture',action='store_true');args=ap.parse_args()
 if args.capture:
  if RAW.exists():raise SystemExit('Captured model-count evidence already exists; refusing overwrite.')
  source='tools/dynamic_functional_rdl_v2_model.py'
  baseline=subprocess.run(['git','show','baseline:'+source],cwd=ROOT,check=True,capture_output=True).stdout
  current=(ROOT/source).read_bytes()
  namespaces=[]
  for name,data in [('baseline',baseline),('current',current)]:
   namespace={'__name__':'model_count_'+name};exec(compile(data,source,'exec'),namespace);namespaces.append(namespace)
  trace=list(csv.DictReader((ROOT/'docs/INVARIANT_TRACEABILITY.csv').open(encoding='utf-8')))
  value={'schema':'metamodel-delta-v1','unit':'canonical declaration','baseline':counts(namespaces[0]['MODEL']),'extended':counts(namespaces[1]['MODEL']),
   'source_sha256':{'baseline':hashlib.sha256(baseline).hexdigest(),'extended':hashlib.sha256(current).hexdigest()},
   'baseline_commit':subprocess.run(['git','rev-parse','baseline'],cwd=ROOT,check=True,capture_output=True,text=True).stdout.strip(),
   'traceability_status_counts':dict(collections.Counter(row['status'] for row in trace)),
   'traceability_sha256':hashlib.sha256((ROOT/'docs/INVARIANT_TRACEABILITY.csv').read_bytes()).hexdigest(),
   'limits':'Declaration counts are not evidence of enforcement. Not-enforced means no complete demonstrated check/negative-fixture audit in this ledger.'}
  RAW.parent.mkdir(parents=True,exist_ok=True);RAW.write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8')
 data=json.loads(RAW.read_text(encoding='utf-8'))
 rows=[{'declaration':key,'baseline':data['baseline'][key],'extended':value,'delta':value-data['baseline'][key]} for key,value in data['extended'].items()]
 out=ROOT/'paper_inputs/tables';out.mkdir(parents=True,exist_ok=True)
 with (out/'T1_metamodel_delta.csv').open('w',newline='',encoding='utf-8') as f:
  writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
 lines=[r'\begin{tabular}{lrrr}',r'\toprule',r'Declaration & Baseline & Extended & Change \\',r'\midrule']
 for r in rows:
  label=r["declaration"].replace("_",chr(92)+"_")
  lines.append(f"{label} & {r['baseline']} & {r['extended']} & {r['delta']:+d} "+r'\\')
 lines += [r'\bottomrule',r'\end{tabular}']
 (out/'T1_metamodel_delta.tex').write_text('\n'.join(lines)+'\n',encoding='utf-8')
 print(json.dumps({'table':'T1','rows':len(rows),'source':RAW.relative_to(ROOT).as_posix(),'enforcement':data['traceability_status_counts']}))
if __name__=='__main__':main()

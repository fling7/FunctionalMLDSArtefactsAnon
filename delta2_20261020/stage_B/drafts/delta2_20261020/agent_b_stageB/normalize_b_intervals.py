"""Write machine-readable interval CSV derivatives; preserve generated originals."""
from pathlib import Path
import csv,json,ast,re,hashlib
R=Path(__file__).resolve().parents[3];base=R/'deliverables/delta2_20261020/stage_B';proof=[]
for folder in (base/'tables',base/'actually_started_rooms/tables'):
 source=folder/'T_B1_detection.csv';target=folder/'T_B1_detection_machine_readable.csv'
 rows=list(csv.DictReader(source.open(encoding='utf-8')))
 for row in rows:
  for key,value in row.items():
   if key.endswith(('wilson95','cluster95')):
    text=re.sub(r'np\.float64\(([^)]+)\)',r'\1',value)
    v=ast.literal_eval(text) if text else None
    if v is not None:assert len(v)==2 and 0<=float(v[0])<=float(v[1])<=1
    row[key]=json.dumps(v)
 with target.open('x',newline='',encoding='utf-8')as f:
  w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
 proof.append({'original':source.relative_to(R).as_posix(),'original_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'derivative':target.relative_to(R).as_posix(),'derivative_sha256':hashlib.sha256(target.read_bytes()).hexdigest(),'change':'Representation only: NumPy scalar repr to JSON float arrays or null. All numeric values preserved.'})
(base/'review/interval_csv_derivatives.json').write_text(json.dumps({'script':Path(__file__).relative_to(R).as_posix(),'files':proof},indent=2)+'\n',encoding='utf-8')

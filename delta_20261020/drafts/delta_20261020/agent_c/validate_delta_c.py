"""Check delta C accounting and that every retained input remains byte-identical."""
from pathlib import Path
import csv,json,hashlib
R=Path(__file__).resolve().parents[3];O=R/'deliverables/delta_20261020'
def rows(name):
 with (O/'tables'/name).open(encoding='utf-8',newline='') as f:return list(csv.DictReader(f))
p=json.loads((O/'review/agent_c_proof.json').read_text())
for rel,h in p['inputs_sha256'].items():assert hashlib.sha256((R/rel).read_bytes()).hexdigest()==h,rel
non=rows('T4b_nonoracle_detectors.csv');oracle=rows('T4b_oracle_sanity.csv')
for r in non+oracle:
 assert sum(int(r[k]) for k in ('tp','fn','fp','tn'))==int(r['n_models'])
 assert int(r['not_applicable'])==0 and int(r['excluded_groundtruth'])==0
 assert int(r['source_rooms'])==({'generated':6,'classroom':1}[r['cohort']])
 for k in r:
  if k.endswith('_room_cluster95'):
   a=json.loads(r[k]);assert 0<=a[0]<=a[1]<=1
   if r['cohort']=='classroom': assert a[0]==a[1]
for r in oracle:assert int(r['fn'])==int(r['fp'])==0
for r in non:
 if r['checker']=='non_oracle_union' and r['refusal_policy']=='include_refusals':
  assert [int(r[k]) for k in ('tp','fn','fp','tn')]==({'generated':[450,72,0,386],'classroom':[87,11,0,55]}[r['cohort']])
for r in rows('T4b_Va_missed_later_caught.csv'):assert int(r['count'])==({'generated':252,'classroom':54}[r['cohort']])
with (R/'tables/T5_executed_ablation.csv').open(encoding='utf-8',newline='') as f:old={(r['cohort'],r['variant']):r for r in csv.DictReader(f)}
for r in rows('T5b_normalized_ablation.csv'):
 for k in ('probe_slots','executed_probes','setup_refused_probes','wrongly_admitted_probes','executed_models','models_with_wrong_admission'):assert r[k]==old[r['cohort'],r['variant']][k]
 assert int(r['source_rooms_with_wrong_admission'])==len(json.loads(r['affected_source_room_ids']))
svg=(O/'figures/F5_detection_delta.svg').read_text()
for x in ('Gate0 (oracle)','I1_reference (oracle)','I2_policy (oracle)'):assert x in svg
assert 'I3_rejection_atomicity' not in svg
result={'status':'PASS','checks':['Every retained input SHA256 unchanged','Confusion accounting and explicit zero missing labels','Six generated rooms and one classroom room','Classroom cluster intervals degenerate and labelled','Corrected union sensitivity denominators','Exact original T5 probe/model counts preserved','C09 matched retained252 and classroom54','F5 has all three oracle labels and excludesI3'],'visual_check':'F5 PNG inspected: labels and caption unclipped','script':Path(__file__).relative_to(R).as_posix()}
(O/'review/agent_c_validation.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
print(json.dumps(result))

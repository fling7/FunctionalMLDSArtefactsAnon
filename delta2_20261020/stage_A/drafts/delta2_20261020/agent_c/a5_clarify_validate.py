"""Clarify A5a finite-distance wording and validate all Stage A4/A5 artifacts."""
from pathlib import Path
import csv,json,hashlib
R=Path(__file__).resolve().parents[3];O=R/'deliverables/delta2_20261020/stage_A';RAW=R/'results/raw/delta2/stage_A/a4_a5';S=Path(__file__).relative_to(R).as_posix()
r=json.loads((RAW/'classroom_all_pairs.json').read_text());rows=[{**x,'reachability':'unreachable' if x['shortest_handoffs'] is None else 'finite_path_exceeds_one'} for x in r if x['shortest_handoffs'] is None or x['shortest_handoffs']>1]
with (O/'tables/A5_classroom_outside_one_handoff_pairs.csv').open('w',encoding='utf-8',newline='') as f:
 w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
num=json.loads((O/'numbers_a4_a5.json').read_text());nc=num['A5_classroom'];nc['outside_one_handoff_limit']=len(rows);nc['unreachable_pairs']=sum(x['shortest_handoffs'] is None for x in rows);nc['finite_more_than_one_handoff']=sum(x['shortest_handoffs'] is not None for x in rows);nc['wording_correction']='27 outside the one-handoff limit comprises9finite two-hop pairs and18unreachable pairs;27 must not be described as finite multi-hop distance.'
(O/'numbers_a4_a5.json').write_text(json.dumps(num,sort_keys=True,indent=2)+'\n',encoding='utf-8')
comparisons=[{'key':'A5/classroom/outside_one_handoff_limit','old':27,'new':len(rows),'script':S,'flag':'UNCHANGED' if len(rows)==27 else 'CHANGED'}, {'key':'A5/classroom/finite_more_than_one_handoff','old':27,'new':nc['finite_more_than_one_handoff'],'script':S,'flag':'CHANGED','interpretation':'Corrected wording, not changed observations'}, {'key':'A5/classroom/unreachable_pairs','old':None,'new':nc['unreachable_pairs'],'script':S,'flag':'NEW_METRIC'}]
for x in comparisons:print(json.dumps(x))
(O/'review/a5_classroom_wording_comparisons.json').write_text(json.dumps(comparisons,indent=2)+'\n',encoding='utf-8')
with (O/'item_notes_a4_a5.md').open('a',encoding='utf-8') as f:
 if 'A5a wording correction:' not in (O/'item_notes_a4_a5.md').read_text(encoding='utf-8'): f.write('\nA5a wording correction: the27one-handoff rejections are9finite two-hop pairs plus18unreachable pairs. New table A5_classroom_outside_one_handoff_pairs.csv listsall27; finite-only table lists9. Do not describeall27as finite distance>1.\n')
proof=json.loads((O/'review/a4_a5_proof.json').read_text())
for rel,h in proof['input_sha256'].items():assert hashlib.sha256((R/rel).read_bytes()).hexdigest()==h,rel
def rowscsv(name):
 with (O/'tables'/name).open(encoding='utf-8',newline='') as f:return list(csv.DictReader(f))
single=rowscsv('A4_single_operator_detection.csv');pairs=rowscsv('A4_pair_operator_detection.csv')
for cohort,n in [('generated',908),('classroom',153)]:
 assert sum(r['cohort']==cohort for r in single)==17
 assert sum(int(r['mutants']) for r in single+pairs if r['cohort']==cohort)==n
cf=rowscsv('A5_latent_counterfactuals.csv');assert len(cf)==12
verdicts=json.loads((RAW/'counterfactual_verdicts.json').read_text())
for row in cf:
 vv=[v for v in verdicts if v['counterfactual']==row['counterfactual']]
 assert len(vv)==int(row['probe_pairs'])
 for k in ('Gate0','I1','I2'):assert sum(v['verdicts'][k].get('reason')=='E_AMBIGUOUS_OWNER' for v in vv)==int(row[k+'_ambiguous_pairs'])
 inv=json.loads((RAW/'counterfactual_inventory.json').read_text());item=next(x for x in inv if x['counterfactual']==row['counterfactual']);base=json.loads((R/item['original_project']/'roomcontract.v2.instance.json').read_text(encoding='utf-8-sig'));copy=json.loads((R/row['copy_path']).read_text());base_by={x['id']:x for x in base['objects']}
 for obj in copy['objects']:
  before=base_by[obj['id']];a={k:v for k,v in before.items() if k!='groundedAsset'};b={k:v for k,v in obj.items() if k!='groundedAsset'};assert a==b
  assert set(obj.get('groundedAsset',[]))<=set(before.get('groundedAsset',[]))
assert len(rows)==27 and nc['finite_more_than_one_handoff']==9 and nc['unreachable_pairs']==18
val={'status':'PASS','script':S,'retained_inputs_unchanged':True,'only_object_owner_references_removed_in_counterfactuals':True,'all_counterfactual_verdict_counts_match_saved_results':True,'all_existing_mutants_accounted_in_disjoint_single_pair_tables':True,'classroom_correction':'9finite2hop+18unreachable=27outsideonehop'}
(O/'review/a4_a5_validation.json').write_text(json.dumps(val,indent=2)+'\n',encoding='utf-8');print(json.dumps(val))

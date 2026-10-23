"""Finalize A2 provenance: prior missing messages were unclassified, not unrecoverable."""
import json,hashlib
from pathlib import Path
R=Path(__file__).resolve().parents[3];O=R/'deliverables/delta2_20261020/stage_A';S='drafts/delta2_20261020/agent_a/finalize_a2.py'
def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def save(p,x):assert not p.exists();p.write_text(json.dumps(x,indent=2,sort_keys=True)+'\n',encoding='utf-8')
changes=read(O/'review/changes_a2.json')
for row in changes:
 if row['key']=='assembly_status_UNRECOVERABLE':
  row.update(old='NOT_REPORTED',changed=True,script=S,correction='Delta1 classified86 messages as unclassified; it did not establish unrecoverability. This supersedes the mistaken old=86 in the initial A2 log.');print(json.dumps(row))
raw=[read(p)for p in sorted((R/'results/raw/delta2/stage_A/a2').glob('*.json'))]
n=read(O/'numbers_a2.json');n['assembly_cause_unclassified']=sum(r['category']=='UNRECOVERABLE'or r['status']=='REPLAY_DID_NOT_REPRODUCE'for r in raw);change={'key':'assembly_cause_unclassified','old':86,'new':n['assembly_cause_unclassified'],'changed':True,'script':S};changes.append(change);print(json.dumps(change))
others=[{'case_id':r['case_id'],'exception_text':r['exception_text']}for r in raw if r['category']=='other'];print(json.dumps(others))
save(O/'numbers_a2_final.json',n);save(O/'review/changes_a2_final.json',changes);save(O/'review/a2_recovered_raw_records.json',raw)
notes=(O/'item_notes_a2.md').read_text()+'\nFinal reporting: all86 exception messages recovered:84 duplicate-asset-owner refusals and2 other refusals (asset owner lacks a responsible zone containing its object). Drift44/44 duplicate; guided9/10 duplicate plus1other; remaining32attempts31duplicate plus1other. Unclassified causes86 ->0. UNRECOVERABLE is0 newly measured; it was not previously established as86. Use numbers_a2_final.json and changes_a2_final.json for the merged delivery; initial log old=86 for UNRECOVERABLE is superseded by this explicit provenance correction.\n'
p=O/'item_notes_a2_final.md';assert not p.exists();p.write_text(notes,encoding='utf-8')

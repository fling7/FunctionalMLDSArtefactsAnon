"""Assemble a new delta release without modifying the sealed baseline."""
import sys,json,csv,hashlib,shutil,zipfile,re
from pathlib import Path
from datetime import datetime,timezone
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'repro/sprint_report.py').exists())
sys.path.insert(0,str(ROOT));sys.dont_write_bytecode=True
SRC=ROOT/'deliverables/delta_20261020';DST=ROOT/'deliverables/delta_20261020_release/for_claude_delta'
from tools.anonymize.anonymize import transform_text,scan_identity
from repro.scan_secrets import scan
from repro.normalize_figures import pdf_bytes,png_bytes

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,x):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(x,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
def main():
 start=json.loads((ROOT/'drafts/delta_20261020/start_record.json').read_text())
 for name,digest in start['original_pins'].items():assert sha(ROOT/name)==digest,('original changed',name)
 base=json.loads((ROOT/'numbers.json').read_text());new=dict(base)
 for agent in ['a','b','c']:
  p=SRC/f'review/numbers_{agent}.json'
  if not p.exists():p=SRC/f'numbers_{agent}.json'
  updates=json.loads(p.read_text(encoding='utf-8-sig'))
  if agent=='c':new['delta_detector_statistics']=updates
  else:new.update(updates)
 new['delta_exploratory_ablation_decomposition']=json.loads((SRC/'numbers_addendum_a.json').read_text())
 new['delta_legacy_ablation_aggregate_definition']='Legacy wrongly-admitted aggregate includes intentionally unbound action mismatches; NEVER quote reach_only aggregate as unsafe admissions. Use exploratory oracle_rejection_admitted instead.'
 new.update(json.loads((SRC/'numbers_addendum_cd.json').read_text()))
 new.update(json.loads((SRC/'review/numbers_property_b.json').read_text()))
 timing=json.loads((SRC/'review/timing_terminal.json').read_text())
 new['cost_cells_done']=timing['new_done_original_grid'];new['delta_cost_scale']=timing
 changed=[k for k in new if k not in base or new[k]!=base[k]]
 new['delta_changed_keys']=changed;new['delta_baseline_numbers_sha256']=sha(ROOT/'numbers.json')
 save(SRC/'numbers.json',new)
 changelog=[{'key':k,'old':base.get(k),'new':new[k],'flag':'CHANGED' if k in base else 'NEW','script':'drafts/delta_20261020/package_delta.py'} for k in changed]
 save(SRC/'review/number_changes.json',changelog)
 for row in changelog:print(json.dumps(row,ensure_ascii=True))
 notes='\n\n'.join(next(p for p in [SRC/f'review/item_notes_{a}.md',SRC/f'item_notes_{a}.md'] if p.exists()).read_text(encoding='utf-8-sig') for a in ['a','b','c'])
 notes+='\n\n'+ '\n\n'.join((SRC/name).read_text(encoding='utf-8-sig') for name in ['item_notes_addendum_a.md','review/item_notes_property_b.md','item_notes_addendum_cd.md'])
 end=datetime.now(timezone.utc).astimezone().isoformat()
 extra=f'''## Item 9 — {'DONE' if timing['cells_done']==timing['cells_total'] else 'PARTLY'}\n\nAll 24 historical timing rows are retained in T8_cost_scale_legacy_invalid.csv with INVALID_TIMER. The prior process_time_ns CPU clock values are not comparable to the new perf_counter_ns wall-clock observations. Two warmups per cell discarded, ten measured repetitions required; median and inclusive-quartile IQR reported. {timing['cells_done']}/{timing['cells_total']} cells complete ({timing['new_done_original_grid']}/24 original-grid cells; three explicit full Gate4 logger protocol cells added). All classroom and 300-object cells finished. The 1000-object preparation did not finish within the allotted active-compute budget, so all its cells are NOT DONE, with no extrapolation. The final 1.85 seconds above 1500 seconds comprise process-tree termination and result accounting, not extra measurement. Gate4 uses the existing default packet protocol and full scope: reload, validation, fingerprint comparison and transactional evidence append; it is not a cooperative-publication speed claim. Sizes mean scene objects, not total native elements. Retained 300-object fixture reused; 1000-object fixture generated locally only if absent. No model or network latency measured. Sequential workers after P0 completion; normal OS services and unrelated desktop applications were not stopped. The user addendum arrived during the 1000-object preparation; owned timing processes were stopped before the new P0 workers started. Complete classroom and300 cells are preserved. Only the unmeasured1000 cells were attempted after all addendum workers ended, using the remaining portion of the original25minute active-compute budget. Isolation evidence and qualifications are in review/timing_isolation.json and review/timing_isolation_resume.json; interruption and resume times are retained.\n\n## Release decisions\n\nStart: {start['start_local']}; analysis end: {end}. Target75 minutes, hard limit100 minutes. API expenditure delta: USD0. All gate statuses and the claims ledger remain unchanged by instruction; GO is not reassessed here. Historical files remain read-only except the explicitly authorized HANDOVER append. New complete numbers.json supersedes numerical wording only within this delta. Raw results and baseline ZIPs remain byte-identical.\n\nThe refreshed anonymous archive is written at the NEW path deliverables/delta_20261020_release/anonymous_repo.zip. It retains every previously sealed member and adds delta_20261020/ with this supplement. Thus old replay/input pins and baseline Git commit remain intact; the supplemental files are independently hash-listed, not claimed as part of that old Git seal. Do not read the old source count or timing rows as corrected values; use this delta. Existing anonymization transformations and identity/secret scans are applied to the new payload, and the unchanged baseline archive hash is verified. No new red-team round or broad replay rebuild.\n\nExcluded as requested: property top-up, natural reject pairs, Linux/Python3.12 diagnostics, new mutants, new LLM runs. The source-room CI has few independent clusters; classroom has only one. Null results and regressions are retained.\n\n## Numeric provenance\n\nFull per-number old/new/script records accompany the tables in review/*numeric* and review/number_changes.json. Old=null means a genuinely new estimand, not an invented zero. Any difference is flagged. Old source data pins in per-agent proofs refer to the retained pre-sanitization originals; review/delta_proof.json pins the delivered transformed payload. Self-reference is excluded from that proof; MANIFEST.sha256 also covers delta_proof.json.\n'''
 (SRC/'DELTA.md').write_text('# DELTA 2026-10-20\n\nIMPORTANT: The reach_only aggregate of 119,903 contains 15,886 oracle-rejected admissions and 104,017 action-binding-only mismatches; it is not 119,903 unsafe admissions. Fair generated detector union sensitivity is 450/522 = 86.2069%, replacing the prior apparent 100%. Native source definition: 56 bases / 59 literal IDs / 134 models. All 86 assembly refusal reasons remain unclassified because detailed messages were not retained.\n\n'+notes+'\n\n'+extra,encoding='utf-8')
 # Copy start record and scripts at their reported workspace-relative locations.
 startcopy=SRC/'drafts/delta_20261020/start_record.json';startcopy.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/'drafts/delta_20261020/start_record.json',startcopy)
 for p in (ROOT/'drafts/delta_20261020').rglob('*.py'):
  if 'timing_raw' in p.parts:continue
  target=SRC/p.relative_to(ROOT);target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,target)
 assert not DST.exists(),'Refuse overwriting a prior release'
 DST.mkdir(parents=True)
 for p in sorted(SRC.rglob('*')):
  if not p.is_file():continue
  rel=p.relative_to(SRC)
  if 'partial' in p.stem:continue
  dest=DST/rel;dest.parent.mkdir(parents=True,exist_ok=True)
  data=p.read_bytes()
  if p.suffix in {'.md','.json','.jsonl','.csv','.py','.svg','.txt'}:data=transform_text(data,dest,rel.as_posix())
  elif p.suffix=='.pdf':data=pdf_bytes(data)
  elif p.suffix=='.png':data=png_bytes(data)
  dest.write_bytes(data)
 secret=scan([DST]);identity=scan_identity(DST)
 save(DST/'review/delta_scan.json',{'secret_findings':secret,'identity_findings':identity,'baseline_archive_sha256':start['original_pins']['deliverables/anonymous_repo.zip'],'baseline_retained_unchanged':True})
 assert not secret and not identity,('scan findings',secret,identity)
 payload={p.relative_to(DST).as_posix():sha(p) for p in sorted(DST.rglob('*')) if p.is_file()}
 save(DST/'review/delta_proof.json',{'status':'PASS','created_utc':datetime.now(timezone.utc).isoformat(),'payload_sha256':payload,'exclusions':['review/delta_proof.json (self-reference)','MANIFEST.sha256 (covers this proof)'],'original_pins_unchanged':True,'api_calls':0,'gate_statuses_changed':False,'changed_keys':changed})
 (DST/'MANIFEST.sha256').write_text(''.join(sha(p)+'  '+p.relative_to(DST).as_posix()+'\n' for p in sorted(DST.rglob('*')) if p.is_file()),encoding='utf-8')
 release=ROOT/'deliverables/for_claude_delta.zip';assert not release.exists()
 with zipfile.ZipFile(release,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
  for p in sorted(DST.rglob('*')):
   if p.is_file():z.write(p,p.relative_to(DST).as_posix())
 with zipfile.ZipFile(release) as z:
  assert z.testzip() is None
  for line in z.read('MANIFEST.sha256').decode().splitlines():
   h,name=line.split('  ',1);assert hashlib.sha256(z.read(name)).hexdigest()==h
 anon=ROOT/'deliverables/delta_20261020_release/anonymous_repo.zip';assert not anon.exists()
 shutil.copyfile(ROOT/'deliverables/anonymous_repo.zip',anon)
 with zipfile.ZipFile(anon,'a',zipfile.ZIP_DEFLATED,compresslevel=1) as z:
  for p in sorted(DST.rglob('*')):
   if p.is_file():z.write(p,'delta_20261020/'+p.relative_to(DST).as_posix())
 with zipfile.ZipFile(anon) as z:
  assert z.testzip() is None
  with zipfile.ZipFile(ROOT/'deliverables/anonymous_repo.zip') as old:
   assert all(z.getinfo(i.filename).CRC==i.CRC and z.getinfo(i.filename).file_size==i.file_size for i in old.infolist())
  for name,h in payload.items():assert hashlib.sha256(z.read('delta_20261020/'+name)).hexdigest()==h
 append='\n\n## DELTA 2026-10-20\n\nRetained-data statistical and terminology corrections are available in deliverables/for_claude_delta.zip (DELTA.md and full supplemental numbers.json). Original raw data, tables, claims and gate statuses are unchanged. Corrections:134 native models correspond to59 literal IDs and56base sources (49deterministic,7LLM-written). Generated non-oracle union sensitivity is450/522=86.2069%, not the old apparent100%. reach_only119903 consists of15886oracle-rejected admissions plus104017action-binding-only mismatches; do not quote the aggregate as unsafe admissions. The720default-backend disagreements are probes in one room, not720bugs. All86assembly refusals remain unclassified because only exception classes were retained. In particular, use the new source definitions, fair detector denominators and clustered intervals; old timing rows are INVALID_TIMER. See deliverables/delta_20261020_release/anonymous_repo.zip for the same anonymized supplement alongside the unchanged sealed baseline. No API calls.\n'
 with (ROOT/'HANDOVER.md').open('a',encoding='utf-8') as f:f.write(append)
 receipt={'start':start['start_local'],'end':datetime.now(timezone.utc).astimezone().isoformat(),'packages':[{'path':p.relative_to(ROOT).as_posix(),'bytes':p.stat().st_size,'sha256':sha(p)} for p in [release,anon]],'manifest_verified':True,'scans_clean':True,'original_files_unchanged_except_handover_append':True}
 save(ROOT/'deliverables/delta_20261020_release/receipt.json',receipt);print(json.dumps(receipt))
if __name__=='__main__':main()

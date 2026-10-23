"""Read-only local checker provenance; no backend execution or API calls."""
from pathlib import Path
from datetime import datetime, timezone
import ast,csv,hashlib,json,subprocess
ROOT=Path(__file__).resolve().parents[3]
ORIGINAL=ROOT.parent/'RoomContract'
OUT=ROOT/'deliverables/delta2_20261020/stage_A'
RAW=ROOT/'results/raw/delta2/stage_A/a3'
SCRIPT=Path(__file__).relative_to(ROOT).as_posix()
BASE='954f199'
started=datetime.now(timezone.utc).isoformat()
B='app/backend_root/agent_backend/backend/'
V='tools/case_study_pipeline/validators/'
items=[
 ('V-a structural','tools/validate_dynamic_functional_rdl_v2.py','InstanceValidator;validate_instance','executed'),
 ('V-a metamodel dependency','tools/dynamic_functional_rdl_v2_model.py','','dependency'),
 ('V-b native_schema',V+'schema_validator.py','_validate_payload','executed'),
 ('V-b native_domain','tools/case_study_pipeline/roomcontract_v2_assembler.py','validate_roomcontract_v2_instance','executed'),
 ('V-b trace_schema',V+'schema_validator.py','_validate_trace_variant','executed'),
 ('V-b legacy_invariants',V+'roomcontract_invariants.py','validate_roomcontract_invariants','executed'),
 ('V-b legacy view adapter','experiments/detection_matrix.py','legacy_validation_view','study adapter'),
 ('V-b handoff_metrics',V+'handoff_metrics.py','compute_handoff_metrics','executed on study role projection'),
 ('V-b role view adapter','experiments/detection_matrix.py','role_view','study adapter'),
 ('V-b placement_metrics',V+'placement_metrics.py','compute_placement_metrics','not applicable to retained mutation unit'),
 ('V-b traceability_metrics',V+'traceability_metrics.py','compute_traceability_metrics','not applicable to retained mutation unit'),
 ('V-c instance loader',B+'roomcontract_v2_runtime.py','_validate_v2_instance','executed'),
 ('V-c trace loader',B+'roomcontract_v2_runtime.py','_validate_v2_trace','executed'),
 ('backend setup study driver','experiments/lib/backend_driver.py','Driver.__init__','executed'),
 ('backend setup SessionStore',B+'state.py','SessionStore.setup_from_request','executed'),
 ('backend setup contract loader',B+'roomcontract_v2_runtime.py','load_project_contract','executed'),
 ('Gate 0','tools/routing_verifier.py','verify_routing;lookup_route','oracle sanity check, not independent detection evidence'),
 ('I1','verification/impl_a/reference.py','evaluate','oracle sanity check'),
 ('I2 Python adapter','verification/impl_b/policy_adapter.py','evaluate','oracle sanity check'),
 ('I2 ASP policy','verification/impl_b/admission.lp','','oracle dependency'),
]
commands=[]
def git(repo,*args):
 r=subprocess.run(['git','-C',str(repo),*args],capture_output=True)
 commands.append({'repository':'original_project' if repo==ORIGINAL else 'research_workspace','argv':list(args),'returncode':r.returncode})
 return r.stdout if r.returncode==0 else b''
def history(repo,path,all_refs=False):
 args=['log']+(['--all'] if all_refs else [])+['--format=%H %cI','--',path]
 found=[]
 for line in git(repo,*args).decode().splitlines():
  commit,date=line.split(' ',1);found.append({'commit':commit,'date':date})
 return sorted(found,key=lambda r:r['date'])
def symbols(text,names):
 if not names:return None,None
 try:tree=ast.parse(text)
 except SyntaxError:return None,None
 parts=[]
 for name in names.split(';'):
  nodes=tree.body
  for bit in name.split('.'):
   node=next((x for x in nodes if isinstance(x,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)) and x.name==bit),None)
   if node is None:return None,None
   nodes=node.body
  parts.append(node)
 return sum(n.end_lineno-n.lineno+1 for n in parts),[ast.dump(n,include_attributes=False) for n in parts]
sha=lambda value:hashlib.sha256(value).hexdigest()
rows=[];details=[];log=[]
for checker,path,symbol,app in items:
 current=(ROOT/path).read_bytes();txt=current.decode('utf-8-sig')
 baseline=git(ROOT,'show',BASE+':'+path)
 wh=history(ROOT,path);oh=history(ORIGINAL,path);oa=history(ORIGINAL,path,True)
 first=(oh or oa or wh)
 firstrepo=ORIGINAL if oh or oa else ROOT
 earliest=git(firstrepo,'show',first[0]['commit']+':'+path) if first else b''
 current_sym_loc,current_ast=symbols(txt,symbol)
 base_sym_loc,base_ast=symbols(baseline.decode('utf-8-sig'),symbol) if baseline else (None,None)
 baseline_equal=(current==baseline) if baseline else None
 if not baseline: classification='WRITTEN_FOR_STUDY_AFTER_2026-08-06'
 elif baseline_equal:classification='PREDATES_CONTRACT_UNCHANGED_FROM_PACKET'
 else:classification='PREDATES_CONTRACT_FILE_CHANGED_FOR_STUDY'
 symbol_same=current_ast==base_ast if current_ast is not None and base_ast is not None else None
 row=dict(checker=checker,file_path=path,symbol=symbol or 'whole file',physical_LOC=len(txt.splitlines()),nonblank_LOC=sum(bool(x.strip()) for x in txt.splitlines()),symbol_physical_LOC=current_sym_loc if current_sym_loc is not None else 'NOT_APPLICABLE',first_commit_date=first[0]['date'] if first else 'UNKNOWN',first_commit=first[0]['commit'] if first else 'UNKNOWN',first_history_scope='original_project_HEAD' if oh else 'original_project_all_refs' if oa else 'research_workspace_HEAD',earliest_retained_sha256=sha(earliest) if earliest else 'UNKNOWN',current_sha256=sha(current),retained_mtime_utc=datetime.fromtimestamp((ROOT/path).stat().st_mtime,timezone.utc).isoformat(),classification=classification,baseline_file_identical=baseline_equal if baseline_equal is not None else 'NOT_PRESENT',baseline_symbol_AST_identical=symbol_same if symbol_same is not None else 'NOT_APPLICABLE',application=app)
 rows.append(row)
 details.append(dict(checker=checker,path=path,workspace_commits=wh,original_HEAD_commits=oh,original_all_refs_commits=oa,baseline_sha256=sha(baseline) if baseline else None,baseline_symbol_LOC=base_sym_loc))
 for key,new in [('physical_LOC',row['physical_LOC']),('nonblank_LOC',row['nonblank_LOC']),('symbol_physical_LOC',current_sym_loc)]:
  old=(len(baseline.decode('utf-8-sig').splitlines()) if key=='physical_LOC' else sum(bool(x.strip()) for x in baseline.decode('utf-8-sig').splitlines()) if key=='nonblank_LOC' else base_sym_loc) if baseline else None
  entry=dict(key=checker+'.'+key,old=old,new=new,script=SCRIPT,flag='NEW' if old is None else 'UNCHANGED' if old==new else 'CHANGED');log.append(entry);print(json.dumps(entry))
with (OUT/'tables/T_A3_checker_provenance.csv').open('x',newline='',encoding='utf-8') as f:
 w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
va=rows[0]
# Explicitly verify the user-named import commit, without exporting commit author names.
import_commit='9ac7502'
import_date=git(ORIGINAL,'show','-s','--format=%cI',import_commit).decode().strip()
import_bytes=git(ORIGINAL,'show',import_commit+':'+items[0][1])
notes="""## A3 checker provenance — DONE

All evidence is read-only local Git history, retained files and AST comparison. Physical LOC includes comments/blank lines; nonblank LOC and callable-span LOC are also provided. File LOC is repeated for components sharing a file and must not be summed as independent checker size. First commit is a retained-history bound, not an authoring date; copied-file mtime is not creation evidence. No personal identities or commit-author fields are exported.

The original structural validator predates the contract study. The named 2026-08-06 import commit is verified, but original project HEAD history also retains an earlier 2026-07-27 add commit. Therefore 2026-08-06 is a re-import milestone, not proven first creation. Current V-a file was changed during the study; the structural InstanceValidator/validate_instance ASTs are unchanged from the 2026-10-15 preserved packet. New routing checks are an opt-in profile, and the metamodel dependency has its own row. This must not be described as an entirely untouched pre-existing checker stack.

The table identifies inherited files changed during the study and entirely study-written files. Gate 0, I1, I2, the backend test driver and mutation projection adapters were written for the study after 2026-08-06. Their oracle or adapter roles are explicit. V-b placement and traceability metrics exist but are not applicable to the retained mutation-unit evaluation; presence is not execution evidence. Backend setup combines a study-written driver with inherited backend components, which are separately listed. Byte differences do not alone show whether a particular checker behavior changed; callable AST comparison gives narrower evidence where possible.

A zero API cost, no re-execution provenance exercise. Old LOC is the preserved packet at commit 954f199; new LOC is the current retained file. Full commit hashes/dates, baseline hashes and current input hashes are retained in the proof, without author identities.
"""
(OUT/'review/item_notes_a3.md').write_text(notes,encoding='utf-8')
counts={c:sum(r['classification']==c for r in rows) for c in sorted({r['classification'] for r in rows})}
for k,v in counts.items():
 entry=dict(key='provenance_component_rows.'+k,old=None,new=v,script=SCRIPT,flag='NEW');log.append(entry);print(json.dumps(entry))
num=dict(delta2_A3_component_rows=len(rows),delta2_A3_classification_counts=counts,delta2_A3_Va_earliest_retained_commit_date=va['first_commit_date'],delta2_A3_Va_August_import_date=import_date,delta2_A3_Va_structural_AST_same_as_packet=va['baseline_symbol_AST_identical'],delta2_A3_scope='Component rows include shared files and dependencies, not independent checker count.')
(OUT/'review/numbers_a3.json').write_text(json.dumps(num,indent=2)+'\n')
proof=dict(status='DONE',started_utc=started,ended_utc=datetime.now(timezone.utc).isoformat(),script=SCRIPT,script_sha256=sha(Path(__file__).read_bytes()),input_sha256={r['file_path']:r['current_sha256'] for r in rows},baseline_commit=BASE,original_repository='neighboring original project (local Git, read-only)',Va_import=dict(commit=import_commit,date=import_date,sha256=sha(import_bytes)),histories=details,api_calls=0)
for p,obj in [(OUT/'review/checker_provenance_proof_a3.json',proof),(RAW/'git_commands.json',commands)]:p.write_text(json.dumps(obj,indent=2)+'\n')
(OUT/'review/checker_provenance_numeric_log_a3.jsonl').write_text(''.join(json.dumps(x)+'\n' for x in log))

"""Prospective, exact one-file report transition; no historical lock mutation.

This verifier is only for separately authorized future batches. It never
patches the old verifier or changes its fallback behavior. No evaluator import.
"""
from pathlib import Path
import ast
import hashlib
import importlib
import json

ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent
REPORT='experiments/analyze_wp7.py'
LOCK10='prereg/wp6_amendments/010_fresh_batch_dispatch.sha256.json'
LOCK9='prereg/wp6_amendments/009_compiled_integration.sha256.json'
LOCK8='prereg/wp6_amendments/008_complete_corpus_scope.sha256.json'
ORIGINAL='experiments/run_mutation_compiled_batch.py'
OLD='8147d71d1a57a8bb2a3431bb61e97fdfca29e3edeb1a29e26413126258a0b8e9'
NEW='71385f52ea9ce0865462af4dc37902a42f9f58746bb2f04c87c71f52a0663b1d'
SHA10='1261f225f6e67995b9a8e310df5d058ae7dd2086088e657815191becc149f71e'
SHA9='0e9dd4fa873d44a834ceb4a8434fcda82880940f2ba7b8833719d726f32c7b55'
SHA8='01c2b461832184bccd029d0e03461c43d615243a54b7b452f01cba0ee37da80e'
ORIGINAL_SHA='6f55f50804eacf9f659cf64e3e9a7d6886c7ac55c7c9fee3a101310ca44a2124'
ADOPTION='results/raw/wp7_report_adoption_v1.json'
ADOPTION_SHA='2efd420acab40a079c99942a40b8c6659cacc9e8d79dd8c034c2f448cd60b94b'
REVIEW='results/raw/wp7_report_root_review_v1.json'
REVIEW_SHA='57e57edba5bb916313b4c5c89bca73226484f28eaf215757cdd108347b582c32'
OLD_COPY='experiments/wp6_hybrid/retained/analyze_wp7_009.py.txt'
TRANSITION={'schema':'exact-report-only-dependency-transition-v1','path':REPORT,
 'original_sha256':OLD,'current_sha256':NEW,'original_009_lock':{'path':LOCK9,'sha256':SHA9},
 'root_adoption':{'path':ADOPTION,'sha256':ADOPTION_SHA},
 'root_review':{'path':REVIEW,'sha256':REVIEW_SHA},
 'retained_original':{'path':OLD_COPY,'sha256':OLD},
 'scope':'Future dispatch only; no original source/lock edits, no evaluator exception.'}
BLOCKED={'config.json','excluded_client','fragebogen-antworten-2026-08-17-vollstaendig-imputiert.json'}

def safe(name):
    p=Path(name)
    if p.is_absolute():
        try:p=p.relative_to(ROOT)
        except ValueError:raise ValueError('Path outside root') from None
    if '..' in p.parts or any(x.lower() in BLOCKED or x.lower().startswith('\x2eenv') for x in p.parts):raise ValueError('Excluded path')
    q=ROOT/p
    for parent in [q,*q.parents]:
        if parent==ROOT:break
        if parent.is_symlink():raise ValueError('Linked source')
    if not q.resolve().is_relative_to(ROOT.resolve()):raise ValueError('Path outside root')
    return q

def digest(b):return hashlib.sha256(b).hexdigest()
def checked_bytes(name,pin):
    data=safe(name).read_bytes()
    if digest(data)!=pin:raise ValueError('Pinned compatibility file changed: '+str(name))
    return data

def reviewed_main_substitutions(old):
    """Exactly the four already reviewed byte replacements, never a loose AST allowlist."""
    replacements=[
      (b'def main():',b'def main(explicit_inputs=None):'),
      (b'args=parser.parse_args()',b'args=parser.parse_args() if explicit_inputs is None else argparse.Namespace(no_figures=False)'),
      (b"    selected={};interrupted=[]\n    for kind in ('interleavings','faults','restore_atomic','scopes','effects','stress'):\n        run,pending=latest(kind);interrupted+=pending\n        if run:selected[kind]=run",
       b"    selected={};interrupted=[]\n    if explicit_inputs is None:\n        for kind in ('interleavings','faults','restore_atomic','scopes','effects','stress'):\n            run,pending=latest(kind);interrupted+=pending\n            if run:selected[kind]=run\n    else:\n        selected={kind:ROOT/path for kind,path in explicit_inputs['selected'].items()}\n        interrupted=list(explicit_inputs['interrupted'])"),
      (b"sorted(run.glob('*.json'))",b"(sorted(run.glob('*.json')) if explicit_inputs is None else [ROOT/path for path in explicit_inputs['stress_cells']])")]
    new=old
    for before,after in replacements:
        if new.count(before)!=1:raise ValueError('Reviewed main substitution is not unique')
        new=new.replace(before,after)
    return new

def validate_transition(transition):
    if transition!=TRANSITION:raise ValueError('Unrecognized report-only dependency transition')
    old=checked_bytes(OLD_COPY,OLD);new=checked_bytes(REPORT,NEW)
    if reviewed_main_substitutions(old)!=new:raise ValueError('Reporter differs beyond reviewed substitutions')
    def outside_main(data):
        return [ast.dump(n,include_attributes=False) for n in ast.parse(data).body
                if not isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) or n.name!='main']
    if outside_main(old)!=outside_main(new):raise ValueError('Reporter AST outside main changed')
    adoption=json.loads(checked_bytes(ADOPTION,ADOPTION_SHA))
    checked_bytes(REVIEW,REVIEW_SHA)
    if adoption['source_hashes'].get(REPORT)!=NEW or adoption['review_path']!=REVIEW or adoption['review_sha256']!=REVIEW_SHA:
        raise ValueError('Root report adoption does not bind transition')

def _verify_with_original(original,lock_path,expected_lock_sha256,transition):
    """Test seam receives only the old verification API, never an evaluator."""
    if safe(lock_path)!=safe(LOCK10) or expected_lock_sha256!=SHA10:raise ValueError('Wrong original execution lock')
    validate_transition(transition)
    # Preserve old delegation for010,008,queue/inventory and all unchanged pins.
    original.pinned(safe(LOCK10),SHA10)
    lock=original.verify_lock(safe(LOCK10))
    if lock['dependency_locks']!={LOCK8:SHA8,LOCK9:SHA9}:raise ValueError('Original dependency closure changed')
    for path,pin in lock['dependency_locks'].items():
        original.pinned(safe(path),pin)
        if path!=LOCK9:
            original.verify_lock(safe(path));continue
        value=json.loads(checked_bytes(LOCK9,SHA9))
        if value.get('status')!='frozen' or value['code_hashes'].get(REPORT)!=OLD:raise ValueError('Original009 report pin changed')
        for name,expected in value['code_hashes'].items():
            if name==REPORT:
                checked_bytes(name,NEW)
            else:
                # Original hashing API preserves its normal data access/error semantics.
                if original.sha(safe(name))!=expected:raise ValueError('Frozen code changed: '+name)
    for key in ['source_inventory','ordered_queue']:
        original.pinned(safe(lock[key]['path']),lock[key]['sha256'])
    validate_transition(transition)  # detect accidental drift across the check
    return lock

def verify_execution_pins_compat(lock_path,expected_lock_sha256,*,transition):
    checked_bytes(ORIGINAL,ORIGINAL_SHA)
    original=importlib.import_module('experiments.run_mutation_compiled_batch')
    if not getattr(original,'__file__',None) or Path(original.__file__).resolve()!=safe(ORIGINAL).resolve():
        raise ValueError('Original verifier module path mismatch')
    checked_bytes(ORIGINAL,ORIGINAL_SHA)
    return _verify_with_original(original,lock_path,expected_lock_sha256,transition)

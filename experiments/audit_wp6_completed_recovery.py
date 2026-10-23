"""Read-only terminal audit of a completed, byte-pinned WP6 recovery run.

Uses the unchanged recovery verifier; never evaluates a mutant or changes labels.
"""
from __future__ import annotations
import argparse, hashlib, json, sys
from pathlib import Path
from datetime import datetime, timezone
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from experiments.recover_mutation_run import inventory, verify_completed
from experiments.mutations import Bundle
CHECKERS={'Va_structural','Vb_native_schema','Vb_native_domain','Vb_trace_schema','Vb_legacy_invariants_view','Vb_handoff_metrics','Vb_placement_metrics','Vb_traceability_metrics','Vc_instance','Vc_trace','Gate0','backend_setup','I3_rejection_atomicity','runtime_routing_faults','I1_reference','I2_policy'}
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def read(path):return json.loads(Path(path).read_text(encoding='utf8'))
def audit(run):
    run=Path(run).resolve()
    summary=read(run/'summary.json');manifest=read(run/'mutation_manifest.json');recovery=read(run/'recovery_manifest.json')
    if not summary.get('evaluation_complete') or summary.get('worker_failures') or list((run/'worker_failures').glob('*')):raise ValueError('Run is not terminal without worker failures')
    expected=[m for m in manifest['models'] if m['status'] in {'changed','incomplete'}]
    identities=[m['storage_id'] for m in expected]
    if len(identities)!=len(set(identities)):raise ValueError('Duplicate scheduled identity')
    actual={p.stem for p in (run/'outcomes').glob('*.json')}
    if actual!=set(identities) or summary['models_evaluated']!=len(expected) or summary['planned_model_evaluations']!=len(expected):raise ValueError('Terminal outcome inventory/count differs')
    unexpected=[p.name for p in (run/'outcomes').iterdir() if not p.is_file() or p.suffix!='.json']
    if unexpected:raise ValueError('Unexpected/partial outcome files: '+repr(unexpected))
    audit_rows={r['storage_id']:r for r in recovery['model_file_audits']}
    if set(audit_rows)!=set(identities):raise ValueError('Model-file audit inventory differs')
    reused={r['id']:r for r in recovery['reused_completed_outcomes']};rows=[]
    for meta in expected:
        sid=meta['storage_id'];children=list((run/'models'/sid).iterdir())
        if len(children)!=1 or not children[0].is_dir():raise ValueError('Expected exactly one expanded model project')
        project=children[0];actual_files=inventory(project);pinned=audit_rows[sid]['regenerated_files']
        if actual_files!=pinned:raise ValueError('Model files changed after verified preparation: '+meta['id'])
        outcome=run/'outcomes'/(sid+'.json');before=sha(outcome)
        data=verify_completed(outcome,meta,Bundle.load(project),{'identical':actual_files==pinned})
        if set(data['checkers'])!=CHECKERS:raise ValueError('Checker fields differ: '+meta['id'])
        if sha(outcome)!=before:raise ValueError('Outcome changed during audit')
        reuse=reused.get(meta['id'])
        if reuse and before!=reuse['sha256']:raise ValueError('Copied observation changed')
        rows.append({'id':meta['id'],'storage_id':sid,'outcome_sha256':before,'model_sha256':data['model_sha256'],'files_verified':len(actual_files),'pair_count':data['probe_count'],'normal_variant_cells':5*data['probe_count'],'stale_backend_cells':2*data['probe_count'],'setup_status':data['checkers']['backend_setup']['status'],'reused_observation':reuse is not None,'independent_disagreements':len(data['independent_disagreements'])})
    return {'utc':datetime.now(timezone.utc).isoformat(),'run_dir':run.relative_to(ROOT).as_posix(),'status':'terminal coverage and prepared-file pins verified','models':len(rows),'pairs':sum(r['pair_count'] for r in rows),'normal_variant_cells':sum(r['normal_variant_cells'] for r in rows),'stale_backend_cells':sum(r['stale_backend_cells'] for r in rows),'reused_observations':sum(r['reused_observation'] for r in rows),'checker_fields':sorted(CHECKERS),'rows':rows,'input_sha256':{(run/name).relative_to(ROOT).as_posix():sha(run/name) for name in ['summary.json','mutation_manifest.json','recovery_manifest.json']},'verification_source_sha256':{name:sha(ROOT/name) for name in ['experiments/audit_wp6_completed_recovery.py','experiments/recover_mutation_run.py','experiments/mutations.py']},'scope':'Completeness/provenance audit only; no fresh evaluation, label change, additional room or publication/concurrency claim.'}
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run-dir',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if a.output.exists():raise FileExistsError(a.output)
    result=audit(a.run_dir)
    with a.output.open('x',encoding='utf8') as f:json.dump(result,f,indent=2);f.write('\n')
    print(json.dumps({k:v for k,v in result.items() if k not in ['rows','input_sha256','verification_source_sha256','checker_fields']}))
if __name__=='__main__':main()

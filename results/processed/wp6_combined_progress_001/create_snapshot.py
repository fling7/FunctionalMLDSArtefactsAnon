from pathlib import Path
import json, hashlib, sys, time
from datetime import datetime, timezone
ROOT=Path.cwd();sys.path.insert(0,str(ROOT))
from experiments.detection_matrix import aggregate
from experiments.report_mutation_analysis import generate
OUT=ROOT/'results/processed/wp6_combined_progress_001'
SOURCE_SPECS=['results/raw/wp6_corpus_original_terminal_v3.json=37ccbd68d240766c322118ecd9e01015a767af857e0cb38974dc9ad34de52513','results/raw/wp6_swap_geometry_sources_v2.json=3b99315a082ab084cdac2087317f6a4c7b8b11111bd9afd7f49a33feb9e77a50']
def sha(raw):return hashlib.sha256(raw).hexdigest()
cutoff=time.time();timestamp=datetime.fromtimestamp(cutoff,timezone.utc).isoformat();runs=[];inventory=[]
for name in ['wp6_example_combined_recovery_v1','wp6_generated_combined_recovery_v1']:
    origin=ROOT/'results/raw'/name;dest=OUT/'snapshots'/name;dest.mkdir(parents=True,exist_ok=False);(dest/'outcomes').mkdir()
    paths=[origin/'mutation_manifest.json',*sorted((origin/'outcomes').glob('*.json')),*sorted((origin/'worker_failures').glob('*.json'))]
    hashes={};excluded=[]
    for path in paths:
        if path.stat().st_mtime>cutoff-5:
            excluded.append({'path':path.relative_to(origin).as_posix(),'reason':'within five-second stability margin at snapshot cutoff; retained in live run'});continue
        raw=path.read_bytes();json.loads(raw)
        if path.read_bytes()!=raw:raise ValueError('Input changed while snapshotting: '+str(path))
        relative=path.relative_to(origin);target=dest/relative;target.parent.mkdir(parents=True,exist_ok=True)
        with target.open('xb') as f:f.write(raw)
        assert target.read_bytes()==raw
        hashes[relative.as_posix()]=sha(raw)
    assert 'mutation_manifest.json' in hashes
    provenance={'source_run':origin.relative_to(ROOT).as_posix(),'snapshot_utc':timestamp,'condition':'Explicit incomplete progress snapshot; every stable completed outcome at cutoff, no sampling by result; latest recovery rows only','copied_sha256':hashes,'stability_margin_seconds':5,'excluded_recent_files':excluded}
    (dest/'snapshot_provenance.json').write_text(json.dumps(provenance,indent=2)+'\n',encoding='utf8')
    summary=aggregate(dest);inventory.append({'source':provenance['source_run'],'snapshot':dest.relative_to(ROOT).as_posix(),'completed':summary['models_evaluated'],'planned':summary['planned_model_evaluations'],'evaluation_complete':summary['evaluation_complete'],'summary_sha256':sha((dest/'summary.json').read_bytes()),'source_hashes':hashes,'excluded_recent_files':excluded});runs.append(dest)
result=generate(runs,OUT/'MUTATION_ANALYSIS.md',OUT/'tables',OUT/'wp6_mutation_summary.json',[ROOT/'results/raw/wp6_swap_geometry_snapshot_004/geometry.json'],SOURCE_SPECS)
record={'utc':timestamp,'snapshots':inventory,'source_manifest_specifications':SOURCE_SPECS,'geometry':'results/raw/wp6_swap_geometry_snapshot_004/geometry.json','script_sha256':sha(Path(__file__).read_bytes()),'report_sha256':sha((OUT/'MUTATION_ANALYSIS.md').read_bytes()),'source_changes':False,'paid_calls':0}
(OUT/'invocation.json').write_text(json.dumps(record,indent=2)+'\n',encoding='utf8')
print(json.dumps({'snapshots':[{k:v for k,v in r.items() if k not in ('source_hashes',)} for r in inventory],'report':(OUT/'MUTATION_ANALYSIS.md').relative_to(ROOT).as_posix()},indent=2))

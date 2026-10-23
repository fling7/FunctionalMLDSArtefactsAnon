from pathlib import Path
import hashlib,json
p=Path(__file__).resolve().parent
m=json.loads((p/'MANIFEST.json').read_text(encoding='utf-8'))
assert {f.relative_to(p).as_posix() for f in p.rglob('*') if f.is_file()} == set(m['files'])|{'MANIFEST.json'}
for n,v in m['files'].items():
 b=(p/n).read_bytes(); assert len(b)==v['bytes'] and hashlib.sha256(b).hexdigest()==v['sha256'],n
read=lambda n:[json.loads(x) for x in (p/n).read_text(encoding='utf-8').splitlines() if x]
h=read('http_fixed600.jsonl');e=read('evolution_pairs_103.jsonl');c=read('completion57_coverage.jsonl')
assert len(h)==600 and sum(r['valid_real_generation'] is True for r in h)==379 and sum(r['committed'] is True for r in h)==593
assert sum(z['status']!='TOKEN_COUNT_ERROR' for r in h for z in r['calls'])==390
assert len(e)==103 and sum(r['independent_comparable_pair'] is True for r in e)==49
assert len(c)==57 and sum(r.get('scientific_status')=='success' for r in c)==8 and sum(r.get('scientific_status')=='failed' for r in c)==11
assert len(read('routing_primary_525.jsonl'))==525 and len(read('natural_four_probes_183.jsonl'))==183
print(json.dumps({'status':'PASS','verified_files':len(m['files']),'http_slots':600,'valid_generations':379,'native_commits':593,'evolution_pairs':103,'comparable_pairs':49,'completion_identities':57}))

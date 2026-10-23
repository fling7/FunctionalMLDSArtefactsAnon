"""Regenerate small example-derived Gate 0 fixtures; no backend imports."""
from __future__ import annotations
import copy
import json
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.routing_verifier import DIGEST_SCHEME, serialization_digest
SOURCE = ROOT / 'app/backend_root/agent_backend/projects/classroom_dinosaur'
OUT = ROOT / 'tests/fixtures/routing'


def generate() -> None:
    source = json.loads((SOURCE / 'roomcontract.v2.instance.json').read_text(encoding='utf-8'))
    trace = json.loads((SOURCE / 'trace_map.v2.json').read_text(encoding='utf-8'))
    index = {o['id']: o for o in source['objects']}
    target = next(o for o in source['objects'] if o.get('entityRole') == 'sceneObject')
    provider = next(o for o in source['objects'] if o.get('type') == 'Agent' and target['id'] in o.get('groundedAsset', []))
    other = next(o for o in source['objects'] if o.get('type') == 'Agent' and o != provider)
    group = index[target['objectGroup'][0]]
    zone = next(o for o in source['objects'] if o.get('kind') == 'zone' and target['sourceId'] in o.get('sourceObjectId', []))
    path = next(r for r in trace['runtime_actions'] if r.get('action_kind') == 'chat' and r.get('provider_entity_id') == provider['id'] and target['id'] in r.get('target_ids', []))
    ids = [provider['id'], other['id'], target['id'], group['id'], zone['id']] + [path[k] for k in ['scenario_step_id','capability_use_id','capability_id','runtime_binding_id','runtime_action_id']]
    action = index[path['runtime_action_id']]
    ids += action.get('locator', []) + action.get('inputSchema', []) + action.get('outputSchema', [])
    rows = [copy.deepcopy(index[i]) for i in dict.fromkeys(ids)]
    by = {o['id']: o for o in rows}
    for a in [provider, other]:
        by[a['id']]['groundedAsset'] = [target['id']] if a == provider else []
        by[a['id']]['groundedObjectGroup'] = []
        by[a['id']]['responsibleZone'] = []
        by[a['id']]['handoffTarget'] = [other['id'] if a == provider else provider['id']]
        by[a['id']]['providedCapability'] = [path['capability_id']] if a == provider else []
    by[target['id']]['objectGroup'] = [group['id']]
    by[group['id']]['sourceObjectId'] = [target['sourceId']]
    by[zone['id']]['sourceObjectId'] = [target['sourceId']]
    by[path['capability_use_id']]['target'] = [target['id']]
    by[path['scenario_step_id']]['capabilityUse'] = [path['capability_use_id']]
    by[path['runtime_binding_id']]['runtimeAction'] = [path['runtime_action_id']]
    projection = copy.deepcopy(path)
    projection['target_ids'] = [target['id']]
    base = {'provenance': 'Small routing-semantic projection derived from the supplied classroom example; not a full authoring fixture.', 'instance': {'fixture_profile':'executable', 'objects': rows}, 'trace': {'runtime_actions':[projection], 'digest_scheme': DIGEST_SCHEME}, 'project': {'roomcontract_digest_scheme': DIGEST_SCHEME}}
    OUT.mkdir(parents=True, exist_ok=True)
    def write(name, bundle):
        raw = (json.dumps(bundle['instance'],indent=2,sort_keys=True)+'\n').encode('utf-8')
        digest = serialization_digest(raw)
        bundle['trace']['model_sha256'] = digest
        bundle['project']['roomcontract_model_sha256'] = digest
        (OUT / (name+'.json')).write_text(json.dumps(bundle,indent=2,sort_keys=True)+'\n',encoding='utf-8',newline='\n')
    write('pass',copy.deepcopy(base))
    for number in [64,65,75,76,77,78,79,80,81]:
        bundle=copy.deepcopy(base)
        by={o['id']:o for o in bundle['instance']['objects']}
        a=by[provider['id']]
        b=by[other['id']]
        if number==64:
            a['providedCapability']=[]
            by[path['scenario_step_id']]['performedBy']=[]
        elif number==65:
            by[path['capability_use_id']]['provider']=[]
        elif number==75: b['groundedAsset']=[target['id']]
        elif number==76: a['groundedAsset']=[]
        elif number==77: by[path['runtime_binding_id']]['runtimeAction']=[]
        elif number==78: a['handoffTarget']=[a['id'],a['id'],target['id']]
        elif number==79:
            a['groundedAsset']=[]
            a['groundedObjectGroup']=[group['id']]
            b['groundedObjectGroup']=[group['id']]
        elif number==80: b['handoffTarget']=[]
        elif number==81: bundle['project'].pop('roomcontract_digest_scheme')
        write(f'inv{number:03d}_fail',bundle)
    manifest={'source_model':'app/backend_root/agent_backend/projects/classroom_dinosaur/roomcontract.v2.instance.json','generator':'tools/generate_routing_fixtures.py','passing_fixture':'pass.json','negative_fixtures':[f'inv{i:03d}_fail.json' for i in [64,65,75,76,77,78,79,80,81]],'note':'INV-079 warning and INV-080 report are nonblocking. Each negative fixture can trigger additional checks.'}
    (OUT/'manifest.json').write_text(json.dumps(manifest,indent=2,sort_keys=True)+'\n',encoding='utf-8',newline='\n')

if __name__=='__main__': generate()

from __future__ import annotations
import copy
import json
import subprocess
import sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.dynamic_functional_rdl_v2_model import MODEL
from tools.routing_verifier import CHECK_REGISTRY, NativeRoutingIndex, load_and_verify, lookup_route, serialization_digest, verify_routing
from tools.validate_dynamic_functional_rdl_v2 import InstanceValidator, validate_routing_publication
FIXTURES = ROOT / 'tests/fixtures/routing'


def fixture(name='pass'):
    return json.loads((FIXTURES / (name+'.json')).read_text(encoding='utf-8'))


def verify(bundle):
    raw = (json.dumps(bundle['instance'],indent=2,sort_keys=True)+'\n').encode('utf-8')
    return verify_routing(bundle['instance'],bundle['trace'],model_sha256=serialization_digest(raw),project=bundle['project'],model_bytes=raw)


@pytest.mark.parametrize('number',range(75,82))
def test_each_new_invariant_pass_and_fail(number):
    inv=f'INV-{number:03d}'
    assert verify(fixture())['checks'][inv]['status']=='pass'
    report=verify(fixture(f'inv{number:03d}_fail'))
    assert report['checks'][inv]['status']=='fail'
    assert any(i['code']==CHECK_REGISTRY[inv]['code'] for i in report['issues'])


@pytest.mark.parametrize('number,codes',[(64,{'ICAP004','ICAP005'}),(65,{'ICAP002'})])
def test_existing_invariant_evidence(number,codes):
    passing=InstanceValidator(MODEL,fixture()['instance'])
    passing.check_capability_uses()
    assert not passing.report.codes() & codes
    failing=InstanceValidator(MODEL,fixture(f'inv{number:03d}_fail')['instance'])
    failing.check_capability_uses()
    assert codes <= failing.report.codes()


def test_native_path_authority_and_ambiguity():
    bundle=fixture()
    index=NativeRoutingIndex(bundle['instance'],bundle['trace'])
    target=next(iter(index.objects))
    provider=index.ownership(target)[1][0]
    entry=bundle['trace']['runtime_actions'][0]
    assert index.answering_path(provider,target)==(None,entry['runtime_action_id'])
    bundle['trace']['runtime_actions'].append(copy.deepcopy(entry))
    assert NativeRoutingIndex(bundle['instance'],bundle['trace']).answering_path(provider,target)[0]=='E_ACTION_AMBIGUOUS'
    bundle=fixture()
    use=next(o for o in bundle['instance']['objects'] if o['type']=='CapabilityUse')
    use['typeRef']=[]
    assert NativeRoutingIndex(bundle['instance'],bundle['trace']).answering_path(provider,target)[0]=='E_NO_DECLARED_ACTION'


def test_answering_designation_excludes_handoff_endpoint():
    bundle=fixture()
    index=NativeRoutingIndex(bundle['instance'],bundle['trace'])
    target=next(iter(index.objects))
    provider=index.ownership(target)[1][0]
    action=index.by_id[bundle['trace']['runtime_actions'][0]['runtime_action_id']]
    schema=index.by_id[action['inputSchema'][0]]
    declaration=json.loads(schema['text'])
    declaration['applicationActionKind']='handoff'
    schema['text']=json.dumps(declaration)
    assert NativeRoutingIndex(bundle['instance'],bundle['trace']).answering_path(provider,target)[0]=='E_NO_DECLARED_ACTION'


def test_duplicate_provider_reference_is_ambiguous():
    bundle=fixture()
    index=NativeRoutingIndex(bundle['instance'],bundle['trace'])
    target=next(iter(index.objects))
    provider=index.ownership(target)[1][0]
    use=next(o for o in bundle['instance']['objects'] if o['type']=='CapabilityUse')
    use['provider']*=2
    assert NativeRoutingIndex(bundle['instance'],bundle['trace']).answering_path(provider,target)[0]=='E_ACTION_AMBIGUOUS'


def test_specificity_sets_and_no_fallthrough():
    bundle=fixture()
    index=NativeRoutingIndex(bundle['instance'],bundle['trace'])
    target=next(iter(index.objects))
    provider=index.ownership(target)[1][0]
    other=next(a for a in index.agents if a!=provider)
    group=next(iter(index.groups))
    zone=next(iter(index.zones))
    index.agents[provider]['groundedObjectGroup']=[group]
    index.agents[other]['groundedObjectGroup']=[group]
    index.agents[provider]['responsibleZone']=[zone]
    report=verify_routing(bundle['instance'],bundle['trace'],model_sha256='00')
    assert report['ok']
    assert report['latent_ambiguities'][0]['shielded']
    index.agents[provider]['groundedAsset']=[]
    report=verify_routing(bundle['instance'],bundle['trace'],model_sha256='00')
    assert all(row[target]['reason']=='E_AMBIGUOUS_OWNER' for row in report['routing_table'].values())
    index.agents[other]['groundedObjectGroup']=[]
    index.agents[provider]['groundedObjectGroup']*=2
    assert NativeRoutingIndex(bundle['instance'],bundle['trace']).ownership(target)==('group',[provider])


def test_group_projection_does_not_create_membership():
    bundle=fixture()
    index=NativeRoutingIndex(bundle['instance'],bundle['trace'])
    target=next(iter(index.objects))
    provider=index.ownership(target)[1][0]
    index.agents[provider]['groundedAsset']=[]
    index.agents[provider]['groundedObjectGroup']=[next(iter(index.groups))]
    index.objects[target]['objectGroup']=[]
    assert NativeRoutingIndex(bundle['instance'],bundle['trace']).ownership(target)==(None,[])


def test_table_precedence_and_runtime_obligations():
    report=verify(fixture('inv080_fail'))
    assert report['ok']  # no-path report is not a publish-blocking invariant
    assert any(x['reason']=='E_NO_HANDOFF_PATH' for row in report['routing_table'].values() for x in row.values())
    assert lookup_route(report,'missing','missing')['reason']=='E_ACTIVE_AGENT_UNKNOWN'
    start=next(iter(report['routing_table']))
    assert lookup_route(report,start,'missing')['reason']=='E_UNKNOWN_ENTITY'
    bundle=fixture()
    report=verify_routing(bundle['instance'],bundle['trace'],model_sha256='00')
    assert report['checks']['INV-081']['status']=='not evaluated'


def test_digest_normalization_and_file_api(tmp_path):
    bundle=fixture()
    raw=(json.dumps(bundle['instance'],indent=2,sort_keys=True)+'\n').encode('utf-8')
    assert serialization_digest(raw)==serialization_digest(raw.replace(b'\n',b'\r\n'))
    assert serialization_digest(raw)!=serialization_digest(raw+b' ')
    paths=[tmp_path/name for name in ['instance.json','trace.json','project.json']]
    paths[0].write_bytes(raw.replace(b'\n',b'\r\n'))
    for path,key in zip(paths[1:],['trace','project']): path.write_text(json.dumps(bundle[key]),encoding='utf-8')
    report=load_and_verify(*paths)
    assert report['ok']
    assert validate_routing_publication(*paths).ok
    out=tmp_path/'routing.json'
    result=subprocess.run([sys.executable,str(ROOT/'tools/routing_verifier.py'),'--instance',str(paths[0]),'--trace',str(paths[1]),'--project',str(paths[2]),'--output',str(out)],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    first=out.read_bytes()
    subprocess.run(result.args,check=True,capture_output=True)
    assert out.read_bytes()==first
    assert list(json.loads(first)['by_digest'])==[report['model_sha256']]


def test_malformed_native_input_fails_closed():
    bundle=fixture()
    bundle['instance']['objects'].append(copy.deepcopy(bundle['instance']['objects'][0]))
    report=verify(bundle)
    assert not report['ok']
    assert report['issues'][0]['code']=='E_PUBLICATION_INCONSISTENT'


def test_gate_zero_does_not_import_backend():
    import ast
    tree=ast.parse((ROOT/'tools/routing_verifier.py').read_text(encoding='utf-8'))
    imports=[node.module or '' for node in ast.walk(tree) if isinstance(node,ast.ImportFrom)]
    imports += [name.name for node in ast.walk(tree) if isinstance(node,ast.Import) for name in node.names]
    assert not any('backend' in name for name in imports)


def test_duplicate_wire_active_agent_identity():
    bundle=fixture()
    agents=[o for o in bundle['instance']['objects'] if o['type']=='Agent']
    agents[1]['sourceAgentId']=agents[0]['sourceAgentId']
    report=verify_routing(bundle['instance'],bundle['trace'],model_sha256='00')
    assert not report['ok']
    assert all(row['reason']=='E_ACTIVE_AGENT_UNKNOWN' for row in report['routing_table'][agents[0]['sourceAgentId']].values())


def test_trace_only_broken_use_does_not_add_native_path():
    bundle=fixture()
    index=NativeRoutingIndex(bundle['instance'],bundle['trace'])
    target=next(iter(index.objects))
    provider=index.ownership(target)[1][0]
    original=bundle['trace']['runtime_actions'][0]
    use=copy.deepcopy(index.by_id[original['capability_use_id']])
    use['id']='BROKEN-USE'
    use['typeRef']=['ABSENT-CAPABILITY']
    bundle['instance']['objects'].append(use)
    projection=copy.deepcopy(original)
    projection['capability_use_id']=use['id']
    bundle['trace']['runtime_actions'].append(projection)
    assert NativeRoutingIndex(bundle['instance'],bundle['trace']).answering_path(provider,target)==(None,original['runtime_action_id'])
    use['typeRef']=[original['capability_id']]
    # It still has no ScenarioStep, and therefore no complete native path.
    assert NativeRoutingIndex(bundle['instance'],bundle['trace']).answering_path(provider,target)==(None,original['runtime_action_id'])

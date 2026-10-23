"""Local tests built independently from the allowed handwritten fixtures."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import unittest

from reference import evaluate


ROOT = Path(__file__).resolve().parent
FIXTURES = json.loads((ROOT / 'fixtures.json').read_text(encoding='utf-8-sig'))
BASE = FIXTURES[0]


def fixture(name='local'):
    return copy.deepcopy(next(f for f in FIXTURES if f['name'] == name))


def obj(f, identity):
    return next(o for o in f['instance']['objects'] if o['id'] == identity)


def run(f):
    return evaluate(f['instance'], f['trace'], f['request'], f['session'])


def rejection(reason):
    return dict(decision='REJECT', reason=reason, provider=None, action=None)


def schema(f, value):
    obj(f, 'IS')['text'] = json.dumps(value)


def other_scene(f):
    record = copy.deepcopy(obj(f, 'T'))
    record.update(id='T2', sourceId='object2')
    f['instance']['objects'].append(record)


class AdmissionTests(unittest.TestCase):
    def assertReason(self, f, reason):
        self.assertEqual(run(f), rejection(reason))

    def assertLocal(self, f):
        self.assertEqual(run(f), BASE['expected'])

    def test_supplied_handwritten_fixtures(self):
        for f in FIXTURES:
            with self.subTest(name=f['name']):
                self.assertEqual(run(f), f['expected'])

    def test_digest_comparison_and_order(self):
        f=fixture(); f['request']['spatial_context']['model_sha256']='a'*64
        f['trace']['model_sha256']='B'*64
        self.assertLocal(f)
        for value in (None, '', 'A'*63, 'Z'*64, 17):
            with self.subTest(value=value):
                f=fixture(); f['request']['spatial_context']['model_sha256']=value
                f['request']['spatial_context']['state']='none'
                self.assertReason(f, 'E_STALE_DIGEST')
        f=fixture('stale'); f['instance']['objects'].append(copy.deepcopy(obj(f,'A')))
        self.assertReason(f, 'E_STALE_DIGEST')

    def test_identity_forms_aliases_and_mismatch(self):
        for removed in ('entity_id','source_object_id'):
            with self.subTest(removed=removed):
                f=fixture(); del f['request']['spatial_context'][removed]; self.assertLocal(f)
        f=fixture(); sc=f['request']['spatial_context']; sc['source_id']=sc.pop('source_object_id'); self.assertLocal(f)
        f=fixture(); f['request']['spatial_context']['source_id']='object'; self.assertLocal(f)
        f=fixture(); other_scene(f); f['request']['spatial_context']['source_object_id']='object2'
        self.assertReason(f,'E_ID_MISMATCH')
        f=fixture(); other_scene(f); f['request']['spatial_context']['source_id']='object2'
        self.assertReason(f,'E_ID_MISMATCH')
        for key in ('entity_id','source_object_id','source_id'):
            with self.subTest(unknown=key):
                f=fixture(); f['request']['spatial_context'][key]='unknown'; self.assertReason(f,'E_UNKNOWN_ENTITY')
        f=fixture(); f['request']['spatial_context']['entity_id']='G'; self.assertReason(f,'E_UNKNOWN_ENTITY')
        f=fixture(); other_scene(f); obj(f,'T2')['sourceId']='object'; self.assertReason(f,'E_UNKNOWN_ENTITY')
        f=fixture(); sc=f['request']['spatial_context']; del sc['entity_id']; del sc['source_object_id']
        self.assertReason(f,'E_UNKNOWN_ENTITY')

    def test_selection_state_flags_candidates_and_priority(self):
        edits=[{'state':'none'},{'state':'ambiguous'},{'state':None}, {'ambiguous':True},
               {'ambiguity':True},{'ambiguity':{'ambiguous':True}}, {'ambiguity':{'is_ambiguous':1}},
               {'candidate_entity_ids':[]},{'candidate_entity_ids':['T','T']},
               {'candidate_entity_ids':['T2']},{'candidate_entity_ids':'T'}, {'entity_id':['T']}]
        for edit in edits:
            with self.subTest(edit=edit):
                f=fixture(); f['request']['spatial_context'].update(edit); self.assertReason(f,'E_SELECTION_STATE')
        for edit in ({'ambiguous':False},{'ambiguity':False},{'ambiguity':{}},
                     {'ambiguity':{'reason':'diagnostic only'}},{'ambiguity_reason':'diagnostic'},
                     {'candidate_entity_ids':['T']}):
            with self.subTest(allowed=edit):
                f=fixture(); f['request']['spatial_context'].update(edit); self.assertLocal(f)
        f=fixture(); f['request']['spatial_context'].update(state='none',entity_id='unknown')
        self.assertReason(f,'E_SELECTION_STATE')
        f=fixture(); sc=f['request']['spatial_context']; del sc['entity_id']; sc['candidate_entity_ids']=['T2']
        self.assertReason(f,'E_SELECTION_STATE')
        f=fixture(); f['request']['interaction_mode']='non_deictic'; del f['request']['spatial_context']
        self.assertReason(f,'E_SELECTION_STATE')

    def test_active_agent_and_server_strict(self):
        f=fixture('unowned'); f['request']['active_agent_id']='missing'; self.assertReason(f,'E_ACTIVE_AGENT_UNKNOWN')
        for active in ('missing','b',None):
            with self.subTest(server=active):
                f=fixture(); f['session'].update(active_agent_mode='server_strict',active_agent_id=active)
                self.assertReason(f,'E_ACTIVE_AGENT_MISMATCH')
        f=fixture(); f['session'].update(active_agent_mode='server_strict',active_agent_id='a'); self.assertLocal(f)
        f=fixture(); f['session'].update(active_agent_mode='client',active_agent_id='b'); self.assertLocal(f)
        f=fixture(); duplicate=copy.deepcopy(obj(f,'A')); duplicate['id']='OTHER'; f['instance']['objects'].append(duplicate)
        self.assertReason(f,'E_ACTIVE_AGENT_UNKNOWN')

    def test_ownership_specificity_and_sets(self):
        f=fixture('unowned'); obj(f,'A')['responsibleZone']=['Z']; self.assertLocal(f)
        f=fixture(); obj(f,'A')['groundedObjectGroup']=['G']; obj(f,'B')['groundedObjectGroup']=['G']; self.assertLocal(f)
        f=fixture('ambiguous_asset'); obj(f,'A')['groundedObjectGroup']=['G']; self.assertReason(f,'E_AMBIGUOUS_OWNER')
        f=fixture('ambiguous_group'); self.assertReason(f,'E_AMBIGUOUS_OWNER')
        f=fixture('unowned'); obj(f,'A')['responsibleZone']=['Z']; obj(f,'B')['responsibleZone']=['Z']
        self.assertReason(f,'E_AMBIGUOUS_OWNER')
        f=fixture('group_fallback'); g=copy.deepcopy(obj(f,'G')); g['id']='G2'; f['instance']['objects'].append(g)
        obj(f,'T')['objectGroup'].append('G2'); obj(f,'A')['groundedObjectGroup'].append('G2'); self.assertLocal(f)
        f=fixture('group_fallback'); obj(f,'T')['objectGroup']=[]; self.assertReason(f,'E_UNOWNED')
        f=fixture('group_fallback'); obj(f,'G')['sourceObjectId']=[]; self.assertLocal(f)
        f=fixture('unowned'); obj(f,'A')['responsibleZone']=['Z']; obj(f,'Z')['sourceObjectId']=[]
        self.assertReason(f,'E_UNOWNED')

    def test_handoff_is_direct_and_directional(self):
        f=fixture('unreachable'); self.assertReason(f,'E_NO_HANDOFF_PATH')
        f=fixture(); c=copy.deepcopy(obj(f,'B')); c.update(id='C_AGENT',sourceId='c',sourceAgentId='c',handoffTarget=['B'])
        f['instance']['objects'].append(c); f['request']['active_agent_id']='c'; self.assertReason(f,'E_NO_HANDOFF_PATH')
        c['handoffTarget'].append('A'); result=run(f)
        self.assertEqual(result['decision'],'ANSWER_AFTER_HANDOFF'); self.assertEqual(result['provider'],'a')
        f=fixture(); obj(f,'A')['handoffTarget']=[]; self.assertLocal(f)

    def test_missing_native_path_links(self):
        edits=[('S','capabilityUse',[]),('S','capabilityUse',['RA']),('U','typeRef',[]),
               ('U','provider',['B']),('U','target',['G','Z']),('RB','capability',[]),
               ('RB','runtimeAction',[]),('RA','locator',[]),
               ('A','providedCapability',[])]
        for identity,key,value in edits:
            with self.subTest(identity=identity,key=key):
                f=fixture(); obj(f,identity)[key]=value; self.assertReason(f,'E_NO_DECLARED_ACTION')
        for identity in ('S','U','C','RB','RA','L'):
            with self.subTest(deleted=identity):
                f=fixture(); f['instance']['objects']=[r for r in f['instance']['objects'] if r['id']!=identity]
                self.assertReason(f,'E_NO_DECLARED_ACTION')
        f=fixture(); obj(f,'S')['runtimeAction']=['RA']; obj(f,'S')['capabilityUse']=[]
        self.assertReason(f,'E_NO_DECLARED_ACTION')

    def test_multiple_native_answering_paths(self):
        f=fixture(); extra=copy.deepcopy(obj(f,'U')); extra['id']='U2'; f['instance']['objects'].append(extra)
        obj(f,'S')['capabilityUse'].append('U2'); self.assertReason(f,'E_ACTION_AMBIGUOUS')
        f=fixture(); extra=copy.deepcopy(obj(f,'S')); extra['id']='S2'; f['instance']['objects'].append(extra)
        self.assertReason(f,'E_ACTION_AMBIGUOUS')
        f=fixture(); extra=copy.deepcopy(obj(f,'RB')); extra['id']='RB2'; f['instance']['objects'].append(extra)
        self.assertReason(f,'E_ACTION_AMBIGUOUS')
        f=fixture(); extra=copy.deepcopy(obj(f,'RA')); extra['id']='RA2'; f['instance']['objects'].append(extra)
        obj(f,'RB')['runtimeAction'].append('RA2'); self.assertReason(f,'E_ACTION_AMBIGUOUS')
        for identity,key,value in [('U','typeRef',['C','C']),('U','provider',['A','B']),
                                   ('S','capabilityUse',['U','U']),('RB','runtimeAction',['RA','RA'])]:
            with self.subTest(repeated=(identity,key)):
                f=fixture(); obj(f,identity)[key]=value; self.assertReason(f,'E_ACTION_AMBIGUOUS')

    def test_broken_extra_declarations_do_not_add_complete_paths(self):
        f=fixture(); extra=copy.deepcopy(obj(f,'U')); extra.update(id='U_BROKEN',typeRef=['C_MISSING'])
        f['instance']['objects'].extend([extra,{'id':'RB_BROKEN','type':'RuntimeBinding','capability':['C_MISSING'],'runtimeAction':['RA']}])
        obj(f,'S')['capabilityUse'].append('U_BROKEN'); self.assertLocal(f)
        f=fixture(); f['request']['provider']='b'; f['request']['provider_id']='b'; self.assertLocal(f)

    def test_infrastructure_and_handoff_not_answering(self):
        f=fixture(); f['instance']['objects'].extend([
            {'id':'RA_TOOL','type':'RuntimeAction','locator':['L_TOOL'],'inputSchema':['IS_TOOL']},
            {'id':'L_TOOL','type':'RuntimeActionLocator','kind':'tool','value':'example.tool'},
            {'id':'IS_TOOL','type':'SchemaReference','uri':'json','text':'{}'}])
        obj(f,'RB')['runtimeAction'].append('RA_TOOL'); self.assertLocal(f)
        f=fixture(); schema(f,{'type':'object','applicationActionKind':'handoff'}); self.assertReason(f,'E_NO_DECLARED_ACTION')
        f=fixture(); schema(f,{'type':'object','applicationActionKind':'chat'})
        obj(f,'L').update(kind='tool',value='answer.tool')
        f['trace']['runtime_actions'][0]['locator']={'kind':'tool','value':'answer.tool'}; self.assertLocal(f)
        f=fixture(); extra=copy.deepcopy(obj(f,'U')); extra['id']='ORPHAN'; f['instance']['objects'].append(extra)
        self.assertLocal(f)

    def test_trace_corroboration_and_target_sets(self):
        f=fixture(); f['trace']['runtime_actions']=[]; self.assertReason(f,'E_NO_DECLARED_ACTION')
        for key in ('scenario_step_id','capability_use_id','capability_id','provider_entity_id',
                    'runtime_binding_id','runtime_action_id','action_kind'):
            with self.subTest(key=key):
                f=fixture(); f['trace']['runtime_actions'][0][key]='wrong'; self.assertReason(f,'E_NO_DECLARED_ACTION')
        f=fixture(); f['trace']['runtime_actions'][0]['target_ids']=['T']; self.assertReason(f,'E_NO_DECLARED_ACTION')
        f=fixture(); f['trace']['runtime_actions'][0]['locator']['value']='other'; self.assertLocal(f)
        f=fixture(); f['trace']['runtime_actions'].append(copy.deepcopy(f['trace']['runtime_actions'][0]))
        self.assertReason(f,'E_ACTION_AMBIGUOUS')
        f=fixture(); f['trace']['runtime_actions'][0]['target_ids']=['Z','T','G','T']; self.assertLocal(f)
        f=fixture(); fake=copy.deepcopy(f['trace']['runtime_actions'][0]); fake['capability_use_id']='ORPHAN'
        f['trace']['runtime_actions'].append(fake); self.assertLocal(f)

    def test_declared_schema_and_original_wire_request(self):
        for declaration in (False, {'type':'object','required':['missing']}, {'type':'array'}, {'type':17}):
            with self.subTest(schema=declaration):
                f=fixture(); schema(f,declaration); self.assertReason(f,'E_SCHEMA')
        f=fixture(); schema(f,True); self.assertLocal(f)
        f=fixture(); obj(f,'IS')['text']='{bad'; self.assertReason(f,'E_SCHEMA')
        f=fixture(); obj(f,'RA')['inputSchema']=[]; self.assertReason(f,'E_SCHEMA')
        f=fixture(); f['instance']['objects']=[r for r in f['instance']['objects'] if r['id']!='IS']; self.assertReason(f,'E_SCHEMA')
        f=fixture(); schema(f,{'$schema':'https://example.invalid/unknown-dialect'}); self.assertReason(f,'E_SCHEMA')
        f=fixture(); schema(f,{'type':'object','properties':{'active_agent_id':{'const':'b'}}})
        f['request']['active_agent_id']='b'; self.assertEqual(run(f)['decision'],'ANSWER_AFTER_HANDOFF')
        f=fixture(); schema(f,{'type':'object','modelBinding':{'runtimeActionId':'incorrect'},'unknownKeyword':False}); self.assertLocal(f)
        f=fixture(); schema(f,{'$defs':{'request':{'type':'object','required':['user_text']}},'$ref':'#/$defs/request'}); self.assertLocal(f)
        f=fixture(); schema(f,{'$ref':'https://example.invalid/must-not-be-fetched'}); self.assertReason(f,'E_SCHEMA')
        f=fixture(); f['request']['spatial_context']['distance_m']=float('nan'); self.assertReason(f,'E_SCHEMA')
        f=fixture('unowned'); schema(f,False); self.assertReason(f,'E_UNOWNED')
        f=fixture(); obj(f,'S')['capabilityUse']=[]; schema(f,False); self.assertReason(f,'E_NO_DECLARED_ACTION')

    def test_example_wire_schema_rejects_bad_geometry_and_text(self):
        instance=json.loads((ROOT/'example.instance.json').read_text(encoding='utf-8-sig'))
        trace=json.loads((ROOT/'example.trace.json').read_text(encoding='utf-8-sig'))
        by={o['id']:o for o in instance['objects']}
        row=next(row for row in trace['runtime_actions'] if row['action_kind']=='chat')
        target=next(by[x] for x in row['target_ids'] if by[x].get('entityRole')=='sceneObject')
        request=copy.deepcopy(BASE['request']); request['active_agent_id']=by[row['provider_entity_id']]['sourceAgentId']
        request['spatial_context'].update(model_sha256=trace['model_sha256'],entity_id=target['id'],source_object_id=target['sourceId'])
        session={'model_sha256':trace['model_sha256']}
        for context_edit in ({'distance_m':-1},{'distance_m':'1'},{'hit_position':{'x':0,'y':0}},
                             {'selection_modality':'invalid'},{'unexpected':True},{'ambiguous':'false'}):
            with self.subTest(context_edit=context_edit):
                changed=copy.deepcopy(request); changed['spatial_context'].update(context_edit)
                self.assertEqual(evaluate(instance,trace,changed,session),rejection('E_SCHEMA'))
        changed=copy.deepcopy(request); changed['user_text']=''
        self.assertEqual(evaluate(instance,trace,changed,session),rejection('E_SCHEMA'))
        changed=copy.deepcopy(request); del changed['spatial_context']['entity_id']
        self.assertEqual(evaluate(instance,trace,changed,session)['decision'],'ANSWER_LOCAL')

    def test_publication_shape_and_immutability(self):
        for bad in (None, [], {'objects':None}, {'objects':[None]}, {'objects':[{'id':'X'}]}):
            with self.subTest(bad=bad):
                f=fixture(); f['instance']=bad; self.assertReason(f,'E_PUBLICATION_INCONSISTENT')
        f=fixture(); f['instance']['objects'].append(copy.deepcopy(obj(f,'T'))); self.assertReason(f,'E_PUBLICATION_INCONSISTENT')
        for original in FIXTURES:
            f=copy.deepcopy(original); before=copy.deepcopy(f)
            first=run(f); second=run(f)
            self.assertEqual(first,second); self.assertEqual(f,before)

    def test_cli_file_stdin_and_errors(self):
        path=ROOT/'selftest_cli_input.json'; path.write_text(json.dumps(BASE),encoding='utf-8')
        command=[sys.executable,str(ROOT/'reference.py')]
        result=subprocess.run(command+[str(path)],capture_output=True,text=True,cwd=ROOT,check=False)
        self.assertEqual(result.returncode,0,result.stderr); self.assertEqual(json.loads(result.stdout),BASE['expected'])
        result=subprocess.run(command+['-'],input=json.dumps(BASE),capture_output=True,text=True,cwd=ROOT,check=False)
        self.assertEqual(result.returncode,0,result.stderr); self.assertEqual(json.loads(result.stdout),BASE['expected'])
        result=subprocess.run(command+['-'],input='not JSON',capture_output=True,text=True,cwd=ROOT,check=False)
        self.assertEqual(result.returncode,2); self.assertEqual(json.loads(result.stdout),rejection('E_PUBLICATION_INCONSISTENT'))

    def test_real_native_example_all_declared_chat_targets(self):
        instance=json.loads((ROOT/'example.instance.json').read_text(encoding='utf-8-sig'))
        trace=json.loads((ROOT/'example.trace.json').read_text(encoding='utf-8-sig'))
        by={o['id']:o for o in instance['objects']}
        rows=[row for row in trace['runtime_actions'] if row['action_kind']=='chat']
        self.assertEqual(len(rows),36)
        for row in rows:
            with self.subTest(use=row['capability_use_id']):
                target=next(by[x] for x in row['target_ids'] if by[x].get('entityRole')=='sceneObject')
                request=copy.deepcopy(BASE['request'])
                request['active_agent_id']=by[row['provider_entity_id']]['sourceAgentId']
                request['spatial_context'].update(model_sha256=trace['model_sha256'],entity_id=target['id'],source_object_id=target['sourceId'])
                actual=evaluate(instance,trace,request,{'model_sha256':trace['model_sha256']})
                self.assertEqual(actual,dict(decision='ANSWER_LOCAL',reason=None,
                    provider=request['active_agent_id'],action=row['runtime_action_id']))


if __name__=='__main__':
    unittest.main(verbosity=2)

"""Self-contained tests authored from the isolated specification and fixtures."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import unittest

from policy_adapter import evaluate

HERE = Path(__file__).resolve().parent
FIXTURES = json.loads((HERE / 'fixtures.json').read_text(encoding='utf-8-sig'))


def rejected(reason):
    return dict(decision='REJECT', reason=reason, provider=None, action=None)


def obj(case, identifier):
    return next(item for item in case['instance']['objects'] if item['id'] == identifier)


def remove(case, identifier):
    case['instance']['objects'] = [x for x in case['instance']['objects'] if x['id'] != identifier]


def schema(case, document):
    obj(case, 'IS')['text'] = json.dumps(document)


class AdmissionTests(unittest.TestCase):
    def setUp(self):
        self.case = copy.deepcopy(FIXTURES[0])
        self.expected = self.case['expected']
        self.spatial = self.case['request']['spatial_context']

    def check(self, reason=None, expected=None):
        before = copy.deepcopy(self.case)
        actual = evaluate(*(self.case[k] for k in ('instance','trace','request','session')))
        self.assertEqual(actual, expected or (rejected(reason) if reason else self.expected))
        self.assertEqual(self.case, before, 'evaluation mutated caller-owned inputs')

    def test_supplied_fixtures(self):
        for case in FIXTURES:
            with self.subTest(case=case['name']):
                self.assertEqual(evaluate(*(case[k] for k in ('instance','trace','request','session'))), case['expected'])

    def test_digest_case_insensitive(self):
        self.case['session']['model_sha256'] = 'a' * 64
        self.check()

    def test_trace_digest_is_not_current_pin(self):
        self.case['trace']['model_sha256'] = 'b' * 64
        self.check()

    def test_missing_digest(self):
        del self.spatial['model_sha256']; self.check('E_STALE_DIGEST')

    def test_nonhex_digest(self):
        self.spatial['model_sha256'] = self.case['session']['model_sha256'] = 'g' * 64
        self.check('E_STALE_DIGEST')

    def test_stale_before_all_other_gate_errors(self):
        self.spatial.update(model_sha256='B'*64,state='ambiguous',entity_id='unknown')
        self.case['request']['active_agent_id']='missing'; obj(self.case,'A')['groundedAsset']=[]
        self.case['trace']['runtime_actions']=[]; schema(self.case,False)
        self.check('E_STALE_DIGEST')

    def test_entity_only(self):
        del self.spatial['source_object_id']; self.check()

    def test_source_only(self):
        del self.spatial['entity_id']; self.check()

    def test_source_alias_only(self):
        del self.spatial['entity_id']; self.spatial['source_id']=self.spatial.pop('source_object_id'); self.check()

    def test_both_source_aliases(self):
        self.spatial['source_id']='object'; self.check()

    def test_unknown_entity(self):
        self.spatial['entity_id']='missing'; self.check('E_UNKNOWN_ENTITY')

    def test_unknown_source(self):
        self.spatial['source_object_id']='missing'; self.check('E_UNKNOWN_ENTITY')

    def test_no_identity(self):
        del self.spatial['source_object_id']; del self.spatial['entity_id']; self.check('E_UNKNOWN_ENTITY')

    def test_nonunique_source(self):
        other=copy.deepcopy(obj(self.case,'T')); other['id']='T2'; self.case['instance']['objects'].append(other)
        self.check('E_UNKNOWN_ENTITY')

    def test_identity_mismatch(self):
        other=copy.deepcopy(obj(self.case,'T')); other.update(id='T2',sourceId='other'); self.case['instance']['objects'].append(other)
        self.spatial['source_object_id']='other'; self.check('E_ID_MISMATCH')

    def test_alias_mismatch(self):
        other=copy.deepcopy(obj(self.case,'T')); other.update(id='T2',sourceId='other'); self.case['instance']['objects'].append(other)
        self.spatial['source_id']='other'; self.check('E_ID_MISMATCH')

    def test_identifier_type_is_selection_error(self):
        self.spatial['entity_id']=['T']; self.check('E_SELECTION_STATE')

    def test_non_deictic_scope(self):
        self.case['request']['interaction_mode']='non_deictic'; self.check('E_SELECTION_STATE')

    def test_state_before_unknown_identity(self):
        self.spatial.update(state='none',entity_id='missing'); self.check('E_SELECTION_STATE')

    def test_boolean_ambiguity_flags(self):
        for key in ('ambiguous','ambiguity'):
            with self.subTest(key=key):
                self.spatial[key]=True; self.check('E_SELECTION_STATE'); del self.spatial[key]

    def test_object_ambiguity_truthy_keys(self):
        for key in ('ambiguous','is_ambiguous'):
            with self.subTest(key=key):
                self.spatial['ambiguity']={key:'yes'}; self.check('E_SELECTION_STATE')

    def test_object_ambiguity_descriptive_only(self):
        self.spatial['ambiguity']={'reason':'a note','ambiguous':False,'is_ambiguous':0}; self.check()

    def test_singleton_candidate(self):
        self.spatial['candidate_entity_ids']=['T']; self.check()

    def test_invalid_candidates(self):
        for candidate in ([],['T','T'],['T','other'],['other'],None,'T',[12]):
            with self.subTest(candidate=candidate):
                self.spatial['candidate_entity_ids']=candidate; self.check('E_SELECTION_STATE')

    def test_active_unknown_before_ownership(self):
        self.case['request']['active_agent_id']='unknown'; obj(self.case,'A')['groundedAsset']=[]
        self.check('E_ACTIVE_AGENT_UNKNOWN')

    def test_active_duplicate_wire_id(self):
        obj(self.case,'B')['sourceAgentId']='a'; self.check('E_ACTIVE_AGENT_UNKNOWN')

    def test_server_strict_mismatch(self):
        self.case['session'].update(active_agent_mode='server_strict',active_agent_id='b')
        self.check('E_ACTIVE_AGENT_MISMATCH')

    def test_server_strict_unknown_client_first(self):
        self.case['session'].update(active_agent_mode='server_strict',active_agent_id='b')
        self.case['request']['active_agent_id']='unknown'; self.check('E_ACTIVE_AGENT_UNKNOWN')

    def test_client_mode_ignores_server_active(self):
        self.case['session'].update(active_agent_mode='client',active_agent_id='b'); self.check()

    def test_server_strict_matching(self):
        self.case['session'].update(active_agent_mode='server_strict',active_agent_id='a'); self.check()

    def test_asset_overrides_ambiguous_lower_levels(self):
        for who in ('A','B'):
            obj(self.case,who).update(groundedObjectGroup=['G'],responsibleZone=['Z'])
        self.check()

    def test_zone_fallback(self):
        obj(self.case,'A').update(groundedAsset=[],responsibleZone=['Z']); self.check()

    def test_zone_ambiguity(self):
        obj(self.case,'A').update(groundedAsset=[],responsibleZone=['Z']); obj(self.case,'B')['responsibleZone']=['Z']
        self.check('E_AMBIGUOUS_OWNER')

    def test_no_fallthrough_from_ambiguous_asset(self):
        obj(self.case,'B')['groundedAsset']=['T']; obj(self.case,'A')['responsibleZone']=['Z']
        self.check('E_AMBIGUOUS_OWNER')

    def test_group_projection_cannot_add_membership(self):
        obj(self.case,'T')['objectGroup']=[]; obj(self.case,'A').update(groundedAsset=[],groundedObjectGroup=['G'])
        self.check('E_UNOWNED')

    def test_same_agent_multiple_groups_is_one_owner(self):
        g=copy.deepcopy(obj(self.case,'G')); g['id']='G2'; self.case['instance']['objects'].append(g)
        obj(self.case,'T')['objectGroup']=['G','G2']; obj(self.case,'A').update(groundedAsset=[],groundedObjectGroup=['G','G2'])
        self.check()

    def test_no_two_hop_handoff(self):
        extra=copy.deepcopy(obj(self.case,'B')); extra.update(id='X',sourceId='x',sourceAgentId='x',handoffTarget=['A'])
        self.case['instance']['objects'].append(extra); obj(self.case,'B')['handoffTarget']=['X']
        self.case['request']['active_agent_id']='b'; self.check('E_NO_HANDOFF_PATH')

    def test_local_needs_no_self_edge(self):
        obj(self.case,'A')['handoffTarget']=[]; self.check()

    def test_missing_capability_use(self):
        remove(self.case,'U'); self.check('E_NO_DECLARED_ACTION')

    def test_missing_scenario_step(self):
        remove(self.case,'S'); self.check('E_NO_DECLARED_ACTION')

    def test_step_calling_action_directly_is_invalid(self):
        obj(self.case,'S')['capabilityUse']=[]; obj(self.case,'S')['runtimeAction']=['RA']; self.check('E_NO_DECLARED_ACTION')

    def test_group_only_use_target_is_invalid(self):
        obj(self.case,'U')['target']=['G','Z']; self.case['trace']['runtime_actions'][0]['target_ids']=['G','Z']
        self.check('E_NO_DECLARED_ACTION')

    def test_provider_must_declare_capability(self):
        obj(self.case,'A')['providedCapability']=[]; self.check('E_NO_DECLARED_ACTION')

    def test_missing_selected_links(self):
        for identifier,key in [('S','capabilityUse'),('U','typeRef'),('RB','capability'),('RB','runtimeAction')]:
            with self.subTest(link=(identifier,key)):
                saved=obj(self.case,identifier)[key]; obj(self.case,identifier)[key]=[]
                self.check('E_NO_DECLARED_ACTION'); obj(self.case,identifier)[key]=saved

    def test_missing_native_records(self):
        for identifier in ('C','RB','RA'):
            with self.subTest(identifier=identifier):
                saved=copy.deepcopy(self.case); remove(self.case,identifier); self.check('E_NO_DECLARED_ACTION'); self.case=saved

    def test_multiple_steps(self):
        s=copy.deepcopy(obj(self.case,'S')); s['id']='S2'; self.case['instance']['objects'].append(s)
        self.check('E_ACTION_AMBIGUOUS')

    def test_multiple_uses(self):
        u=copy.deepcopy(obj(self.case,'U')); u['id']='U2'; self.case['instance']['objects'].append(u)
        obj(self.case,'S')['capabilityUse'].append('U2'); self.check('E_ACTION_AMBIGUOUS')

    def test_multiple_capability_references(self):
        obj(self.case,'U')['typeRef'].append('not-a-capability'); self.check('E_ACTION_AMBIGUOUS')

    def test_multiple_provider_references(self):
        obj(self.case,'U')['provider'].append('B'); self.check('E_ACTION_AMBIGUOUS')

    def test_multiple_bindings(self):
        binding=copy.deepcopy(obj(self.case,'RB')); binding['id']='RB2'; self.case['instance']['objects'].append(binding)
        self.check('E_ACTION_AMBIGUOUS')

    def test_multiple_answer_actions(self):
        action=copy.deepcopy(obj(self.case,'RA')); action['id']='RA2'; self.case['instance']['objects'].append(action)
        obj(self.case,'RB')['runtimeAction'].append('RA2'); self.check('E_ACTION_AMBIGUOUS')

    def test_unrelated_infrastructure_action_ignored(self):
        self.case['instance']['objects'] += [dict(id='RA2',type='RuntimeAction',locator=['L2']),dict(id='L2',type='RuntimeActionLocator',kind='tool',value='execute')]
        obj(self.case,'RB')['runtimeAction'].append('RA2'); self.check()

    def test_explicit_handoff_at_chat_endpoint_excluded(self):
        schema(self.case,dict(type='object',applicationActionKind='handoff')); self.check('E_NO_DECLARED_ACTION')

    def test_explicit_chat_kind_designates_answer(self):
        schema(self.case,dict(type='object',applicationActionKind='chat')); obj(self.case,'L')['value']='custom:endpoint'; self.check()

    def test_missing_trace(self):
        self.case['trace']['runtime_actions']=[]; self.check('E_NO_DECLARED_ACTION')

    def test_trace_wrong_core_fields(self):
        for key in ('scenario_step_id','capability_use_id','capability_id','provider_entity_id','runtime_binding_id','runtime_action_id','action_kind'):
            with self.subTest(key=key):
                row=self.case['trace']['runtime_actions'][0]; saved=row[key]; row[key]='wrong'
                self.check('E_NO_DECLARED_ACTION'); row[key]=saved

    def test_trace_wrong_targets(self):
        self.case['trace']['runtime_actions'][0]['target_ids']=['T']; self.check('E_NO_DECLARED_ACTION')

    def test_trace_targets_compare_as_sets(self):
        self.case['trace']['runtime_actions'][0]['target_ids']=['Z','G','T','T']; self.check()

    def test_duplicate_trace(self):
        self.case['trace']['runtime_actions'] *= 2; self.check('E_ACTION_AMBIGUOUS')

    def test_unrelated_trace_is_not_global_failure(self):
        self.case['trace']['runtime_actions'].append(dict(action_kind='chat',capability_use_id='unknown')); self.check()

    def test_schema_false(self):
        schema(self.case,False); self.check('E_SCHEMA')

    def test_schema_true(self):
        schema(self.case,True); self.check()

    def test_missing_schema(self):
        obj(self.case,'RA')['inputSchema']=[]; self.check('E_SCHEMA')

    def test_multiple_schemas(self):
        obj(self.case,'RA')['inputSchema']=['IS','IS']; self.check('E_SCHEMA')

    def test_invalid_schema_json(self):
        obj(self.case,'IS')['text']='{'; self.check('E_SCHEMA')

    def test_invalid_json_schema(self):
        schema(self.case,dict(type='nonsense')); self.check('E_SCHEMA')

    def test_external_schema_reference_never_retrieved(self):
        schema(self.case,{'$ref':'https://example.invalid/request.json'}); self.check('E_SCHEMA')

    def test_file_schema_reference_never_retrieved(self):
        schema(self.case,{'$ref':'file:///not-authorized.json'}); self.check('E_SCHEMA')

    def test_unknown_declared_dialect_is_schema_error(self):
        schema(self.case, {'$schema':'https://example.invalid/unsupported-dialect','type':'object'})
        self.check('E_SCHEMA')

    def test_supported_declared_dialect(self):
        schema(self.case, {'$schema':'http://json-schema.org/draft-07/schema#','type':'object'})
        self.check()

    def test_local_schema_reference(self):
        schema(self.case,{'$defs':{'req':{'type':'object'}},'$ref':'#/$defs/req'}); self.check()

    def test_unknown_schema_keywords_are_annotations(self):
        schema(self.case,{'type':'object','modelBinding':{'runtimeActionId':'WRONG'},'unrecognized':False}); self.check()

    def test_complete_original_request_is_validated(self):
        schema(self.case,{'type':'object','properties':{'active_agent_id':{'const':'b'}}}); self.check('E_SCHEMA')

    def test_schema_last_after_identity(self):
        schema(self.case,False); self.spatial['entity_id']='missing'; self.check('E_UNKNOWN_ENTITY')

    def test_schema_last_after_ownership(self):
        schema(self.case,False); obj(self.case,'A')['groundedAsset']=[]; self.check('E_UNOWNED')

    def test_schema_last_after_declaration(self):
        schema(self.case,False); self.case['trace']['runtime_actions']=[]; self.check('E_NO_DECLARED_ACTION')

    def test_duplicate_native_ids_are_publication_failure(self):
        self.case['instance']['objects'].append(copy.deepcopy(obj(self.case,'T'))); self.check('E_PUBLICATION_INCONSISTENT')

    def test_nonobject_record_publication_failure(self):
        self.case['instance']['objects'].append(123); self.check('E_PUBLICATION_INCONSISTENT')

    def test_nonobject_top_level_publication_failure(self):
        self.case['instance']=[]; self.check('E_PUBLICATION_INCONSISTENT')

    def test_fixture_cli(self):
        payload={k:self.case[k] for k in ('instance','trace','request','session')}
        result=subprocess.run([sys.executable,str(HERE/'policy_adapter.py'),'-'],input=json.dumps(payload),text=True,capture_output=True,check=True,cwd=HERE)
        self.assertEqual(json.loads(result.stdout),self.expected)
        self.assertEqual(result.stderr,'')

    def test_cli_file(self):
        target=HERE/'bulk-selftest.input.json'
        target.write_text(json.dumps({k:self.case[k] for k in ('instance','trace','request','session')}),encoding='utf-8')
        result=subprocess.run([sys.executable,str(HERE/'policy_adapter.py'),str(target)],text=True,capture_output=True,check=True,cwd=HERE)
        self.assertEqual(json.loads(result.stdout),self.expected)

    def test_cli_malformed_json(self):
        result=subprocess.run([sys.executable,str(HERE/'policy_adapter.py'),'-'],input='{',text=True,capture_output=True,check=True,cwd=HERE)
        self.assertEqual(json.loads(result.stdout),rejected('E_PUBLICATION_INCONSISTENT'))

    def test_complete_native_example_local_and_handoff(self):
        instance=json.loads((HERE/'example.instance.json').read_text(encoding='utf-8-sig'))
        trace=json.loads((HERE/'example.trace.json').read_text(encoding='utf-8-sig'))
        self.case.update(instance=instance,trace=trace)
        self.case['session']['model_sha256']=trace['model_sha256']
        self.spatial.update(model_sha256=trace['model_sha256'],entity_id='ENT-ASSET-CHALKBOARD',source_object_id='chalkboard')
        self.case['request']['active_agent_id']='teacher_agent'
        expected=dict(decision='ANSWER_LOCAL',reason=None,provider='teacher_agent',action='RA-CLASSROOM_DINOSAUR-BACKEND-CHAT')
        self.check(expected=expected)
        self.case['request']['active_agent_id']='reading_area_guide'; expected['decision']='ANSWER_AFTER_HANDOFF'
        self.check(expected=expected)


if __name__=='__main__':
    unittest.main(verbosity=2)

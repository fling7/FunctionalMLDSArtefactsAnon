"""Draft supplementary path comparison; raw routing metrics stay unchanged.

Only exact assembler case-prefix positions in enumerated identifier fields are
removed. Provider wire IDs, semantic values, suffixes, order and unknown IDs stay.
"""
from __future__ import annotations
import copy,hashlib,json
from tools.case_study_pipeline.roomcontract_assembler import _case_prefix

PATH_ID_KINDS={'scenario_step_id':'STEP','capability_use_id':'CU','capability_id':'CAP','runtime_binding_id':'RB','runtime_action_id':'RA'}
NODE_ID_KINDS={'ScenarioStep':'STEP','CapabilityUse':'CU','Capability':'CAP','RuntimeBinding':'RB','RuntimeAction':'RA','RuntimeActionLocator':'LOC-RA','SchemaReference':'SCHEMA-RA'}
REFERENCE_KINDS={'capabilityUse':('CU',),'typeRef':('CAP',),'capability':('CAP',),'runtimeAction':('RA',),
 'locator':('LOC-RA',),'inputSchema':('SCHEMA-RA',),'outputSchema':('SCHEMA-RA',),
 'triggeredBy':('EV',),'resultingAssertion':('SA',),'guard':('COND',),'precondition':('COND',),
 'effect':('EFF',),'occurrenceProbability':('PV-STEP',)}
BINDING_KINDS={'runtimeActionId':('RA',),'runtimeBindingId':('RB',),'capabilityIds':('CAP',),'capabilityUseIds':('CU',)}

def sha(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()

def remove_exact_prefix(value,case_id,kinds):
    if isinstance(value,list):return [remove_exact_prefix(v,case_id,kinds) for v in value]
    if not isinstance(value,str):return value
    case=_case_prefix(case_id)
    for kind in kinds:
        prefix=kind+'-'+case+'-'
        if value.startswith(prefix):return {'assembler_identifier_kind':kind,'case_prefix_removed':True,'suffix':value[len(prefix):]}
    return value

def normalize_node(node,case_id):
    result=copy.deepcopy(node);kind=NODE_ID_KINDS.get(node.get('type'))
    if kind and 'id' in result:result['id']=remove_exact_prefix(result['id'],case_id,(kind,))
    for field,kinds in REFERENCE_KINDS.items():
        if field in result:result[field]=remove_exact_prefix(result[field],case_id,kinds)
    if node.get('type')=='SchemaReference' and isinstance(node.get('text'),str):
        try:schema=json.loads(node['text'])
        except (ValueError,TypeError):return result
        if isinstance(schema,dict) and isinstance(schema.get('modelBinding'),dict):
            for field,kinds in BINDING_KINDS.items():
                if field in schema['modelBinding']:schema['modelBinding'][field]=remove_exact_prefix(schema['modelBinding'][field],case_id,kinds)
            result['text']=json.dumps(schema,sort_keys=True,separators=(',',':'),ensure_ascii=False)
    return result

def normalize_descriptor(descriptor,case_id):
    result=copy.deepcopy(descriptor)
    for field,kind in PATH_ID_KINDS.items():
        if field in (result.get('path') or {}):result['path'][field]=remove_exact_prefix(result['path'][field],case_id,(kind,))
    result['nodes']=[normalize_node(node,case_id) for node in descriptor.get('nodes',[])]
    return result

def declared_descriptor(index,trace,probe):
    """Retained native path only; cannot supply or override an independent label."""
    a=probe['verdicts']['I1'];b=probe['verdicts']['I2']
    fields=('decision','reason','provider','action')
    if any(a.get(k)!=b.get(k) for k in fields):return None,'independent_label_disagreement'
    label={k:a.get(k) for k in fields}
    if a.get('decision') not in ('ANSWER_LOCAL','ANSWER_AFTER_HANDOFF'):
        return {'label':label,'path':None,'nodes':[]},None
    providers=[oid for oid,wire in index.wire.items() if wire==a['provider']]
    if len(providers)!=1:return None,'provider_wire_identity_not_unique'
    provider=providers[0];target=probe['target'];error,action=index.answering_path(provider,target)
    if error or action!=a['action']:return None,'native_declared_path_not_verified'
    candidates=[row for row in trace.get('runtime_actions',[]) if row.get('action_kind')=='chat' and row.get('provider_entity_id')==provider and row.get('runtime_action_id')==action and target in row.get('target_ids',[])]
    if len(candidates)!=1:return None,'trace_path_not_unique'
    selected=candidates[0]
    path={key:selected[key] for key in PATH_ID_KINDS}
    path.update(provider_entity_id=selected['provider_entity_id'],target_ids=selected['target_ids'],action_kind=selected['action_kind'])
    ids=[selected[key] for key in PATH_ID_KINDS];action_node=index.by_id[action]
    for field in ('locator','inputSchema','outputSchema','runtimeParameter'):ids.extend(action_node.get(field,[]))
    if any(oid not in index.by_id for oid in ids):return None,'declared_node_missing'
    # Keep each full node and every semantic field in these selected nodes.
    nodes=[copy.deepcopy(index.by_id[oid]) for oid in dict.fromkeys(ids)]
    return {'label':label,'path':path,'nodes':nodes},None

def compare(before,before_case,after,after_case):
    if before is None or after is None:return {'defined':False,'raw_descriptor_changed':None,'namespace_adjusted_path_changed':None,'case_namespace_only_change':None}
    raw_changed=sha(before)!=sha(after)
    left=normalize_descriptor(before,before_case);right=normalize_descriptor(after,after_case)
    # The action field is an explicitly declared action-ID field, unlike provider.
    left['label']['action']=remove_exact_prefix(left['label'].get('action'),before_case,('RA',))
    right['label']['action']=remove_exact_prefix(right['label'].get('action'),after_case,('RA',))
    adjusted_changed=sha(left)!=sha(right)
    return {'defined':True,'raw_descriptor_changed':raw_changed,'namespace_adjusted_path_changed':adjusted_changed,
        'case_namespace_only_change':raw_changed and not adjusted_changed,'before_namespace_adjusted_sha256':sha(left),'after_namespace_adjusted_sha256':sha(right)}


def normalized_for_case(descriptor,case_id):
    result=normalize_descriptor(descriptor,case_id)
    result['label']['action']=remove_exact_prefix(result['label'].get('action'),case_id,('RA',))
    return result


def project_retained_run(run,root):
    from pathlib import Path
    from tools.routing_verifier import NativeRoutingIndex
    def read(path):return json.loads(Path(path).read_text(encoding='utf-8-sig'))
    def file_sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    result={'case_id':run['case_id'],'defined':False,'missing_reason':run.get('independent_label_missing_reason'),
        'raw_table_sha256':None,'adjusted_table_sha256':None,'registered_probe_records':None,'registered_queries':None,
        'unique_query_identities':None,'defined_queries':0,'undefined_query_records':None,'missing_queries':{},
        'raw_query_sha256':{},'adjusted_query_sha256':{}}
    if not run['materialized'] or not run['independent_comparable']:return result
    original_path=root/run['run_result_path']
    if file_sha(original_path)!=run['run_result_sha256']:raise RuntimeError('Retained run changed')
    original=read(original_path);project=root/run['project_path'];model=project/'roomcontract.v2.instance.json';trace_path=project/'trace_map.v2.json'
    # Integrity/protocol guards remain outside unavailable-data exception handling.
    for path in (model,trace_path):
        if original['artifact_sha256'].get(path.relative_to(root).as_posix())!=file_sha(path):raise RuntimeError('Retained native path artifact changed')
    analysis_path=root/run['analysis_path']
    if file_sha(analysis_path)!=run['analysis_sha256']:raise RuntimeError('Retained independent labels changed')
    result.update(model_file_sha256=file_sha(model),trace_sha256=file_sha(trace_path),independent_analysis_sha256=file_sha(analysis_path))
    try:analysis=read(analysis_path)
    except Exception as exc:result['missing_reason']='independent_analysis_parse_error:'+type(exc).__name__;return result
    if not isinstance(analysis,dict):result['missing_reason']='independent_analysis_shape_unavailable';return result
    if analysis.get('room')!=run['case_id'] or analysis.get('source')!=original['source']:raise RuntimeError('Independent analysis identity differs from retained run')
    expected_digest=hashlib.sha256(model.read_bytes().replace(b'\r\n',b'\n')).hexdigest().upper()
    if analysis.get('model_sha256')!=expected_digest:raise RuntimeError('Independent labels refer to another native model')
    probes=analysis.get('probes')
    if not isinstance(probes,list):result['missing_reason']='probe_records_unavailable';return result
    result.update(registered_probe_records=len(probes),registered_queries=len(probes),undefined_query_records=len(probes))
    try:model_data=read(model);trace=read(trace_path)
    except Exception as exc:result['missing_reason']='native_descriptor_input_parse_error:'+type(exc).__name__;return result
    if not isinstance(trace,dict) or not isinstance(model_data,dict):result['missing_reason']='native_document_shape_unavailable';return result
    if not trace.get('case_id') or not model_data.get('caseId'):result['missing_reason']='native_namespace_identity_unavailable';return result
    if trace['case_id']!=run['case_id'] or model_data['caseId']!=run['case_id']:raise RuntimeError('Native namespace identity differs from registered case')
    try:
        keys=[json.dumps([analysis['Gate0']['objects'][probe['target']],probe['start_agent']],separators=(',',':')) for probe in probes]
    except Exception as exc:result['missing_reason']='query_identity_error:'+type(exc).__name__;return result
    result['unique_query_identities']=len(set(keys))
    if len(set(keys))!=len(keys):
        result['missing_reason']='duplicate_query_identity';result['duplicate_query_records']=len(keys)-len(set(keys));return result
    try:index=NativeRoutingIndex(model_data,trace)
    except Exception as exc:result['missing_reason']='native_index_error:'+type(exc).__name__;return result
    raw={};adjusted={};missing={}
    for key,probe in zip(keys,probes):
        try:
            descriptor,reason=declared_descriptor(index,trace,probe)
            if reason:missing[key]=reason;continue
            normalized=normalized_for_case(descriptor,run['case_id'])
            raw[key]=descriptor;adjusted[key]=normalized
        except Exception as exc:missing[key]='descriptor_extraction_error:'+type(exc).__name__
    result.update(defined=not missing,missing_reason='one_or_more_query_descriptors_unavailable' if missing else None,
        defined_queries=len(raw),undefined_query_records=len(probes)-len(raw),missing_queries=missing,
        raw_query_sha256={key:sha(value) for key,value in raw.items()},adjusted_query_sha256={key:sha(value) for key,value in adjusted.items()},
        raw_table_sha256=sha(raw) if not missing else None,adjusted_table_sha256=sha(adjusted) if not missing else None)
    return result


def analyze_retained(summary_path,output,root):
    from pathlib import Path
    from experiments.natural_faults import clustered_interval
    summary_path=Path(summary_path).resolve();output=Path(output).resolve();root=Path(root).resolve()
    summary=json.loads(summary_path.read_text(encoding='utf-8-sig'))
    runs=[project_retained_run(run,root) for run in summary['runs']];lookup={r['case_id']:r for r in runs};pairs=[]
    for primary in summary['pairs']:
        before=lookup[primary['before_case_id']];after=lookup[primary['after_case_id']]
        defined=before['defined'] and after['defined']
        left=before.get('adjusted_query_sha256',{});right=after.get('adjusted_query_sha256',{})
        matched=set(left)&set(right);changed=sum(left[k]!=right[k] for k in matched)
        row={'source':primary['source'],'before_case_id':before['case_id'],'after_case_id':after['case_id'],
            'defined':defined,'raw_declared_path_table_changed':(before['raw_table_sha256']!=after['raw_table_sha256']) if defined else None,
            'namespace_adjusted_path_table_changed':(before['adjusted_table_sha256']!=after['adjusted_table_sha256']) if defined else None,
            'matched_defined_queries':len(matched),'changed_matched_queries':changed,'matched_query_change_fraction':changed/len(matched) if matched else None,
            'before_registered_query_records':before.get('registered_probe_records'),'after_registered_query_records':after.get('registered_probe_records'),
            'before_undefined_query_records':before.get('undefined_query_records'),'after_undefined_query_records':after.get('undefined_query_records'),
            'before_defined_queries_absent_after':len(set(left)-set(right)),'after_defined_queries_absent_before':len(set(right)-set(left)),
            'before_missing_reason':before['missing_reason'],'after_missing_reason':after['missing_reason']}
        row['case_namespace_only_table_change']=row['raw_declared_path_table_changed'] and not row['namespace_adjusted_path_table_changed'] if defined else None
        pairs.append(row)
    models={}
    for model in summary['models']:
        selected=[r for r in pairs if r['source']['model']==model]
        models[model]={'registered_pairs':len(selected),'defined_pairs':sum(r['defined'] for r in selected),
            'undefined_pairs':sum(not r['defined'] for r in selected),
            'namespace_adjusted_path_table_change_rate':clustered_interval(selected,lambda r:float(r['namespace_adjusted_path_table_changed']) if r['defined'] else None),
            'case_namespace_only_table_change_rate':clustered_interval(selected,lambda r:float(r['case_namespace_only_table_change']) if r['defined'] else None),
            'matched_query_change_fraction':clustered_interval(selected,lambda r:r['matched_query_change_fraction'])}
    report={'schema':'wp5-operation-path-namespace-supplement-v1','raw_drift_summary_path':summary_path.relative_to(root).as_posix(),
        'raw_drift_summary_sha256':hashlib.sha256(summary_path.read_bytes()).hexdigest(),'plan_sha256':summary['plan_sha256'],
        'analysis_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'runs':runs,'pairs':pairs,'models':models,
        'limit':'Supplementary mechanical namespace adjustment only. Raw declared-ID metrics and provider changes remain reported unchanged. This is not semantic equivalence or runtime adoption. Missing/disputed labels leave affected comparisons undefined; no Gate0 exclusion.'}
    text=json.dumps(report,sort_keys=True,indent=2)+'\n'
    if output.exists() and output.read_text(encoding='utf-8-sig')!=text:raise RuntimeError('Choose a new immutable supplement output')
    output.parent.mkdir(parents=True,exist_ok=True);output.write_text(text,encoding='utf-8',newline='\n');return report


if __name__=='__main__':
    import argparse
    from pathlib import Path
    from experiments.pipeline_runs import ROOT
    parser=argparse.ArgumentParser();parser.add_argument('--protocol',type=Path,required=True)
    args=parser.parse_args();protocol_path=args.protocol.resolve();sidecar=protocol_path.with_suffix('.sha256')
    file_sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
    if not sidecar.exists() or sidecar.read_text(encoding='ascii').split()[0]!=file_sha(protocol_path):raise RuntimeError('Supplement protocol is not frozen')
    protocol=json.loads(protocol_path.read_text(encoding='utf-8-sig'))
    if protocol.get('status')!='FROZEN':raise RuntimeError('Supplement protocol is not authorized')
    for relative,expected in protocol['implementation_sha256'].items():
        path=(ROOT/relative).resolve()
        if not path.is_relative_to(ROOT.resolve()) or file_sha(path)!=expected:raise RuntimeError('Supplement dependency changed')
    plan_path=ROOT/protocol['extension_plan_path']
    if file_sha(plan_path)!=protocol['extension_plan_sha256']:raise RuntimeError('Extension plan pin changed')
    raw_path=ROOT/protocol['raw_drift_summary_path'];output=ROOT/protocol['output_path']
    for path in (raw_path,output):
        if not path.resolve().is_relative_to(ROOT.resolve()):raise RuntimeError('Supplement artifact path escapes workspace')
    raw=json.loads(raw_path.read_text(encoding='utf-8-sig'))
    if raw['plan_sha256']!=protocol['extension_plan_sha256']:raise RuntimeError('Raw drift evidence belongs to another plan')
    plan=json.loads(plan_path.read_text(encoding='utf-8-sig'))
    expected_cases=[row['case_id'] for row in plan['fresh_drift_runs']]
    if len(raw['runs'])!=120 or [row['case_id'] for row in raw['runs']]!=expected_cases:raise RuntimeError('Supplement does not cover all registered drift runs in order')
    lookup={(row['source_id'],row['model'],row['repetition']):row['case_id'] for row in plan['fresh_drift_runs']}
    expected_pairs=[(lookup[(source['source_id'],model,rep)],lookup[(source['source_id'],model,rep+1)]) for source in plan['new_deterministic_sources'] for model in plan['models'] for rep in range(1,5)]
    if len(raw['pairs'])!=96 or [(row['before_case_id'],row['after_case_id']) for row in raw['pairs']]!=expected_pairs:raise RuntimeError('Supplement differs from fixed adjacent-pair registry')
    if raw['analysis_sha256']!=protocol['raw_drift_analysis_sha256']:raise RuntimeError('Unreviewed primary drift analyzer')
    result=analyze_retained(raw_path,output,ROOT)
    print(json.dumps({'schema':result['schema'],'registered_pairs':len(result['pairs']),'models':result['models']}))

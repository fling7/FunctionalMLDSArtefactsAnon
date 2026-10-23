"""Preregistered native-model mutations; no independent-evaluator code is read.

Mutation definitions operate on native objects. Derived trace, wire modelBinding,
and deployed agent projections are refreshed coherently; incomplete mutations and
projection failures remain explicit results rather than being silently repaired.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import itertools
import json
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SEED=20261015
OPERATORS=(
    'drop_handoff','add_handoff','move_owner_without_path','move_owner_with_path',
    'duplicate_asset_owner','duplicate_group_owner','duplicate_zone_owner',
    'remove_asset_owner','remove_group_owner','remove_zone_owner','remove_all_owners',
    'remove_action','duplicate_action','swap_owners_consistently','reassign_group_owner',
    'merge_agents','rename_agent_dangling',
)
DESCRIPTIONS={
 'drop_handoff':'Delete one existing directed non-self handoff edge.',
 'add_handoff':'Add one absent directed edge between distinct agents.',
 'move_owner_without_path':'Move one uniquely asset-owned object to another agent; keep its capability-use providers.',
 'move_owner_with_path':'Move one uniquely asset-owned object and all provider/performer declarations targeting it to another agent.',
 'duplicate_asset_owner':'Add another agent to an existing asset responsibility; keep more general relations.',
 'duplicate_group_owner':'Add another agent to an existing group responsibility; do not remove asset overrides.',
 'duplicate_zone_owner':'Add another agent to an existing zone responsibility; do not remove asset/group overrides.',
 'remove_asset_owner':'Remove one existing asset-responsibility reference; fallback remains possible.',
 'remove_group_owner':'Remove one existing group-responsibility reference; other levels remain.',
 'remove_zone_owner':'Remove one existing zone-responsibility reference; other levels remain.',
 'remove_all_owners':'Remove every responsibility reference that can own a selected scene object at asset/group/zone level.',
 'remove_action':'Remove one answering RuntimeAction and its owned locator/schema/parameter records; remove references to those deleted records. Empty bindings remain invalid rather than being repaired.',
 'duplicate_action':'Clone one answering RuntimeAction and its owned locator/schema/parameter records into the same binding, yielding an additional answering path.',
 'swap_owners_consistently':'Exchange the unique asset owners of two objects with different owners; move every targeted capability-use provider/performer path with them.',
 'reassign_group_owner':'Move one existing group responsibility reference to an agent not already responsible for that group.',
 'merge_agents':'Merge one Agent into another, union its responsibilities/capabilities, redirect references, remove resulting self-handoffs and duplicate references.',
 'rename_agent_dangling':'Rename one native Agent ID without updating its references, intentionally leaving them dangling.',
}


def refs(obj,key):
    value=obj.get(key,[])
    return list(value) if isinstance(value,list) else []


def encoded(value):
    return (json.dumps(value,sort_keys=True,indent=2,ensure_ascii=False)+'\n').encode('utf-8')


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest().upper()


@dataclass
class Bundle:
    instance: dict
    trace: dict
    project: dict
    agents: dict
    source: str=''
    lineage: dict[str,str]=field(default_factory=dict)

    @classmethod
    def load(cls, project: Path):
        project=Path(project)
        def read(name): return json.loads((project/name).read_text(encoding='utf-8-sig'))
        return cls(read('roomcontract.v2.instance.json'),read('trace_map.v2.json'),read('project.json'),read('agents.json'),project.as_posix())


class NotApplicable(ValueError): pass


def _index(bundle):
    return {o['id']:o for o in bundle.instance['objects']}


def _collections(bundle):
    by=_index(bundle)
    agents={i:o for i,o in by.items() if o.get('type')=='Agent'}
    objects={i:o for i,o in by.items() if o.get('entityRole')=='sceneObject'}
    groups={i:o for i,o in by.items() if o.get('entityRole')=='objectGroup'}
    zones={i:o for i,o in by.items() if o.get('kind')=='zone'}
    return by,agents,objects,groups,zones


def _choose(candidates,rng,avoid):
    candidates=sorted(candidates,key=lambda c:json.dumps(c,sort_keys=True))
    if not candidates: raise NotApplicable('No eligible target in the current model.')
    disjoint=[c for c in candidates if not set(c if isinstance(c,tuple) else [c]) & avoid]
    return rng.choice(disjoint or candidates)


def _replace(value,old,new):
    if isinstance(value,dict):
        return {k:_replace(v,old,new) for k,v in value.items()}
    if isinstance(value,list):
        items=[_replace(v,old,new) for v in value]
        return list(dict.fromkeys(items)) if all(isinstance(x,str) for x in items) else items
    return new if value==old else value


def _move_paths(bundle,target,old,new):
    by=_index(bundle)
    for use in bundle.instance['objects']:
        if use.get('type')=='CapabilityUse' and target in refs(use,'target') and old in refs(use,'provider'):
            use['provider']=[new if x==old else x for x in refs(use,'provider')]
            if new in by:
                by[new]['providedCapability']=list(dict.fromkeys(refs(by[new],'providedCapability')+refs(use,'typeRef')))
            for step in bundle.instance['objects']:
                if step.get('type')=='ScenarioStep' and use['id'] in refs(step,'capabilityUse'):
                    step['performedBy']=[new if x==old else x for x in refs(step,'performedBy')]


def _answer_actions(bundle):
    by=_index(bundle)
    answer=[]
    for obj in by.values():
        if obj.get('type')!='RuntimeAction': continue
        kinds=[]
        for sid in refs(obj,'inputSchema'):
            try: schema=json.loads(by.get(sid,{}).get('text','null'))
            except (ValueError,TypeError): schema=None
            if isinstance(schema,dict) and 'applicationActionKind' in schema: kinds.append(schema['applicationActionKind'])
        if ('chat' in kinds) if kinds else any(by.get(l,{}).get('value')=='POST /chat' for l in refs(obj,'locator')):
            for bind in by.values():
                if bind.get('type')=='RuntimeBinding' and obj['id'] in refs(bind,'runtimeAction'): answer.append((bind['id'],obj['id']))
    return answer


def mutate(bundle: Bundle, operator: str, seed: int, *, avoid=()) -> tuple[Bundle,dict]:
    if operator not in OPERATORS: raise ValueError(operator)
    result=copy.deepcopy(bundle)
    rng=random.Random(seed)
    by,agents,objects,groups,zones=_collections(result)
    avoid=set(avoid)
    touched=[]
    before=digest(result.instance)
    if operator in {'drop_handoff','add_handoff'}:
        edges=[(a,b) for a in agents for b in agents if a!=b and ((b in refs(agents[a],'handoffTarget'))==(operator=='drop_handoff'))]
        a,b=_choose(edges,rng,avoid)
        agents[a]['handoffTarget']=[x for x in refs(agents[a],'handoffTarget') if x!=b] if operator=='drop_handoff' else refs(agents[a],'handoffTarget')+[b]
        touched=[a,b,f'{a}->{b}']
    elif operator in {'move_owner_without_path','move_owner_with_path','swap_owners_consistently'}:
        ownership={t:[a for a in agents if t in refs(agents[a],'groundedAsset')] for t in objects}
        unique={t:values[0] for t,values in ownership.items() if len(values)==1}
        if operator=='swap_owners_consistently':
            left,right=_choose([(l,r) for l,r in itertools.combinations(unique,2) if unique[l]!=unique[r]],rng,avoid)
            old,new=unique[left],unique[right]
            agents[old]['groundedAsset']=[right if x==left else x for x in refs(agents[old],'groundedAsset')]
            agents[new]['groundedAsset']=[left if x==right else x for x in refs(agents[new],'groundedAsset')]
            _move_paths(result,left,old,new)
            _move_paths(result,right,new,old)
            touched=[left,right]
        else:
            target,old,new=_choose([(t,a,b) for t,a in unique.items() for b in agents if b!=a],rng,avoid)
            agents[old]['groundedAsset']=[x for x in refs(agents[old],'groundedAsset') if x!=target]
            agents[new]['groundedAsset']=refs(agents[new],'groundedAsset')+[target]
            if operator=='move_owner_with_path': _move_paths(result,target,old,new)
            touched=[target]
    elif operator.startswith('duplicate_') and operator!='duplicate_action' or operator.startswith('remove_') and operator in {'remove_asset_owner','remove_group_owner','remove_zone_owner'} or operator=='reassign_group_owner':
        level=operator.split('_')[1] if operator!='reassign_group_owner' else 'group'
        key={'asset':'groundedAsset','group':'groundedObjectGroup','zone':'responsibleZone'}[level]
        valid={'asset':objects,'group':groups,'zone':zones}[level]
        existing=[(a,t) for a,row in agents.items() for t in refs(row,key) if t in valid]
        if operator.startswith('remove_'):
            a,target=_choose(existing,rng,avoid)
            agents[a][key]=[x for x in refs(agents[a],key) if x!=target]
        else:
            a,target,b=_choose([(a,t,b) for a,t in existing for b in agents if b!=a and t not in refs(agents[b],key)],rng,avoid)
            agents[b][key]=refs(agents[b],key)+[target]
            if operator=='reassign_group_owner': agents[a][key]=[x for x in refs(agents[a],key) if x!=target]
        touched=[target]
    elif operator=='remove_all_owners':
        target=_choose(list(objects),rng,avoid)
        relevant_groups=set(refs(objects[target],'objectGroup'))
        relevant_zones={z for z,row in zones.items() if objects[target].get('sourceId') in refs(row,'sourceObjectId')}
        for agent in agents.values():
            agent['groundedAsset']=[x for x in refs(agent,'groundedAsset') if x!=target]
            agent['groundedObjectGroup']=[x for x in refs(agent,'groundedObjectGroup') if x not in relevant_groups]
            agent['responsibleZone']=[x for x in refs(agent,'responsibleZone') if x not in relevant_zones]
        touched=[target,*sorted(relevant_groups),*sorted(relevant_zones)]
    elif operator in {'remove_action','duplicate_action'}:
        binding,action=_choose(_answer_actions(result),rng,avoid)
        owned={action,*refs(by[action],'locator'),*refs(by[action],'inputSchema'),*refs(by[action],'outputSchema'),*refs(by[action],'runtimeParameter')}
        if operator=='remove_action':
            result.instance['objects']=[o for o in result.instance['objects'] if o['id'] not in owned]
            for obj in result.instance['objects']:
                for key,value in list(obj.items()):
                    if isinstance(value,list) and all(isinstance(x,str) for x in value): obj[key]=[x for x in value if x not in owned]
        else:
            suffix='-MUT-'+hashlib.sha256(str(seed).encode()).hexdigest()[:8].upper()
            mapping={old:old+suffix for old in owned}
            copies=[]
            for old in sorted(owned):
                if old not in by: continue
                cloned=copy.deepcopy(by[old])
                for src,dst in mapping.items(): cloned=_replace(cloned,src,dst)
                result.lineage[mapping[old]]=old
                copies.append(cloned)
            result.instance['objects'].extend(copies)
            by[binding]['runtimeAction']=refs(by[binding],'runtimeAction')+[mapping[action]]
        touched=[action]
    elif operator=='merge_agents':
        keep,drop=_choose(list(itertools.permutations(agents,2)),rng,avoid)
        for key in ['groundedAsset','groundedObjectGroup','responsibleZone','providedCapability','handoffTarget','playsActor']:
            agents[keep][key]=list(dict.fromkeys(refs(agents[keep],key)+refs(agents[drop],key)))
        result.instance['objects']=[o for o in result.instance['objects'] if o['id']!=drop]
        result.instance=_replace(result.instance,drop,keep)
        merged=_index(result)[keep]
        merged['handoffTarget']=[x for x in refs(merged,'handoffTarget') if x!=keep]
        touched=[keep,drop]
    elif operator=='rename_agent_dangling':
        old=_choose(list(agents),rng,avoid)
        new=old+'-RENAMED'
        if new in by: raise NotApplicable('Renamed ID already exists.')
        agents[old]['id']=new
        touched=[old,new]
    after=digest(result.instance)
    return result,{'operator':operator,'seed':seed,'touched':touched,'changed':before!=after,'before_sha256':before,'after_sha256':after,'overlap_with_previous':sorted(set(touched)&avoid)}


def refresh_projections(bundle: Bundle) -> Bundle:
    """Derive trace rows from native paths, retaining unrelated template metadata.

    No validator is bypassed or repaired. Missing chains simply have no derived
    trace row. Validators inspect the resulting broken native model separately.
    """
    result=copy.deepcopy(bundle)
    by,agents,objects,groups,zones=_collections(result)
    old_rows=result.trace.get('runtime_actions',[])
    scenario_by_step={step:s for s in by.values() if s.get('type')=='Scenario' for step in refs(s,'step')}
    usecase_by_scenario={sc:refs(s,'useCase')[0] for s in by.values() if s.get('type')=='UseCaseScenarioSpecification' and len(refs(s,'useCase'))==1 for sc in refs(s,'scenario')}
    steps_by_use={}
    for step in by.values():
        if step.get('type')=='ScenarioStep':
            for use in refs(step,'capabilityUse'): steps_by_use.setdefault(use,[]).append(step)
    rows=[]
    for binding in by.values():
        if binding.get('type')!='RuntimeBinding': continue
        for cap in refs(binding,'capability'):
            for action_id in refs(binding,'runtimeAction'):
                action=by.get(action_id,{})
                if action.get('type')!='RuntimeAction': continue
                template=next((r for r in old_rows if r.get('runtime_binding_id')==binding['id'] and r.get('capability_id')==cap and r.get('runtime_action_id')==result.lineage.get(action_id,action_id)),None)
                if template is None: template=next((r for r in old_rows if r.get('runtime_binding_id')==binding['id'] and r.get('capability_id')==cap),None)
                if template is None: raise ValueError(f'No trace prototype for native binding {binding["id"]}')
                locator=by.get((refs(action,'locator') or [''])[0],{})
                for use in by.values():
                    if use.get('type')!='CapabilityUse' or cap not in refs(use,'typeRef'): continue
                    for step in steps_by_use.get(use['id'],[]):
                        for provider in refs(use,'provider'):
                            sc=scenario_by_step.get(step['id'],{})
                            row=copy.deepcopy(template)
                            row.update(scenario_step_id=step['id'],scenario_id=sc.get('id'),use_case_id=usecase_by_scenario.get(sc.get('id')),capability_use_id=use['id'],provider_entity_id=provider,target_ids=refs(use,'target'),runtime_action_id=action_id)
                            row['locator']={'kind':locator.get('kind'),'value':locator.get('value')}
                            for kind in ['endpoint','tool','topic']: row[kind]=locator.get('value') if locator.get('kind')==kind else None
                            rows.append(row)
    result.trace['runtime_actions']=rows
    for row in result.trace.get('scenario_steps',[]):
        step=by.get(row.get('scenario_step_id'),{})
        row['capability_use_ids']=refs(step,'capabilityUse')
        row['provider_entity_ids']=refs(step,'performedBy')
    # Both input and output modelBinding annotations mirror the full native action set.
    for binding in by.values():
        if binding.get('type')!='RuntimeBinding': continue
        caps=refs(binding,'capability')
        uses=[o['id'] for o in by.values() if o.get('type')=='CapabilityUse' and set(refs(o,'typeRef'))&set(caps)]
        for action_id in refs(binding,'runtimeAction'):
            action=by.get(action_id,{})
            expected={'runtimeBindingId':binding['id'],'runtimeActionId':action_id,'capabilityIds':caps,'capabilityUseIds':uses}
            for sid in refs(action,'inputSchema')+refs(action,'outputSchema'):
                schema_obj=by.get(sid)
                if not schema_obj: continue
                try: schema=json.loads(schema_obj.get('text','null'))
                except (ValueError,TypeError): continue
                if isinstance(schema,dict) and 'modelBinding' in schema:
                    schema['modelBinding']=expected
                    schema_obj['text']=json.dumps(schema,sort_keys=True,separators=(',',':'),ensure_ascii=False)
    deployed=[]
    previous={o.get('id'):o for o in result.agents.get('agents',[])}
    for aid,agent in agents.items():
        wire=agent.get('sourceAgentId')
        row=copy.deepcopy(previous.get(wire,{}))
        row.update(id=wire,roomcontract_agent_ref=aid,roomcontract_entity_ref=aid,grounded_object_ids=[by.get(t,{}).get('sourceId',t) for t in refs(agent,'groundedAsset')],responsible_zone_ids=[by.get(t,{}).get('sourceId',t) for t in refs(agent,'responsibleZone')],handoff_targets=[by.get(t,{}).get('sourceAgentId',t) for t in refs(agent,'handoffTarget')],provided_capability_ids=refs(agent,'providedCapability'))
        deployed.append(row)
    result.agents['agents']=deployed
    from tools.case_study_pipeline.project_materializer import placement_projection_sha256
    placement_digest=placement_projection_sha256(deployed)
    result.project['placement_projection_sha256']=placement_digest
    result.trace['placement_projection_sha256']=placement_digest
    result.agents['placement_projection_sha256']=placement_digest
    result.trace['agents']=[{'agent_id':a.get('sourceAgentId'),'roomcontract_agent_id':i,'entity_id':i,'plays_actor':refs(a,'playsActor'),'provided_capability_ids':refs(a,'providedCapability'),'responsible_zone_ids':refs(a,'responsibleZone'),'grounded_asset_ids':refs(a,'groundedAsset'),'grounded_object_group_ids':refs(a,'groundedObjectGroup'),'knowledge_tags':refs(a,'knowledgeTag')} for i,a in agents.items()]
    model_digest=digest(result.instance)
    result.project.update(roomcontract_model_sha256=model_digest,roomcontract_digest_scheme='sha256-lf-v1')
    result.trace.update(model_sha256=model_digest,digest_scheme='sha256-lf-v1')
    return result


def mutation_plan(bundle: Bundle, seed=SEED):
    """One single mutant and one compound per pair; reverse only for eligibility."""
    for op in OPERATORS:
        case_seed=int.from_bytes(hashlib.sha256(f'{seed}|{bundle.instance.get("caseId")}|{op}'.encode()).digest()[:8],'big')
        try:
            mutated,change=mutate(bundle,op,case_seed)
            yield {'id':op,'operators':[op],'attempt':1,'status':'changed' if change['changed'] else 'no_op','changes':[change]},mutated
        except NotApplicable as exc:
            yield {'id':op,'operators':[op],'attempt':1,'status':'not_applicable','reason':str(exc),'changes':[]},copy.deepcopy(bundle)
    for first,second in itertools.combinations(OPERATORS,2):
        pair_id=f'{first}__{second}'
        for attempt,order in enumerate([(first,second),(second,first)],1):
            mutated=copy.deepcopy(bundle)
            changes=[]
            try:
                for ordinal,op in enumerate(order):
                    case_seed=int.from_bytes(hashlib.sha256(f'{seed}|{bundle.instance.get("caseId")}|{pair_id}|{attempt}|{ordinal}'.encode()).digest()[:8],'big')
                    avoid={x for c in changes for x in c['touched']}
                    mutated,change=mutate(mutated,op,case_seed,avoid=avoid)
                    changes.append(change)
                status='changed' if all(c['changed'] for c in changes) and digest(mutated.instance)!=digest(bundle.instance) else 'no_op'
                yield {'id':pair_id+f'__attempt{attempt}','pair_id':pair_id,'operators':list(order),'attempt':attempt,'status':status,'changes':changes},mutated
                if status=='changed': break
            except NotApplicable as exc:
                yield {'id':pair_id+f'__attempt{attempt}','pair_id':pair_id,'operators':list(order),'attempt':attempt,'status':'incomplete' if changes else 'not_applicable','reason':str(exc),'changes':changes},mutated


def natural_diff_plan(before: Bundle, after: Bundle, pair_id: str, seed=SEED):
    """Observed WP5 before/after models, followed by one core operation per pair.

    This does not invent a natural result. The caller must supply both real
    published project paths and their WP5 evidence identity.
    """
    before_by=_index(before)
    after_by=_index(after)
    changed=sorted(i for i in set(before_by)|set(after_by) if before_by.get(i)!=after_by.get(i))
    metadata={'id':f'natural_diff__{pair_id}','operators':['natural_diff'],'attempt':1,'status':'changed' if digest(before.instance)!=digest(after.instance) else 'no_op','natural_pair_id':pair_id,'changes':[{'operator':'natural_diff','changed':bool(changed),'touched':changed,'before_sha256':digest(before.instance),'after_sha256':digest(after.instance)}]}
    yield metadata,copy.deepcopy(after)
    for operator in OPERATORS:
        case_seed=int.from_bytes(hashlib.sha256(f'{seed}|natural|{pair_id}|{operator}'.encode()).digest()[:8],'big')
        info=copy.deepcopy(metadata)
        info.update(id=f'natural_diff__{pair_id}__{operator}',pair_id=f'natural_diff__{operator}',operators=['natural_diff',operator])
        try:
            mutated,change=mutate(after,operator,case_seed,avoid=changed)
            info['changes'].append(change)
            info['status']='changed' if metadata['status']=='changed' and change['changed'] else 'no_op'
            yield info,mutated
        except NotApplicable as exc:
            info.update(status='incomplete',reason=str(exc))
            yield info,copy.deepcopy(after)


def write_bundle(bundle,directory):
    directory=Path(directory)
    directory.mkdir(parents=True,exist_ok=False)
    for name,value in [('roomcontract.v2.instance.json',bundle.instance),('trace_map.v2.json',bundle.trace),('project.json',bundle.project),('agents.json',bundle.agents)]: (directory/name).write_bytes(encoded(value))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--describe',action='store_true')
    args=parser.parse_args()
    if args.describe: print(json.dumps({'seed':SEED,'operators':DESCRIPTIONS,'single_mutants_per_operator':1,'pair_repetitions':1,'operator_pairs':len(list(itertools.combinations(OPERATORS,2)))},indent=2))

if __name__=='__main__': main()

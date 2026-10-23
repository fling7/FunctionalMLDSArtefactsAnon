"""DELTA2 Stage A4/A5: retained detection counts and isolated offline counterfactuals."""
from pathlib import Path
from collections import Counter,defaultdict
from datetime import datetime,timezone
import copy,csv,hashlib,json,socket,sys,subprocess
R=Path(__file__).resolve().parents[3];D=R/'data/go_sprint';O=R/'deliverables/delta2_20261020/stage_A';RAW=R/'results/raw/delta2/stage_A/a4_a5';S=Path(__file__).relative_to(R).as_posix();sys.path.insert(0,str(R))
for p in (O/'tables',O/'review',RAW):p.mkdir(parents=True,exist_ok=True)
def deny(*a,**k):raise RuntimeError('Network forbidden')
socket.create_connection=deny;socket.socket.connect=deny
from experiments.mutations import OPERATORS
from tools.routing_verifier import NativeRoutingIndex,verify_routing,serialization_digest
from verification.impl_a import reference as I1
from verification.impl_b import policy_adapter as I2
from experiments.natural_faults import request_for
START=datetime.now(timezone.utc).isoformat();pins={};logs=[]
def read(p):
 b=p.read_bytes();pins[p.relative_to(R).as_posix()]=hashlib.sha256(b).hexdigest();return json.loads(b.decode('utf-8-sig'))
def jsonout(p,v):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,indent=2,sort_keys=True)+'\n',encoding='utf-8')
def csvout(name,rows):
 with (O/'tables'/name).open('w',encoding='utf-8',newline='') as f:
  w=csv.DictWriter(f,fieldnames=list(dict.fromkeys(k for r in rows for k in r)));w.writeheader();w.writerows({k:json.dumps(v) if isinstance(v,(list,dict)) else v for k,v in r.items()} for r in rows)
def comp(k,old,new):
 x={'key':k,'old':old,'new':new,'script':S,'flag':'NEW_METRIC' if old is None else 'UNCHANGED' if old==new else 'CHANGED'};logs.append(x);print(json.dumps(x),flush=True)
def logrows(tag,rows):
 for j,r in enumerate(rows):
  for k,v in r.items():
   if isinstance(v,(int,float)):comp(f'{tag}/{j}/{k}',None,v)
records=defaultdict(list)
for p in sorted((D/'wp6/outcomes').glob('*.jsonl')):
 b=p.read_bytes();pins[p.relative_to(R).as_posix()]=hashlib.sha256(b).hexdigest();records['generated'].extend(json.loads(s) for s in b.decode('utf-8-sig').splitlines() if s.strip())
for p in sorted((D/'sprint/w2/completed').glob('*/*.json')):records['generated'].append(read(p))
for p in sorted((D/'wp6_classroom').glob('snapshot/*/outcomes/*.json')):records['classroom'].append(read(p))
singles=[];pairs=[];oracle=[];summaries={};missed=[]
for cohort,rr in sorted(records.items()):
 assert len({r['metadata']['id'] for r in rr})==len(rr)
 comp('A4/'+cohort+'/models',908 if cohort=='generated' else 153,len(rr))
 groups=defaultdict(list)
 for r in rr:
  ops=r['metadata']['operators'];groups[('single' if len(ops)==1 else 'pair',' + '.join(sorted(ops)))].append(r)
 for op in OPERATORS:groups.setdefault(('single',op),[])
 for (kind,op),rs in sorted(groups.items()):
  vb=sorted({k for r in rr for k in r['checkers'] if k.startswith('Vb_')})
  row={'cohort':cohort,'operator_group':kind,'operators':op,'mutants':len(rs),'routing_faulty':sum(r['groundtruth']['routing_faulty'] is True for r in rs),'routing_truth_unknown':sum(r['groundtruth']['routing_faulty'] is None for r in rs),'source_rooms':len({r['metadata']['room'] for r in rs})}
  funs={'Va_structural':lambda c:c['Va_structural']['status']=='reject','Vb_domain':lambda c:c['Vb_native_domain']['status']=='reject','Vb_union':lambda c:any(c[k]['status']=='reject' for k in vb),'loader':lambda c:any(c[k]['status']=='reject' for k in ('Vc_instance','Vc_trace')),'backend_setup':lambda c:c['backend_setup']['status']=='reject'}
  funs.update({k:(lambda c,k=k:c[k]['status']=='reject') for k in vb})
  for key,pred in funs.items():row[key+'_flagged']=sum(pred(r['checkers']) for r in rs)
  row['missed_by_all_nonoracle']=sum(r['groundtruth']['routing_faulty'] is True and not any(pred(r['checkers']) for pred in funs.values()) for r in rs)
  row['not_flagged_any_truth']=sum(not any(pred(r['checkers']) for pred in funs.values()) for r in rs)
  for k in vb:row[k+'_not_applicable']=sum(r['checkers'][k]['status']=='not_applicable' for r in rs)
  (singles if kind=='single' else pairs).append(row)
  oracle.append({'cohort':cohort,'operator_group':kind,'operators':op,'mutants':len(rs),'block':'oracle sanity check, not independent evidence',**{k+'_flagged':sum(r['checkers'][k]['status']=='reject' for r in rs) for k in ('Gate0','I1_reference','I2_policy')}})
  for r in rs:
   if r['groundtruth']['routing_faulty'] is True and not any(pred(r['checkers']) for pred in funs.values()):missed.append({'cohort':cohort,'model':r['metadata']['id'],'source_room':r['metadata']['room'],'operators':op,'operator_group':kind})
 summaries[cohort]={'models':len(rr),'singles':sum(len(v) for (k,o),v in groups.items() if k=='single'),'pairs':sum(len(v) for (k,o),v in groups.items() if k=='pair'),'missed_all_nonoracle':sum(r['cohort']==cohort for r in missed)}
for name,rs in [('A4_single_operator_detection.csv',singles),('A4_pair_operator_detection.csv',pairs),('A4_oracle_sanity.csv',oracle),('A4_missed_by_all_nonoracle.csv',missed)]:csvout(name,rs);logrows(name,rs)
# Classroom facts: recompute all native pairs and actual graph distances.
P=R/'app/backend_root/agent_backend/projects/classroom_dinosaur';m=read(P/'roomcontract.v2.instance.json');t=read(P/'trace_map.v2.json');meta=read(P/'project.json');index=NativeRoutingIndex(m,t);dig=serialization_digest((P/'roomcontract.v2.instance.json').read_bytes());gate=verify_routing(m,t,model_sha256=dig)
long=[];allpairs=[]
for aid in sorted(index.agents):
 for target in sorted(index.objects):
  level,owners=index.ownership(target);distance=index.distance(aid,owners[0]) if len(owners)==1 else None
  row={'start_agent':index.wire[aid],'target':target,'source_object':index.objects[target]['sourceId'],'owner':index.wire[owners[0]] if len(owners)==1 else None,'shortest_handoffs':distance,'decision':gate['routing_table'][index.wire[aid]][target]['decision'],'reason':gate['routing_table'][index.wire[aid]][target]['reason']};allpairs.append(row)
  if distance is not None and distance>1:long.append(row)
csvout('A5_classroom_long_handoff_pairs.csv',long);jsonout(RAW/'classroom_all_pairs.json',allpairs)
comp('A5/classroom_pairs',144,len(allpairs));comp('A5/classroom_long_handoff_pairs',27,len(long));logrows('classroom_long_handoff',long)
provenance={'authorship':'Supplied RoomContract authored classroom example. Retained metadata identifies generation_mode=roomcontract, but does not establish a human author or which model/tool authored original role choices. No identity attribution inferred.','created_metadata_utc':datetime.fromtimestamp(meta['created_ms']/1000,timezone.utc).isoformat(),'updated_metadata_utc':datetime.fromtimestamp(meta['updated_ms']/1000,timezone.utc).isoformat(),'native_file_mtime_utc':datetime.fromtimestamp((P/'roomcontract.v2.instance.json').stat().st_mtime,timezone.utc).isoformat(),'timestamps_caveat':'Stored project timestamps and filesystem mtime support pre-2026-10-15 retention, not independently authenticated authorship. Git import date is not creation date.','created_before_2026_10_15':meta['created_ms']<1792022400000,'classroom_latent_group_count':sum(x['kind']=='group' for x in gate['latent_ambiguities']),'classroom_latent_zone_count':sum(x['kind']=='zone' for x in gate['latent_ambiguities'])}
proc=subprocess.run(['git','log','--all','--format=%h %aI %cI','--',P.relative_to(R).as_posix()+'/roomcontract.v2.instance.json'],cwd=R,capture_output=True,text=True);provenance['git_date_evidence_without_identities']=proc.stdout.strip();jsonout(RAW/'classroom_provenance.json',provenance)
# Twelve signals are original evaluation + ownership-repair, NOT classroom.
analyses=[R/'results/raw/wp5/natural_evaluation_v1/rooms/scene_030_music_workshop_full_r0.json',*sorted((R/'results/raw/wp5_extension/natural_ownership_repair_v1/rooms').glob('*.json'))]
cfrows=[];cfverdicts=[];inventory=[]
for ap in analyses:
 a=read(ap);cohort='original_natural' if 'natural_evaluation_v1' in str(ap) else 'ownership_repair';case=a['room'];runpath=R/('results/raw/wp5/evaluation' if cohort=='original_natural' else 'results/raw/wp5_extension/ownership_repair')/case/'run_result.json';run=read(runpath);proj=R/run['project_dir'];base=read(proj/'roomcontract.v2.instance.json');trace=read(proj/'trace_map.v2.json');baseindex=NativeRoutingIndex(base,trace)
 for latent in a['Gate0']['latent_ambiguities']:
  ident=f'cf_{len(cfrows)+1:02d}';instance=copy.deepcopy(base);members=set(latent['members']);removed=[]
  for obj in instance['objects']:
   if obj['id'] in baseindex.agents:
    before=obj.get('groundedAsset',[]);deleted=[v for v in before if v in members]
    if deleted:removed.extend({'agent':obj['id'],'target':v} for v in deleted);obj['groundedAsset']=[v for v in before if v not in members]
  raw=(json.dumps(instance,sort_keys=True,indent=2)+'\n').encode();outpath=RAW/'counterfactual_models'/f'{ident}.instance.json';outpath.parent.mkdir(parents=True,exist_ok=True);outpath.write_bytes(raw);digest=serialization_digest(raw);g=verify_routing(instance,trace,model_sha256=digest);idx=NativeRoutingIndex(instance,trace);vc=[]
  # All members and all start agents; no handpicked favorable target.
  for target in sorted(members):
   for aid in sorted(idx.agents):
    agent=idx.wire[aid];req=request_for(agent,idx.objects[target],digest,session_id='delta2-counterfactual');sess={'model_sha256':digest,'active_agent_mode':'client'};vs={'Gate0':g['routing_table'][agent][target]}
    for label,module in [('I1',I1),('I2',I2)]:
     try:vs[label]=module.evaluate(instance,trace,req,sess)
     except Exception as exc:vs[label]={'evaluation_error':type(exc).__name__,'message':str(exc)}
    level,owners=idx.ownership(target);v={'counterfactual':ident,'target':target,'start_agent':agent,'deciding_level_after':level,'owner_count_after':len(owners),'verdicts':vs};vc.append(v);cfverdicts.append(v)
  counts={k:sum(v['verdicts'][k].get('reason')=='E_AMBIGUOUS_OWNER' for v in vc) for k in ('Gate0','I1','I2')};agree=sum(len({json.dumps(v['verdicts'][k],sort_keys=True) for k in ('Gate0','I1','I2')})==1 for v in vc)
  row={'counterfactual':ident,'cohort':cohort,'case':case,'latent_kind':latent['kind'],'latent_entity':latent['entity'],'members':len(members),'object_owner_references_removed':len(removed),'probe_pairs':len(vc),**{k+'_ambiguous_pairs':v for k,v in counts.items()},'all_three_any_ambiguity':all(v>0 for v in counts.values()),'all_three_every_pair_ambiguous':all(v==len(vc) for v in counts.values()),'full_verdict_agreement_pairs':agree,'deciding_levels_after':dict(Counter(v['deciding_level_after'] for v in vc)),'copy_sha256':hashlib.sha256(raw).hexdigest(),'copy_path':outpath.relative_to(R).as_posix()};cfrows.append(row);inventory.append({'counterfactual':ident,'original_project':proj.relative_to(R).as_posix(),'original_analysis':ap.relative_to(R).as_posix(),'latent':latent,'removed_references':removed});print(json.dumps({'counterfactual_complete':ident,'row':row}),flush=True)
csvout('A5_latent_counterfactuals.csv',cfrows);jsonout(RAW/'counterfactual_verdicts.json',cfverdicts);jsonout(RAW/'counterfactual_inventory.json',inventory);logrows('latent_counterfactuals',cfrows)
comp('A5/latent_entities',12,len(cfrows));comp('A5/latent_entities_any_ambiguous_all3',12,sum(r['all_three_any_ambiguity'] for r in cfrows));comp('A5/latent_entities_every_probe_ambiguous_all3',None,sum(r['all_three_every_pair_ambiguous'] for r in cfrows))
# Retained drift comparison labels: exactly fresh-regeneration, not four edits.
p=D/'wp4_wp5/evolution_pairs_103.jsonl';b=p.read_bytes();pins[p.relative_to(R).as_posix()]=hashlib.sha256(b).hexdigest();evol=[json.loads(s) for s in b.decode().splitlines() if s.strip()];drift=[r for r in evol if r['pair_family']=='fresh_regeneration' and r['independent_comparable_pair']];drows=[{k:r.get(k) for k in ('pair_id','source_id','before_case_id','after_case_id','same_ownership_partition_up_to_provider_renaming','provider_renaming_only_candidate','defined_provider_pairs','undefined_provider_pairs','provider_id_change_fraction')} for r in drift];csvout('A5_drift_partition.csv',drows);logrows('drift_partition',drows)
cs=Counter(r['same_ownership_partition_up_to_provider_renaming'] for r in drift);comp('A5/drift_comparable',45,len(drift));comp('A5/drift_same_partition',None,cs[True]);comp('A5/drift_different_partition',None,cs[False])
numbers={'A4':summaries,'A4_interpretation':'Flagged columns count checker rejections irrespective of truth; missed_by_all counts routing_faulty=True not rejected by any listed non-oracle checker. Vb union ORs all retained Vb rejection statuses; unavailable placement/traceability are explicitly counted and do not erase available negatives. Singles and pairs are disjoint.','A5_classroom':{'pairs':len(allpairs),'long_handoff_pairs':len(long),'provenance':provenance},'A5_latent':{'scope':'one original natural group plus two groups/nine zones from ownership-repair; not classroom; separate drift latent entities outside this12','entities':len(cfrows),'by_kind':dict(Counter(r['latent_kind'] for r in cfrows)),'any_ambiguous_all3':sum(r['all_three_any_ambiguity'] for r in cfrows),'every_pair_ambiguous_all3':sum(r['all_three_every_pair_ambiguous'] for r in cfrows),'method':'One copy per latent entity; remove only groundedAsset references for all its members, preserving group/zone ownership; evaluate all member x agent pairs with retained Gate0/I1/I2. Group masking retained. In-memory Gate0 INV081 publication check not evaluated.','counterfactual_not_natural_incidence':True},'A5_drift':{'comparable_fresh_regeneration_pairs':len(drift),'same_partition':cs[True],'different_partition':cs[False],'renaming_only_candidate':sum(bool(r['provider_renaming_only_candidate']) for r in drift),'caveat':'Partition equality on matched objects with defined providers only; potential provider renaming is not semantic role equivalence; pairs/source repeats are not independent rooms.'}}
jsonout(O/'numbers_a4_a5.json',numbers)
for src in ('tools/routing_verifier.py','verification/impl_a/reference.py','verification/impl_b/policy_adapter.py','verification/impl_b/admission.lp','experiments/mutations.py','experiments/natural_faults.py'):
 p=R/src
 if p.exists():pins[src]=hashlib.sha256(p.read_bytes()).hexdigest()
for rel,h in pins.items():assert hashlib.sha256((R/rel).read_bytes()).hexdigest()==h,rel
jsonout(O/'review/a4_a5_comparisons.json',logs);jsonout(O/'review/a4_a5_proof.json',{'status':'PASS','script':S,'started_utc':START,'ended_utc':datetime.now(timezone.utc).isoformat(),'input_sha256':pins,'original_input_hashes_unchanged':True,'network_forbidden':True,'spend_usd':0})
notes=['A4 DONE:17 single-operator rows per cohort, pair combinations separate; all Vb components including unavailable-status counts, Vb union, loader/backend, missed-all and separate oracle block. Existing908generated/153classroom only.', 'A5a DONE: classroom long-handoff pairs recomputed and listed; stored metadata/mtime precedes2026-10-15, but human author and exact authoring tool are unestablished. Supplied authored example, not natural LLM fault incidence.', 'A5b DONE with explicit scope: requested12=original-natural1group + ownership-repair2groups9zones. Classroom itself has3groups0zones. Counterfactuals remove ONLY object-level ownership, for all members of each latent entity; no group override removed to force expected result. All members/allagents measured. Exact results in numbers/table, including masking/null outcomes. These are injected counterfactual faults, not12observed natural deciding-level faults.', 'A5c DONE:45comparable fresh-regeneration pairs separated from4edit/rename pairs; partition comparison on matched,defined objects. Equality does not prove semantic equivalence.', 'No existing raw/cache/table/claims/gates/delta1 file modified. All retained inputs rehashed; no API calls.']
(O/'item_notes_a4_a5.md').write_text('\n\n'.join(notes)+'\n',encoding='utf-8');print('A4_A5_COMPLETE',flush=True)

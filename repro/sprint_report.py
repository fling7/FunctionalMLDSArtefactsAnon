"""Offline descriptive report replay of explicitly retained sprint inputs."""
from __future__ import annotations
import argparse,csv,json,hashlib,math,random,socket,sys
from collections import Counter,defaultdict
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def lines(p):
 if p.exists():
  with p.open(encoding='utf-8-sig') as f:
   for s in f:
    if s.strip():yield json.loads(s)
def csvrows(p):
 if not p.exists():return []
 with p.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def writecsv(p,rows,fields=None):
 p.parent.mkdir(parents=True,exist_ok=True);fields=fields or list(dict.fromkeys(k for r in rows for k in r))
 if not fields:fields=['status','reason'];rows=[{'status':'NOT DONE','reason':'No retained observations in this snapshot'}]
 with p.open('w',encoding='utf-8',newline='') as f:
  w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');w.writeheader();w.writerows({k:json.dumps(v,sort_keys=True) if isinstance(v,(list,dict)) else v for k,v in r.items()} for r in rows)
def wilson(x,n):
 if not n:return None
 z=1.959963984540054;p=x/n;d=1+z*z/n;c=(p+z*z/(2*n))/d;h=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/d;return [max(0,c-h),min(1,c+h)]
def key(v):return tuple(v.get(k) for k in ['decision','reason','provider','action'])
def aggregate_mutants(data):
 matrix=defaultdict(Counter);ablation=defaultdict(Counter);counts=Counter();seen=set()
 def consume(cohort,r):
  ident=(cohort,r['metadata']['id']);assert ident not in seen,ident;seen.add(ident);counts[cohort]+=1
  groups=['all']+['operator:'+s for s in r['metadata'].get('operators',[])]+['fault_class:'+s for s in r['groundtruth'].get('fault_classes',[])]
  if len(r['metadata'].get('operators',[]))==2 and r['metadata'].get('status')=='changed':groups+=['two_operator']
  checks={k:v.get('status') for k,v in r['checkers'].items() if k!='I3_rejection_atomicity'}
  for union,prefix in [('Va_Vb_union',('Va_','Vb_')),('authoring_loader_union',('Va_','Vb_','Vc_'))]:
   ss=[v for k,v in checks.items() if k.startswith(prefix)];checks[union]='reject' if 'reject' in ss else 'pass' if ss and all(s=='pass' for s in ss) else 'not_applicable'
  truth=r['groundtruth']['routing_faulty']
  for group in groups:
   for checker,status in checks.items():
    cell='excluded_groundtruth' if truth is None else 'not_applicable' if status not in ('pass','reject') else 'tp' if truth and status=='reject' else 'fn' if truth else 'fp' if status=='reject' else 'tn';matrix[(cohort,group,checker)][cell]+=1
  wrong_models=Counter();executed_models=set()
  for p in r['probes']:
   endpoints=[(variant,v,p['I1'],p['I2']) for variant,v in p['variants'].items()]
   stale=p.get('stale_request',{})
   endpoints += [('stale_'+variant,stale[variant],stale['I1'],stale['I2']) for variant in ('runtime','no_digest') if variant in stale]
   for variant,v,oracle1,oracle2 in endpoints:
    a=ablation[(cohort,variant)];a['probe_slots']+=1
    if v.get('status')=='not_run_setup_refused':a['setup_refused_probes']+=1;continue
    a['executed_probes']+=1;executed_models.add(variant)
    wrong=v.get('decision') in ('ANSWER_LOCAL','ANSWER_AFTER_HANDOFF') and key(v)!=key(oracle1) and key(oracle1)==key(oracle2);a['wrongly_admitted_probes']+=wrong;wrong_models[variant]+=wrong
  for variant in executed_models:ablation[(cohort,variant)]['executed_models']+=1;ablation[(cohort,variant)]['models_with_wrong_admission']+=bool(wrong_models[variant])
 for p in sorted((data/'wp6/outcomes').glob('*.jsonl')):
  for r in lines(p):consume('generated',r)
 for p in sorted((data/'sprint/w2/completed').glob('*/*.json')):consume('generated',read(p))
 for p in sorted((data/'wp6_classroom').glob('snapshot/*/outcomes/*.json')):consume('classroom',read(p))
 rows=[]
 for (cohort,group,checker),c in sorted(matrix.items()):
  cells={k:c[k] for k in ('tp','fp','fn','tn','excluded_groundtruth','not_applicable')};rows.append({'cohort':cohort,'group':group,'checker':checker,'interpretation':'oracle sanity check, not independent sensitivity' if checker.startswith(('I1','I2')) else 'routing-fault detector endpoint','n_models':sum(c[k] for k in ('tp','fp','fn','tn')),**cells,'sensitivity_wilson95':wilson(c['tp'],c['tp']+c['fn']),'false_positive_wilson95':wilson(c['fp'],c['fp']+c['tn'])})
 abl=[{'cohort':cohort,'variant':variant,**dict(c),'model_wrong_admission_wilson95':wilson(c['models_with_wrong_admission'],c['executed_models'])} for (cohort,variant),c in sorted(ablation.items())]
 return rows,abl,counts

def cluster(rows,predicate):
 groups=defaultdict(list)
 for r in rows:groups[r.get('room',r.get('source_room_id'))].append(int(predicate(r)))
 keys=sorted(groups)
 if not keys:return None
 rng=random.Random(20261019);values=[]
 for _ in range(2000):
  selected=[groups[rng.choice(keys)] for _ in keys];values.append(sum(map(sum,selected))/sum(map(len,selected)))
 values.sort();return [values[49],values[1949]]

def build(data,out):
 out.mkdir(parents=True,exist_ok=True);tables=out/'tables';figures=out/'figures';numbers={};manifest=read(data/'INPUT_MANIFEST.json')
 for rel,pin in manifest.items():
  if hashlib.sha256((data/rel).read_bytes()).hexdigest()!=pin:raise ValueError('Input pin mismatch: '+rel)
 prop=csvrows(data/'wp1_wp2_wp3/wp2/completed_observations.csv');diff=csvrows(data/'wp1_wp2_wp3/wp3/differential/probes.csv');inv=csvrows(data/'wp1_wp2_wp3/wp1/invariant_traceability.csv')
 numbers.update(property_rows=len(prop),property_distinct_models=len({r['model_sha256'] for r in prop}),differential_probes=len(diff),differential_disagreements=sum(r['all_verdicts_agree']=='False' for r in diff))
 routing=list(lines(data/'wp4_wp5/routing_primary_525.jsonl'));evaluation=[r for r in routing if r.get('split')=='evaluation' and r['baseline'] in ('B0','B1')];numbers['routing_evaluation_rooms']=len({r['source_room_id'] for r in evaluation});numbers['routing_evaluation_calls']=len(evaluation)
 w3=[read(p) for p in sorted((data/'sprint/w3/rows').glob('*.json'))];numbers['reject_experiment_retained']=len(w3);numbers['reject_experiment_successful_calls']=sum(r.get('status')=='SUCCESS' for r in w3)
 route_table=[]
 for cohort,rows in [('primary_exploratory',evaluation),('reject_sprint',w3)]:
  group=defaultdict(list)
  for r in rows:group[(r['baseline'],r['model'],r.get('fault_class','unspecified'))].append(r)
  for (baseline,model,fault),rr in sorted(group.items()):
   valid=[r for r in rr if r.get('status')=='SUCCESS'];c=Counter(r.get('outcome') for r in valid)
   route_table.append({'cohort':cohort,'baseline':baseline,'model':model,'fault_class':fault,'attempts':len(rr),'successful_calls':len(valid),'rooms':len({r.get('room',r.get('source_room_id')) for r in rr}),**{k:c[k] for k in ['CORRECT','WRONG_PROVIDER','SILENT_VIOLATION','ABSTAIN_OK','FORMAT_ERROR']},'silent_violation_room_cluster95':cluster(valid,lambda r:r['outcome']=='SILENT_VIOLATION'),'wrong_provider_room_cluster95':cluster(valid,lambda r:r['outcome']=='WRONG_PROVIDER')})
 numbers['B0_primary_wrong']=sum(r['outcome']=='WRONG_PROVIDER' for r in evaluation if r['baseline']=='B0');numbers['B1_primary_wrong']=sum(r['outcome']=='WRONG_PROVIDER' for r in evaluation if r['baseline']=='B1')
 writecsv(tables/'T2_routing_baselines.csv',route_table)
 runs=[r for p in sorted((data/'pipeline_runs').glob('*.jsonl')) for r in lines(p)];pipeline=[]
 for r in runs:
  source=r.get('source',{});pipeline.append({'case_id':r.get('case_id'),'source_id':source.get('source_id',source.get('scene_id')),'phase':source.get('phase','original'),'model':source.get('model'),'status':r.get('status'),'failure_stage':r.get('failure_stage'),'repair_attempts':r.get('repair_attempts'),'before_repair_native':'not available: stage repairs precede native assembly; retained candidates are separate'})
 writecsv(tables/'T3_pipeline_outcomes.csv',pipeline)
 audits=[read(p) for p in sorted((data/'sprint/w4/models').glob('*.json'))];good=[r for r in audits if 'model' in r and r.get('authoring') is not None and 'gate0_ok' in r and r.get('probes') and all(all(k in p for k in ('I1','I2','Gate0')) and p['I1']==p['I2']==p['Gate0'] for p in r['probes']) and not r.get('disagreements')];native=[r for r in good if r['model']['cohort'] not in ('classroom','evaluation_routing')]
 numbers['audited_native_models']=len(native);numbers['audited_native_sources']=len({r['model']['source_id'] for r in native});numbers['native_audit_disagreements']=sum(r.get('disagreements',0) for r in audits);numbers['pipeline_terminal_records']=len(pipeline);writecsv(tables/'T3_native_audits.csv',[{'model_id':r['model']['model_id'],'source_id':r['model']['source_id'],'cohort':r['model']['cohort'],'objects':r['model']['objects'],'authoring_ok':r.get('authoring',{}).get('ok'),'gate0_ok':r.get('gate0_ok'),'probes':len(r.get('probes',[])),'label_disagreements':r.get('disagreements'),'reject_pairs':sum(p['decision']=='REJECT' for p in r.get('probes',[]))} for r in audits if 'model' in r])
 matrix,ablation,counts=aggregate_mutants(data);numbers['generated_mutants_complete']=counts['generated'];numbers['generated_mutants_scheduled']=908;numbers['generated_mutants_missing']=908-counts['generated'];numbers['classroom_mutants_complete']=counts['classroom'];writecsv(tables/'T4_detection_matrix.csv',matrix);writecsv(tables/'T5_executed_ablation.csv',ablation)
 writecsv(tables/'T1_corpus.csv',[{'cohort':'evaluation_routing','unit':'source room','observed':numbers['routing_evaluation_rooms'],'scheduled':20},{'cohort':'native_pipeline_audited','unit':'source room','observed':numbers['audited_native_sources'],'scheduled':30},{'cohort':'generated_mutants','unit':'mutant model','observed':counts['generated'],'scheduled':908},{'cohort':'classroom_mutants','unit':'mutant model','observed':counts['classroom'],'scheduled':153},{'cohort':'property_completed','unit':'distinct model','observed':numbers['property_distinct_models'],'scheduled':5000}])
 protocol=read(data/'wp7/summary.json');writecsv(tables/'T6_commit_protocol.csv',[{'metric':k,'value':v,'unit':'states' if 'states' in k else 'sessions' if 'sessions' in k else 'commits' if 'commit' in k and 'cells' not in k else 'cells' if 'cells' in k else 'schedules' if 'schedules' in k else 'rows' if 'rows' in k else 'recorded events','scope':'synthetic finite schedules / retained stress'} for k,v in protocol['numbers'].items()]);numbers.update(protocol['numbers'])
 scopes=csvrows(data/'exports/fingerprint_scopes_pairs.csv');writecsv(tables/'T7_fingerprint_scopes.csv',scopes);numbers['scope_pairs_measured']=sum(r.get('status')=='measured' for r in scopes)
 cost=csvrows(data/'exports/cost_scale.csv');writecsv(tables/'T8_cost_scale.csv',cost);numbers['cost_cells_done']=sum(r.get('status')=='DONE' for r in cost)
 dcounts=Counter((r['variant'],r['all_verdicts_agree'],r['decisions_agree']) for r in diff);writecsv(tables/'T9_independence.csv',[{'variant':k[0],'all_agree':k[1],'decisions_agree':k[2],'probes':v} for k,v in sorted(dcounts.items())]);writecsv(tables/'T10_invariant_traceability.csv',inv)
 http=list(lines(data/'wp4_wp5/http_fixed600.jsonl'));writecsv(tables/'T11_HTTP.csv',http);numbers['http_rows']=len(http);numbers['http_valid_real_generations']=sum(bool(r.get('valid_real_generation')) for r in http);numbers['http_commits']=sum(bool(r.get('committed')) for r in http);numbers['http_commits_without_valid_generation']=sum(bool(r.get('committed')) and not r.get('valid_real_generation') for r in http)
 evolution=list(lines(data/'wp4_wp5/evolution_pairs_103.jsonl'));writecsv(tables/'T12_evolution.csv',evolution);numbers['evolution_registered']=len(evolution);numbers['evolution_comparable']=sum(r['independent_comparable_pair'] for r in evolution)
 (out/'numbers.json').write_text(json.dumps(numbers,sort_keys=True,indent=2)+'\n');draw(figures,numbers,route_table,pipeline,matrix,scopes,cost,data)
 outputs={p.relative_to(out).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in out.rglob('*') if p.is_file() and p.name not in ('REPLAY.json',)}
 (out/'REPLAY.json').write_text(json.dumps({'offline':True,'input_files_verified':len(manifest),'outputs':outputs,'scope':'Current retained report regenerated offline after integrated cache hash, request and outcome verification. Missing experiments remain explicitly missing.'},sort_keys=True,indent=2)+'\n');print(json.dumps(numbers,sort_keys=True))

def draw(folder,numbers,routing,pipeline,matrix,scopes,cost,data):
 import matplotlib
 matplotlib.use('Agg')
 import matplotlib.pyplot as plt
 plt.rcParams.update({'font.size':8,'axes.titlesize':9,'svg.hashsalt':'sprint20261019','pdf.fonttype':42,'svg.fonttype':'none'})
 folder.mkdir(parents=True,exist_ok=True)
 def finish(fig,name):
  fig.tight_layout();fig.savefig(folder/(name+'.svg'),metadata={'Date':None,'Creator':'Research artifact'});fig.savefig(folder/(name+'.pdf'),metadata={'CreationDate':None,'ModDate':None,'Creator':'Research artifact','Author':'Anonymous Authors'});plt.close(fig)
 fig,axes=plt.subplots(1,2,figsize=(17.5/2.54,6/2.54))
 axes[0].bar(['B0','B1'],[numbers['B0_primary_wrong'],numbers['B1_primary_wrong']],color=['#0072B2','#E69F00'],edgecolor='black',hatch='//');axes[0].set_ylabel('Declared-model deviations');axes[0].set_title('Primary:240 calls per arm')
 values=[sum(r['SILENT_VIOLATION'] for r in routing if r['cohort']=='reject_sprint' and r['baseline']==base) for base in ['B0','B1','B1r']]
 axes[1].bar(['B0','B1','B1r'],values,color=['#0072B2','#E69F00','#999999'],edgecolor='black',hatch='//');axes[1].set_ylabel('Silent violations');axes[1].set_title('Reject study:90 calls per arm');finish(fig,'F3_routing')
 fig,axes=plt.subplots(1,2,figsize=(17.5/2.54,7/2.54));c=Counter(r['status'] for r in pipeline);axes[0].bar(list(c),list(c.values()),color='#0072B2');axes[0].set_ylabel('Retained pipeline attempts');axes[0].tick_params(axis='x',rotation=25)
 audit_rows=[read(p) for p in (data/'sprint/w4/models').glob('*.json')];native_rows=[r for r in audit_rows if r.get('model',{}).get('cohort') not in ('classroom','evaluation_routing')];probes=[p for r in native_rows for p in r.get('probes',[])];reasons=['E_UNOWNED','E_AMBIGUOUS_OWNER','E_NO_DECLARED_ACTION','E_ACTION_AMBIGUOUS'];faults=[sum(p.get('reason')==reason for p in probes) for reason in reasons]
 axes[1].bar(['Unowned','Ambiguous','No action','Action tie'],faults,color='#999999',edgecolor='black');axes[1].set_ylabel('Native fault probes');axes[1].set_ylim(0,max(1,max(faults)));axes[1].tick_params(axis='x',rotation=25,labelsize=7);axes[1].set_title(str(len(probes))+' dependent native probes');finish(fig,'F4_pipeline')
 rows=[r for r in matrix if r['cohort']=='generated' and r['group']=='all'];fig,ax=plt.subplots(figsize=(17.5/2.54,10/2.54));im=ax.imshow([[r[k] for k in ['tp','fp','fn','tn']] for r in rows],aspect='auto',cmap='Greys');ax.set_yticks(range(len(rows)),[r['checker']+(' (oracle)' if r['checker'].startswith(('I1','I2')) else '') for r in rows],fontsize=7);ax.set_xticks(range(4),['TP','FP','FN','TN']);ax.set_title(f"Generated cohort: {numbers['generated_mutants_complete']}/908 retained mutants");fig.colorbar(im,ax=ax,label='Mutant count');finish(fig,'F5_detection')
 # Use retained packet trace when available; missing trace is disclosed, not synthesized.
 traces=[]
 for p in sorted((data/'wp7').rglob('*.json')):
  if 'interleaving' in str(p):
   x=read(p)
   def walk(v):
    if isinstance(v,dict):
     for k,z in v.items():
      if ('counterexample' in k or k=='trace') and isinstance(z,list) and z:traces.append(z)
      else:walk(z)
    elif isinstance(v,list):
     for z in v:walk(z)
   walk(x)
 fig,ax=plt.subplots(figsize=(17.5/2.54,10/2.54));ax.axis('off')
 if traces:
  trace=traces[0];ax.set_xlim(-.3,1.6);ax.set_ylim(-1,len(trace));ax.plot([0,0],[0,len(trace)-1],color='#777777')
  for i,event in enumerate(trace):
   y=len(trace)-1-i;ax.plot(0,y,'o',color='#D55E00' if 'VIOLATION' in str(event) else '#0072B2');ax.text(.08,y,str(i+1)+'. '+str(event),va='center',fontsize=7)
  ax.set_title('Retained packet counterexample: ordered abstract transitions')
 else:ax.text(0,1,'NOT DONE: detailed packet trace unavailable',va='top',fontsize=7)
 finish(fig,'F6_protocol')
 fig,ax=plt.subplots(figsize=(8.5/2.54,6/2.54));fields=['F0_digest','F1_packet_fingerprint','F2_routing_slice','F3_slice_plus_prompt'];ax.bar(['F0','F1','F2','F3'],[sum(r.get(k)=='True' for r in scopes) for k in fields],color='#0072B2');ax.set_ylabel('Pairs with changed fingerprint');ax.set_title(f"{numbers['scope_pairs_measured']} measured pairs");finish(fig,'F7_scopes')
 fig,ax=plt.subplots(figsize=(17.5/2.54,7/2.54));valid=[r for r in cost if r.get('status')=='DONE'];
 if valid:
  labels=[str(r['size'])+'/'+r['cell'] for r in valid];ax.barh(labels,[float(r['p50_ms']) for r in valid],color='#0072B2');ax.tick_params(axis='y',labelsize=7);ax.set_xlabel('Median process CPU milliseconds')
 else:ax.text(.1,.5,'NOT DONE: requested cost cells unavailable',transform=ax.transAxes)
 finish(fig,'F8_cost')

def main():
 p=argparse.ArgumentParser();p.add_argument('--replay',action='store_true',required=True);p.add_argument('--output',type=Path,default=ROOT/'results/replay/go_sprint');a=p.parse_args()
 def deny(*a,**k):raise RuntimeError('Network disabled during report replay')
 socket.create_connection=deny;socket.socket.connect=deny
 from repro.report_cache import verify
 proof=verify(ROOT,ROOT/'data/go_sprint')
 build(ROOT/'data/go_sprint',a.output.resolve())
 (a.output.resolve()/'CACHE_REPLAY.json').write_text(json.dumps(proof,sort_keys=True,indent=2)+'\n',encoding='utf-8')
 manifest_path=a.output.resolve()/'REPLAY.json';manifest=read(manifest_path);manifest['outputs']['CACHE_REPLAY.json']=hashlib.sha256((a.output.resolve()/'CACHE_REPLAY.json').read_bytes()).hexdigest();manifest_path.write_text(json.dumps(manifest,sort_keys=True,indent=2)+'\n',encoding='utf-8')
 return 0
if __name__=='__main__':raise SystemExit(main())

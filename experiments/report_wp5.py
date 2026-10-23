"""Deterministic WP5 corpus/repair tables and generation/reachability figures.

Original frozen50 outcomes retain their own denominator. Extension results are
separately labeled exploratory; probes never become independent source samples.
"""
from __future__ import annotations
import argparse,csv,hashlib,json,random
from pathlib import Path
from experiments.lib.wp5_reporting import ROOT,BACKEND,clustered_interval

def read(path):return json.loads(Path(path).read_text(encoding='utf-8-sig'))
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def tex(text):
    value=str(text)
    for old,new in (('\\',r'\textbackslash{}'),('_',r'\_'),('%',r'\%'),('&',r'\&'),('#',r'\#')):value=value.replace(old,new)
    return value

def table(name,rows,columns,tex_columns=None):
    folder=ROOT/'paper_inputs/tables';folder.mkdir(parents=True,exist_ok=True)
    with (folder/(name+'.csv')).open('w',encoding='utf-8',newline='') as handle:
        writer=csv.DictWriter(handle,fieldnames=columns,extrasaction='ignore');writer.writeheader();writer.writerows(rows)
    columns=tex_columns or columns
    lines=[r'\begin{tabular}{'+'l'*len(columns)+'}',r'\toprule',' & '.join(tex(c) for c in columns)+r' \\',r'\midrule']
    for row in rows:lines.append(' & '.join(tex('NA' if row.get(c) is None else row[c]) for c in columns)+r' \\')
    lines.extend([r'\bottomrule',r'\end{tabular}'])
    (folder/(name+'.tex')).write_text('\n'.join(lines)+'\n',encoding='utf-8',newline='\n')

def corpus_domain_rows(original):
    scenes=read(ROOT/'experiments/scenes/sources/manifest.json')['scenes'];rows=[]
    for domain in sorted({r['domain'] for r in scenes}):
        source_ids={r['scene_id'] for r in scenes if r['domain']==domain};selected=[r for r in original['rows'] if r['source_room_id'] in source_ids]
        rows.append({'corpus':'original deterministic','domain':domain,'generated_sources':len(source_ids),
            'development_sources':sum(r['split']=='dev' for r in scenes if r['scene_id'] in source_ids),
            'evaluation_pool_sources':sum(r['split']=='evaluation' for r in scenes if r['scene_id'] in source_ids),
            'evaluated_distinct_sources':len({r['source_room_id'] for r in selected}),'pipeline_model_runs':len(selected),
            'native_valid_model_runs':sum(r['eligible_native_success'] and r['gate0_ok'] is True for r in selected),
            'native_valid_distinct_sources':len({r['source_room_id'] for r in selected if r['eligible_native_success'] and r['gate0_ok'] is True}),
            'status':'terminal original50'})
    combined_path=ROOT/'results/processed/wp5_primary_projects.json'
    if combined_path.exists():
        combined=read(combined_path)
        for family in ('extension_deterministic','extension_llm'):
            selected=[r for r in combined['rows'] if r['corpus_family']==family]
            rows.append({'corpus':family+' exploratory','domain':'12 fixed domains','generated_sources':sum(r['source_valid'] for r in selected),
                'development_sources':0,'evaluation_pool_sources':12,'evaluated_distinct_sources':sum(r['terminal_status']=='completed' or (r['terminal_status']=='failed' and r['failure_stage']!='not_attempted') for r in selected),
                'pipeline_model_runs':sum(r['failure_stage']!='not_attempted' for r in selected),'native_valid_model_runs':sum(r['eligible_native_success'] for r in selected),
                'native_valid_distinct_sources':len({r['source_room_id'] for r in selected if r['eligible_native_success']}),
                'status':'terminal exploratory initial' if combined['manifest_is_complete'] else 'partial exploratory initial'})
    return rows

def before_after_rows(original,natural_rows):
    natural={r['room']:r for r in natural_rows};rows=[]
    for selected in original['rows']:
        run=read(ROOT/selected['run_result_path']);analysis=natural[selected['case_id']]
        rows.append({'arm':'original frozen','source_id':selected['source_room_id'],'model':selected['pipeline_model'],'case_id':selected['case_id'],
            'pipeline_status':run['status'],'failure_stage':run.get('failure_stage','none'),'stage_repair_attempts':run['repair_attempts'],
            'before_authoring_status':'retained candidate reports' if analysis['candidate_reports'] else 'unavailable',
            'after_authoring_status':'valid' if selected['canonical_valid'] and selected['schema_valid'] else 'not fully valid',
            'before_native_available':False,'after_native_available':selected['project_produced'],'gate0_after':selected['gate0_ok'],
            'source_denominator':'30 distinct original sources','run_denominator':'50 registered original model runs',
            'analysis_path':f"results/raw/wp5/natural_evaluation_v1/rooms/{selected['case_id']}.json"})
    for path in sorted((ROOT/'results/raw/wp5_extension/ownership_repair').glob('*/repair_result.json')):
        result=read(path);candidate=result['candidate']
        rows.append({'arm':'exploratory targeted repair','source_id':candidate['source']['scene_id'],'model':candidate['source']['model'],'case_id':candidate['case_id'],
            'pipeline_status':result['status'],'failure_stage':result.get('error_code','none'),'stage_repair_attempts':result.get('generation_request_attempts',0),
            'before_authoring_status':result['before_report']['status'],'after_authoring_status':result.get('after_report',{}).get('status','unavailable'),
            'before_native_available':False,'after_native_available':bool(result.get('after_native_project') and (ROOT/result['after_native_project']/'roomcontract.v2.instance.json').is_file()),
            'gate0_after':'see retained repair run','source_denominator':'3 preregistered natural-failure sources','run_denominator':'3 registered repair requests',
            'analysis_path':path.relative_to(ROOT).as_posix()})
    return rows

def figure(original,rooms):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':8,'axes.spines.top':False,'axes.spines.right':False,'axes.titlesize':8,'axes.labelsize':8,'xtick.labelsize':7,'ytick.labelsize':7,
        'svg.hashsalt':'wp5-f4-source-denominators-v1','svg.fonttype':'none','pdf.fonttype':42})
    models=sorted({r['pipeline_model'] for r in original['rows']},key=lambda m:('mini' not in m,m));rows=[]
    for model in models:
        registered=[r for r in original['rows'] if r['pipeline_model']==model]
        inputs=[{'source':{'scene_id':r['source_room_id']},'value':float(r['pipeline_success'])} for r in registered]
        interval=clustered_interval(inputs,lambda r:r['value'],repetitions=10000)
        rows.append({'metric':'generation_success','model':model,'estimate':interval['estimate'],'low':interval['low'],'high':interval['high'],
            'source_clusters':interval['source_clusters'],'model_runs':len(registered),'probes':None,'numerator':sum(r['pipeline_success'] for r in registered),'denominator':len(registered)})
        native=[r for r in rooms if r['source']['model']==model and 'rates' in r]
        for sample in ('all_pairs','nearest_agent'):
            for h in (1,2,3):
                interval=clustered_interval(native,lambda r:r['rates'][sample][str(h)],repetitions=10000)
                probes=[p for r in native for p in r['probes'] if sample=='all_pairs' or p['nearest_agent_proxy']]
                rows.append({'metric':sample+'_hop'+str(h),'model':model,'estimate':interval['estimate'],'low':interval['low'],'high':interval['high'],
                    'source_clusters':interval['source_clusters'],'model_runs':len(native),'probes':len(probes),
                    'numerator':sum(p['static_admitted_at_hop_limit'][str(h)] for p in probes),'denominator':len(probes)})
    table('WP5_generation_hop_denominators',rows,list(rows[0]))
    folder=ROOT/'paper_inputs/figures';folder.mkdir(parents=True,exist_ok=True)
    colors=['#176B8A','#BC5A45']
    for name,width,height in (('single',8.5/2.54,4.40),('double',17.5/2.54,2.85)):
        if name=='single':fig,axes=plt.subplots(2,1,figsize=(width,height),gridspec_kw={'height_ratios':[1,1.4]})
        else:fig,axes=plt.subplots(1,2,figsize=(width,height),gridspec_kw={'width_ratios':[1,1.6]})
        for i,model in enumerate(models):
            row=next(r for r in rows if r['model']==model and r['metric']=='generation_success');y=row['estimate'];lo=row['low'];hi=row['high']
            axes[0].bar(i,y,color=colors[i],width=.6,yerr=[[y-lo],[hi-y]] if lo is not None else None,capsize=3)
            axes[0].text(i,min(1.03,(hi if hi is not None else y)+.04),f"{row['numerator']}/{row['denominator']} runs",ha='center',fontsize=7)
            for sample,style in (('all_pairs','-'),('nearest_agent','--')):
                points=[next(r for r in rows if r['model']==model and r['metric']==sample+'_hop'+str(h)) for h in (1,2,3)]
                axes[1].plot([1,2,3],[p['estimate'] for p in points],style,marker='o' if i==0 else 's',color=colors[i],label=('mini' if 'mini' in model else 'full')+' '+('all pairs' if sample=='all_pairs' else 'nearest proxy'))
        axes[0].set(xticks=[0,1],xticklabels=['4.1 mini','4.1'],ylim=(0,1.12),ylabel='Generation success',title='Original frozen50')
        axes[1].set(xticks=[1,2,3],ylim=(-.02,1.05),xlabel='Static maximum handoffs',ylabel='Source-cluster mean admission',title='Produced native rooms only')
        axes[1].legend(fontsize=7,loc='lower right');axes[1].grid(axis='y',alpha=.2)
        fig.tight_layout();fig.savefig(folder/f'WP5_generation_reachability_{name}.svg',metadata={'Date':None});fig.savefig(folder/f'WP5_generation_reachability_{name}.pdf',metadata={'CreationDate':None,'ModDate':None});plt.close(fig)
    return rows

# Each metric retains its own observational unit. Latent ambiguities and graph
# properties are per-room counts/values, never divided by scene-object count.
FAULT_METRICS = {
    'unowned': ('objects', 'objects'),
    'ambiguous_deciding_level': ('objects', 'objects'),
    'without_declared_action': ('objects', 'objects'),
    'latent_group_ambiguities': (None, 'groups per room'),
    'latent_zone_ambiguities': (None, 'zones per room'),
    'more_than_one_handoff': ('pairs', 'start-agent/object pairs'),
    'no_path_to_unique_owner': ('pairs', 'start-agent/object pairs'),
    'isolated_agents': ('agents', 'agents'),
    'handoff_density': (None, 'directed graph density per room'),
    'directed_diameter': (None, 'directed graph diameter per room'),
}

def corpus_room_rows(original, natural_rows):
    natural = {r['room']: r for r in natural_rows}
    scenes = read(ROOT/'experiments/scenes/sources/manifest.json')['scenes']
    rows = []
    reference_source=ROOT/'output/case_studies/classroom_dinosaur/input/source_rdl.json'
    reference_agents=BACKEND/'projects/classroom_dinosaur/agents.json'
    if reference_source.exists() and reference_agents.exists():
        reference=read(reference_source);agents=read(reference_agents)['agents']
        rows.append({'room':'classroom_dinosaur','case_id':None,'corpus':'provided reference; separate',
            'domain':'classroom','objects':len(reference['scene']['objects']),'agents':len(agents),
            'authored_or_generated':'provided reference; authorship not evaluated','pipeline_model':None,
            'split':'reference','status':'provided model','source_sha256':sha(reference_source),'run_result_sha256':None})
    for scene in scenes:
        selected = [r for r in original['rows'] if r['source_room_id'] == scene['scene_id']]
        development=[]
        if scene['split']=='dev':
            development=[(p,read(p)) for p in sorted((ROOT/'results/raw/wp5/development').glob('*/run_result.json')) if read(p)['source']['scene_id']==scene['scene_id']]
        for path,run in development:
            project=ROOT/run['project_dir'] if run.get('project_dir') else None
            agent_path=project/'agents.json' if project else None
            agents=read(agent_path)['agents'] if agent_path and agent_path.exists() else None
            rows.append({'room':scene['scene_id'],'case_id':run['case_id'],'corpus':'development; excluded from evaluation',
                'domain':scene['domain'],'objects':scene['object_count'],'agents':len(agents) if agents is not None else None,
                'authored_or_generated':'deterministic source; real-LLM pipeline','pipeline_model':run['source']['model'],
                'split':'dev','status':run['status'],'source_sha256':scene['sha256'],'run_result_sha256':sha(path)})
        if not selected and not development:
            rows.append({'room':scene['scene_id'],'case_id':None,'corpus':'original source pool',
                'domain':scene['domain'],'objects':scene['object_count'],'agents':None,
                'authored_or_generated':'deterministic source; no evaluation model run',
                'pipeline_model':None,'split':scene['split'],'status':'not in original50',
                'source_sha256':scene['sha256'],'run_result_sha256':None})
        for selected_row in selected:
            analysis = natural[selected_row['case_id']]
            rows.append({'room':scene['scene_id'],'case_id':selected_row['case_id'],'corpus':'original frozen50',
                'domain':scene['domain'],'objects':scene['object_count'],
                'agents':analysis.get('graph',{}).get('agent_count'),
                'authored_or_generated':'deterministic source; real-LLM pipeline',
                'pipeline_model':selected_row['pipeline_model'],'split':'evaluation',
                'status':'native produced' if selected_row['project_produced'] else 'pipeline failed; no native',
                'source_sha256':scene['sha256'],'run_result_sha256':selected_row['run_result_sha256']})
    combined_path = ROOT/'results/processed/wp5_primary_projects.json'
    if combined_path.exists():
        combined = read(combined_path)
        if not combined.get('manifest_is_complete'):raise RuntimeError('Do not report an incomplete exploratory initial corpus as final')
        plan = read(ROOT/combined['extension_plan_path'])
        domain = {r['source_id']:r['domain'] for key in ('new_deterministic_sources','llm_authored_sources') for r in plan[key]}
        for selected in combined['rows']:
            if selected['corpus_family']=='original':continue
            source = read(ROOT/selected['source_path']) if selected.get('source_path') else None
            project = ROOT/selected['project_path'] if selected.get('project_path') else None
            agents = read(project/'agents.json')['agents'] if project and (project/'agents.json').exists() else None
            rows.append({'room':selected['source_room_id'],'case_id':selected['case_id'],
                'corpus':selected['corpus_family']+' exploratory','domain':domain[selected['source_room_id']],
                'objects':len(source['scene']['objects']) if source else None,'agents':len(agents) if agents is not None else None,
                'authored_or_generated':('LLM-authored source' if selected['corpus_family']=='extension_llm' else 'deterministic source')+'; real-LLM pipeline',
                'pipeline_model':selected['pipeline_model'],'split':'exploratory initial','status':selected['terminal_status'],
                'source_sha256':selected['source_sha256'],'run_result_sha256':selected['run_result_sha256']})
    return rows

def fault_row(analysis, *, corpus='original frozen50', timepoint='after pipeline', path=None):
    counts=analysis.get('object_faults',{}); pairs=analysis.get('pair_counts',{}); graph=analysis.get('graph',{})
    native=bool(analysis.get('model_sha256')); available=bool(counts)
    candidates=[r for r in analysis.get('candidate_reports',[]) if 'ambiguous_asset_declarations' in r]
    result={'source':analysis['source'],'corpus':corpus,'source_id':analysis['source']['scene_id'],
        'model':analysis['source']['model'],'case_id':analysis['room'],'timepoint':timepoint,
        'pipeline_status':analysis.get('original_pipeline_status'),'failure_stage':analysis.get('failure_stage'),
        'native_available':native,'native_fault_labels_available':available,
        'objects':counts.get('objects'),'agents':graph.get('agent_count'),'pairs':pairs.get('all'),
        'gate0_ok':analysis.get('Gate0',{}).get('ok'),'runtime_setup_error':analysis.get('runtime_setup_error'),
        'independent_runtime_disagreements':pairs.get('disagreements'),
        'isolated_agents':len(graph['isolated_agents']) if 'isolated_agents' in graph else None,
        'handoff_density':graph.get('density'),'directed_diameter':graph.get('directed_diameter'),
        'unreachable_agent_pairs':graph.get('unreachable_agent_pairs'),
        'before_native_available':False,
        'retained_candidate_reports':len(analysis.get('candidate_reports',[])),
        'maximum_ambiguous_assets_in_one_retained_candidate':max((len(r['ambiguous_asset_declarations']) for r in candidates),default=None),
        'stage_repair_attempts':analysis.get('repair_attempts',0),
        'analysis_path':path,'analysis_sha256':sha(ROOT/path) if path else None,
        'before_native_caveat':'Not synthesized: retained authoring candidates precede native assembly.'}
    for key in ('unowned','ambiguous_deciding_level','without_declared_action','latent_group_ambiguities','latent_zone_ambiguities'):result[key]=counts.get(key)
    for key in ('more_than_one_handoff','no_path_to_unique_owner'):result[key]=pairs.get(key)
    for key,(denominator,_) in FAULT_METRICS.items():
        result[key+'_rate']=result[key]/result[denominator] if denominator and result.get(key) is not None and result.get(denominator) else None
    return result

def fault_rows(original_rooms, extension_analysis=None):
    rows=[fault_row(r,path='results/raw/wp5/natural_evaluation_v1/rooms/'+r['room']+'.json') for r in original_rooms]
    if extension_analysis:
        manifest=read(extension_analysis)
        if manifest.get('terminal') is not True:raise RuntimeError('Extension analysis report manifest is not terminal')
        for entry in manifest['rows']:
            path=ROOT/entry['path']
            if sha(path)!=entry['sha256']:raise RuntimeError('Pinned extension natural row changed')
            rows.append(fault_row(read(path),corpus=entry['corpus'],timepoint=entry['timepoint'],path=entry['path']))
    return rows

def pooled_interval(rows,metric,denominator,repetitions=10000):
    grouped={}
    for row in rows:grouped.setdefault(row['source_id'],[]).append(row)
    clusters=[grouped[key] for key in sorted(grouped)]
    if not clusters:return {'estimate':None,'low':None,'high':None}
    def value(sample):
        records=[row for cluster in sample for row in cluster]
        total=sum(row[denominator] for row in records) if denominator else len(records)
        return sum(row[metric] for row in records)/total
    rng=random.Random(20261015)
    samples=sorted(value([clusters[rng.randrange(len(clusters))] for _ in clusters]) for _ in range(repetitions))
    return {'estimate':value(clusters),'low':samples[int(.025*(repetitions-1))],'high':samples[int(.975*(repetitions-1))]}

def pooled_faults(rows):
    result=[]
    groups=sorted({(r['corpus'],r['model'],r['timepoint']) for r in rows})
    for corpus,model,timepoint in groups:
        registered=[r for r in rows if (r['corpus'],r['model'],r['timepoint'])==(corpus,model,timepoint)]
        for metric,(denominator,unit) in FAULT_METRICS.items():
            selected=[r for r in registered if r.get(metric) is not None and (not denominator or r.get(denominator))]
            interval=clustered_interval(selected,lambda r:r[metric]/r[denominator] if denominator else r[metric],repetitions=10000)
            pooled_interval_result=pooled_interval(selected,metric,denominator)
            numerator=sum(r[metric] for r in selected); total=sum(r[denominator] for r in selected) if denominator else len(selected)
            result.append({'corpus':corpus,'pipeline_model':model,'timepoint':timepoint,'metric':metric,'observational_unit':unit,
                'registered_model_runs':len(registered),'registered_source_rooms':len({r['source_id'] for r in registered}),
                'available_model_runs':len(selected),'missing_model_runs':len(registered)-len(selected),
                'source_clusters':interval['source_clusters'],'pooled_numerator':numerator,'pooled_denominator':total,
                'pooled_rate_or_mean':numerator/total if total else None,'pooled_ci_low':pooled_interval_result['low'],'pooled_ci_high':pooled_interval_result['high'],'source_cluster_mean':interval['estimate'],
                'source_cluster_ci_low':interval['low'],'source_cluster_ci_high':interval['high'],
                'interval_scope':'bootstrap resamples whole source clusters; pooled ratio and source-cluster mean reported separately'})
    return result

def fault_figure(rows):
    import numpy as np
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.colors import Normalize
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':8,'axes.titlesize':8,'axes.labelsize':8,
        'xtick.labelsize':7,'ytick.labelsize':7,'legend.fontsize':7,
        'svg.hashsalt':'wp5-f4-natural-faults-v1','svg.fonttype':'none','pdf.fonttype':42})
    metrics=['unowned','ambiguous_deciding_level','without_declared_action','latent_group_ambiguities',
        'latent_zone_ambiguities','more_than_one_handoff','no_path_to_unique_owner','isolated_agents','maximum_ambiguous_assets_in_one_retained_candidate']
    labels=['Unowned','Ambiguous','No action','Latent group','Latent zone','Multi-hop','No path','Isolated','Role cand.']
    folder=ROOT/'paper_inputs/figures';folder.mkdir(parents=True,exist_ok=True)
    for corpus in sorted({r['corpus'] for r in rows}):
        selected=[r for r in rows if r['corpus']==corpus]
        suffix='' if corpus=='original frozen50' else '_exploratory_'+hashlib.sha256(corpus.encode()).hexdigest()[:8]
        maximum=max((r[k] for r in selected for k in metrics if r[k] is not None),default=0)
        for name,width_cm in (('single',8.5),('double',17.5)):
            blocks=[selected] if name=='single' else [selected[:(len(selected)+1)//2],selected[(len(selected)+1)//2:]]
            height=max(3.2,max(map(len,blocks))*.135+1.5)
            fig,axes=plt.subplots(1,len(blocks),figsize=(width_cm/2.54,height),squeeze=False)
            for ax,block in zip(axes.flat,blocks):
                data=np.array([[r[k] if r[k] is not None else np.nan for k in metrics] for r in block],dtype=float)
                colors=plt.colormaps['Blues'].copy();colors.set_bad('#d9d9d9')
                ax.imshow(np.ma.masked_invalid(data),aspect='auto',cmap=colors,norm=Normalize(0,max(1,maximum)))
                names=[]
                for row in block:
                    sid=row['source_id'];short=sid.split('_')[1] if sid.startswith('scene_') else sid.replace('extension_','')[-16:]
                    names.append(short+(' M' if 'mini' in row['model'] else ' F'))
                ax.set(xticks=range(len(metrics)),xticklabels=labels,yticks=range(len(block)),yticklabels=names)
                ax.tick_params(length=0);plt.setp(ax.get_xticklabels(),rotation=50,ha='right',rotation_mode='anchor')
                ax.set_ylabel('Source / pipeline model (M mini, F full)')
                for y,row in enumerate(data):
                    for x,value in enumerate(row):
                        text='-' if np.isnan(value) else str(int(value))
                        ax.text(x,y,text,ha='center',va='center',fontsize=7,color='white' if not np.isnan(value) and maximum and value>maximum*.55 else 'black')
            sources=len({r['source_id'] for r in selected});native=sum(r['native_fault_labels_available'] for r in selected)
            fig.suptitle(f'Natural faults: {corpus}\n{sources} sources; {len(selected)} model runs; {native} native-label rows',fontsize=8)
            fig.text(.5,.008,'Gray / - = unavailable, not zero; units differ.\nRole cand. = maximum ambiguous assets in one retained candidate.',ha='center',fontsize=7,wrap=True)
            fig.tight_layout(rect=(0,.045,1,.95))
            target=folder/f'F4_natural_faults{suffix}_{name}'
            fig.savefig(target.with_suffix('.svg'),metadata={'Date':None})
            fig.savefig(target.with_suffix('.pdf'),metadata={'CreationDate':None,'ModDate':None});plt.close(fig)

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--extension-analysis-manifest',type=Path)
    args=parser.parse_args()
    root=ROOT/'results/raw/wp5/natural_evaluation_v1';terminal=read(root/'terminal.json')
    if not terminal.get('terminal'):raise RuntimeError('Natural analysis must be terminal before final paper outputs')
    original=read(ROOT/'results/raw/wp5/evaluation_final_manifest_v1.json');rooms=[read(ROOT/rel) for rel in sorted(terminal['room_sha256'])]
    for rel,expected in terminal['room_sha256'].items():
        if sha(ROOT/rel)!=expected:raise RuntimeError('Retained natural analysis changed')
    from experiments.source_native_coverage import audit_original
    coverage=audit_original(ROOT)
    coverage_path=ROOT/'results/processed/wp5_source_native_coverage.json'
    coverage_path.write_text(json.dumps(coverage,sort_keys=True,indent=2)+'\n',encoding='utf-8',newline='\n')
    coverage_rows=[{k:json.dumps(v,ensure_ascii=False) if isinstance(v,(dict,list)) else v for k,v in row.items()} for row in coverage['rows']]
    coverage_columns=list(dict.fromkeys(k for row in coverage_rows for k in row))
    table('WP5_source_native_coverage',coverage_rows,coverage_columns,['case_id','pipeline_model','source_object_records','native_target_records','absent_source_objects','extra_native_source_objects','coverage_fraction'])
    corpus=corpus_room_rows(original,rooms)
    table('T1_corpus',corpus,list(corpus[0]),['room','domain','objects','agents','authored_or_generated','pipeline_model'])
    domains=corpus_domain_rows(original)
    table('T1_corpus_domain_summary',domains,list(domains[0]))
    repairs=before_after_rows(original,rooms)
    table('T3_before_after_per_room_model',repairs,list(repairs[0]),['case_id','pipeline_status','stage_repair_attempts','before_native_available','after_native_available','gate0_after'])
    faults=fault_rows(rooms,args.extension_analysis_manifest)
    columns=[k for k in faults[0] if k!='source']
    table('T3_natural_faults_per_room',faults,columns,['case_id','timepoint','native_available','unowned','ambiguous_deciding_level','without_declared_action','latent_group_ambiguities','latent_zone_ambiguities'])
    pooled=pooled_faults(faults)
    table('T3_natural_faults_pooled',pooled,list(pooled[0]),['pipeline_model','metric','available_model_runs','pooled_numerator','pooled_denominator','pooled_rate_or_mean','pooled_ci_low','pooled_ci_high'])
    fault_figure(faults);plot=figure(original,rooms)
    summary={'schema':'wp5-paper-input-summary-v2','report_bootstrap':{'repetitions':10000,'seed':20261015,'unit':'whole source rooms','reason':'Mission brief section 6.7 reporting compliance correction; earlier 2000-resample outputs retained.'},'original_source_rooms':30,'original_registered_model_runs':50,
        'original_successful_native_model_runs':original['eligible_runs'],'original_successful_native_sources':original['eligible_distinct_sources'],
        'natural_probe_count':sum(r.get('pair_counts',{}).get('all',0) for r in rooms),'generation_and_reachability_denominators':plot,
        'natural_fault_source_cluster_summaries':pooled,'original_terminal_sha256':sha(ROOT/'results/raw/wp5/evaluation_terminal_v1.json'),
        'natural_terminal_sha256':sha(root/'terminal.json'),'extension_analysis_manifest_sha256':sha(args.extension_analysis_manifest) if args.extension_analysis_manifest else None,
        'source_native_coverage_path':coverage_path.relative_to(ROOT).as_posix(),'source_native_coverage_sha256':sha(coverage_path),
        'script_sha256':sha(Path(__file__)),'limits':'Faults use native model labels when available; failed/no-native rows are missing, not zero. Pooled ratios and source-cluster intervals have separate labels. Hop2/3 are static graph metrics. Nearest-agent start is a geometric proxy. Original50 and expanded exploratory corpus remain separate. Before-native models are never invented. Source objects absent from the native routing target set are separately reported by the post-freeze descriptive coverage audit; they are neither verified zero faults nor inferred unowned faults.'}
    path=ROOT/'results/processed/wp5_paper_summary.json';path.write_text(json.dumps(summary,sort_keys=True,indent=2)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps({k:v for k,v in summary.items() if k not in ('generation_and_reachability_denominators','natural_fault_source_cluster_summaries')}))
if __name__=='__main__':main()

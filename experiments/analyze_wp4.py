"""Raw-only WP4 analysis. No API import or network; room is the cluster."""
from __future__ import annotations
import argparse, csv, hashlib, json, math, sys
from collections import defaultdict
from decimal import Decimal
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
SEED=20261015
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from experiments.lib.wp4_reporting import attach_costs,cost_summary,load_manifest,question_summary,denominators,scored,ENGINEERING

def read_rows(directory):
    return [json.loads(p.read_text(encoding='utf-8-sig')) for p in sorted(Path(directory).glob('rows/*.json'))] if directory else []

def attach_gateway_costs(router,http,log_path=None):
    return attach_costs(router,http,log_path if log_path is not None else ROOT/'logs/llm_calls.jsonl')


def cluster_rate(rows,key):
    grouped=defaultdict(list)
    for r in rows:grouped[r['source_room_id']].append(float(bool(r.get(key))))
    means=np.array([sum(v)/len(v) for _,v in sorted(grouped.items())],dtype=float)
    if not len(means):return {'rooms':0,'rate':None,'lower':None,'upper':None}
    rate=float(means.mean())
    if len(means)<2:return {'rooms':len(means),'rate':rate,'lower':None,'upper':None}
    draws=np.random.default_rng(SEED).choice(means,size=(10000,len(means)),replace=True).mean(axis=1)
    lo,hi=np.quantile(draws,[.025,.975])
    return {'rooms':len(means),'rate':rate,'lower':float(lo),'upper':float(hi)}

def wilson(k,n):
    if not n:return (None,None)
    z=1.959963984540054;p=k/n;den=1+z*z/n
    middle=(p+z*z/(2*n))/den;half=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/den
    return (middle-half,middle+half)

def exact_mcnemar(n01,n10):
    n=n01+n10
    return 1.0 if n==0 else min(1.0,2*sum(math.comb(n,k) for k in range(min(n01,n10)+1))/(2**n))

def summarize_routing(rows):
    groups=defaultdict(list)
    keys=('split','model','baseline','abstain_allowed','phrasing','question_kind','temperature','fault_class')
    for r in rows:
        r={**r,'misroute':r.get('outcome') in ('WRONG_PROVIDER','SILENT_VIOLATION'),'silent_violation':r.get('outcome')=='SILENT_VIOLATION','format_error':r.get('outcome')=='FORMAT_ERROR','correct':r.get('outcome') in ('CORRECT','ABSTAIN_OK')}
        groups[tuple(r.get(k) for k in keys)].append(r)
    result=[]
    for key,group in sorted(groups.items(),key=lambda x:str(x[0])):
        row=dict(zip(keys,key));rate=cluster_rate(group,'misroute')
        row.update(attempts=len(group),generation_responses=sum(r.get('status')=='SUCCESS' and bool(r.get('response')) for r in group),rooms=rate['rooms'],misroute_count=sum(r['misroute'] for r in group),misroute_room_rate=rate['rate'],misroute_ci_low=rate['lower'],misroute_ci_high=rate['upper'],silent_violations=sum(r['silent_violation'] for r in group),format_errors=sum(r['format_error'] for r in group),correct_or_abstain_ok=sum(r['correct'] for r in group),unscored_failures=sum(r.get('status')!='SUCCESS' for r in group),input_tokens=sum(r.get('usage',{}).get('input_tokens',0) for r in group),output_tokens=sum(r.get('usage',{}).get('output_tokens',0) for r in group))
        latencies=[r['latency_seconds'] for r in group if 'latency_seconds' in r];cost=cost_summary(group);paid=Decimal(cost['accounted_cost_usd']) if cost['accounted_cost_usd'] is not None else None
        row.update(**cost,accounted_cost_per_attempt_usd=str(paid/len(group)) if paid is not None else None,attempt_latency_p50_seconds=float(np.quantile(latencies,.5)) if latencies else None,attempt_latency_p95_seconds=float(np.quantile(latencies,.95)) if latencies else None)
        valid_rows=[r for r in group if scored(r)]
        scored_rate=cluster_rate(valid_rows,'misroute')
        pooled_ci=wilson(sum(r['misroute'] for r in valid_rows),len(valid_rows))
        row.update(secondary_pooled_wilson_low=pooled_ci[0],secondary_pooled_wilson_high=pooled_ci[1],valid_scored_decisions=len(valid_rows),misroute_valid_scored_room_rate=scored_rate['rate'],misroute_valid_scored_ci_low=scored_rate['lower'],misroute_valid_scored_ci_high=scored_rate['upper'])
        result.append(row)
    return result

def paired_comparisons(rows):
    keys=('source_room_id','model','abstain_allowed','phrasing','question_kind','temperature','repetition','target_id','start_agent')
    pairs=defaultdict(dict)
    for r in rows:
        if r.get('split')=='evaluation' and r.get('status')=='SUCCESS' and r.get('outcome')!='FORMAT_ERROR':pairs[tuple(r.get(k) for k in keys)][r['baseline']]=r
    out=[];groups=defaultdict(list)
    for key,pair in pairs.items():
        if set(pair)!={'B0','B1'}:continue
        meta=dict(zip(keys,key));a=pair['B0']['outcome'] in ('WRONG_PROVIDER','SILENT_VIOLATION');b=pair['B1']['outcome'] in ('WRONG_PROVIDER','SILENT_VIOLATION')
        groups[(meta['model'],meta['abstain_allowed'],meta['phrasing'],meta['question_kind'],meta['temperature'])].append((meta['source_room_id'],a,b))
    for key,pairs in sorted(groups.items(),key=lambda x:str(x[0])):
        byroom=defaultdict(list)
        for room,a,b in pairs:byroom[room].append(int(b)-int(a))
        values=np.array([sum(v)/len(v) for _,v in sorted(byroom.items())]);estimate=float(values.mean());ci=[None,None]
        if len(values)>1:ci=[float(x) for x in np.quantile(np.random.default_rng(SEED).choice(values,size=(10000,len(values)),replace=True).mean(axis=1),[.025,.975])]
        out.append(dict(zip(('model','abstain_allowed','phrasing','question_kind','temperature'),key))|{'paired_rooms':len(values),'paired_decisions':len(pairs),'B1_minus_B0_room_rate':estimate,'ci_low':ci[0],'ci_high':ci[1],'mcnemar_exact_room_p':exact_mcnemar(sum(not a and b for _,a,b in pairs),sum(a and not b for _,a,b in pairs)) if len(pairs)==len(byroom) else None})
    return out

def routing_coverage(rows):
    sources=sorted({r['source_room_id'] for r in rows if r.get('split')=='evaluation'})
    models=('gpt-4.1-mini-2025-04-14','gpt-4.1-2025-04-14');out=[]
    for source in sources:
        for model in models:
            group=[r for r in rows if r['source_room_id']==source and r.get('model')==model and r.get('question_kind')=='neutral' and r.get('repetition',0)==0]
            observed={(r.get('baseline'),r.get('abstain_allowed'),r.get('phrasing')) for r in group}
            valid={(r.get('baseline'),r.get('abstain_allowed'),r.get('phrasing')) for r in group if r.get('status')=='SUCCESS' and r.get('outcome')!='FORMAT_ERROR'}
            out.append({'source_room_id':source,'model':model,'expected_cells':12,'observed_cells':len(observed),'valid_scored_cells':len(valid),'missing_cells':12-len(observed),'complete_valid_block':len(valid)==12})
    return out

def summarize_stability(rows):
    groups=defaultdict(dict)
    keys=('source_room_id','model','baseline','abstain_allowed','phrasing','target_id','start_agent')
    for r in rows:
        if r.get('split')=='evaluation' and r.get('question_kind')=='neutral' and r.get('baseline') in ('B0','B1'):
            groups[tuple(r.get(k) for k in keys)][r.get('repetition',0)]=r
    out=[]
    for key,reps in sorted(groups.items(),key=lambda x:str(x[0])):
        if not any(k in reps for k in (1,2,3)):continue
        value=lambda r:json.dumps(r.get('parsed'),sort_keys=True) if r.get('status')=='SUCCESS' and r.get('outcome')!='FORMAT_ERROR' else None
        triple=[value(reps[x]) if x in reps else None for x in (0,1,2)]
        zero=value(reps[3]) if 3 in reps else None
        out.append(dict(zip(keys,key))|{'observed_repeat_rows':len(reps),'three_valid_main_temperature_calls':all(x is not None for x in triple),'all_three_agree':len(set(triple))==1 if all(x is not None for x in triple) else None,'temperature_zero_matches_initial':zero==triple[0] if zero is not None and triple[0] is not None else None})
    return out

def summarize_http(rows):
    groups=defaultdict(list)
    keys=('model','channel','proposal_mode','temperature','question_kind')
    for r in rows:groups[tuple(r.get(k) for k in keys)].append(r)
    out=[]
    for key,group in sorted(groups.items(),key=lambda x:str(x[0])):
        valid=[r for r in group if r.get('valid_real_generation')];rate=cluster_rate(valid,'proposal_present')
        lat=[r['http_latency_seconds'] for r in group if 'http_latency_seconds' in r]
        calls=[c for r in group for c in r.get('calls',[])];usage=[c.get('usage',{}) for c in calls]
        aborted=[r for r in group if r.get('response',{}).get('code')=='E_HANDOFF_PROPOSAL'];aborted_usage=[c.get('usage',{}) for r in aborted for c in r.get('calls',[])];aborted_latency=[r['http_latency_seconds'] for r in aborted if 'http_latency_seconds' in r]
        out.append(dict(zip(keys,key))|{**cost_summary(group),**cost_summary(aborted,'aborted_'),'aborted_input_tokens':sum(u.get('input_tokens',0) for u in aborted_usage),'aborted_output_tokens':sum(u.get('output_tokens',0) for u in aborted_usage),'aborted_http_latency_p50_seconds':float(np.quantile(aborted_latency,.5)) if aborted_latency else None,'observed_rows':len(group),'rooms':len({r['source_room_id'] for r in group}),'admitted_at_precall':sum(bool(r.get('admitted_at_precall')) for r in group),'completed_real_responses':sum(bool(r.get('real_generation_completed')) for r in group),'valid_real_generations':len(valid),'committed_real_generations':sum(bool(r.get('committed')) for r in valid),'committed_without_valid_generation':sum(bool(r.get('committed')) and not r.get('valid_real_generation') for r in group),'proposals':sum(bool(r.get('proposal_present')) for r in valid),'declared_proposals':sum(bool(r.get('proposal_declared_target')) for r in valid),'proposal_room_rate':rate['rate'],'proposal_ci_low':rate['lower'],'proposal_ci_high':rate['upper'],'proposal_aborts':sum(r.get('response',{}).get('code')=='E_HANDOFF_PROPOSAL' for r in group),'retry_after_abort':sum(r.get('retry_eligibility')=='IDENTICAL_REQUEST_AFTER_ABORT' for r in group),'repeated_proposal_after_abort':sum(bool(r.get('proposal_repeated_after_abort')) for r in group),'input_tokens':sum(u.get('input_tokens',0) for u in usage),'output_tokens':sum(u.get('output_tokens',0) for u in usage),'http_latency_p50_seconds':float(np.quantile(lat,.5)) if lat else None,'http_latency_p95_seconds':float(np.quantile(lat,.95)) if lat else None})
    return out

def corpus_strata(router,http,routing_dir,http_dir):
    """Join retained source provenance; scoring functions remain unchanged."""
    manifests=[]
    for directory in (routing_dir,http_dir):
        if directory and (Path(directory)/'corpus'/'manifest.json').exists():
            path=Path(directory)/'corpus'/'manifest.json';pin=hashlib.sha256(path.read_bytes()).hexdigest()
            if pin!=(path.with_suffix('.sha256')).read_text(encoding='utf-8-sig').strip():raise RuntimeError('Archived corpus manifest changed')
            manifests.append((pin,json.loads(path.read_text(encoding='utf-8-sig')),path.parent))
    if not manifests:return {'cohort_label':'No archived expanded-corpus provenance supplied','strata':[],'counts':[]}
    if len({x[0] for x in manifests})!=1:raise RuntimeError('Routing and HTTP analyses use different corpora')
    pin,manifest,directory=manifests[0]
    if not manifest.get('selection'):return {'cohort_label':manifest.get('cohort_label','Original corpus'),'strata':[],'counts':[]}
    selection=directory/'selection.json'
    if hashlib.sha256(selection.read_bytes()).hexdigest()!=manifest['selection']['sha256']:raise RuntimeError('Archived selection audit changed')
    audit=json.loads(selection.read_text(encoding='utf-8-sig'))
    selected={r['source_room_id']:r for r in audit['selected']}
    for row in router+http:
        if row['source_room_id']!='authored_example' and row['source_room_id'] not in selected:raise RuntimeError('Observed result uses a source outside the frozen selection')
    strata=[];counts=[]
    for family in ('original','extension_deterministic','extension_llm'):
        ids={sid for sid,r in selected.items() if r['source_stratum']==family}
        rr=[r for r in router if r['source_room_id'] in ids];hh=[r for r in http if r['source_room_id'] in ids]
        candidates=[r for r in audit['candidate_rows'] if r.get('source_stratum')==family]
        counts.append({'source_stratum':family,'registered_sources':len({r['source_room_id'] for r in candidates}),'pipeline_attempted_sources':len({r['source_room_id'] for r in candidates if r.get('source_valid') is True and r['terminal_status'] in ('completed','failed')}),'eligible_sources':len({r['source_room_id'] for r in candidates if r['eligible_native_success']}),'selected_sources':len(ids),'materialized_corpus_sources':sum(r['source_room_id'] in ids for r in manifest['rooms']),'selected_after_source_repair':sum(bool(selected[sid].get('source_authoring_repaired')) for sid in ids),'routing_observed_sources':len({r['source_room_id'] for r in rr if r.get('baseline') in ('B0','B1')}),'routing_valid_scored_sources':len({r['source_room_id'] for r in rr if r.get('baseline') in ('B0','B1') and r.get('status')=='SUCCESS' and r.get('outcome')!='FORMAT_ERROR'}),'http_observed_sources':len({r['source_room_id'] for r in hh}),'http_valid_generation_sources':len({r['source_room_id'] for r in hh if r.get('valid_real_generation')})})
        strata.append({'source_stratum':family,'interpretation':'Descriptive subset of an outcome-informed expanded exploratory corpus; identical frozen scoring.','routing':summarize_routing(rr),'http':summarize_http(hh),'paired_comparisons':paired_comparisons(rr),'coverage':routing_coverage(rr)})
    return {'cohort_label':audit['cohort_label'],'corpus_manifest_sha256':pin,'counts':counts,'strata':strata}


def table(path,rows,data_kind=None):
    if data_kind:rows=[{'data_kind':data_kind,**row} for row in rows] if rows else [{'data_kind':data_kind,'status':'NOT_RUN'}]
    path.parent.mkdir(parents=True,exist_ok=True)
    if not rows:path.write_text('status\nNOT_RUN\n',encoding='utf-8');return
    with path.open('w',newline='',encoding='utf-8') as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)

def tex(path,rows,columns,caption):
    labels={'model':'Model','baseline':'Router','abstain_allowed':'Abst.','phrasing':'Prompt','question_kind':'Question','rooms':'Rooms','attempts':'Rows','misroute_room_rate':'All-attempt deviation','misroute_valid_scored_room_rate':'Deviation','valid_scored_decisions':'Valid','unscored_failures':'Errors','channel':'Channel','proposal_mode':'Policy','temperature':'Temp.','valid_real_generations':'Valid','committed_real_generations':'Commit','proposals':'Proposals','proposal_aborts':'Aborts'}
    short=lambda x:str(x).replace('gpt-4.1-mini-2025-04-14','4.1 mini').replace('gpt-4.1-2025-04-14','4.1').replace('deterministic_native_guard','native')
    esc=lambda x:short(x).replace('_',r'\_').replace('%',r'\%').replace('&',r'\&')
    lines=[r'\begin{table*}',r'\centering',r'\scriptsize',r'\caption{'+caption+'}',r'\begin{tabular}{'+'l'*len(columns)+'}',r'\toprule',' & '.join(esc(labels.get(x,x)) for x in columns)+r' \\',r'\midrule']
    for r in rows:lines.append(' & '.join(esc('NA' if r.get(k) is None else round(r[k],4) if isinstance(r[k],float) else r[k]) for k in columns)+r' \\')
    lines += [r'\bottomrule',r'\end{tabular}',r'\end{table*}'];path.write_text('\n'.join(lines)+'\n',encoding='utf-8')

def figures(router,http,out,exploratory=False,engineering=False):
    import matplotlib;matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams.update({'font.size':7,'axes.titlesize':8,'axes.labelsize':7,'xtick.labelsize':7,'ytick.labelsize':7,'legend.fontsize':7,'pdf.fonttype':42,'svg.fonttype':'none','svg.hashsalt':'wp4-static-figures-v1'})
    out.mkdir(parents=True,exist_ok=True)
    for name,data,metric,title in (('F3_routing',router,'misroute_valid_scored_room_rate','Routing deviation: valid decisions'),('F3b_handoff_channel',http,'proposal_room_rate','Recorded handoff proposals')):
        # Every condition remains in the CSV; figure uses primary neutral comparisons.
        selected=[r for r in data if r.get('question_kind')=='neutral' and r.get('temperature')==.3 and (name!='F3_routing' or r.get('split')=='evaluation')]
        if not selected:continue
        for width,label in ((8.5,'single'),(17.5,'double')):
            fig,ax=plt.subplots(figsize=(width/2.54,max(4,len(selected)*.18)))
            labels=[]
            for r in selected:
                model='mini' if 'mini' in r['model'] else 'full'
                labels.append(f"{model} {r['baseline']} {'A' if r['abstain_allowed'] else 'F'} P{r['phrasing']} n={r['valid_scored_decisions']}/{r['attempts']}" if name=='F3_routing' else f"{model} {r['channel']} {r['proposal_mode']}")
            vals=[r.get(metric) if r.get(metric) is not None else np.nan for r in selected];ax.barh(range(len(vals)),vals,color='#285c75');
            for yi,r in enumerate(selected):
                if r.get(metric) is None:ax.text(.01,yi,'No valid responses',va='center',fontsize=7,color='#555555')
            ax.set_yticks(range(len(vals)),labels);ax.set_ylim(-.6,len(vals)-.4);ax.set_xlim(0,1);ax.set_xlabel('Mean within-room rate');ax.set_title(title+('\nEngineering fixture only' if engineering else ('\nExploratory expanded corpus' if exploratory else '')));ax.invert_yaxis();fig.tight_layout()
            from repro.normalize_figures import pdf_bytes,svg_bytes
            for fmt in ('svg','pdf'):
                target=out/(name+'_'+label+'.'+fmt)
                metadata={'Creator':'Reproducible WP4 analysis','CreationDate':None,'ModDate':None} if fmt=='pdf' else {'Creator':'Reproducible WP4 analysis','Date':None}
                fig.savefig(target,metadata=metadata)
                target.write_bytes(pdf_bytes(target.read_bytes()) if fmt=='pdf' else svg_bytes(target.read_bytes()))
            plt.close(fig)

def replay(*,routing=None,http=None,questions=None,corpus=None,gateway_log=None,output_root=ROOT,no_figures=False,engineering_fixture=False):
    output_root=Path(output_root)
    if engineering_fixture and output_root.resolve()==ROOT.resolve():raise RuntimeError('Engineering fixtures must use an isolated output root')
    router=read_rows(routing);http_rows=read_rows(http)
    manifest_path,manifest=load_manifest(corpus,routing,http,questions)
    contains_engineering=any(r.get('data_kind')==ENGINEERING for r in router+http_rows) or (manifest or {}).get('data_kind')==ENGINEERING
    if contains_engineering and not engineering_fixture:raise RuntimeError('Synthetic engineering data require the explicit engineering flag and isolated outputs')
    accounting=attach_gateway_costs(router,http_rows,gateway_log)
    rs=summarize_routing(router);hs=summarize_http(http_rows);pairs=paired_comparisons(router);stability=summarize_stability(router)
    den=denominators(router,http_rows,manifest);coverage=den['coverage']
    primary=summarize_routing([{**r,'fault_class':'all'} for r in router if r.get('split')=='evaluation' and r.get('question_kind')=='neutral' and r.get('repetition',0)==0])
    cohort=corpus_strata(router,http_rows,routing,http)
    question_report=question_summary(questions,manifest)
    def label(path):
        if path is None:return None
        path=Path(path)
        try:return path.resolve().relative_to(ROOT.resolve()).as_posix()
        except ValueError:return path.name
    out=output_root/'results/processed';out.mkdir(parents=True,exist_ok=True)
    summary={'data_kind':ENGINEERING if engineering_fixture else 'RETAINED_WP4_OUTCOMES','raw_routing':label(routing),'raw_http':label(http),'raw_questions':label(questions),'corpus_manifest_sha256':hashlib.sha256(manifest_path.read_bytes()).hexdigest() if manifest_path else None,
             'seed':SEED,'bootstrap_resamples':10000,'routing_rows':len(router),'routing_evaluation_rooms':len({r['source_room_id'] for r in router if r.get('split')=='evaluation' and r.get('baseline') in ('B0','B1') and scored(r)}),
             'routing_complete_valid_rooms_by_model':{m:sum(x['model']==m and x['valid_primary_routing_cells']==12 for x in coverage) for m in sorted({x['model'] for x in coverage})},
             'http_valid_generations_by_model':{m:sum(r.get('model')==m and bool(r.get('valid_real_generation')) for r in http_rows) for m in sorted({x['model'] for x in coverage}|{r['model'] for r in http_rows})},
             'routing':rs,'routing_primary':primary,'http':hs,'paired_comparisons':pairs,'stability':stability,'coverage':coverage,
             'denominators':den,'questions':question_report,'gateway_accounting':accounting,'corpus_provenance':cohort,
             'limitations':['Misroute means deviation from the declared model, not from visitor intent.','Question objects and probes are nested within source rooms.','Identical input retries are distinct model calls, not independent rooms.','Lexical monitors are exploratory and have no independent semantic judges in this runner.','No Unity or deployment evidence.']}
    if cohort['strata']:summary['limitations'].append(cohort['cohort_label'])
    if engineering_fixture:summary['limitations'].insert(0,'All values are fabricated engineering fixture inputs. They validate report arithmetic and rendering and estimate nothing about an LLM.')
    emit_table=lambda path,rows:table(path,rows,data_kind=summary['data_kind'])
    emit_table(out/'wp4_source_strata.csv',cohort['counts']);emit_table(out/'wp4_question_outcomes.csv',[{k:v for k,v in question_report.items() if k not in ('files_sha256','interpretation','statuses')}]);emit_table(out/'wp4_gateway_accounting.csv',accounting['experiments'])
    (out/'wp4_summary.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    tables=output_root/'paper_inputs/tables';emit_table(tables/'T2_routing_baselines.csv',rs);emit_table(tables/'T5_guarded_llm_turns.csv',hs);emit_table(out/'wp4_paired_comparisons.csv',pairs);emit_table(out/'wp4_stability.csv',stability);emit_table(out/'wp4_coverage.csv',coverage)
    prefix='ENGINEERING FIXTURE ONLY. ' if engineering_fixture else ('Expanded exploratory corpus. ' if cohort['strata'] else '')
    tex(tables/'T2_routing_baselines.tex',primary,('model','baseline','abstain_allowed','phrasing','question_kind','rooms','attempts','misroute_valid_scored_room_rate','valid_scored_decisions','unscored_failures'),prefix+'Routing deviation from the declared model. All-attempt, valid-scored and missing-cell denominators remain separate in CSV/JSON.')
    tex(tables/'T5_guarded_llm_turns.tex',hs,('model','channel','proposal_mode','temperature','question_kind','rooms','valid_real_generations','committed_real_generations','proposals','proposal_aborts'),prefix+'HTTP outcomes. Attempted requests, admitted calls, valid generations and commits are distinct. Forced JSON fallback is experimental.')
    title='# ENGINEERING FIXTURE: WP4 report validation' if engineering_fixture else '# WP4 retained model outcomes'
    lines=[title,'',prefix+cohort['cohort_label'],'',f"Recorded router rows: {len(router)}. Valid-scored evaluation source rooms: {summary['routing_evaluation_rooms']}. Recorded HTTP rows: {len(http_rows)}.",'','Expected primary/core coverage comes from the frozen corpus, including rooms with no result rows. Missing cells remain missing and never become successful observations. Conditional valid-scored rates and all-observed-row deviation rates have distinct denominators.','',f"HTTP chat attempts: {den['http_chat_requests_attempted']}; admitted at pre-call: {den['http_admitted_at_precall']}; completed model responses: {den['http_completed_real_responses']}; valid generations: {den['http_valid_real_generations']}; committed valid generations: {den['http_committed_real_generations']}. Commit without a valid model generation: {den['http_committed_without_valid_generation']}.",'',f"Question objects: expected {question_report['expected_object_rows']}, observed {question_report['observed_object_rows']}, missing {question_report['missing_object_rows']}, valid pairs {question_report['valid_question_pairs']}, error outcomes {question_report['error_object_rows']}.",'','Accounted costs come from the retained sanitized log; unmatched started attempts retain their reservation. Missing log coverage is unknown, not zero cost. The backend can commit an offline fallback after an API error; such commits are excluded from valid model generations.','',*['- '+x for x in summary['limitations']]]
    (output_root/'docs').mkdir(parents=True,exist_ok=True);(output_root/'docs/WP4_RESULTS.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    if not no_figures:figures(primary,hs,output_root/'paper_inputs/figures',exploratory=bool(cohort['strata']),engineering=engineering_fixture)
    return summary


def main():
    p=argparse.ArgumentParser();p.add_argument('--routing');p.add_argument('--http');p.add_argument('--questions');p.add_argument('--corpus');p.add_argument('--gateway-log',default=str(ROOT/'logs/llm_calls.jsonl'));p.add_argument('--output-root',default=str(ROOT));p.add_argument('--no-figures',action='store_true');p.add_argument('--engineering-fixture',action='store_true')
    summary=replay(**vars(p.parse_args()))
    print(json.dumps({k:summary[k] for k in ('data_kind','routing_rows','routing_evaluation_rooms','http_valid_generations_by_model')}))
if __name__=='__main__':main()

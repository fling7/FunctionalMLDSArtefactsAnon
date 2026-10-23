"""Rebuild WP7 tables, figures and claim-sized counts from retained raw runs.

Selects the newest COMPLETE run per experiment; interrupted runs remain listed.
Requires reportlab only for the vector figures; --no-figures is stdlib-only.
"""
from __future__ import annotations
import argparse
import csv
import json
from pathlib import Path
from xml.sax.saxutils import escape
ROOT=Path(__file__).resolve().parents[1]


def load(path):return json.loads(path.read_text(encoding='utf-8-sig'))
def jsonl(path):return [json.loads(line) for line in path.read_text(encoding='utf-8-sig').splitlines() if line.strip()]
def write_json(path,value):path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value,indent=2,sort_keys=True)+'\n',encoding='utf-8')
def tex(value):return str(value).replace('_',r'\_').replace('%',r'\%').replace('&',r'\&')


def latest(kind):
    directory=ROOT/'results/raw'/('wp7_'+kind)
    runs=sorted(directory.glob('*')) if directory.exists() else []
    complete=[run for run in runs if (run/'summary.json').exists()]
    return complete[-1] if complete else None,[r.relative_to(ROOT).as_posix() for r in runs if not (r/'summary.json').exists()]


def csv_write(path,rows):
    keys=list(dict.fromkeys(k for r in rows for k in r))
    with path.open('w',newline='',encoding='utf-8') as out:
        writer=csv.DictWriter(out,keys);writer.writeheader();writer.writerows(rows)


def figures(out,scopes,explorer):
    from reportlab import rl_config
    rl_config.invariant=True
    from reportlab.graphics.shapes import Drawing,Rect,String,Line,Polygon
    from reportlab.graphics import renderPDF,renderSVG
    from reportlab.lib.colors import HexColor
    blue=HexColor('#0072B2');orange=HexColor('#D55E00');grey=HexColor('#333333');light=HexColor('#EAF3F8')
    def text(d,x,y,value,size=7,color=grey):d.add(String(x,y,value,fontName='Helvetica',fontSize=size,fillColor=color))
    def box(d,x,y,w,h,label,color=light):
        d.add(Rect(x,y,w,h,fillColor=color,strokeColor=grey,strokeWidth=.5));text(d,x+5,y+h/2-2.5,label)
    def arrow(d,x,y1,y2,color=grey):
        d.add(Line(x,y1,x,y2,strokeColor=color,strokeWidth=.7));d.add(Polygon([x,y2,x-2,y2+4,x+2,y2+4],fillColor=color,strokeColor=color))
    def save(d,name):renderPDF.drawToFile(d,str(out/(name+'.pdf')));renderSVG.drawToFile(d,str(out/(name+'.svg')))
    for tag,width in [('single',85/25.4*72),('double',175/25.4*72)]:
        height=360 if tag=='single' else 245;d=Drawing(width,height)
        text(d,10,height-16,'F6  Commit / publication order',9)
        if tag=='single':positions=[(10,195,width-20),(10,48,width-20)]
        else:positions=[(10,80,(width-30)/2),(20+(width-30)/2,80,(width-30)/2)]
        for i,(x,y,w) in enumerate(positions):
            text(d,x,y+126,'Packet: check before lock' if i==0 else 'Cooperative: shared project lock',8,color=orange if i==0 else blue)
            labels=['Read and validate pin g','Publisher flips to g+1','Lock and append old evidence'] if i==0 else ['Lock; reload and compare g','Append pair; remove undo intent','Unlock; publisher may flip']
            for j,label in enumerate(labels):
                by=y+88-j*35;box(d,x,by,w,25,label)
                if j<2:arrow(d,x+w/2,by,by-10)
            text(d,x,y+3,'Race: checked g != append generation' if i==0 else 'Commit: undo-intent removal under lock',7,color=orange if i==0 else blue)
        if tag=='single':
            text(d,10,28,'Direct edits bypassing the lock retain a race.',7)
            text(d,10,16,'Evidence visibility requires the cooperating reader.',7)
        else:
            text(d,10,45,'Direct edits can change a projection without advancing the generation; the next consistent load refuses it.',7)
            text(d,10,30,'Pair visibility is defined by the shared-lock reader. Raw unlocked JSONL reads can see intermediate bytes.',7)
            text(d,10,15,'Timeline explains the protocol. Exhaustive finite-state schedules are an abstraction, not a Python/OS proof.',7)
        save(d,'F6_commit_timeline_'+tag)
        height=235 if tag=='single' else 215;d=Drawing(width,height)
        text(d,10,height-16,'F7  Commit fingerprint scope (synthetic)',9)
        text(d,10,height-31,'Aborts on routing-equivalent edits',7)
        left=32;right=width-16;bottom=70;top=height-45;plotheight=top-bottom
        denominator=max([v['nonrouting_edit_denominator'] for v in scopes.values()]+[1])
        d.add(Line(left,bottom,left,top,strokeColor=grey,strokeWidth=.6));d.add(Line(left,bottom,right,bottom,strokeColor=grey,strokeWidth=.6))
        for value in range(denominator+1):
            y=bottom+plotheight*value/denominator;text(d,14,y-2,str(value),7)
            d.add(Line(left,y,right,y,strokeColor=HexColor('#DDDDDD'),strokeWidth=.3))
        labels=[('F0','digest_only'),('F1','full'),('F2','slice'),('F3','slice_prompt')]
        step=(right-left)/len(labels)
        for i,(label,key) in enumerate(labels):
            count=scopes[key]['false_aborts'];x=left+i*step+step*.22;w=step*.55;h=plotheight*count/denominator
            d.add(Rect(x,bottom,w,max(.6,h),fillColor=blue if key!='slice_prompt' else orange,strokeColor=grey,strokeWidth=.5))
            text(d,x+w/2-2,bottom+h+5,str(count),7)
            text(d,x+w/2-5,bottom-13,label,8)
        text(d,10,43,'F0 digest; F1 full; F2 route; F3 route + prompt',7)
        route_den=scopes['slice']['routing_edit_denominator'];miss=scopes['slice']['misses']
        text(d,10,30,f'F2 misses: {miss}/{route_den} routing-changing synthetic edit(s).',7)
        text(d,10,17,'Same-author labels; no natural pairs or rate inference.',7)
        save(d,'F7_scope_tradeoff_'+tag)


def main(explicit_inputs=None):
    parser=argparse.ArgumentParser();parser.add_argument('--no-figures',action='store_true');args=parser.parse_args() if explicit_inputs is None else argparse.Namespace(no_figures=False)
    selected={};interrupted=[]
    if explicit_inputs is None:
        for kind in ('interleavings','faults','restore_atomic','scopes','effects','stress'):
            run,pending=latest(kind);interrupted+=pending
            if run:selected[kind]=run
    else:
        selected={kind:ROOT/path for kind,path in explicit_inputs['selected'].items()}
        interrupted=list(explicit_inputs['interrupted'])
    # Recompute from per-cell/row evidence, never trust a hand-maintained total.
    summaries={}
    for kind,run in selected.items():
        if kind=='interleavings':
            rows=jsonl(run/'rows.jsonl')
            summaries[kind]={'rows':rows,'cells':len(rows),'states':sum(r['reachable_states'] for r in rows),'cooperative_violating_schedules':sum(r['violating_schedules'] for r in rows if r['mode']=='cooperative'),'packet_counterexample_cells':sum(bool(r['first_counterexample']) for r in rows if r['mode']=='packet'),'uncooperative_counterexample_cells':sum(bool(r['first_counterexample']) for r in rows if r['mode']=='uncooperative')}
        elif kind=='faults':
            rows=jsonl(run/'rows.jsonl')
            summaries[kind]={'results':rows,'append_fault_cells':sum(r['experiment']=='append_fault' for r in rows),'unpaired_cells':sum(r.get('paired') is False for r in rows),'session_rollback_failures':sum(r['experiment']=='session_append_fault' and not r['snapshot_restored'] for r in rows),'restore_partial_after_fault':sum(r['experiment']=='restore_fault' and not r['complete_after_fault'] for r in rows)}
        elif kind=='restore_atomic':
            rows=jsonl(run/'rows.jsonl');summaries[kind]={'rows':rows,'cells':len(rows),'atomic_cells':sum(r['atomic_before_or_restored'] for r in rows)}
        elif kind=='scopes':
            rows=jsonl(run/'scope_rows.jsonl')
            summaries[kind]={'scope_rows':len(rows),'natural_pairs':0,'by_scope':{key:{'false_aborts':sum(r['scope']==key and r['false_abort'] for r in rows),'misses':sum(r['scope']==key and r['miss'] for r in rows),'nonrouting_edit_denominator':sum(r['scope']==key and r['routing_changed'] is False for r in rows),'routing_edit_denominator':sum(r['scope']==key and r['routing_changed'] is True for r in rows)} for key in sorted({r['scope'] for r in rows})}}
        elif kind=='effects':
            rows=jsonl(run/'rows.jsonl');summaries[kind]={'rows':rows,'cells':len(rows)}
        else:
            cells=[load(p) for p in (sorted(run.glob('*.json')) if explicit_inputs is None else [ROOT/path for path in explicit_inputs['stress_cells']]) if p.name.startswith(('threads_','processes_'))]
            rebuilt=[]
            for cell in cells:
                rows=cell['rows'];row={k:v for k,v in cell.items() if k not in ('rows','publications')}
                row.update(sessions=len(rows),committed=sum(r['outcome']=='committed' for r in rows),aborted=sum(r['outcome']=='aborted' for r in rows),generation_check_append_mismatches=sum(r['outcome']=='committed' and r.get('check_generation') is not None and r.get('append_generation') is not None and r['check_generation']!=r['append_generation'] for r in rows))
                row['torn_reads_accepted']=sum(r['outcome']=='committed' and r.get('append_manifest_consistent') is False for r in rows) if any('append_manifest_consistent' in r for r in rows) else cell.get('torn_reads_accepted')
                row['manifest_monitored_commits']=sum(r['outcome']=='committed' and r.get('append_manifest_consistent') is not None and not r.get('append_monitor_error') for r in rows)
                row['manifest_monitor_errors']=sum(r['outcome']=='committed' and bool(r.get('append_monitor_error')) for r in rows)
                rebuilt.append(row)
            summaries[kind]={'sessions':sum(c['sessions'] for c in rebuilt),'committed':sum(c['committed'] for c in rebuilt),'aborted':sum(c['aborted'] for c in rebuilt),'cooperative_generation_mismatches':sum(c['generation_check_append_mismatches'] for c in rebuilt if c['protocol']=='cooperative'),'cooperative_torn_reads_accepted':sum(c['torn_reads_accepted'] or 0 for c in rebuilt if c['protocol']=='cooperative'),'cooperative_torn_reads_measured':all(c['manifest_monitored_commits']==c['committed'] for c in rebuilt if c['protocol']=='cooperative'),'cooperative_monitored_commits':sum(c['manifest_monitored_commits'] for c in rebuilt if c['protocol']=='cooperative'),'cooperative_monitor_errors':sum(c['manifest_monitor_errors'] for c in rebuilt if c['protocol']=='cooperative'),'cell_summaries':rebuilt}
    numbers={}
    exp=summaries.get('interleavings',{});faults=summaries.get('faults',{});restore=summaries.get('restore_atomic',{});scope=summaries.get('scopes',{});stress=summaries.get('stress',{})
    numbers.update({'wp7_interleaving_cells':exp.get('cells',0),'wp7_reachable_states':exp.get('states',0),'wp7_cooperative_violating_schedules':exp.get('cooperative_violating_schedules',0),'wp7_packet_counterexample_cells':exp.get('packet_counterexample_cells',0),'wp7_direct_edit_counterexample_cells':exp.get('uncooperative_counterexample_cells',0),'wp7_append_fault_cells':faults.get('append_fault_cells',0),'wp7_unpaired_fault_cells':faults.get('unpaired_cells',0),'wp7_pre_fix_partial_restore_cells':faults.get('restore_partial_after_fault',0),'wp7_post_fix_atomic_restore_cells':restore.get('atomic_cells',0),'wp7_post_fix_restore_cells':restore.get('cells',0),'wp7_synthetic_scope_rows':scope.get('scope_rows',0),'wp7_natural_pairs':scope.get('natural_pairs',0),'wp7_stress_sessions':stress.get('sessions',0),'wp7_stress_committed':stress.get('committed',0),'wp7_stress_aborted':stress.get('aborted',0),'wp7_stress_cooperative_generation_mismatches':stress.get('cooperative_generation_mismatches',0),'wp7_stress_cooperative_manifest_mismatches':stress.get('cooperative_torn_reads_accepted') if stress.get('cooperative_torn_reads_measured') else None,'wp7_stress_cooperative_monitored_commits':stress.get('cooperative_monitored_commits'),'wp7_stress_cooperative_monitor_errors':stress.get('cooperative_monitor_errors')})
    tabledir=ROOT/'paper_inputs/tables';figdir=ROOT/'paper_inputs/figures';tabledir.mkdir(parents=True,exist_ok=True);figdir.mkdir(parents=True,exist_ok=True)
    t6=[]
    for row in exp.get('rows',[]):
        t6.append({'panel':'finite_state_abstraction','condition':row['mode'],'publishers':row['publishers'],'sessions':row['sessions'],'states':row['reachable_states'],'schedules':row['complete_schedules'],'violating_schedules':row['violating_schedules'],'limits':row['claim_scope']})
    for row in stress.get('cell_summaries',[]):
        t6.append({'panel':'scripted_production_stress','condition':row['execution']+'_'+row['protocol']+'_'+row['scope'],'sessions':row['sessions'],'committed':row['committed'],'aborted':row['aborted'],'generation_mismatches':row['generation_check_append_mismatches'],'manifest_mismatches':row.get('torn_reads_accepted'),'manifest_monitored_commits':row.get('manifest_monitored_commits'),'manifest_monitor_errors':row.get('manifest_monitor_errors'),'paired_ids':row['paired_ids'],'wasted_generation_ms':row['wasted_generation_ms'],'limits':'50 in-flight scripted model calls; no real model; marker equality strict in cooperative mode; independent byte-hash monitor under shared lock only in cooperative cells'})
    for name in ('append_fault_cells','unpaired_cells','session_rollback_failures','restore_partial_after_fault'):
        t6.append({'panel':'fault_injection','condition':name,'count':faults.get(name),'limits':'before atomic restore fix; external process kill, not power loss'})
    csv_write(tabledir/'T6_commit_protocol.csv',t6)
    lines=['% Generated from WP7 raw complete runs; finite-state abstraction is not implementation proof.',r'\begin{tabular}{llrrrr}',r'\toprule',r'Mode & Execution & Sessions & Commit & Abort & Mismatch \\',r'\midrule']
    for row in stress.get('cell_summaries',[]):lines.append(' & '.join(tex(x) for x in (row['protocol']+'/'+row['scope'],row['execution'],row['sessions'],row['committed'],row['aborted'],row['generation_check_append_mismatches']))+r' \\')
    lines += [r'\bottomrule',r'\end{tabular}','% Scripted concurrency; strict generation pins invalidate equivalent republications.','% Direct-edit and packet counterexamples are in the retained traces.']
    (tabledir/'T6_commit_protocol.tex').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    t7=jsonl(selected['scopes']/'scope_rows.jsonl') if 'scopes' in selected else []
    csv_write(tabledir/'T7_fingerprint_scopes.csv',t7)
    lines=['% Synthetic edits only; same-author labels. Natural pairs unavailable.',r'\begin{tabular}{lrrr}',r'\toprule',r'Scope & Equivalent aborts & Routing misses & Prompt edits caught \\',r'\midrule']
    for key,row in scope.get('by_scope',{}).items():
        caught=sum(r['scope']==key and r['edit'] in ('persona','knowledge_base','persona_redirection') and r['aborted'] for r in t7)
        lines.append(' & '.join([tex(key),str(row['false_aborts'])+'/'+str(row['nonrouting_edit_denominator']),str(row['misses'])+'/'+str(row['routing_edit_denominator']),str(caught)+'/'+str(sum(r['scope']==key and r['edit'] in ('persona','knowledge_base','persona_redirection') for r in t7))])+r' \\')
    lines += [r'\bottomrule',r'\end{tabular}','% Prompt protection intentionally aborts some routing-equivalent edits.']
    (tabledir/'T7_fingerprint_scopes.tex').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    index={'selected_raw_runs':{k:v.relative_to(ROOT).as_posix() for k,v in selected.items()},'interrupted_raw_runs':interrupted,'numbers':numbers,'status':'PARTIAL: natural pairs, independent labels and real-model stress unavailable','limits':['Finite-state schedules are not empirical sample sizes.','Synthetic scope labels are same-author Gate-0 comparisons.','Strict cooperative generation equality aborts on routing-equivalent republication.','Append-time manifest consistency was independently monitored under the project lock; this is not a universal absence-of-torn-reads proof.','Raw unlocked evidence-file readers have no paired visibility guarantee.','Process death does not preserve in-memory sessions.']}
    write_json(ROOT/'results/processed/wp7_index.json',index)
    text=['# WP7 generated result index','','Generated by `python experiments/analyze_wp7.py`. Selected raw runs are complete; interrupted runs remain retained.','','WP7 remains partial: no natural evolution pairs, independent scope labels, or real-model stress run.','','| Metric | Value |','|---|---:|']+[f'| {key} | {value} |' for key,value in numbers.items()]
    text += ['','The state-explorer counts are exhaustive abstract schedules, not independent samples. The script does not compute confidence intervals for them. Synthetic scope labels use the same-author Gate-0 verifier. The strict cooperative generation rule invalidates old pins even when F2 is unchanged.','','## Selected raw runs']+[f'- {k}: `{v}`' for k,v in index['selected_raw_runs'].items()]
    (ROOT/'docs/WP7_RESULTS.md').write_text('\n'.join(text)+'\n',encoding='utf-8')
    if not args.no_figures:figures(figdir,scope.get('by_scope',{}),exp)
    print(json.dumps({'numbers':numbers,'selected':index['selected_raw_runs'],'figures':not args.no_figures}))

if __name__=='__main__':main()

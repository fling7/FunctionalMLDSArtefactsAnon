"""Small synthetic ENGINEERING fixtures for offline WP4 report QA, never LLM evidence."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from experiments.analyze_wp4 import replay
from experiments.lib.wp4_reporting import ENGINEERING,MODELS
from repro.normalize_figures import normalize


def put(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,indent=2,sort_keys=True)+'\n',encoding='utf-8')
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_fixture(out):
    out=Path(out);out.mkdir(parents=True,exist_ok=False)
    (out/'ENGINEERING_ONLY.txt').write_text('Fabricated report-validation inputs. No API calls, actual model answers, or scientific observations. Never merge these values into study results.\n',encoding='utf-8')
    manifest={'data_kind':ENGINEERING,'cohort_label':'ENGINEERING fixture, not model evidence','rooms':[{'source_room_id':'engineering_room_1','split':'evaluation'},{'source_room_id':'engineering_room_2','split':'evaluation'}],
              'question_objects':[{'source_room_id':s,'target_id':t} for s,t in [('engineering_room_1','target_1'),('engineering_room_1','target_2'),('engineering_room_2','target_1')]]}
    pin=put(out/'corpus/manifest.json',manifest);(out/'corpus/manifest.sha256').write_text(pin+'\n',encoding='utf-8')
    events=[]
    def event(experiment,item,status,cost,*,attempt=True,pending=False):
        base={'data_kind':ENGINEERING,'experiment_id':experiment,'item_id':item,'repetition_id':'0','endpoint':'/responses'}
        if attempt:events.append({**base,'status':'ATTEMPT_STARTED','attempt':1,'reservation_id':'engineering-'+item,'reserved_usd':cost})
        if not pending:events.append({**base,'status':status,'cost_usd':cost,**({'attempt':1} if attempt else {})})
    router_specs=[(MODELS[0],'B0',1,True,'SUCCESS','CORRECT','0.01'),(MODELS[0],'B1',1,True,'SUCCESS','WRONG_PROVIDER','0.02'),
                  (MODELS[1],'B0',1,True,'SUCCESS','FORMAT_ERROR','0.03'),(MODELS[1],'B1',1,True,'INPUT_TOKEN_LIMIT','INPUT_TOKEN_LIMIT','0'),
                  (MODELS[0],'B0',2,False,'NETWORK_ERROR','NETWORK_ERROR','0.04')]
    for i,(model,baseline,phrasing,abstain,status,outcome,cost) in enumerate(router_specs):
        item='engineering.router.'+str(i)
        row={'data_kind':ENGINEERING,'source_room_id':'engineering_room_1','split':'evaluation','model':model,'baseline':baseline,'phrasing':phrasing,'abstain_allowed':abstain,'question_kind':'neutral','temperature':.3,'fault_class':'local','repetition':0,
             'status':status,'outcome':outcome,'experiment_id':'WP4.routing','item_id':item,'repetition_id':'0','latency_seconds':.25,'target_id':'target_1','start_agent':'agent_1'}
        if status=='SUCCESS':row.update(response={'status':'completed'},usage={'input_tokens':100,'output_tokens':10})
        put(out/'routing/rows'/('row_'+str(i)+'.json'),row)
        event('WP4.routing',item,'INPUT_LIMIT' if status=='INPUT_TOKEN_LIMIT' else ('SUCCESS' if status=='SUCCESS' else 'API_ERROR'),cost,attempt=status!='INPUT_TOKEN_LIMIT')
    event('WP4.routing','engineering.orphan','ATTEMPT_STARTED','0.05',pending=True)
    http_specs=[(MODELS[0],0,'SUCCESS',True,True,True,True,False,'0.01'),(MODELS[0],1,'NETWORK_ERROR',True,False,False,True,False,'0.02'),
                (MODELS[0],2,'E_ROUTE',False,False,False,False,False,None),(MODELS[0],3,'QUESTION_UNAVAILABLE',False,False,False,False,False,None),
                (MODELS[1],0,'E_HANDOFF_PROPOSAL',True,True,True,False,True,'0.03')]
    for i,(model,slot,status,admitted,completed,valid,committed,proposal,cost) in enumerate(http_specs):
        item='engineering.http.'+str(i)
        row={'data_kind':ENGINEERING,'source_room_id':'engineering_room_1','model':model,'slot':slot,'channel':'fallback' if proposal else 'constrained','proposal_mode':'abort','temperature':.3,'question_kind':'neutral',
             'status':status,'admitted_at_precall':admitted,'real_generation_completed':completed,'valid_real_generation':valid,'committed':committed,'proposal_present':proposal,'proposal_declared_target':False,'calls':[],
             'response':{'code':status} if status!='SUCCESS' else {}}
        if status!='QUESTION_UNAVAILABLE':row['http_latency_seconds']=.5
        if cost is not None:
            row['calls']=[{'item_id':item,'repetition_id':'0','status':'SUCCESS' if completed else status,'usage':{'input_tokens':100,'output_tokens':10} if completed else {}}]
            event('WP4.http',item,'SUCCESS' if completed else 'API_ERROR',cost)
        put(out/'http/rows'/('row_'+str(i)+'.json'),row)
    questions={}
    for i,(key,status) in enumerate([('engineering_room_1.target_1','SUCCESS'),('engineering_room_1.target_2','FORMAT_ERROR')]):
        item='engineering.question.'+str(i)
        row={'data_kind':ENGINEERING,'key':key,'status':status,'item_id':item,'repetition_id':'0'}
        if status=='SUCCESS':row['parsed']={'question_1':'Fabricated engineering question one?','question_2':'Fabricated engineering question two?'}
        questions[key]=row;event('WP4.questions',item,'SUCCESS','0.001' if i==0 else '0.002')
    pin=put(out/'questions/questions.json',questions);(out/'questions/questions.sha256').write_text(pin+'\n',encoding='utf-8')
    (out/'gateway.jsonl').write_text('\n'.join(json.dumps(r,sort_keys=True) for r in events)+'\n',encoding='utf-8')
    return out


def validate_figures(folder):
    from pypdf import PdfReader
    checks=[]
    for path in sorted(Path(folder).glob('*')):
        if path.suffix not in ('.svg','.pdf'):continue
        expected=8.5 if '_single.' in path.name else 17.5
        if path.suffix=='.svg':
            data=path.read_text(encoding='utf-8');root=ET.fromstring(data)
            width=float(root.attrib['width'].removesuffix('pt'))/72*2.54
            fonts=[float(v) for v in re.findall(r'(?:font-size:|font:)\s*([\d.]+)(?:px|pt)',data)]
            assert '<metadata' not in data and 'dc:date' not in data
        else:
            pdf=PdfReader(path);width=float(pdf.pages[0].mediabox.width)/72*2.54;fonts=[]
            pdf.pages[0].extract_text(visitor_text=lambda text,cm,tm,font,size:fonts.append(float(size)) if text.strip() else None)
            assert pdf.metadata is None and '/Metadata' not in pdf.trailer['/Root']
        assert abs(width-expected)<1e-6,(path.name,width,expected)
        assert fonts and min(fonts)>=7,(path.name,fonts)
        checks.append({'file':path.name,'width_cm':width,'expected_width_cm':expected,'minimum_font_points':min(fonts),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
    assert len(checks)==8
    return checks


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--out',required=True);args=parser.parse_args()
    out=make_fixture(args.out)
    kwargs={'routing':out/'routing','http':out/'http','questions':out/'questions','corpus':out/'corpus','gateway_log':out/'gateway.jsonl','engineering_fixture':True}
    runs=[]
    for label in ('replay_a','replay_b'):
        target=out/label;summary=replay(**kwargs,output_root=target)
        normalize(target)
        checks=validate_figures(target/'paper_inputs/figures')
        assert summary['denominators']['http_chat_requests_attempted']==4
        assert summary['denominators']['http_admitted_at_precall']==3
        assert summary['denominators']['http_valid_real_generations']==2
        assert summary['denominators']['http_committed_real_generations']==1
        assert summary['denominators']['http_committed_without_valid_generation']==1
        assert summary['questions']['missing_object_rows']==1 and summary['questions']['error_object_rows']==1
        runs.append({'root':label,'figures':checks})
    first={r['file']:r['sha256'] for r in runs[0]['figures']};second={r['file']:r['sha256'] for r in runs[1]['figures']}
    assert first==second,'Normalized figure bytes differ across identical-input replays'
    report_files=('results/processed/wp4_summary.json','results/processed/wp4_coverage.csv','results/processed/wp4_question_outcomes.csv','paper_inputs/tables/T2_routing_baselines.csv','paper_inputs/tables/T5_guarded_llm_turns.csv','docs/WP4_RESULTS.md')
    assert all((out/'replay_a'/p).read_bytes()==(out/'replay_b'/p).read_bytes() for p in report_files)
    report={'data_kind':ENGINEERING,'real_model_calls':0,'normalized_figures_deterministic':True,'report_files_deterministic':True,'runs':runs,
            'source_sha256':{p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in ('experiments/analyze_wp4.py','experiments/lib/wp4_reporting.py','experiments/wp4_report_engineering.py','repro/normalize_figures.py')}}
    put(out/'validation.json',report)
    print(json.dumps({'data_kind':ENGINEERING,'figures_per_run':len(first),'two_run_byte_equality':True,'report':str(out/'validation.json')}))

if __name__=='__main__':main()

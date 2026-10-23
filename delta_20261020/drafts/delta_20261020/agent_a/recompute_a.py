"""Offline retained-data delta items 1, 6, 8. Never modifies retained inputs."""
import json,csv,hashlib,re,sys,collections
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT))
from tools.case_study_pipeline.roomcontract_v2_assembler import validate_roomcontract_v2_instance
OUT=ROOT/'deliverables/delta_20261020'
SCRIPT='drafts/delta_20261020/agent_a/recompute_a.py'
def read(p): return json.loads(p.read_text(encoding='utf-8-sig'))
def save(rel,obj):
 p=OUT/rel;p.parent.mkdir(parents=True,exist_ok=True);assert not p.exists(),str(p);p.write_text(json.dumps(obj,indent=2,sort_keys=True)+'\n',encoding='utf-8')
def table(rel,rows):
 p=OUT/rel;p.parent.mkdir(parents=True,exist_ok=True);assert not p.exists()
 with p.open('w',newline='',encoding='utf-8') as f:w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
old=read(ROOT/'numbers.json');nums={};log=[]
def number(k,v):
 nums[k]=v;line={'key':k,'old':old.get(k,'NOT_REPORTED'),'new':v,'changed':old.get(k)!=v,'script':SCRIPT};log.append(line);print(json.dumps(line),flush=True)
A=[read(p) for p in sorted((ROOT/'data/go_sprint/sprint/w4/models').glob('*.json'))]
good=[r for r in A if 'model'in r and r.get('authoring')is not None and 'gate0_ok'in r and r.get('probes') and all(all(k in p for k in('I1','I2','Gate0'))and p['I1']==p['I2']==p['Gate0']for p in r['probes'])and not r.get('disagreements')]
native=[r for r in good if r['model']['cohort']not in('classroom','evaluation_routing')]
def base(s):return re.sub(r'_edit_(add|move|remove)$','',s)
lineage=[]
for r in native:
 m=r['model'];mid=m['model_id'];sid=m['source_id'];lineage.append({'model_id':mid,'cohort':m['cohort'],'base_source':base(sid),'edit_definition':sid,'rename_definition':sid+'::zone_rename' if m['cohort']=='zone_rename' else sid,'regeneration_definition':re.sub(r'_ownershiprepair_v\d+$','',mid),'raw_source_id':sid})
rows=[]
for definition,col,text in [('distinct_base_source','base_source','Collapse registered edit variants; exclude classroom and evaluation_routing duplicate audit cohort. Retain distinct registered base IDs even when theme names coincide.'),('plus_edit_variants','edit_definition','Count edit_add/edit_move/edit_remove source variants separately.'),('plus_rename_variants','rename_definition','Additionally count retained zone_rename variant separately.'),('plus_regeneration_variants','regeneration_definition','Additionally distinguish retained generated instance IDs/repetitions/models; ownershiprepair views collapse to their parent generated instance.'),('historical_raw_source_id','raw_source_id','Historical 59/134 used literal source_id strings; includes edit variants but collapses rename and regeneration variants.')]:
 rows.append({'definition':definition,'native_audited_models':len(native),'sources_under_definition':len({x[col]for x in lineage}),'definition_text':text})
table('tables/T3b_source_definitions.csv',rows);table('tables/T3b_source_lineage.csv',lineage)
number('audited_native_models',len(native));number('audited_native_sources',len({x['base_source']for x in lineage}));number('audited_native_sources_historical_raw_ids',len({x['raw_source_id']for x in lineage}));number('audited_native_source_definition',rows[0]['definition_text']);number('base_sources_including_authored_classroom',len({base(r['model']['source_id'])for r in good if r['model']['cohort']!='evaluation_routing'}))
for r in rows:number('source_definition_'+r['definition'],r['sources_under_definition'])
missing=[r for r in A if r.get('model',{}).get('cohort')=='evaluation_routing' and 'ok'not in(r.get('authoring')or{})]
resolved=[];details=[]
for r in missing:
 meta=r['metadata'];p=ROOT/'results/raw/wp4_corpus_parallel_v1'/meta['corpus_file'];raw=p.read_bytes();sha=hashlib.sha256(raw).hexdigest();assert sha==meta['corpus_sha256']==r['authoring']['corpus_file_sha256'];c=read(p);assert c['source_room_id']==r['model']['source_id'];report=validate_roomcontract_v2_instance(c['instance']);details.append({'model_id':r['model']['model_id'],'corpus_relative_path':'results/raw/wp4_corpus_parallel_v1/'+meta['corpus_file'],'corpus_sha256':sha,'audit':report});resolved.append({'model_id':r['model']['model_id'],'source_id':r['model']['source_id'],'old_authoring_ok':'','old_status':r['authoring']['status'],'new_status':'offline_validated','authoring_ok':report['ok'],'errors':report['error_count'],'warnings':report['warning_count'],'audit_missing':False,'source_count_effect':0,'reason':'Export fallback retained a corpus hash/status placeholder but omitted the authoring ok field; audited now from hash-verified retained native instance.'})
table('tables/T3c_authoring_audit_completion.csv',resolved);save('review/authoring_audits_completed_a.json',details)
number('evaluation_authoring_empty_before',len(missing));number('evaluation_authoring_empty_after',sum(x['audit_missing']for x in resolved));number('evaluation_authoring_completed_pass',sum(x['authoring_ok']for x in resolved));number('evaluation_authoring_completed_fail',sum(not x['authoring_ok']for x in resolved));number('evaluation_authoring_source_count_effect',0)
# Recompute differential units from original retained final probe rows, not a new run.
probes=[]
for run in('go_final_full','go_final_extended'):
 p=ROOT/'anonymous_repo/results/raw/differential'/run/'probes.jsonl';probes.extend(json.loads(s)for s in p.read_text().splitlines()if s.strip())
print('DIFFERENTIAL_SCHEMA',list(probes[0]),flush=True)
save('review/source_and_audit_numbers_a_partial.json',nums);save('review/source_and_audit_changes_a_partial.json',log)

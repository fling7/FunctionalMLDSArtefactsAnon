"""Requested actually-used-room intervals alongside unchanged registered analysis."""
from pathlib import Path
import importlib.util,json,hashlib
p=Path(__file__).with_name('stage_b_v5.py');spec=importlib.util.spec_from_file_location('b_analysis_original',p);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
plan=m.read(m.RAW/'preregistration_v5.json');console_names=[p.name for p in (m.RAW/'console').glob('*.txt')]
used=[r for r in plan['selected']if any(name.startswith(r['room']+'__')for name in console_names)]
assert used
original_read=m.read
m.OUT=m.OUT/'actually_started_rooms'
def read(path):
 value=original_read(path)
 if Path(path).name=='preregistration_v5.json':value={**value,'selected':used}
 return value
m.read=read;m.summarize()
m.save(m.OUT/'analysis_scope.json',{'status':'SUPPLEMENTAL_REQUESTED_ACTUAL_ROOM_DENOMINATOR','registered_rooms':len(plan['selected']),'actually_started_rooms':len(used),'room_ids':[r['room']for r in used],'selection_rule':'A room is actually used when an owned worker console exists for at least one operator; independent of detector outcomes. Includes rooms with zero eligible results. Unstarted registered rooms excluded from this bootstrap only.','bootstrap_resamples':10000,'seed':20261015,'original_registered_analysis':'../tables/T_B1_detection.csv remains unchanged, including all374 planned slots.','generator':Path(__file__).relative_to(m.ROOT).as_posix(),'generator_sha256':m.sha(Path(__file__)),'source_module':p.relative_to(m.ROOT).as_posix(),'source_module_sha256':m.sha(p),'original_plan_sha256':m.sha(m.RAW/'preregistration_v5.json'),'caution':'Actual-room analysis cannot resolve informative technical censoring. No claim of complete>=20room coverage unless actually achieved.'})

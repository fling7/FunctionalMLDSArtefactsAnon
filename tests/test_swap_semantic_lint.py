"""Engineering geometry fixtures; no semantic corpus labels."""
import copy,json,sys
from pathlib import Path
from types import SimpleNamespace
import pytest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from experiments.swap_semantic_lint import measure,changed_targets

def fixture(tmp_path,overlap=False,missing=False,partial=False):
 (tmp_path/'input').mkdir();(tmp_path/'intermediate').mkdir()
 objects=[{'objectId':'one','position':{'x':0,'z':0},'dimensions':{'width':1,'depth':1}},
          {'objectId':'two','position':{'x':0 if overlap else 10,'z':0},'dimensions':{'width':1,'depth':1}}]
 (tmp_path/'input/source_rdl.json').write_text(json.dumps({'scene':{'objects':objects}}))
 (tmp_path/'intermediate/scene_graph.normalized.json').write_text('{}')
 def make(swapped):
  assignments={'o1':['b' if swapped else 'a'],'o2':['a' if swapped else 'b']}
  return SimpleNamespace(objects={'o1':{'sourceId':'one'},'o2':{'sourceId':'two'}},
   zones={'z1':{'sourceObjectId':['one']},'z2':{'sourceObjectId':['two']}},
   agents={'a':{'responsibleZone':[] if missing else ['z1']},'b':{'responsibleZone':[] if missing or partial else ['z2']}},
   wire={'a':'agent_a','b':'agent_b'},ownership=lambda t:('asset',assignments[t]))
 return make(False),make(True)

def test_separated_footprints_newly_flag_both_swapped_targets(tmp_path):
 b,m=fixture(tmp_path);r=measure(tmp_path,b,m)
 assert r['baseline_outside']==0 and r['mutant_outside']==2 and r['newly_outside']==2
 assert r['model_newly_flagged'] is True

def test_overlapping_footprints_do_not_imply_bad_semantics(tmp_path):
 b,m=fixture(tmp_path,overlap=True);r=measure(tmp_path,b,m)
 assert r['paired_geometry_available']==2 and r['newly_outside']==0
 assert r['model_newly_flagged'] is False and 'unavailable' in r['semantic_ground_truth']

@pytest.mark.parametrize('option',['missing','partial'])
def test_unavailable_zone_geometry_excluded_from_model_denominator(tmp_path,option):
 b,m=fixture(tmp_path,**{option:True});r=measure(tmp_path,b,m)
 assert r['unavailable']==2 and r['model_newly_flagged'] is None
 assert all(row['newly_outside'] is None for row in r['changed_targets'])

def test_non_swap_model_refused(tmp_path):
 b,m=fixture(tmp_path)
 with pytest.raises(ValueError,match='exactly two'):changed_targets(b,b)

def test_changed_object_set_refused(tmp_path):
 b,m=fixture(tmp_path);m.objects.pop('o1')
 with pytest.raises(ValueError,match='object set'):changed_targets(b,m)

import copy
import pytest
from experiments.semantic_judge_draft import *

def source():
 return {"scene":{"sceneName":"fixture","objects":[{"objectId":"b","objectType":"rock","group":"g","position":{"x":1,"y":0,"z":0},"dimensions":{"width":1,"height":1,"depth":1},"specification":"A rock."},{"objectId":"a","objectType":"book","group":"g","specification":"A book."}]}}
def test_grounding_keeps_original_selected_record_and_every_object():
 src=source();before=copy.deepcopy(src)
 g=grounding(src,"b",[{"id":"agent","persona":"Geology"}],"agent")
 assert g["selected_original_object"]==src["scene"]["objects"][0]
 assert [r[0] for r in g["complete_room_inventory"]]==["a","b"]
 assert src==before

def test_profiles_and_source_ids_must_resolve():
 with pytest.raises(ValueError):grounding(source(),"none",[{"id":"a"}],"a")
 with pytest.raises(ValueError):grounding(source(),"a",[{"id":"a"}],"b")

def test_same_evidence_for_both_models_and_no_condition_leak():
 g=grounding(source(),"a",[{"id":"a"}],"a")
 rows=blind_order([{"key":["swap","before"],"condition":"before","grounding":g},{"key":["swap","after"],"condition":"after","grounding":g}])
 assert rows==blind_order(list(reversed(rows)))
 a,b=[payload(g,m) for m in MODELS]
 assert a["input"]==b["input"]
 assert "condition" not in a["input"][1]["content"]
 assert a["max_output_tokens"]==192 and a["temperature"]==0

def test_source_selection_earliest_success_and_stable_order():
 rows=[{"source_room_id":s,"source_priority":p,"run_ordinal":r,"case_id":str(r),"eligible_native_success":True} for s,p,r in [("a",1,31),("b",2,2),("a",1,1)]]
 assert [r["run_ordinal"] for r in source_order(rows)]==[1,2]
 assert source_order(rows)==source_order(list(reversed(rows)))
 rows.append({**rows[0],"source_room_id":"collision"})
 with pytest.raises(ValueError,match="unique"):source_order(rows)

def test_incomplete_manifest_cannot_be_frozen():
 with pytest.raises(ValueError,match="not terminal"):primary_rows({"rows":[]})

def test_format_and_insufficient_evidence_denominators():
 good={"judgment":"insufficient_evidence","reason":"No topic specified.","supporting_source_ids":[]}
 assert valid_label(good,{"a"})=="insufficient_evidence"
 assert valid_label({**good,"supporting_source_ids":["invented"]},{"a"})=="FORMAT_ERROR"
 assert valid_label({**good,"extra":1},{"a"})=="FORMAT_ERROR"
 a=agreement([("plausible","plausible"),("implausible","implausible"),("insufficient_evidence","plausible"),("FORMAT_ERROR","plausible")])
 assert a["valid_paired_items"]==3 and a["invalid_or_missing_pairs"]==1
 assert a["agreement_rate"]==2/3 and a["insufficient_evidence_model_A"]==1
 assert a["cohen_kappa"]==pytest.approx(.5)

def test_kappa_undefined_is_not_zero():
 assert agreement([])["cohen_kappa"] is None
 assert agreement([("plausible","plausible")])["kappa_undefined_reason"]=="constant_marginals"

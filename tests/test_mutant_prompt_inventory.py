import json
import pytest
from experiments.prepare_mutant_prompt_inventory import choose_probe, collect

def verdict(decision="REJECT",reason="E_AMBIGUOUS_OWNER",provider=None):
 return {"decision":decision,"reason":reason,"provider":provider,"action":None}
def probe(start="a",target="x",v=None):
 v=v or verdict();return {"start_agent":start,"target":target,"I1":v,"I2":dict(v)}
def baseline():
 return {"routing_table":{"a":{"x":verdict("ANSWER_LOCAL",None,"a"),"y":verdict("ANSWER_LOCAL",None,"a")}}}
def test_selection_is_order_independent_and_excludes_disagreement():
 p=probe();q=probe(target="y");bad=probe(start="z");bad["I2"]["reason"]="E_UNOWNED"
 first=choose_probe([bad,p,q],"duplicate_asset_owner","room",baseline())
 assert first==choose_probe([q,p,bad],"duplicate_asset_owner","room",baseline())
 assert first["candidate_count"]==2

def test_requires_newly_affected_baseline_admission():
 b=baseline();b["routing_table"]["a"]["x"]=verdict(reason="E_NO_HANDOFF_PATH")
 assert choose_probe([probe(v=verdict(reason="E_NO_HANDOFF_PATH"))],"drop_handoff","room",b) is None

def test_swap_requires_changed_target_and_owner():
 p=probe(v=verdict("ANSWER_AFTER_HANDOFF",None,"b"))
 assert choose_probe([p],"swap_owners_consistently","room",baseline(),["x"])
 assert choose_probe([p],"swap_owners_consistently","room",baseline(),[]) is None
 p=probe(v=verdict("ANSWER_LOCAL",None,"a"))
 assert choose_probe([p],"swap_owners_consistently","room",baseline(),["x"]) is None

def make_run(path,setup="reject"):
 path.mkdir();(path/"outcomes").mkdir();meta={"id":"same","storage_id":"m","operators":["remove_action"],"room":"r","status":"changed"}
 (path/"mutation_manifest.json").write_text(json.dumps({"models":[meta]}))
 (path/"outcomes/m.json").write_text(json.dumps({"metadata":meta,"checkers":{"backend_setup":{"status":setup}}}))
 return path

def test_setup_refusal_preserved_as_outcome(tmp_path):
 rows,_=collect([make_run(tmp_path/"r")])
 assert rows["same"]["outcome"]["checkers"]["backend_setup"]["status"]=="reject"

def test_original_recovery_double_count_rejected(tmp_path):
 with pytest.raises(ValueError,match="Duplicate original/recovery"):
  collect([make_run(tmp_path/"old"),make_run(tmp_path/"recovery")])

def test_outcome_metadata_mismatch_rejected(tmp_path):
 p=make_run(tmp_path/"r");o=json.loads((p/"outcomes/m.json").read_text());o["metadata"]["room"]="different";(p/"outcomes/m.json").write_text(json.dumps(o))
 with pytest.raises(ValueError,match="metadata mismatch"):collect([p])

import copy
import pytest
from experiments.wp6_provenance import join_mutants,source_cluster_interval

def record(mid,case):return {"metadata":{"id":mid,"room":case},"probe_count":7}
def test_counterparts_repetitions_and_mutants_do_not_create_rooms():
 records=[record("a1","a_mini_r0"),record("a2","a_full_r0"),record("a3","a_mini_r1"),record("a4","a_mini_r1"),record("b1","b_mini_r0")];before=copy.deepcopy(records)
 sources=[{"case_id":c,"source_room_id":"a"} for c in ["a_mini_r0","a_full_r0","a_mini_r1"]]+[{"case_id":"b_mini_r0","source_id":"b"}]
 j=join_mutants(records,sources)
 assert j["counts"]=={"mutants":5,"probes":35,"snapshots":4,"resolved_source_rooms":2,"unresolved_mutants":0,"unresolved_probes":0} and records==before
 interval=source_cluster_interval(j,{"a1":(1,1),"a2":(1,1),"a3":(1,1),"a4":(1,1),"b1":(0,1)},repetitions=100)
 assert interval["source_clusters"]==2 and interval["numerator"]==4 and interval["denominator"]==5 and interval["interval"]==[0.,1.]
 assert interval==source_cluster_interval(j,{"a1":(1,1),"a2":(1,1),"a3":(1,1),"a4":(1,1),"b1":(0,1)},repetitions=100)

def test_missing_conflicting_and_family_provenance_explicit():
 j=join_mutants([record("m","unknown"),record("c","conflict"),record("e","edit")],[{"case_id":"conflict","source_id":"a"},{"case_id":"conflict","source_id":"b"},{"case_id":"edit","source_id":"edited_bytes","source_family_id":"original_room"}])
 assert [r["join_status"] for r in j["rows"]]==["missing_provenance","conflicting_provenance","resolved"]
 assert j["counts"]["resolved_source_rooms"]==1 and j["counts"]["unresolved_mutants"]==2
 report=source_cluster_interval(j,{"m":(1,1),"c":(1,1),"e":(1,1)})
 assert report["interval"] is None and report["unresolved_value_rows"]==2 and report["denominator"]==1

def test_duplicate_recovery_observation_refused():
 with pytest.raises(ValueError,match="Duplicate"):join_mutants([record("x","a"),record("x","a")],[])


def test_source_manifest_pins_and_geometry_schema(tmp_path):
 import json,hashlib
 from experiments.wp6_provenance import load_source_manifests
 path=tmp_path/"source.json";path.write_text(json.dumps({"sources":{"a_mini_r0":{"source_room_id":"a"}}}))
 sha=hashlib.sha256(path.read_bytes()).hexdigest();rows,pins=load_source_manifests([str(path)+"="+sha])
 assert rows==[{"case_id":"a_mini_r0","source_room_id":"a"}] and pins[0]["sha256"]==sha
 path.write_text(json.dumps({"sources":{"a_mini_r0":{"source_room_id":"changed"}}}))
 with pytest.raises(ValueError,match="hash mismatch"):load_source_manifests([str(path)+"="+sha])


def test_checker_intervals_keep_unresolved_and_na_denominators():
 from experiments.wp6_provenance import checker_source_intervals
 records=[]
 for mid,truth,status in [("a",True,"reject"),("b",True,"pass"),("u",None,"reject"),("n",False,"na")]:
  r=record(mid,mid);r.update(groundtruth={"routing_faulty":truth},checkers={"Vb":{"status":status}});records.append(r)
 joined=join_mutants(records,[{"case_id":x,"source_id":x} for x in ["a","b","u","n"]])
 r=checker_source_intervals(records,joined)["Vb"]
 assert r["sensitivity"]["numerator"]==1 and r["sensitivity"]["denominator"]==2 and r["sensitivity"]["source_clusters"]==2
 assert r["excluded_unresolved_models"]==1 and r["excluded_unavailable_models"]==1 and r["false_positive_proportion"]["denominator"]==0


def test_derived_analyze_counts_snapshots_separately(tmp_path,monkeypatch):
 import json
 from experiments import report_mutation_analysis as report
 monkeypatch.setattr(report,"ROOT",tmp_path)
 run=tmp_path/"run";(run/"outcomes").mkdir(parents=True)
 (run/"mutation_manifest.json").write_text(json.dumps({"models":[]}));(run/"summary.json").write_text("{}")
 for mid,case in [("a","room_mini"),("b","room_full")]:
  r=record(mid,case);r["metadata"].update(operators=["swap_owners_consistently"],status="changed");r.update(groundtruth={"routing_faulty":False},checkers={},probes=[])
  (run/"outcomes"/(mid+".json")).write_text(json.dumps(r))
 result=report.analyze(run,[{"case_id":c,"source_room_id":"room"} for c in ["room_mini","room_full"]])
 assert result["source_accounting"]["counts"]["snapshots"]==2 and result["source_accounting"]["counts"]["resolved_source_rooms"]==1
 assert result["snapshot_case_ids"]==["room_full","room_mini"] and "rooms" not in result


def test_report_paths_and_reproduction_keep_source_pins(tmp_path,monkeypatch):
 import json,hashlib
 from experiments import report_mutation_analysis as report
 monkeypatch.setattr(report,"ROOT",tmp_path)
 run=tmp_path/"nested"/"run";(run/"outcomes").mkdir(parents=True)
 (run/"mutation_manifest.json").write_text(json.dumps({"models":[]}))
 summary={"evaluation_complete":False,"models_evaluated":0,"planned_model_evaluations":2,"worker_failures":0,"independent_disagreement_models":0,"eligibility_counts":{},"matrix":[],"admission_ablations":[],"stale_digest_ablations":{},"behavior_properties":{}}
 (run/"summary.json").write_text(json.dumps(summary))
 source=tmp_path/"provenance"/"sources.json";source.parent.mkdir();source.write_text(json.dumps({"rows":[{"case_id":"mini","source_id":"one"}]}))
 pin=hashlib.sha256(source.read_bytes()).hexdigest();out=tmp_path/"out";paper=out/"paper.json";doc=out/"report.md"
 report.generate([run],doc,out/"tables",paper,source_manifests=[str(source)+"="+pin])
 result=json.loads(paper.read_text());assert result["runs"][0]["run"]=="nested/run"
 for key in ["summary_path","operator_pair_coverage_path","single_operator_eligibility_path"]:assert "\\" not in result["runs"][0][key]
 assert result["report"]=="out/report.md" and result["source_manifest_pins"][0]["sha256"]==pin
 assert "--source-manifest <path>=<sha256>" in doc.read_text() and "[--geometry <geometry-json>]" in doc.read_text()
 assert "source_manifest_pins" in doc.read_text()


def test_default_bootstrap_performs_ten_thousand_source_resamples(monkeypatch):
 from experiments import wp6_provenance as provenance
 original_random=provenance.random.Random;calls=[];seeds=[]
 class CountingRandom:
  def __init__(self,seed):seeds.append(seed);self.rng=original_random(seed)
  def randrange(self,size):calls.append(size);return self.rng.randrange(size)
 monkeypatch.setattr(provenance.random,"Random",CountingRandom)
 joined=join_mutants([record("a","a"),record("b","b")],[{"case_id":"a","source_id":"one"},{"case_id":"b","source_id":"two"}])
 values={"a":(1,1),"b":(0,1)};before=copy.deepcopy((joined,values))
 result=source_cluster_interval(joined,values)
 assert result["repetitions"]==10000 and result["defined_replicates"]==10000
 assert seeds==[20261015] and calls==[2]*20000
 assert result["estimate"]==.5 and result["interval"]==[0.,1.]
 assert (joined,values)==before


def test_pooled_checker_reporting_uses_ten_thousand_fixed_seed_resamples():
 from experiments.wp6_provenance import checker_source_intervals
 records=[]
 for mid,truth,status in [("a",True,"reject"),("b",True,"pass"),("c",False,"reject"),("d",False,"pass")]:
  row=record(mid,mid);row.update(groundtruth={"routing_faulty":truth},checkers={"checker":{"status":status}});records.append(row)
 joined=join_mutants(records,[{"case_id":x,"source_id":x} for x in "abcd"])
 first=checker_source_intervals(records,joined);second=checker_source_intervals(records,joined)
 assert first==second
 for name in ["sensitivity","false_positive_proportion"]:
  result=first["checker"][name]
  assert result["repetitions"]==10000 and result["defined_replicates"]==10000 and result["seed"]==20261015
  assert result["numerator"]==1 and result["denominator"]==2 and result["source_clusters"]==2

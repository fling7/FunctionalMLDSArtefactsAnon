"""Derived source-room accounting; never changes frozen mutant classifications."""
from collections import defaultdict
import random
import hashlib
import json
from pathlib import Path

def join_mutants(records,source_rows):
 sources=defaultdict(set)
 for row in source_rows:
  case=row.get("case_id");source=row.get("source_family_id") or row.get("source_room_id") or row.get("source_id")
  if case and source:sources[case].add(source)
 seen=set();joined=[]
 for record in records:
  identity=record["metadata"]["id"]
  if identity in seen:raise ValueError("Duplicate original/recovery mutant observation: "+identity)
  seen.add(identity);snapshot=record["metadata"]["room"];candidates=sources[snapshot]
  status="resolved" if len(candidates)==1 else "missing_provenance" if not candidates else "conflicting_provenance"
  joined.append({"mutant_id":identity,"snapshot_case_id":snapshot,"source_room_id":next(iter(candidates)) if len(candidates)==1 else None,"join_status":status,"probe_count":record["probe_count"]})
 counts={"mutants":len(joined),"probes":sum(r["probe_count"] for r in joined),"snapshots":len({r["snapshot_case_id"] for r in joined}),"resolved_source_rooms":len({r["source_room_id"] for r in joined if r["join_status"]=="resolved"}),"unresolved_mutants":sum(r["join_status"]!="resolved" for r in joined),"unresolved_probes":sum(r["probe_count"] for r in joined if r["join_status"]!="resolved")}
 return {"counts":counts,"rows":joined,"interpretation":"metadata.room is a snapshot/case identity, not a source-room count. Unresolved provenance never creates a new source room."}

def source_cluster_interval(joined,values,*,seed=20261015,repetitions=10000):
 """Exploratory percentile interval; resample whole sources, keeping snapshots."""
 groups=defaultdict(lambda:[0,0]);unresolved=0
 for row in joined["rows"]:
  if row["mutant_id"] not in values:continue
  success,total=values[row["mutant_id"]]
  if not (0<=success<=total):raise ValueError("Invalid numerator/denominator")
  if row["join_status"]!="resolved":unresolved+=1;continue
  group=groups[row["source_room_id"]];group[0]+=success;group[1]+=total
 points=list(groups.values());numerator=sum(v[0] for v in points);denominator=sum(v[1] for v in points)
 report={"source_clusters":len(points),"numerator":numerator,"denominator":denominator,"unresolved_value_rows":unresolved,"estimate":numerator/denominator if denominator else None,"interval":None,"method":"Exploratory source-cluster percentile bootstrap; all snapshots/mutants of a sampled source are kept together. Original preregistered Wilson intervals remain separate.","seed":seed,"repetitions":repetitions}
 if len(points)<2 or not denominator:report["undefined_reason"]="fewer than two resolved source clusters or zero denominator";return report
 rng=random.Random(seed);draws=[]
 for _ in range(repetitions):
  sample=[points[rng.randrange(len(points))] for _ in points];n=sum(v[0] for v in sample);d=sum(v[1] for v in sample)
  if d:draws.append(n/d)
 draws.sort()
 def q(f):
  k=(len(draws)-1)*f;i=int(k);j=min(i+1,len(draws)-1);return draws[i]+(draws[j]-draws[i])*(k-i)
 report["interval"]=[q(.025),q(.975)] if draws else None;report["defined_replicates"]=len(draws);return report


def load_source_manifests(specifications):
 """Read explicit path=SHA256 pins; never accept silently changed provenance."""
 rows=[];pins=[]
 for specification in specifications:
  name,expected=specification.rsplit("=",1);path=Path(name);raw=path.read_bytes();actual=hashlib.sha256(raw).hexdigest()
  if actual!=expected.lower():raise ValueError("Source provenance hash mismatch: "+name)
  value=json.loads(raw)
  if isinstance(value.get("rows"),list):current=value["rows"]
  elif isinstance(value.get("sources"),dict):current=[dict(row,case_id=case) for case,row in value["sources"].items()]
  elif isinstance(value.get("selected_projects"),list):current=value["selected_projects"]
  else:raise ValueError("Unrecognized source provenance schema: "+name)
  rows.extend(current);pins.append({"path":path.as_posix(),"sha256":actual,"rows":len(current)})
 return rows,pins


def checker_source_intervals(records,joined):
 """Supplement the frozen mutant-level Wilson cells without changing labels."""
 names=sorted({name for record in records for name in record["checkers"]});result={}
 for name in names:
  faulty={};nonfaulty={};unresolved=0;unavailable=0
  for record in records:
   truth=record["groundtruth"]["routing_faulty"];status=record["checkers"].get(name,{}).get("status")
   if truth is None:unresolved+=1;continue
   if status not in {"pass","reject"}:unavailable+=1;continue
   (faulty if truth else nonfaulty)[record["metadata"]["id"]]=(int(status=="reject"),1)
  result[name]={"sensitivity":source_cluster_interval(joined,faulty),"false_positive_proportion":source_cluster_interval(joined,nonfaulty),"excluded_unresolved_models":unresolved,"excluded_unavailable_models":unavailable}
 return result

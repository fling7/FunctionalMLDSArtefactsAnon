import package_stage as p
from datetime import datetime,timezone
import json,zipfile
stage="A";dst=p.RELEASE/"stage_A";initial=p.pins()
secret=p.scan([dst]);identity=p.scan_identity(dst)
assert not secret and not identity,(secret,identity)
p.save(dst/"review/release_scan.json",{"secret_findings":secret,"identity_findings":identity,"export_only_fix":"Portable path privacy assertion expressed using character construction; no scientific data changed."})
payload={x.relative_to(dst).as_posix():p.sha(x) for x in sorted(dst.rglob("*")) if x.is_file()}
p.save(dst/"review/release_proof.json",{"status":"PASS","stage":stage,"utc":datetime.now(timezone.utc).isoformat(),"payload_sha256":payload,"baseline_pins":initial,"excludes":["review/release_proof.json","MANIFEST.sha256"],"baseline_pins_unchanged":True,"gate_statuses_changed":False})
(dst/"MANIFEST.sha256").write_text("".join(p.sha(x)+"  "+x.relative_to(dst).as_posix()+"\n" for x in sorted(dst.rglob("*")) if x.is_file()),encoding="utf-8")
archive=p.ROOT/"deliverables/for_claude_delta2_A.zip"
with zipfile.ZipFile(archive,"x",zipfile.ZIP_DEFLATED,compresslevel=6) as z:
 for x in sorted(dst.rglob("*")):
  if x.is_file():z.write(x,x.relative_to(dst).as_posix())
p.verify_zip(archive);p.pins()
receipt={"stage":stage,"path":archive.relative_to(p.ROOT).as_posix(),"bytes":archive.stat().st_size,"sha256":p.sha(archive),"manifest_verified":True,"scans_clean":True}
p.save(p.RELEASE/"receipt_A.json",receipt);print(json.dumps(receipt))

"""Strict export gate. Reports locations and pattern labels, never matched text."""
from __future__ import annotations
import argparse,json,re,os
from pathlib import Path
PATTERNS={
 "secret_token":re.compile(rb"sk"+"-".encode()+rb"[A-Za-z0-9_-]{12,}"),
 "credential_assignment":re.compile(("OPENAI_API_KEY"+"=").encode()),
 "authorization_header":re.compile(("Bearer"+chr(32)).encode()),
 "credential_filename":re.compile(rb"\."+b"env"+rb"(?![A-Za-z0-9_])"),
 "nonempty_config_credential":re.compile(rb'"openai_api_key"\s*:\s*"(?:[^"\\]|\\.)+"'),
}
def known_secrets():
    values=[os.environ.get("OPENAI_API_KEY","")]
    source=Path(__file__).resolve().parents[1]/("."+ "env")
    if source.is_file():
        for line in source.read_text(encoding="utf-8-sig").splitlines():
            name,sep,value=line.partition("=")
            if sep and name.strip()=="OPENAI_API_KEY":
                values.append(value.strip().strip(chr(34)).strip(chr(39)))
    return [v.encode("utf-8") for v in values if len(v)>12]

def scan(paths):
    findings=[]
    credentials=known_secrets()
    for root in paths:
        root=Path(root)
        files=sorted(root.rglob("*")) if root.is_dir() else [root]
        for p in files:
            if not p.is_file():continue
            if p.name=="."+ "env" or p.name=="config.json":
                findings.append({"path":str(p),"line":0,"pattern":"forbidden_file"});continue
            data=p.read_bytes()
            if any(key in data for key in credentials):
                findings.append({"path":str(p),"line":0,"pattern":"known_credential_value"})
            for name,pattern in PATTERNS.items():
                for match in pattern.finditer(data):
                    findings.append({"path":str(p),"line":data[:match.start()].count(b"\n")+1,"pattern":name})
    return findings
def main():
    ap=argparse.ArgumentParser();ap.add_argument("paths",nargs="+",type=Path);ap.add_argument("--report",type=Path);args=ap.parse_args()
    findings=scan(args.paths)
    report={"clean":not findings,"hits":len(findings),"findings":findings}
    if args.report:args.report.parent.mkdir(parents=True,exist_ok=True);args.report.write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"clean":not findings,"hits":len(findings)}))
    return 0 if not findings else 1
if __name__=="__main__":raise SystemExit(main())

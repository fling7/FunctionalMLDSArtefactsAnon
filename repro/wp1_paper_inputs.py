"""Generate invariant-summary table and architecture figures from saved evidence."""
from pathlib import Path
import collections,csv,hashlib,json,subprocess,sys,shutil
ROOT=Path(__file__).resolve().parents[1]

def traceability():
    raw=ROOT/'docs/INVARIANT_TRACEABILITY.csv'
    records=list(csv.DictReader(raw.open(encoding='utf-8')))
    counts=collections.Counter((r['profile'],r['status'],r['severity']) for r in records)
    rows=[{'profile':p,'status':s,'severity':v,'invariants':n} for (p,s,v),n in sorted(counts.items())]
    out=ROOT/'paper_inputs/tables';out.mkdir(exist_ok=True,parents=True)
    with (out/'T10_invariant_traceability.csv').open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    lines=[r'\begin{tabular}{lllr}',r'\toprule',r'Profile & Enforcement status & Severity & Count \\',r'\midrule']
    for r in rows:lines.append(' & '.join(str(r[k]).replace('_',r'\_') for k in ('profile','status','severity','invariants'))+r' \\')
    lines += [r'\bottomrule',r'\end{tabular}','% Not enforced means no complete check/negative-fixture audit; related checks may exist.']
    (out/'T10_invariant_traceability.tex').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    result={'unit':'numbered invariant','invariants':len(records),'rows':rows,'source':raw.relative_to(ROOT).as_posix(),'source_sha256':hashlib.sha256(raw.read_bytes()).hexdigest(),
            'limit':'Enforced requires a linked executable check and negative fixture. Not enforced does not assert that no related implementation check exists.'}
    (ROOT/'results/processed/invariant_traceability_summary.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    return result

def architecture():
    from reportlab import rl_config
    rl_config.invariant=True
    from reportlab.graphics.shapes import Drawing,Rect,String,Line,Polygon
    from reportlab.graphics import renderPDF,renderSVG
    from reportlab.lib.colors import HexColor
    from reportlab.pdfbase.pdfmetrics import stringWidth
    out=ROOT/'paper_inputs/figures';out.mkdir(exist_ok=True,parents=True)
    font=7.5;ink=HexColor('#25313D');blue=HexColor('#0072B2');orange=HexColor('#D55E00')
    neutral=HexColor('#F4F4F4');model=HexColor('#E7F2F8');commit=HexColor('#FFF1E8')
    def text(d,x,y,label,size=font,bold=False):
        d.add(String(x,y,label,fontName='Helvetica-Bold' if bold else 'Helvetica',fontSize=size,fillColor=ink))
    def box(d,x,y,w,h,lines,fill=neutral):
        d.add(Rect(x,y,w,h,fillColor=fill,strokeColor=ink,strokeWidth=.6))
        step=10
        for i,label in enumerate(lines):
            assert stringWidth(label,'Helvetica-Bold' if i==0 else 'Helvetica',font)<=w-12,(w,label)
            text(d,x+6,y+h-13-i*step,label,bold=i==0)
    def arrow(d,x1,y1,x2,y2):
        d.add(Line(x1,y1,x2,y2,strokeColor=ink,strokeWidth=.65))
        if x1==x2:d.add(Polygon([x2,y2,x2-2,y2+4,x2+2,y2+4],fillColor=ink,strokeColor=ink))
        else:d.add(Polygon([x2,y2,x2-4,y2-2,x2-4,y2+2],fillColor=ink,strokeColor=ink))
    rows=[
      ('Publish artifacts',['Model, trace, agent and placement projections'],model),
      ('Gate 0: model verification',['Unique owner; one declared answering path;','handoff reachability; derive routing table'],model),
      ('Setup and pin',['Validate one published version; pin digest','and generation (cooperative mode)'],neutral),
      ('Gates 1-3: admit before generation',['Check selection identity and model pin;','derive provider and declared action;','validate request schema'],model),
      ('Generate answer',['Call the selected provider; constrain output;','handle handoff proposals by configured mode'],neutral),
      ('Gate 4: cooperative commit',['Under shared project/evidence lock: reload,','compare generation and fingerprint,','append evidence pair; then expose commit'],commit)]
    manifest=[]
    for tag,width,height in [('single',85/25.4*72,475),('double',175/25.4*72,292)]:
        d=Drawing(width,height);text(d,10,height-16,'F1  Model-relative routing assurance',9,bold=True)
        if tag=='single':
            w=width-20;x=10;y=height-80
            for i,(title,body,fill) in enumerate(rows):
                h=55 if len(body)==3 else 45
                box(d,x,y,w,h,[title,*body],fill)
                if i<len(rows)-1:arrow(d,x+w/2,y,x+w/2,y-10)
                y-=65
            text(d,10,39,'Failure: reject before generation or restore snapshot.',7)
            text(d,10,27,'A changed publication requires a new setup / pin.',7)
            text(d,10,15,'Meaning and answer correctness remain outside the contract.',7)
        else:
            w=(width-40)/2;left=10;right=30+w
            text(d,left,height-34,'Publication / setup',8,bold=True)
            text(d,right,height-34,'Request / turn',8,bold=True)
            ys=[height-90,height-151,height-212]
            for i in range(3):
                title,body,fill=rows[i];box(d,left,ys[i],w,47,[title,*body],fill)
                if i<2:arrow(d,left+w/2,ys[i],left+w/2,ys[i+1]+47)
            for j in range(3):
                title,body,fill=rows[j+3];box(d,right,ys[j]-6,w,55,[title,*body],fill)
                if j<2:arrow(d,right+w/2,ys[j]-6,right+w/2,ys[j+1]+49)
            mid=left+w+10
            d.add(Line(left+w,height-188,mid,height-188,strokeColor=ink,strokeWidth=.65))
            d.add(Line(mid,height-188,mid,height-68,strokeColor=ink,strokeWidth=.65))
            arrow(d,mid,height-68,right,height-68)
            text(d,10,55,'Request supplies selected object, active agent and question. Table mode retains request-bound checks.',7)
            text(d,10,42,'Gate 4 failure restores session state; publication drift requires setup with a new pin.',7)
            text(d,10,29,'The cooperative publisher holds the same lock and advances its generation last. Direct edits retain a race.',7)
            text(d,10,16,'Assurance is relative to declared routing policy; semantic ownership and answer correctness are outside it.',7)
        for fmt,renderer in [('pdf',renderPDF),('svg',renderSVG)]:renderer.drawToFile(d,str(out/f'F1_architecture_{tag}.{fmt}'))
        manifest.append({'tag':tag,'width_cm':85/10 if tag=='single' else 175/10,'height_pt':height,'minimum_font_pt':7})
    (out/'F1_architecture_manifest.json').write_text(json.dumps({'generator':'repro/wp1_paper_inputs.py','figures':manifest,'kind':'Design diagram, not an empirical result'},indent=2)+'\n',encoding='utf-8')

def main():
    result=traceability();architecture()
    subprocess.run([sys.executable,str(ROOT/'tools/generate_routing_figures.py')],cwd=ROOT,check=True)
    for tag in ('single','double'):
        for fmt in ('pdf','svg'):
            shutil.copyfile(ROOT/f'output/metamodel_v2/figures/routing_slice_{tag}.{fmt}',
                            ROOT/f'paper_inputs/figures/F2_routing_slice_{tag}.{fmt}')
    print(json.dumps({'table':'T10','invariants':result['invariants'],'figure':'F1','variants':2}))
if __name__=='__main__':main()

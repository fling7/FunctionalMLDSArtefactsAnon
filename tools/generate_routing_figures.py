"""Publication-sized routing slice; fixed 8.5/17.5 cm widths, minimum 7 pt.

The figure distinguishes native metamodel declarations from runtime-only state.
"""
from __future__ import annotations
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'output/metamodel_v2/figures'
FONT=7.2


def figure(width_cm: float, suffix: str):
    single=width_cm<10
    height_cm=17.0 if single else 12.0
    fig,ax=plt.subplots(figsize=(width_cm/2.54,height_cm/2.54))
    fig.subplots_adjust(left=0,right=1,bottom=0,top=1)
    ax.set(xlim=(0,1),ylim=(0,1))
    ax.axis('off')
    def text(x,y,label,**kwargs):
        return ax.text(x,y,label,fontsize=FONT,ha='center',va='center',**kwargs)
    def box(x,y,w,h,label,runtime=False):
        ax.add_patch(FancyBboxPatch((x,y),w,h,boxstyle='round,pad=0.003',linewidth=.7,edgecolor='#304358',facecolor='#f1f5f8' if not runtime else '#fffaf0',linestyle='--' if runtime else '-'))
        text(x+w/2,y+h/2,label)
    def arrow(start,end,label='',offset=(0,0),curve=0):
        ax.add_patch(FancyArrowPatch(start,end,arrowstyle='-|>',mutation_scale=7,linewidth=.65,color='#304358',connectionstyle=f'arc3,rad={curve}'))
        if label:
            text((start[0]+end[0])/2+offset[0],(start[1]+end[1])/2+offset[1],label,bbox={'facecolor':'white','edgecolor':'none','pad':.5})
    if single:
        text(.5,.977,'Native V2 routing declarations',fontweight='bold')
        box(.025,.790,.24,.095,'Agent\nkind: agent')
        box(.735,.845,.24,.064,'Entity (asset)\nsceneObject')
        box(.735,.740,.24,.064,'Entity (asset)\nobjectGroup')
        box(.735,.635,.24,.064,'Entity\nkind: zone')
        arrow((.265,.868),(.735,.878),'groundedAsset',offset=(0,.017))
        arrow((.265,.832),(.735,.772),'groundedObjectGroup',offset=(0,.017))
        arrow((.265,.799),(.735,.667),'responsibleZone',offset=(0,.017))
        arrow((.067,.885),(.221,.885),'handoffTarget',offset=(0,.063),curve=-1.15)
        text(.5,.595,'Specificity: asset > group > zone')
        text(.5,.571,'Exactly one owner at the deciding level')
        text(.5,.533,'Declared answering path',fontweight='bold')
        names=['s  ScenarioStep','u  CapabilityUse','c  Capability','b  RuntimeBinding','a  RuntimeAction']
        ys=[.462,.385,.308,.231,.154]
        for name,y in zip(names,ys): box(.40,y,.565,.048,name)
        for upper,lower in zip(ys,ys[1:]): arrow((.6825,upper),(.6825,lower+.048))
        box(.025,.410,.255,.048,'Agent')
        box(.025,.318,.255,.048,'Entity (asset)\nsceneObject')
        arrow((.40,.419),(.28,.434),'provider',offset=(-.11,.034))
        arrow((.40,.398),(.28,.342),'target',offset=(-.10,0))
        text(.15,.237,'No direct\nstep-to-action\ncall')
        box(.025,.025,.95,.085,'Runtime only (not metamodel)\nSession pin + model digest\nCommit fingerprint',runtime=True)
    else:
        text(.5,.965,'Native V2 routing declarations',fontweight='bold')
        box(.035,.66,.17,.13,'Agent\nkind: agent')
        box(.43,.78,.17,.09,'Entity (asset)\nsceneObject')
        box(.43,.63,.17,.09,'Entity (asset)\nobjectGroup')
        box(.43,.48,.17,.09,'Entity\nkind: zone')
        arrow((.205,.77),(.43,.825),'groundedAsset',offset=(0,.027))
        arrow((.205,.725),(.43,.675),'groundedObjectGroup',offset=(0,.025))
        arrow((.205,.68),(.43,.525),'responsibleZone',offset=(0,.025))
        arrow((.065,.79),(.17,.79),'handoffTarget',offset=(0,.09),curve=-1.1)
        box(.65,.57,.31,.23,'Specificity\nasset > group > zone\n\nExactly one provider at\nthe first nonempty level')
        text(.5,.425,'Declared answering path: s → u → c → b → a',fontweight='bold')
        names=['ScenarioStep','CapabilityUse','Capability','RuntimeBinding','RuntimeAction']
        xs=[.025,.22,.415,.61,.805]
        for name,x in zip(names,xs): box(x,.275,.17,.075,name)
        for left,right in zip(xs,xs[1:]): arrow((left+.17,.3125),(right,.3125))
        arrow((.29,.35),(.135,.66),'provider',offset=(-.015,.01),curve=.23)
        box(.22,.15,.17,.075,'Entity (asset)\nsceneObject')
        arrow((.305,.275),(.305,.225),'target',offset=(.055,0))
        text(.69,.205,'A step names a capability use;\nit never invokes an action directly.')
        box(.025,.025,.95,.08,'Runtime only (not metamodel): session pin + model digest + commit fingerprint',runtime=True)
    for fmt in ['svg','pdf']:
        metadata={'Date':None,'Creator':'tools/generate_routing_figures.py'} if fmt=='svg' else {'CreationDate':None,'ModDate':None,'Creator':'tools/generate_routing_figures.py'}
        fig.savefig(OUT/f'routing_slice_{suffix}.{fmt}',format=fmt,metadata=metadata)
    fig.savefig(OUT/f'routing_slice_{suffix}.png',dpi=180)
    plt.close(fig)
    return {'width_cm':width_cm,'height_cm':height_cm,'minimum_font_pt':FONT,'files':[f'routing_slice_{suffix}.{fmt}' for fmt in ['svg','pdf','png']]}


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    plt.rcParams.update({'font.family':'DejaVu Sans','svg.fonttype':'none','svg.hashsalt':'rcm-routing-v1','pdf.fonttype':42})
    rows=[figure(8.5,'single'),figure(17.5,'double')]
    (OUT/'routing_figure_manifest.json').write_text(json.dumps({'generator':'tools/generate_routing_figures.py','figures':rows},indent=2)+'\n',encoding='utf-8',newline='\n')

if __name__=='__main__': main()

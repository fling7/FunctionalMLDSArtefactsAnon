"""Exhaustive finite-state protocol abstraction; not a proof of Python or OS code.

All enabled labelled step schedules are counted by dynamic programming over the
acyclic reachable-state graph. No random sampling or depth bound is used. A
publication has five separate projection writes. Uncooperative direct edits do
not advance the marker, exposing the limitation of generation-only assertions.
"""
from __future__ import annotations
import argparse
from functools import lru_cache
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from experiments.lib.wp7_common import start_run,finish_run,write_json


def explore(mode,publishers,sessions):
    # Session: pc, pin generation, pinned file revision, check generation,
    # checked revision. Complete state also records whether any append violated.
    empty=(-1,)*5
    initial=((0,)*publishers,tuple((0,-1,empty,-1,empty) for _ in range(sessions)),0,(0,)*5,(0,)*5,-1,False)
    states=edges=0
    first_counterexample=None
    path=[]
    def transitions(st):
        ps,ss,generation,files,manifest,owner,bad=st
        for i,pc in enumerate(ps):
            if pc==7: continue
            if pc==0:
                if mode=='cooperative' and owner!=-1: continue
                newowner=i if mode=='cooperative' else owner
                yield f'P{i}:lock/stage', (ps[:i]+(1,)+ps[i+1:],ss,generation,files,manifest,newowner,bad)
            elif pc<=5:
                changed=files[:pc-1]+(i+1,)+files[pc:]
                yield f'P{i}:write_projection_{pc}',(ps[:i]+(pc+1,)+ps[i+1:],ss,generation,changed,manifest,owner,bad)
            else:
                newgen=generation if mode=='uncooperative' else generation+1
                newmanifest=manifest if mode=='uncooperative' else files
                newowner=-1 if mode=='cooperative' else owner
                yield f'P{i}:'+('finish_direct_edits' if mode=='uncooperative' else 'atomic_flip/unlock'),(ps[:i]+(7,)+ps[i+1:],ss,newgen,files,newmanifest,newowner,bad)
        for i,item in enumerate(ss):
            pc,pin,pinrev,seen,seenrev=item
            if pc==9: continue
            newowner=owner; violation=bad
            if pc==0:
                nxt=(1,pin,pinrev,seen,seenrev); label='snapshot'
            elif pc==1:
                # Cooperative loader refuses a partial publication. Packet's
                # native loader also rejects this abstraction's mixed versions.
                consistent=len(set(files))==1 and (mode!='cooperative' or files==manifest)
                nxt=(2,generation,files,seen,seenrev) if consistent else (8,pin,pinrev,seen,seenrev)
                label='read_pin' if consistent else 'torn_read_refused'
            elif pc==2:
                nxt=(3,pin,pinrev,seen,seenrev); label='validate'
            elif pc==3:
                if mode=='packet':
                    valid=pinrev==files and pin==generation
                    nxt=(4,pin,pinrev,generation,files) if valid else (8,pin,pinrev,seen,seenrev)
                    label='compare_before_lock' if valid else 'compare_abort'
                else:
                    if owner!=-1: continue
                    newowner=publishers+i; nxt=(4,pin,pinrev,seen,seenrev); label='lock'
            elif pc==4:
                if mode=='packet':
                    if owner!=-1: continue
                    newowner=publishers+i; nxt=(5,pin,pinrev,seen,seenrev); label='lock'
                else:
                    valid=pin==generation and pinrev==files and files==manifest
                    nxt=(5,pin,pinrev,generation,files) if valid else (7,pin,pinrev,seen,seenrev)
                    label='compare_inside_lock' if valid else 'compare_abort'
            elif pc==5:
                gen_ok=pin==seen==generation
                revision_ok=pinrev==seenrev==files
                violation=bad or not(gen_ok and revision_ok)
                nxt=(6,pin,pinrev,seen,seenrev)
                label='append_visible'+(' [VIOLATION generation]' if not gen_ok else ' [VIOLATION direct revision]' if not revision_ok else '')
            elif pc==6:
                newowner=-1; nxt=(9,pin,pinrev,seen,seenrev); label='unlock_success'
            elif pc==7:
                newowner=-1; nxt=(8,pin,pinrev,seen,seenrev); label='unlock_abort'
            else:
                nxt=(9,pin,pinrev,seen,seenrev); label='restore'
            yield f'S{i}:{label}',(ps,ss[:i]+(nxt,)+ss[i+1:],generation,files,manifest,newowner,violation)
    @lru_cache(None)
    def visit(st):
        nonlocal states,edges,first_counterexample
        states+=1
        if st[-1] and first_counterexample is None:
            first_counterexample=list(path)
        total=violations=0
        successors=list(transitions(st))
        if not successors:
            assert all(p==7 for p in st[0]) and all(s[0]==9 for s in st[1]),'deadlock'
            return 1,int(st[-1])
        for label,nxt in successors:
            edges+=1;path.append(label)
            count,bad=visit(nxt)
            total+=count;violations+=bad;path.pop()
        return total,violations
    count,bad=visit(initial)
    return {'mode':mode,'publishers':publishers,'sessions':sessions,'reachable_states':states,'transition_edges':edges,'complete_schedules':count,'violating_schedules':bad,'first_counterexample':first_counterexample,'claim_scope':'finite-state abstraction; direct-edit violations include revision mismatch even if generation is unchanged'}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--quick',action='store_true');args=parser.parse_args()
    root=start_run('interleavings',['verification/interleavings.py'])
    rows=[]
    for mode in ('packet','cooperative','uncooperative'):
        for p in (1,2):
            for s in (1,2):
                row=explore(mode,p,s);rows.append(row)
                with (root/'rows.jsonl').open('a',encoding='utf-8') as out: out.write(json.dumps(row)+'\n')
                print(json.dumps({k:v for k,v in row.items() if k!='first_counterexample'}),flush=True)
    finish_run(root,{'cells':len(rows),'states':sum(r['reachable_states'] for r in rows),'cooperative_violating_schedules':sum(r['violating_schedules'] for r in rows if r['mode']=='cooperative'),'packet_counterexample_cells':sum(bool(r['first_counterexample']) for r in rows if r['mode']=='packet'),'uncooperative_counterexample_cells':sum(bool(r['first_counterexample']) for r in rows if r['mode']=='uncooperative'),'rows':rows})

if __name__=='__main__': main()

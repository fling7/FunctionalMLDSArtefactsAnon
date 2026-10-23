"""Pure retained-observation helpers for WP5 reporting. No evaluator imports.

The clustered_interval function is copied unchanged from the frozen natural
analysis module; tests compare its AST so report import isolation cannot silently
change the estimator. Generation and analysis code retain their original source.
"""
from pathlib import Path
import random

ROOT=Path(__file__).resolve().parents[2]
BACKEND=ROOT/"app/backend_root/agent_backend"

def clustered_interval(rows,selector,seed=20261015,repetitions=2000):
    grouped={}
    for row in rows:
        value=selector(row)
        if value is not None:grouped.setdefault(row["source"]["scene_id"],[]).append(value)
    clusters=list(grouped.values())
    if not clusters:return {"estimate":None,"low":None,"high":None,"source_clusters":0}
    means=[sum(c)/len(c) for c in clusters]
    estimate=sum(means)/len(means)
    if len(means)<2:return {"estimate":estimate,"low":None,"high":None,"source_clusters":len(means)}
    rng=random.Random(seed)
    draws=sorted(sum(rng.choice(means) for _ in means)/len(means) for _ in range(repetitions))
    return {"estimate":estimate,"low":draws[int(.025*repetitions)],"high":draws[int(.975*repetitions)-1],
            "source_clusters":len(means),"bootstrap_repetitions":repetitions,"seed":seed}

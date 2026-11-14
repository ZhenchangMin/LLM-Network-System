#!/usr/bin/env python3
"""PEEK-motivated *abstract* token-budget prefix-cache trace. CPU only.
Not PEEK/SGLang, not independent token RadixCache, and not a GPU benchmark.
Tests paused-session metadata as an *information hypothesis*, with false positives.
"""
from __future__ import annotations
import argparse
import csv
import random
import statistics
from collections import Counter, deque
from pathlib import Path

SIZES = {"A":1280, "B":512, "C":768}
CAPACITY = 3200

def episode(seed:int, episode_idx:int, return_probability:float, *, noise_count:int, tool_ttl:int):
    rng=random.Random(seed*1000003 + episode_idx*17 + 2602)
    arrivals=[]
    t=2
    for j in range(noise_count):
        arrivals.append((t+j//2, f"U{j}"))
    last_noise=t+(noise_count-1)//2
    if rng.random()<0.88:
        arrivals.append((last_noise+1,"B"))
        if rng.random()<0.55:
            arrivals.append((last_noise+1,"B"))
    if rng.random()<0.88:
        arrivals.append((last_noise+1,"C"))
    if rng.random()<return_probability:
        arrivals.append((last_noise+3,"A"))
    # Following requests: hot B/C may remain valuable; paused A may be stale
    if rng.random()<0.90:
        arrivals.append((last_noise+4,"B"))
    if rng.random()<0.90:
        arrivals.append((last_noise+5,"C"))
    arrivals.sort(key=lambda x:x[0])
    sizes=SIZES|{f"U{j}":640 for j in range(noise_count)}
    return arrivals,sizes

def run_one(arrivals,sizes,policy,*,ttl:int, beta:float=0.5):
    cached={"A","B","C"}
    last={"A":0,"B":1,"C":2}  # A least recent when external tool starts
    queue=deque()
    cursor=0
    clk=2
    order=3
    missed_bytes=0
    miss_count=0
    queue_protect_events=0
    pause_protect_events=0
    evictions=0
    a_returned=False
    while cursor<len(arrivals) or queue:
        while cursor<len(arrivals) and arrivals[cursor][0]<=clk:
            queue.append(arrivals[cursor][1]); cursor+=1
        if not queue:
            clk+=1;continue
        req=queue.popleft()
        if req not in cached:
            missed_bytes+=sizes[req];miss_count+=1
            while sum(sizes[c] for c in cached)+sizes[req]>CAPACITY:
                pending=Counter(queue)
                def priority(x):
                    qscore=pending[x]*sizes[x] if policy!="lru" else 0
                    # tool metadata: user-issued active pause signal, not predicted return
                    paused=(x=="A" and not a_returned and clk < 2+ttl)
                    pscore=beta*sizes[x] if policy=="pause+queue" and paused else 0
                    return (qscore+pscore,last[x],x)
                v=min(cached,key=priority)
                if policy!="lru" and pending[v]==0 and any(pending[c] for c in cached):
                    queue_protect_events+=1
                if policy=="pause+queue" and "A" in cached and v!="A" and clk<2+ttl:
                    pause_protect_events+=1
                cached.remove(v);evictions+=1
            cached.add(req)
        if req=="A": a_returned=True
        last[req]=order;order+=1;clk+=1
    return {"missed_tokens":missed_bytes,"misses":miss_count,"evictions":evictions,
            "queue_protect_events":queue_protect_events,"pause_protect_events":pause_protect_events}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--seeds",type=int,default=24)
    ap.add_argument("--episodes",type=int,default=300)
    ap.add_argument("--out",type=Path,required=True)
    ap.add_argument("--beta",type=float,default=0.5)
    args=ap.parse_args()
    rows=[]
    # Paused information may be accurate, uncertain, or stale.
    for scenario,p_return in [("likely_returns",0.95),("uncertain_returns",0.5),("rarely_returns",0.05)]:
        for nnoise in [2,4,6]:
            for ttl in [2,8,100]:
                for seed in range(args.seeds):
                    sums={p:Counter() for p in ("lru","queue","pause+queue")}
                    for idx in range(args.episodes):
                        arrivals,sizes=episode(seed,idx,p_return,noise_count=nnoise,tool_ttl=ttl)
                        for p in sums:
                            result=run_one(arrivals,sizes,p,ttl=ttl,beta=args.beta)
                            sums[p].update(result)
                    for p,stats in sums.items():
                        rows.append({"scenario":scenario,"p_return":p_return,"noise_count":nnoise,"tool_ttl":ttl,
                                     "seed":seed,"policy":p,**dict(stats)})
    args.out.parent.mkdir(parents=True,exist_ok=True)
    with args.out.open("w",newline="") as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    print(f"SIMULATION rows={len(rows)} seeds={args.seeds} episodes_per_seed={args.episodes} capacity={CAPACITY} token units")
    for scenario in ["likely_returns","uncertain_returns","rarely_returns"]:
        print(f"\n{scenario}: nnoise=4, tool_ttl=8:")
        sub=[r for r in rows if r["scenario"]==scenario and r["noise_count"]==4 and r["tool_ttl"]==8]
        base=statistics.mean(r["missed_tokens"] for r in sub if r["policy"]=="queue")
        for p in ("lru","queue","pause+queue"):
            rs=[r for r in sub if r["policy"]==p]
            mean=statistics.mean(r["missed_tokens"] for r in rs)
            print(f"  {p:14s} mean missed {mean:9.1f}, vs queue {(mean/base-1)*100:+6.2f}%")
    print("\nSENSITIVITY (pause+queue relative to queue; smaller is better)")
    for scenario in ["likely_returns","rarely_returns"]:
        print(" ",scenario)
        for ttl in [2,8,100]:
            parts=[]
            for nnoise in [2,4,6]:
                sub=[r for r in rows if r["scenario"]==scenario and r["noise_count"]==nnoise and r["tool_ttl"]==ttl]
                means={p:statistics.mean(r["missed_tokens"] for r in sub if r["policy"]==p) for p in ("queue","pause+queue")}
                parts.append(f"noise{nnoise}:{(means['pause+queue']/means['queue']-1)*100:+.2f}%")
            print(f"    ttl={ttl:3d} "+"  ".join(parts))
    print("CSV",args.out)

if __name__=="__main__":
    main()

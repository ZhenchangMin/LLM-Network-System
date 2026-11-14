#!/usr/bin/env python3
"""PEEK v23 offline evidence audit. READS existing traces; never modifies original inputs.
No counterfactual performance or safe admission is inferred from log snapshots.
"""
import collections
import hashlib
import json
import math
from pathlib import Path
import statistics
import sys

EXP = Path("/root/bayes-tmp/peek-c-group/experiment")
RESULTS = EXP / "results"
OUT = Path(__file__).resolve().parent
SPECS = [
    ("v17_peek_aa", "gpu_ablation_v17_seed1911_peek_aa", "no_chunk"),
    ("v17_trace_ab", "gpu_ablation_v17_seed1911_audit_v2", "no_chunk"),
    ("v21_native_shadow", "gpu_ablation_v21_seed1911_native_shadow", "chunk512"),
    ("v21_victim", "gpu_ablation_v21_seed1911_victim_ticket", "chunk512"),
    ("v22_cross_1911", "gpu_ablation_v22_seed1911_crosssection_chunk", "chunk512"),
    ("v22_cross_1711", "gpu_ablation_v22_seed1711_crosssection_chunk", "chunk512"),
    ("v22_quick_1911", "gpu_ablation_v22_seed1911_quickdemote_chunk", "chunk512"),
]
def quant(vals, p):
    z = sorted(float(x) for x in vals)
    if not z:
        return None
    x = (len(z)-1)*p/100
    a = int(x)
    return z[a]+(z[min(a+1,len(z)-1)]-z[a])*(x-a)

def checksum(p):
    h=hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda:f.read(65536),b""):
            h.update(chunk)
    return h.hexdigest()

def metrics_for(run):
    p=run/"metrics.json"
    d=json.loads(p.read_text())
    rows={int(x["req_id"]):x for x in d["per_request"] if int(x["req_id"])>=64 and not x.get("error")}
    if len(rows)!=512:
        raise ValueError(f"Expected exactly 512 scored: {run} =>{len(rows)}")
    return d,rows

def summary(rows):
    a=list(rows.values())
    t=[r["ttft_ms"] for r in a]
    return {"scored":len(a),"mean_ttft_ms":round(statistics.mean(t),3),
            "p95_ttft_ms":round(quant(t,95),3),"p99_ttft_ms":round(quant(t,99),3),
            "ttft_ge_2000":sum(v>=2000 for v in t)}

def pair_stats(a,b):
    assert a.keys()==b.keys()
    delta={k:float(b[k]["ttft_ms"])-float(a[k]["ttft_ms"]) for k in a}
    diffs=list(delta.values())
    cache_deltas=[int(b[k]["cached_tokens"])-int(a[k]["cached_tokens"]) for k in a]
    scored_high={k for k in a if int(a[k]["cached_tokens"])>=512}
    collapse={k for k in scored_high if int(b[k]["cached_tokens"])<32}
    return {
      "n_matched":len(delta),
      "paired_ttft_ms_delta_b_minus_a":{"mean":round(statistics.mean(diffs),3),
         "p05":round(quant(diffs,5),3),"p50":round(quant(diffs,50),3),
         "p95":round(quant(diffs,95),3)},
      "b_faster_by_500ms":sum(v<=-500 for v in diffs),
      "b_slower_by_500ms":sum(v>=500 for v in diffs),
      "b_faster_by_1000ms":sum(v<=-1000 for v in diffs),
      "b_slower_by_1000ms":sum(v>=1000 for v in diffs),
      "cache_token_delta_mean":round(statistics.mean(cache_deltas),3),
      "a_high_hit_512_count":len(scored_high),
      "a_high_hit_to_b_low_hit_32":len(collapse),
      "collapse_request_indices_sample":sorted(collapse)[:12],
      "top_10_b_hurt": [{"req_id":k,"delta_ttft_ms":round(v,3),
        "a_hit":int(a[k]["cached_tokens"]),"b_hit":int(b[k]["cached_tokens"])}
        for k,v in sorted(delta.items(),key=lambda x:-x[1])[:10]],
      "top_10_b_helped": [{"req_id":k,"delta_ttft_ms":round(v,3),
        "a_hit":int(a[k]["cached_tokens"]),"b_hit":int(b[k]["cached_tokens"])}
        for k,v in sorted(delta.items(),key=lambda x:x[1])[:10]]
    }

def trace_analysis(run, scored):
    files=sorted([x for x in (run/"runtime").glob("*audit*.jsonl") if x.stat().st_size>0])
    if not files:
        return {"has_trace":False,"reason":"No nonempty audit JSONL"}
    by_kind=collections.Counter(); fields=collections.defaultdict(set)
    sorts={}; prefills={}; evictions=[]; shadow=[]
    for file in files:
        for line in file.open():
            if not line.strip():continue
            try:d=json.loads(line)
            except Exception:continue
            k=d.get("kind","UNKNOWN");by_kind[k]+=1;fields[k].update(d)
            if k=="sort":sorts[d["sort_tick"]]=d
            elif k=="prefill_batch":prefills[d["sort_tick"]]=d
            elif k=="cache_evict":evictions.append(d)
            elif k=="shadow_native_validation":shadow.append(d)
    response_ids={x["response_id"] for x in scored.values()}
    src_rids={x["rid"] for v in sorts.values() for x in v["queue"]}
    admitted_rids={x["rid"] for v in prefills.values() for x in v["admitted"]}
    has_waiting=has_free=has_candidate=raw_sufficient=full_prefill_proxy_events=0
    candidates=collections.Counter();long_rids=set();raw_screen_rids=set(); full_prefill_proxy_rids=set()
    summary_rows=[]
    unmatched_sort=[tick for tick in sorts if tick not in prefills]
    for tick,s in sorted(sorts.items()):
        p=prefills.get(tick)
        if not p:
            continue
        adm={x["rid"] for x in p["admitted"]}
        q=[x for x in s["queue"] if x["rid"] not in adm]
        if q:has_waiting+=1
        if (p.get("free_kv_after") or 0)>0:has_free+=1
        if not q:continue
        has_candidate+=1
        raw_free=p.get("free_kv_after")
        for x in q:
            rid=x["rid"]
            if rid not in response_ids:continue
            candidates[rid]+=1
            r=next((v for v in scored.values() if v["response_id"]==rid),None)
            if r and r["ttft_ms"]>=2000:long_rids.add(rid)
            # Proxy only! main_hit is sort-time estimate and not guaranteed physical
            # prefix indices at potential alternative admission. No reservation/locks.
            naive_need=max(0,int(x["total_tokens"])-int(x["main_hit"]))
            if raw_free is not None and naive_need<raw_free:
                raw_sufficient+=1
                raw_screen_rids.add(rid)
                if naive_need<=512:
                    full_prefill_proxy_events+=1
                    full_prefill_proxy_rids.add(rid)
        if len(summary_rows)<200:
            summary_rows.append({"tick":tick,"sort_queue_count":len(s["queue"]),
                "admitted_count":len(adm),"not_admitted_in_sort":len(q),
                "free_kv_after_raw":raw_free,
                "evictable_after_raw":p.get("evictable_after"),
                "waiting_after":p.get("waiting_count_after")})
    scored_tails=sum(x["ttft_ms"]>=2000 for x in scored.values())
    return {
      "has_trace":True,"trace_files":[{"name":str(p.relative_to(RESULTS)),"bytes":p.stat().st_size,
                       "sha256":checksum(p)} for p in files],
      "event_counts":dict(by_kind),"fields":{k:sorted(v) for k,v in fields.items()},
      "sort_ticks_observed":len(sorts),"nonempty_prefill_ticks":len(prefills),
      "sort_ticks_no_prefill_record":len(unmatched_sort),
      "sort_tick_without_nonempty_prefill_sample":unmatched_sort[:10],
      "sort_unique_request_rids":len(src_rids),
      "sort_rid_scored_client_join":len(src_rids & response_ids),
      "admitted_rid_scored_client_join":len(admitted_rids & response_ids),
      "trace_extra_requests":len(src_rids-response_ids),
      "prefill_ticks_with_raw_free_kv_after_gt0":has_free,
      "prefill_ticks_with_unadmitted_sort_candidate":has_candidate,
      "prefill_ticks_with_nonempty_sort_suffix":has_waiting,
      "not_admitted_candidate_rid_occurrences":sum(candidates.values()),
      "distinct_scored_candidate_rids":len(candidates),
      "repeated_candidate_occurrences_excluding_first":sum(max(0,v-1) for v in candidates.values()),
      "candidate_ttft_ge2000_distinct":len(long_rids),
      "scored_ttft_ge2000":scored_tails,
      "raw_allocator_proxy_screen_events":raw_sufficient,
      "raw_allocator_proxy_screen_distinct":len(raw_screen_rids),
      "naive_complete_512_and_raw_free_proxy_events":full_prefill_proxy_events,
      "naive_complete_512_and_raw_free_proxy_rids":len(full_prefill_proxy_rids),
      "raw_free_proxy_not_safe_admission":True,
      "native_admission_slack_confirmed":None,
      "complete_prompt_prefill_confirmed":None,
      "zero_extra_eviction_confirmed":None,
      "future_kv_and_batch_time_confirmed":None,
      "eviction_events":len(evictions),
      "eviction_deleted_kv_tokens":sum(int(x.get("removed_kv_tokens") or 0) for x in evictions),
      "shadow_validation_events":len(shadow),
      "shadow_validation_matches":sum(v.get("exact_order_match") is True for v in shadow),
      "per_tick_illustrative_rows":summary_rows[:12]
    }

def main():
    inventory=[]; audited=[]; pairs=[]
    for key,dirname,cfgtype in SPECS:
        root=RESULTS/dirname
        meta=json.loads((root/"metadata"/"git_before.json").read_text())
        cmd_head=meta.get("head",{}).get("stdout","").strip()
        summary_per_run=[]
        full_rows={}
        for run in sorted((root/"runs").iterdir()):
            if not (run/"metrics.json").exists():continue
            met,scored=metrics_for(run)
            config=json.loads((run/"config.json").read_text())
            cmd=config.get("server_command",[])
            trace=trace_analysis(run,scored)
            rec={"case":key,"root":dirname,"name":run.name,"config_type":cfgtype,
                 "historical_head":cmd_head,"server_command":cmd,
                 "counts":met.get("counts"),"goodput_req_per_s":met.get("throughput",{}).get("goodput_req_per_s"),
                 "metrics":summary(scored),"trace":trace}
            summary_per_run.append(rec);audited.append(rec);full_rows[run.name]=scored
            inventory.append({"case":key,"run":run.name,
                 "metric_file":str((run/"metrics.json").relative_to(EXP)),
                 "metrics_sha256":checksum(run/"metrics.json"),
                 "has_trace":trace["has_trace"],"trace_event_counts":trace.get("event_counts",{}),
                 "head":cmd_head,
                 "native_chunk512":'--chunked-prefill-size' in cmd and '512' in cmd})
        # every named run comparison stays within the same run case and seed.
        names=list(full_rows)
        if key=="v17_peek_aa":
            pairs.append({"case":key,"comparison":"PEEK r1 -> PEEK r2 (A/A)",
                          "a":names[0],"b":names[1],
                          "data":pair_stats(full_rows[names[0]],full_rows[names[1]])})
        if key=="v17_trace_ab":
            pairs.append({"case":key,"comparison":"PEEK trace -> v16 trace (observational 2 arms)",
                          "a":names[0],"b":names[1],
                          "data":pair_stats(full_rows[names[0]],full_rows[names[1]])})
        if key in ("v21_victim","v22_cross_1911","v22_cross_1711","v22_quick_1911"):
            for x,y in [(0,1),(3,2)]:
                pairs.append({"case":key,"comparison":"PEEK matched vs Extension",
                  "a":names[x],"b":names[y],
                  "data":pair_stats(full_rows[names[x]],full_rows[names[y]])})
        if key=="v21_native_shadow":
            pairs.append({"case":key,"comparison":"PEEK shadow -> ticket shadow (not an A/A)",
                    "a":names[0],"b":names[1],
                    "data":pair_stats(full_rows[names[0]],full_rows[names[1]])})
    result={"analysis_type":"observational trace inventory; no causal counterfactual performance",
      "generated_utc":"2026-11-14","source_root":str(EXP),
      "cases":list(SPECS),"runs":audited,"pairs":pairs,
      "funnel_definition":[
       {"stage":"all_decisions","status":"partial_direct","reason":"sort events only after early gates; no every scheduling tick"},
       {"stage":"positive_remaining_budget","status":"not_observable","reason":"free_kv_after is raw pool, not remaining PrefillAdder budgets, mixed decode or reservation"},
       {"stage":"nonadmitted_candidate","status":"direct_for_nonempty_prefill_only","reason":"sort queue and admitted list via sort_tick"},
       {"stage":"preserve_native_and_admit","status":"not_observable","reason":"no stop cause, req chunks, snapshot/lock and native plan delta"},
       {"stage":"complete_prefill_same_tick","status":"proxy_only","reason":"sort main_hit/total token plus chunk512 cannot establish actual extend_input_len"},
       {"stage":"no_extra_eviction","status":"not_observable","reason":"posthoc eviction trace from original plan is not hypothetical append"},
       {"stage":"future_kv_and_time","status":"not_observable","reason":"running decode reservation and bounded execution-time model unavailable"}
      ]}
    (OUT/"V23_E1_MACHINE_RESULTS.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n")
    with (OUT/"V23_E1_INVENTORY.json").open("w") as f:
        json.dump(inventory,f,ensure_ascii=False,indent=2)
    with (OUT/"V23_E1_PAIRS.json").open("w") as f:
        json.dump(pairs,f,ensure_ascii=False,indent=2)
    print("DONE runs",len(audited),"pairs",len(pairs),"traced",sum(x["trace"]["has_trace"] for x in audited))
    for v in audited:
        q=v["trace"]
        if q["has_trace"]:
            print(v["case"],v["name"],"sort",q["sort_ticks_observed"],
              "nonempty",q["nonempty_prefill_ticks"],"noevent",q["sort_ticks_no_prefill_record"],
              "suffix ticks",q["prefill_ticks_with_unadmitted_sort_candidate"],
              "rid",q["distinct_scored_candidate_rids"],
              "repeats",q["repeated_candidate_occurrences_excluding_first"],
              "slow",q["candidate_ttft_ge2000_distinct"],
              "proxy",q["raw_allocator_proxy_screen_events"])
    for v in pairs:
        q=v["data"]
        print("PAIR",v["case"],v["a"][:12],v["b"][:12],
          "meanD",q["paired_ttft_ms_delta_b_minus_a"]["mean"],
          "better500",q["b_faster_by_500ms"],"worse500",q["b_slower_by_500ms"],
          "hitcollapse",q["a_high_hit_to_b_low_hit_32"])
if __name__=="__main__":main()

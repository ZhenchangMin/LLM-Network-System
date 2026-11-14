#!/usr/bin/env python3
"""Independent aggregation of B4 raw records; does not run inference."""
import argparse
import csv
import hashlib
import json
import math
import re
import statistics as st
from collections import Counter
from datetime import datetime,timedelta,timezone
from pathlib import Path

def load(path):return json.loads(Path(path).read_text(encoding='utf-8'))
def write(path,obj):Path(path).write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def pct(xs,p):return sorted(xs)[int(p*(len(xs)-1))] if xs else -1
def near(a,b):return math.isclose(a,b,rel_tol=1e-9,abs_tol=1e-6)
def mdtable(headers,rows):
    return '\n'.join(['| '+' | '.join(headers)+' |','|'+'|'.join(['---']*len(headers))+'|']+
                     ['| '+' | '.join(str(x) for x in row)+' |' for row in rows])

def recalc(d):
    rows=[r for r in d['per_request'] if r['req_id']>=32 and not r['error'] and r['ttft_ms']>0]
    if len(rows)!=224 or len(d['per_request'])!=256:raise AssertionError('Unexpected request count')
    tt=[r['ttft_ms'] for r in rows];e2=[r['total_ms'] for r in rows]
    prompts=sum(r['prompt_tokens'] for r in rows);cached=sum(r['cached_tokens'] for r in rows)
    for r in rows:
        assert 0<=r['cached_tokens']<=r['prompt_tokens']
        assert r['completion_tokens']<=64
    values={'ttft_mean_ms':st.fmean(tt),'ttft_p50_ms':pct(tt,.5),'ttft_p95_ms':pct(tt,.95),
            'ttft_p99_ms':pct(tt,.99),'e2e_mean_ms':st.fmean(e2),'e2e_p95_ms':pct(e2,.95),
            'throughput_req_s':len(rows)/d['wall_clock_s'],
            'cache_hit_pct':cached/prompts*100,'prefilled_tokens':prompts-cached,
            'cached_tokens':cached,'prompt_tokens':prompts,'completion_tokens':sum(r['completion_tokens'] for r in rows),
            'output_64_count':sum(r['completion_tokens']==64 for r in rows),
            'tpot_mean_ms':st.fmean((r['total_ms']-r['ttft_ms'])/(r['completion_tokens']-1) for r in rows if r['completion_tokens']>=2),
            'wall_clock_s':d['wall_clock_s'],'all_submitted_req_s':256/d['wall_clock_s'],
            'slo_attainment_pct':d['throughput']['slo_attainment_pct'],
            'inflight_max':d['concurrency']['max_in_flight'],'ok':224,'errored':d['counts']['errored']}
    expected={'ttft_mean_ms':d['ttft_ms']['mean'],'ttft_p95_ms':d['ttft_ms']['p95'],
              'ttft_p99_ms':d['ttft_ms']['p99'],'e2e_mean_ms':d['e2e_ms']['mean'],
              'throughput_req_s':d['throughput']['request_per_s'],
              'cache_hit_pct':d['cache']['hit_rate_pct'],'prefilled_tokens':d['cache']['prefilled_tokens_total'],
              'tpot_mean_ms':d['tpot_ms']['mean']}
    for key,val in expected.items():assert near(values[key],val),(key,values[key],val)
    return values,rows

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--root',required=True);args=parser.parse_args()
    root=Path(args.root).resolve();out=root/'analysis';out.mkdir(exist_ok=True)
    state=load(root/'STATUS.json')
    assert state['state'] in ['experiments_complete','complete'],state
    runs=[];failed=[];group_rows=[];tail_rows=[]
    for run in sorted((root/'runs').iterdir()):
        if not run.is_dir() or not (run/'state.json').exists():continue
        s=load(run/'state.json')
        if s['state']!='complete':failed.append({'directory':str(run),'state':s});continue
        config=load(run/'config.json');d=load(run/'metrics.json');v,raw=recalc(d)
        log=(run/'server.log').read_text(errors='replace')
        q=[int(x) for x in re.findall(r'#queue-req:\s*(\d+)',log)]
        usage=[float(x) for x in re.findall(r'token usage:\s*([0-9.]+)',log)]
        fatal=[line for line in log.splitlines() if any(s in line for s in
               ['CUDA out of memory','Traceback (most recent call last)','AssertionError:','RuntimeError:'])]
        hook='injected PeekDemandStrategy' in log
        row={'run_id':config['run_id'],'policy':config['policy'],'repeat':config['repeat'],
             'relative_directory':str(run.relative_to(root)),**v,
             'server_queue_max':max(q,default=0),'nonzero_queue_log_records':sum(x>0 for x in q),
             'token_usage_max':max(usage,default=0),'retract_log_records':log.count('Retract requests.'),
             'peek_eviction_hook_seen':hook,'fatal_log_signals':len(fatal),
             'phase_matched_rids':d['phases']['matched_rids'],
             'metrics_sha256':digest(run/'metrics.json')}
        row['ttft_max_ms']=max(q['ttft_ms'] for q in raw)
        row['ttft_over_2s_count']=sum(q['ttft_ms']>2000 for q in raw)
        row['ttft_over_2s_low_cache_count']=sum(q['ttft_ms']>2000 and q['cached_tokens']<50 for q in raw)
        for q in sorted(raw,key=lambda x:x['ttft_ms'],reverse=True)[:10]:
            tail_rows.append({'run_id':config['run_id'],'policy':config['policy'],'repeat':config['repeat'],
                 **{k:q[k] for k in ['req_id','group_id','ttft_ms','total_ms','cached_tokens','prompt_tokens','completion_tokens']},
                 'ttft_over_2s':q['ttft_ms']>2000})
        assert row['fatal_log_signals']==0,fatal
        assert hook==(config['policy']=='peek')
        assert load(run/'input_parity.json')['all_256_req_id_group_and_prompt_token_counts_match_historical_A3']
        assert row['server_queue_max']>0,'No observed waiting queue in '+row['run_id']
        info=load(run/'server_info_before.json');serverargs=info.get('server_args',info)
        if serverargs:
            assert serverargs['max_total_tokens']==8192
            assert serverargs['schedule_policy']=='lpm'
            assert serverargs['random_seed']==950056913
        row['server_args_confirmed']=bool(serverargs)
        monitor=[]
        for line in (run/'gpu_monitor.jsonl').read_text().splitlines():
            m=json.loads(line)
            if m.get('returncode')==0:
                try:
                    bits=m['stdout'].strip().split(',');monitor.append([float(bits[1]),float(bits[3])])
                except (ValueError,IndexError):pass
        row['gpu_memory_peak_mib']=max((x[0] for x in monitor),default=-1)
        row['gpu_utilization_peak_pct']=max((x[1] for x in monitor),default=-1)
        runs.append(row)
        for g in range(16):
            gr=[r for r in raw if r['group_id']==g]
            if gr:group_rows.append({'run_id':config['run_id'],'policy':config['policy'],'group':g,
                 'count':len(gr),'ttft_mean_ms':st.fmean(r['ttft_ms'] for r in gr),
                 'ttft_p95_ms':pct([r['ttft_ms'] for r in gr],.95),
                 'cache_hit_pct':100*sum(r['cached_tokens'] for r in gr)/sum(r['prompt_tokens'] for r in gr)})
    assert len(runs)==6,runs
    assert Counter(r['policy'] for r in runs)=={'vanilla':3,'peek':3}
    metric_keys=['ttft_mean_ms','ttft_p95_ms','ttft_p99_ms','e2e_mean_ms','throughput_req_s',
                 'cache_hit_pct','prefilled_tokens','tpot_mean_ms','slo_attainment_pct']
    summary={}
    for pol in ['vanilla','peek']:
        selected=[r for r in runs if r['policy']==pol];summary[pol]={}
        for key in metric_keys:
            xs=[r[key] for r in selected]
            summary[pol][key]={'median':st.median(xs),'mean':st.fmean(xs),'sample_sd':st.stdev(xs),
                               'min':min(xs),'max':max(xs),'n':len(xs)}
    comparison={}
    for key in metric_keys:
        v=summary['vanilla'][key]['median'];p=summary['peek'][key]['median']
        comparison[key]={'vanilla_median':v,'peek_median':p,'peek_minus_vanilla':p-v,
                         'peek_change_pct':100*(p/v-1) if v else None,
                         'vanilla_over_peek':v/p if p else None}
    historical,recs=recalc(load(root/'inputs/historical_a3.json'))
    primary=min((r for r in runs if r['policy']=='peek'),key=lambda r:r['repeat'])
    paired=[]
    for rep in [1,2,3]:
        v=next(r for r in runs if r['policy']=='vanilla' and r['repeat']==rep)
        p=next(r for r in runs if r['policy']=='peek' and r['repeat']==rep)
        paired.append({'repeat':rep,'ttft_reduction_pct':100*(1-p['ttft_mean_ms']/v['ttft_mean_ms']),
                       'throughput_change_pct':100*(p['throughput_req_s']/v['throughput_req_s']-1),
                       'cache_hit_change_pp':p['cache_hit_pct']-v['cache_hit_pct']})
    protected=load(root/'metadata/protected_after.json')
    assert protected['all_original_protected_files_unchanged'],protected
    checks={'six_formal_runs_complete':len(runs)==6,
            'all_1344_measured_requests_successful':sum(r['ok'] for r in runs)==1344,
            'all_1536_submitted_records_saved':all(len(load(root/r['relative_directory']/'metrics.json')['per_request'])==256 for r in runs),
            'all_1536_submitted_requests_successful':all(not q['error'] and q['ttft_ms']>0 for r in runs for q in load(root/r['relative_directory']/'metrics.json')['per_request']),
            'all_metrics_recomputed_from_raw_records':True,'all_workloads_match_historical_A3':True,
            'all_runs_have_observed_nonzero_waiting_queue':all(r['server_queue_max']>0 for r in runs),
            'all_peek_runs_show_hook_and_strategy_injection':all(r['peek_eviction_hook_seen'] for r in runs if r['policy']=='peek'),
            'no_vanilla_run_shows_peek_injection':all(not r['peek_eviction_hook_seen'] for r in runs if r['policy']=='vanilla'),
            'no_extra_debug_flags_enabled':all(not any(str(v).lower() in ['1','true','yes','on'] for k,v in load(root/r['relative_directory']/'config.json')['environment'].items() if k in ['PEEK_ONLINE_PROFILE','PEEK_ONLINE_VALIDATE','PEEK_ONLINE_EVICTION_DEBUG','PEEK_ONLINE_VALIDATE_LPM_ORDER']) for r in runs),
            'all_226_original_protected_files_unchanged':protected['all_original_protected_files_unchanged'],
            'all_formal_runs_have_no_fatal_log_signals':all(r['fatal_log_signals']==0 for r in runs)}
    assert all(checks.values()),checks
    write(out/'acceptance.json',checks)
    write(out/'per_run_summary.json',runs);write(out/'aggregate.json',summary)
    write(out/'comparison.json',comparison);write(out/'paired_repeats.json',paired)
    write(out/'failed_attempts.json',failed)
    write(out/'historical_comparison.json',{'historical_a3':historical,'primary_peek':primary,
        'ttft_reduction_pct':100*(1-primary['ttft_mean_ms']/historical['ttft_mean_ms']),
        'throughput_change_pct':100*(primary['throughput_req_s']/historical['throughput_req_s']-1),
        'cache_hit_change_pp':primary['cache_hit_pct']-historical['cache_hit_pct']})
    tail_audit={p:{'measured_observations':672,
        'ttft_over_2s':sum(r['ttft_over_2s_count'] for r in runs if r['policy']==p),
        'ttft_over_2s_with_cached_tokens_lt50':sum(r['ttft_over_2s_low_cache_count'] for r in runs if r['policy']==p)} for p in ['vanilla','peek']}
    write(out/'tail_audit.json',tail_audit)
    for name,rows in [('per_run_summary.csv',runs),('per_group_summary.csv',group_rows),('paired_repeats.csv',paired),('tail_requests.csv',tail_rows)]:
        with (out/name).open('w',encoding='utf-8',newline='') as f:
            w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    tab=mdtable(['轮次','策略','TTFT均值(ms)','TTFT P95(ms)','E2E均值(ms)','吞吐(req/s)','命中率(%)','Prefill tokens','队列峰值','Retract日志'],
        [[r['repeat'],r['policy'],f"{r['ttft_mean_ms']:.3f}",f"{r['ttft_p95_ms']:.3f}",f"{r['e2e_mean_ms']:.3f}",
          f"{r['throughput_req_s']:.4f}",f"{r['cache_hit_pct']:.4f}",r['prefilled_tokens'],r['server_queue_max'],r['retract_log_records']] for r in runs])
    labels={'ttft_mean_ms':'Mean TTFT (ms)','ttft_p95_ms':'P95 TTFT (ms)','ttft_p99_ms':'P99 TTFT (ms)',
            'e2e_mean_ms':'Mean E2E (ms)','throughput_req_s':'Throughput (req/s)','cache_hit_pct':'Cache hit (%)',
            'prefilled_tokens':'Prefilled tokens','tpot_mean_ms':'Mean TPOT (ms)','slo_attainment_pct':'SLO attainment (%)'}
    agg=mdtable(['指标','Vanilla 中位数','PEEK 中位数','PEEK变化'],[[labels[k],f"{v['vanilla_median']:.4f}",f"{v['peek_median']:.4f}",
        (f"{v['peek_minus_vanilla']:+.4f} pp" if k in ['cache_hit_pct','slo_attainment_pct'] else f"{v['peek_change_pct']:+.2f}%")] for k,v in comparison.items()])
    sdtab=mdtable(['指标','Vanilla mean ± sample SD','PEEK mean ± sample SD'],[[labels[k],
         f"{summary['vanilla'][k]['mean']:.3f} ± {summary['vanilla'][k]['sample_sd']:.3f}",
         f"{summary['peek'][k]['mean']:.3f} ± {summary['peek'][k]['sample_sd']:.3f}"] for k in metric_keys])
    tailtab=mdtable(['轮次','策略','P99 TTFT(ms)','最大TTFT(ms)','TTFT>2s请求数','SLO达标率(%)'],
         [[r['repeat'],r['policy'],f"{r['ttft_p99_ms']:.3f}",f"{r['ttft_max_ms']:.3f}",
           r['ttft_over_2s_count'],f"{r['slo_attainment_pct']:.4f}"] for r in runs])
    latency=100*(1-comparison['ttft_mean_ms']['peek_median']/comparison['ttft_mean_ms']['vanilla_median'])
    throughput=comparison['throughput_req_s']['peek_change_pct']
    cache=comparison['cache_hit_pct']['peek_minus_vanilla']
    e2e_reduction=-comparison['e2e_mean_ms']['peek_change_pct']
    p99_change=comparison['ttft_p99_ms']['peek_change_pct']
    slo_change=comparison['slo_attainment_pct']['peek_minus_vanilla']
    workload=load(root/'inputs/workload.json')
    last_arrival=max(q['arrival_time_s'] for q in workload)
    interpretation=(f"计划中最后一个请求在 t={last_arrival:.3f}s 到达；本实验是有限长度开放式Poisson请求流，吞吐还受发送节奏与末尾排空影响。"
        f"实际服务端队列峰值：Vanilla最大 {max(r['server_queue_max'] for r in runs if r['policy']=='vanilla')}，"
        f"PEEK最大 {max(r['server_queue_max'] for r in runs if r['policy']=='peek')}，不能用总请求数256代替同时排队数量。"
        f"缓存命中率中位数的变化为 {cache:+.4f}pp，应与延迟和Prefill token变化一起解释；仅凭延迟下降不能断言全部来自额外缓存命中。")
    conclusion=(f"在本次固定 W1-Lite 负载的三次同seed重复中，按组内中位数比较，PEEK 的平均 TTFT "
                f"{'降低' if latency>=0 else '升高'} {abs(latency):.2f}%，平均 E2E "
                f"{'降低' if e2e_reduction>=0 else '升高'} {abs(e2e_reduction):.2f}%，吞吐 "
                f"{'提高' if throughput>=0 else '降低'} {abs(throughput):.2f}%，缓存命中率变化 {cache:+.4f} 个百分点。"
                f"同时，P99 TTFT {'升高' if p99_change>=0 else '降低'} {abs(p99_change):.2f}%，SLO达标率变化 {slo_change:+.4f} 个百分点；平均延迟收益伴随尾部退化。")
    report=f'''# B4 正式交付：PEEK Online W1-Lite

生成时间：{datetime.now(timezone(timedelta(hours=8))).isoformat()}。

## 1. 结论与完成状态

B4 已完成同条件正式对照、逐请求结果保存、三次重复及独立重算。{conclusion}

该结论仅适用于当前 3B/4090D/8K KV/固定seed=42 的 Lite 负载，不能等同于论文多工作负载、多seed的收益，也不宣称已获得统计显著性。所有轮次均披露，没有按结果挑选最好的一轮。

## 2. 冻结条件与公平性

- Qwen2.5-3B-Instruct，BF16，TP=1，RTX 4090 D，SGLang 0.5.9，KV=8192 tokens，mem_fraction_static=0.75。
- 同一份本地LooGLE与字节不变的A组客户端快照；全部256个请求的req_id、group_id和prompt_tokens逐条与历史A3一致。
- N=256，按req_id去掉前32个warmup；计量224；G=16，prefix≈1024，Zipf alpha=1，Poisson 20 req/s，concurrency=64，max_output=64，client seed=42。
- 服务端seed=950056913，取历史A3实际日志值。此处显式固定seed，其他关键服务参数与A/B既有配置一致。
- Vanilla使用A环境，PEEK使用B环境；所有客户端均使用A环境。Python补丁版本A=3.12.16、B=3.12.4；关键依赖版本和已核查的SGLang核心文件一致。这不是完全消除环境差异的同进程消融实验。
- 顺序预登记为ABBAAB：Vanilla1/PEEK1/PEEK2/Vanilla2/Vanilla3/PEEK3。每轮新服务、新KV缓存，单GPU顺序执行。
- 额外Profile/Validate/Eviction Debug关闭；PEEK原实现默认phase tracking仍保留，未修改官方核心实现。
- 输入、版本、运行前计划分别见 `../inputs/`、`../metadata/versions.json` 和 `../metadata/plan.json`。

## 3. 全部正式运行结果

{tab}

每轮含256条原始请求记录；六轮共1536条，计量请求共1344条，全部成功。队列峰值来自服务端日志，不是客户端in-flight。

## 4. 三次重复汇总

{agg}

指标均先按每轮客户端公式计算，再取三轮中位数；没有把多轮请求合并成一个假想长实验。

{sdtab}

三次重复仅用于观察同一到达计划下的运行波动，不能当成三个独立数据seed。配对结果见 `paired_repeats.csv`。

{interpretation}

### 尾延迟审计

{tailtab}

三轮PEEK计量观测共672条，其中TTFT>2s为{tail_audit['peek']['ttft_over_2s']}条，全部{tail_audit['peek']['ttft_over_2s_with_cached_tokens_lt50']}条的cached_tokens<50；Vanilla相应为{tail_audit['vanilla']['ttft_over_2s']}条，其中{tail_audit['vanilla']['ttft_over_2s_with_cached_tokens_lt50']}条cached_tokens<50。PEEK慢请求多为几乎没有缓存命中的请求，与局部性优先调度存在取舍的解释一致，但本轮没有用排序前后记录或组件消融证明具体因果。

逐轮最慢10个请求保存于 `tail_requests.csv`，完整记录仍在各轮metrics.json。224个计量样本按原定义的P99实际上是第4大的值，对少量慢请求敏感；保留该退化事实，不将3次同seed重复包装成稳定的多seed尾部保证。

## 5. 与既有A3交付的直接对应

历史A3：Mean TTFT={historical['ttft_mean_ms']:.3f}ms，P95={historical['ttft_p95_ms']:.3f}ms，E2E={historical['e2e_mean_ms']:.3f}ms，吞吐={historical['throughput_req_s']:.4f}req/s，命中率={historical['cache_hit_pct']:.4f}%。

预先指定的第一轮PEEK（primary）：`{primary['relative_directory']}`；Mean TTFT={primary['ttft_mean_ms']:.3f}ms，P95={primary['ttft_p95_ms']:.3f}ms，E2E={primary['e2e_mean_ms']:.3f}ms，吞吐={primary['throughput_req_s']:.4f}req/s，命中率={primary['cache_hit_pct']:.4f}%。

历史A3和primary的完整比较见 `historical_comparison.json`。历史结果没有覆盖或重新命名；新增Vanilla重复只是本次B4中的当前时段参照。

## 6. 指标口径与解释限制

- 原客户端吞吐=224个成功计量请求/包含warmup和排空的全程wall time。它不是最大饱和吞吐；本次同时导出256/wall time作为另一列，禁止混用。
- Cache hit=sum(cached_tokens)/sum(prompt_tokens)，只计量warmup后的成功请求；不是请求命中率。
- P95/P99使用原客户端的排序后floor索引定义，独立重算沿用同口径。
- phase字段缺少样本时为不可用，不能解释为零等待。B4主要对照使用客户端TTFT/E2E；现有默认phase数据仅作为辅助，不能把pick→first-token称为纯GPU prefill kernel时间。
- Retract是日志事件数，不是去重请求数。GPU监控峰值覆盖整个服务生命周期，并非仅计时窗口。
- 没有为每次Eviction增加高开销跟踪，因此本轮不能给出精确释放token总数或完整淘汰顺序；B3已有功能证据与本次性能计量分别归档。
- 当前结果未包含官方全消融、多个工作负载seed、输出文本准确率评测、硬公平性证明或论文H100规模复现。
- 各轮实际completion tokens与达到64-token上限的请求数已导出，模型生成长度存在少量波动；没有将API成功等同于输出文本完全一致。

## 7. 失败记录与新增内容

保留失败attempt数量：{len(failed)}。详见 `failed_attempts.json` 和 `../RUN_LOG.md`。正式统计仅使用state=complete的预定轮次，没有将启动失败当作性能失败，也没有删除错误日志。

首次启动在压测前遇到ZMQ Unix IPC路径长度限制；v2只将TMPDIR缩短到本B4根目录内的runtime/ipc。随后PEEK服务实际已启用，但runner错误地查找calc_priority日志文本而非installed scheduler，被核验器在计时前误拒绝；v3修正该日志关键字。保留全部脚本和失败attempt；模型、工作负载和算法没有因此改变。

新增内容分类见 `../ADDED_CONTENTS.md`；每次准确命令与环境在各轮config.json中；所有结果均位于本B4专属子目录，B3原地址保持有效。

## 8. 验收与保护检查

独立重算已核对请求数、TTFT/E2E/TPOT、缓存token与吞吐。验收项见 `acceptance.json`。

已有文件保护清单计 {protected['original_file_count']} 个；检查结果：原有受保护文件全部未变。见 `../metadata/protected_before.json` 与 `protected_after.json`。这项检查覆盖既有Git文件、B组交付文件、A组工作文件、冻结数据及模型小配置，不包括对整个Linux环境/全盘逐字节审计。

服务仅停止本次runner创建的进程组；不会以进程名批量停止其他成员服务。

## 9. 交付入口

- 本报告：`analysis/B4_REPORT.md`。
- 一览表：`per_run_summary.csv`；机器可读比较：`comparison.json`、`aggregate.json`。
- 每组前缀统计：`per_group_summary.csv`，用于查看热门组/冷门组差异，不据少量组内样本推导严格公平保证。
- 原始结果、日志、GPU监控、server info与配置：`../runs/`。
- 冻结输入与历史参照：`../inputs/`。
- 脚本与过程记录：`../scripts/`、`../events.jsonl`、`../RUN_LOG.md`。
'''
    (out/'B4_REPORT.md').write_text(report,encoding='utf-8')
    print(conclusion)
    print(tab)
    print('ACCEPTANCE',json.dumps(checks,ensure_ascii=False))
    return 0

if __name__=='__main__':raise SystemExit(main())

# V23_TRACE_COVERAGE — E0 原始数据、版本一致性及字段缺口

2026-11-14；所有数据在 rental-sglang 上只读打开。机器可读明细见 `V23_E1_INVENTORY.json` / `V23_E1_MACHINE_RESULTS.json`。完整复核命令：`python3 audit_v23_e1.py`（CPU、标准库、仅读文件，重生成本目录 JSON）。

## 1. 历史配置与真实文件清单

| 组 | 远端根目录（均相对 experiment/results/） | 运行臂 | Prefill 配置 | 可用日志 |
|---|---|---:|---|---|
| v17 原 PEEK A/A | `gpu_ablation_v17_seed1911_peek_aa` | 2 | **未开 Chunk512** | 2 个非空 `runtime/peek_audit_*.jsonl` |
| v17 PEEK / v16 audit | `gpu_ablation_v17_seed1911_audit_v2` | 2 | **未开 Chunk512** | 2 个非空 `peek_audit` |
| v21 native-shadow | `gpu_ablation_v21_seed1911_native_shadow` | 2 | **开了 Chunk512 + mixed** | 2 个非空 `peek_audit`，其中包含 Shadow |
| v21 victim-ticket | `gpu_ablation_v21_seed1911_victim_ticket` | 4 | Chunk512 + mixed | `metrics.json`、server/client log，无 `peek_audit` |
| v22 cross-section seed1911 | `gpu_ablation_v22_seed1911_crosssection_chunk` | 4 | Chunk512 + mixed | metrics/server/client，无 `peek_audit` |
| v22 cross-section seed1711 | `gpu_ablation_v22_seed1711_crosssection_chunk` | 4 | Chunk512 + mixed | metrics/server/client，无 `peek_audit` |
| v22 quickdemote seed1911 | `gpu_ablation_v22_seed1911_quickdemote_chunk` | 4 | Chunk512 + mixed | metrics/server/client，无 `peek_audit` |

**总计 22 个成功历史运行臂，其中 6 臂具有 v17-style request/sort/evict tracing。** 仅 v21 native-shadow 一组提供 Chunk512 的逐 tick 源数据，**而且 seed 都是 1911**。因此不能把 No-Chunk 的 v17 A/A 直接当成固定 Chunk512 路线的充分代表，也没有独立 seed 的逐 tick 机会证明。

逐臂原始数据：`runs/<arm>/metrics.json`、`config.json`、`hook_validation.json`、`server.log`、`client.log`、`runtime/`，组元信息 `metadata/git_before.json`、`versions.json`、`plan.json`、`protected_before.json` / `protected_after.json`。

已直接从 7 组历史 `metadata/git_before.json` 核查原始 PEEK 版本都是 `6fbf2205f1c8bc6fe55746d75860e23779b003a2`；本机 tracked diff 为空，但 B 组有未跟踪文件，这不等于可任意修改该目录。主要模型均为 Qwen2.5-3B BF16、KV 8192、LooGLE64组 / 12 RPS / 64并发、每臂 64 warmup +512 scored，但 **审计组的 Chunk 配置、Hook 代码和时间探针不同**，必须按组分别比较。

## 2. 实际事件字段覆盖

审计源码：`extension_candidates/v17_audit/python/peek/online/engines/sglang/patch_hook.py:703–768,1202–1230`。

| 事件/位置 | 已有字段 | 能证明什么 | 无法证明什么 |
|---|---|---|---|
| `sort`（在 calc_priority 后） | `sort_tick,queue[{rid,rank,main_hit,prefix128,total_tokens}],proposal_rid,t` | 当时的排序、排队 RID、Sort-Time Cache Hit 代理 | 真实未来尝试次数、锁后的实际命中、原生结束/拒绝原因 |
| `prefill_batch`（**仅有实际非空入批时**） | `sort_tick,admitted[{rid,sort,proposal,hit_at_admission,prefix128,prompt_tokens}], admitted_count, waiting_count_before/after, free_kv_before/after, evictable_before/after,t` | 该 tick 中成功由 waiting→batch 的 RID；原生计划结束后的可用/可驱逐池快照 | 失败尝试、实际剩余 `rem_input_tokens/rem_chunk_tokens/rem_total_tokens`、Slot、Chunk 长度、真实 stop reason |
| `cache_evict` | `sort_tick,requested_tokens,removed_nodes[{prefix_len,prefix128,kv_len}],removed_kv_tokens,free_kv_before/after,evictable_before/after,t` | 原始轨迹真实删除的缓存节点和其时序 | 假设追加另一请求后会删哪些 KV；后续未来回访与资源损害 |
| `shadow_native_validation`（v21） | `sort_tick,requested_tokens,predicted_nodes,actual_nodes,exact_order_match,prediction_error,t` | **在真实 eviction 时刻** Native Shadow 与原生 Eviction 的一致性 | 更早组批时刻的预测一致性，或精确的未来 Admission 可行性 |
| `metrics.json/per_request` | `req_id,group_id,ttft_ms,total_ms,prompt_tokens,completion_tokens,cached_tokens,dispatch_ts,first_token_ts,last_token_ts,response_id,error` | 计分 RID 对齐、TTFT/cache 分布和 A/A/ABBA 请求级影响 | 可无影响追加的原生余量、server 内部剩余预算、可用的在线未来信息 |

RID 连接经过实测：v17 A/A 第一臂在 `sort` 的 578 个独立 RID 中，**576 个与客户端 576 个 response_id 匹配**；额外 2 个是服务探针/健康检查请求。分析严格采用 `req_id>=64` 的 512 scored，请求级配对按同一冻结请求索引 `req_id`；不把跨运行不同的 server response_id 当成相同 ID，也不把重复 sort tick 算独立请求。

部分运行还包含 `gpu_monitor.jsonl`，它是稀疏 GPU 使用率采样，不能替代 PrefillAdder tick 内部预算。v17 审计最初为了避免每 tick 空事件日志爆量，**只有 actually_admitted 非空才 emit prefill_batch**（`patch_hook.py:726`）。即便 sort 事件存在、没有对应 prefill_batch，也不能准确知道是返回 None、Chunk/Slot/budget 约束、probe drop 或别的分支。

## 3. E1 所需字段逐项判定

| 机会漏斗/约束 | 当前状态 | 原因 |
|---|---|---|
| 每个真实调度决策（包括 early return） | **不完整** | `sort` 在早期守卫之后，早退事件缺失 |
| 原生一次排序后真正选了哪些请求 | **部分直接** | 有 `prefill_batch.admitted`，但没有逐请求 Chunk token 数和全部尝试 |
| 是否仍有未入批候选 | **部分直接** | 仅非空 Prefill tick 的 `sort.queue - admitted`；空 batch 的末端候选无法确认完整流程 |
| Prefill/Chunk 剩余额度 | **缺失** | `PrefillAdder.rem_input_tokens/rem_chunk_tokens` 未写出 |
| KV 全局预算/Decode 预留 | **缺失** | 只有 allocator free/evictable 前后，不含 `rem_total_token_offset/cur_rem_token_offset,new_token_ratio` |
| Request slot / running batch 和 PP | **缺失** | 未记录 `get_num_allocatable_reqs` 最终值、retry/preempt/retract |
| 首个失败候选及精确拒绝原因 | **缺失** | `AddReqResult`、退出原因、已尝试数和最后一个检查 RID 未记录 |
| 原始已选请求的实际 chunk/continuation | **缺失** | admitted 仅有 prompt_tokens，不等于本 tick extend_input_len |
| 可追加候选完成完整 Prefill | **只能粗代理** | Sort-Time `main_hit` 与 `total_tokens` 无法保证是最后的 `extend_input_len` |
| 不增加当下 eviction | **无法判断反事实** | 需要同一原生状态的只读模拟和 native 保存，不能看原轨迹后的 evict 次数代替 |
| 后续 KV 占用/Batch 时间 | **缺失/需模型** | 缺去重后的 decode reservation、后续时序、calibrated batch-time model |

## 4. 原始实验统计与字段可信度原则

- `prefill_batch.free_kv_after>0` 表示 allocator 当前还有原始空闲格；**并不意味着 PrefillAdder 仍有 token budget**，更不意味着可以追加 512 Token Prefill。
- `sort` 中 `main_hit` 是排序时推断，与真正 `hit_at_admission` 可能存在时差；不能偷换为安全的缓存匹配/资源需求。
- 请求在多次 tick 中等待是正常现象，按 `rid` 去重；同一运行内 512 条请求会相互影响，不能把它们视为 512 次独立实验。
- `sort` 没有相应 `prefill_batch` 不能标注为“浪费了一次 Batch”；早期 return 等不可见，而且不会观测全部真实调度 tick。
- 原始日志中的晚到/未来回访、完成输出长度只能离线解释；不能用于未来在线策略。
- 目录中的 `V23_E1_MACHINE_RESULTS.json` 保存所有 22 臂的证据计数、字段列表、抽样 sort_tick、源日志 SHA256；旧数据未修改。

**E0/E1 数据结论**：现有日志足以证明“原生提前结束扫描的代码路径”并量化剩余候选暴露、A/A 背景变异，但不能独立给出完整可行性漏斗。必须作 **Need instrumentation** 判断，而不是把缺失等同于没有机会。

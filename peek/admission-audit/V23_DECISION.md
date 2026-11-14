# V23_DECISION — 修订版（探针 CPU 阶段，未运行 GPU）

> **2026-11-14 15:15 修订**：以下修订优先于本文件原 E0/E1 初稿的 GPU 探针草案；后面历史版本保留作为证据，不应引用其过于简化的返回值/止损语义。

## 2026-11-14 15:15 修订：探针语义与判断标准

### I. OTHER / NO_TOKEN 不等于拒绝

采用 **调用前后 can_run_list 身份差**、本次 RID 是否真的加入、`new_chunked_req is req` 和 `req.extend_input_len` 变化作为实际接纳与 continuation 的依据，且应记录 `AddReqResult`。同一个返回值允许两种相反情况。真实源码 `schedule_policy.py`：

| 函数/行号 | 返回原因 | 当前 RID 是否可能已加入 | 范围 |
|---|---|---|---|
| `budget_state():494–508` | rem_total/cur_rem <=0 -> NO_TOKEN；rem_input/rem_chunk <=0 -> OTHER | **是**（若前面已 append） | **接纳后**预算耗尽，后继扫描停止 |
| `add_one_req():725–729` | NSA/context-parallel 或 `prefill_max_requests` 限额 -> OTHER | 否 | 本次未接纳；当前 slot/模式限制 |
| `add_one_req():734–745` | 当前 input+输出声明上界 >= rem_total -> NO_TOKEN | 否 | 候选大小相关，较小后继**可能**适配 |
| `add_one_req():747–748` | 当前 real_input >= rem_input 且已有入批 -> OTHER | 否 | 候选大小相关，可能有较小后继 |
| `add_one_req():750–753` | 暂时锁住前缀后 total 容量二次检查 -> NO_TOKEN | 否 | 候选大小相关；锁可能减少 evictable |
| `add_one_req():755–767` | host load 后实际 input >= rem_input 且已有入批 -> OTHER | 否 | 候选大小相关；主机加载可能改变命中与需求 |
| `add_one_req():769–778` | prefill-delayer 或 DLLM budget -> OTHER | 否 | 策略/当前模式约束，需记录实际状态 |
| `add_one_req():786–827` | 完整 Prefill **append** 后调用 `budget_state()` 返回 OTHER/NO_TOKEN | **是** | 本次接纳，停止后续扫描 |
| `add_one_req():799–825` | chunk 对齐无法形成有效 Chunk -> OTHER，或创建 continuation 后 `budget_state()` 结束 | 分别否 / **是（含 continuation）** | 必须读实际状态差 |
| `add_one_req_ignore_eos():632–717` | early capacity / reserve -> NO_TOKEN；成功 append 后 budget_state 可 OTHER/NO_TOKEN | 分别否 / **是** | ignore_eos 独立安全语义 |
| `add_chunked_req():591–616` | 已存在 continuation 优先追加，不返回 AddReqResult | **是** | 保护已有 continuation，不能重复检查为新候选 |

以上是源码分支表；某些分支的 `return` 发生在状态修改之后（例如 host load，虽然 RID 没加入），所以探针**只能观察，不能在同一状态重试准入**。逐分支 `reason` 是只读标记，不能改变原 `return`、已有锁、预算计算。对于崩溃、异常、外部状态不匹配，只输出 unknown/failed-observe，绝不能据此声称已接纳。

### II. 候选相关约束 ≠ 全局不可行

全局禁止追加的条件需通过**真实原生快照**验证，包括 slot 容量为 0（且没有可保留原计划的安全 preemption）、Chunk 预算已归零、`rem_input_tokens` 全部耗尽、全部可用 KV 包括可驱逐部分与 decode 预留之后为 0、特殊模式要求一次仅一个请求。相对地 **某一请求 total tokens 太大**、`real_input_tokens` 太大或锁后二次校验失败，只能解释该候选失败；更小/不同前缀候选仍可能可行，必须保留这种可能性。stop reason 采用 `candidate_specific`、`global_constraint`、`policy_or_mode`、`accepted_then_stop`、`unknown` 的层级标签，**不能只凭 OTHER/NO_TOKEN 归类为不可继续**。

### III. 未尝试请求需求的纯读取边界

`Req.init_next_round_input`（`schedule_batch.py`）具有 Req 状态变化；`RadixCache.match_prefix` (`radix_cache.py:352–388`) 会更新时间戳、拆分树节点，**并非纯查询**。因此未尝试候选的精确 cache-hit、`extend_input_len`、锁后的可驱逐集合不能通过这两个接口在真实服务中探测；若 `prefix_indices` 已被本次排序填充，可把其长度记录为“**预排序近似值**”而不能作为完整保守 admission guard；空字段或被 Lazy Match 跳过则置 `unknown`。当前验证没有发现能替代完整 `init_next_round_input` 的已确认只读原生接口。后续如需估算，必须独立构造 `Req` / Radix/KV/锁/Batch 状态的 CPU 快照模拟器，使用原生实际准入前后日志测试其一致性，拒绝在真实服务上第二次调用任何变更方法。

### IV. 全 tick 轻量计数、详细记录有界

每次尝试组批的进入、所有 early exit、所有 `add_one_req` 返回，以及已接纳后停止都走**固定字段计数**；详细候选队列和预算快照可以有界采样，但必须记录 `ticks_seen / ticks_detail / events_emitted / events_dropped / detail_truncated / errors` 等覆盖信息以及后续日志溢出。`max_detail_ticks=1000`、`max_candidate_rows=16` 只控制**详细样本量**，后续仍累计轻量 counters，不能用前 1000 个 tick 或 top16 没看到机会，声称全负载没有机会。日志写入错误、序列化错误、对象异常只能计入探针失误；原生服务控制流不改变。

### V. CPU 差分验收

在**完全相同的 Req/Pool/Cache/Adder 初始 CPU 状态**下对未插桩源码与隔离插桩源码分别单次运行，比较：返回枚举、`can_run_list` 和 continuation、Req 已改字段、累计预算、前缀锁及 allocator、队列内容。测试覆盖“接纳后 STOP”、“拒绝”、“锁后复检”、“已有 chunk continuation”、“slot/queue early-return”、“详情溢出”、“探针关”和“日志失败”；所有成功差分必须完全一致。CPU fake 只验证探针非侵入性，不证明真实 SGLang 在 GPU/异步执行下也完全无扰动。

---
# V23_DECISION — E0/E1 研究判定与最小后续行动

日期：2026-11-14。**判定：B — Need instrumentation（现有证据不足）。不是 A/Go，也不是 C/Stop。**

## 1. 已完成且可核验的事实

- E0：远端当前 PEEK HEAD 与历史提交 `6fbf2205f1c8bc6fe55746d75860e23779b003a2` 一致；核对了真实运行中的 SGLang wheel 与 PEEK Hook 源码、原生 PrefillAdder、ScheduleBatch、v21 Native Shadow，给出准确函数/行号。原始 PEEK 的 tracked diff 为空，保留 B 组 untracked 文件不动。
- E1：编写 CPU-only `audit_v23_e1.py`，扫描 22 个历史成功臂、6 个逐 tick 审计臂，生成三份机器可读 JSON；v17 A/A、v17 Trace AB、v21、v22 的相同请求索引配对形成 11 组请求级比较。
- 原生组批可在遇到 `AddReqResult.OTHER` 或 `NO_TOKEN` 时直接 `break`（`scheduler.py:2052–2114`）；这与“所有更后面的更小候选都已被测试过”不同。部分特定外部条件（如 LoRA/HiCache）会 `continue`。
- 但 **“更后面候选可安全完成完整 Prefill 并且不增加 Eviction”** 未被证明。历史 tick 记录只有 raw free KV，没有 rem_input/rem_chunk/rem_total、原因、slot、running decode reservation、actual input_len 和完整延迟模型。
- v21 Shadow 的 1253/1253 正确性只适用于实际 Eviction 时刻，不保证在更早 Prefill Admission 时刻可用。
- v17 A/A 自身发生 22 例高命中→低命中坍塌、显著 TTFT 波动；v21/v22 多轮 cold 提优的 warm 受害与 Goodput 损失均值得保留为机制风险证据。不能通过 `30−22` 定义净因果损失。

**结论：首选 Admission-Slack 假设目前值得做一次有界、只读的可观测性确认，不值得直接部署候选调度算法。**

## 2. 为什么既不判 A，也不判 C

**不能判 A**：已有 441 个 PEEK+Chunk512“非空 Batch 后仍有未入批候选”的 tick，以及 5 个非常粗糙的 raw-free/512 代理事件；前者可能受到硬容量限制，后者不具备完整请求/预算和真实锁状态。没有任何安全完整入批机会的确认数。

**不能判 C**：原生 `OTHER/NO_TOKEN` 时直接 break，的确可能跳过后续较小请求。当前日志没记录拒绝原因及所有资源边界。仅仅无法观察，不等于不存在机会；不能用 5 个代理数充作“理论上最多 5 次”。

## 3. 下一步最小探针：准确接入点和计划改动文件

**本轮未写入或部署任何 Hook；以下是后续审批用的具体最小补丁方案。**

独立候选目录（只在 C 组新建）：

    /root/bayes-tmp/peek-c-group/experiment/extension_candidates/v23_admission_slack_probe/
        README.md
        native_probe.py             # 只读记录器、事件 schema、溢出/采样计数
        tests/test_probe.py         # 证明 off/on 不改变 Admission、状态和异常返回
        vendor_sglang_patch.diff    # 仅供独立 C 组加载的 SGLang 仿制/副本
        probe_report.py             # CPU 统计、按 RID 去重、机会漏斗

**源码精确插桩位置**（限 C 组受控隔离副本；原 wheel 源文件不直接改）：

1. `sglang/srt/managers/scheduler.py:1990–2007`：在 batch_is_full / waiting_queue / slot 的 early return 出口记录 `decision_tick` 与 `stop=early_* `；只访问已有值。
2. `scheduler.py:2013,2021–2047`：记录 PEEK Sort 后队列长度、KV/Chunk/prefill budget 初值、已有 continuation、running_bs 和 request slot；无原始 prompt。
3. `scheduler.py:2052–2114`：对真正尝试的请求记录 `rid`、rank、当前 `extend_input_len`、命中/host hit、调用前后预算、返回值 `CONTINUE/OTHER/NO_TOKEN`、LoRA/HiCache skip、实际 stop 候选索引；**原生只执行一次 `add_one_req`**。
4. `sglang/srt/managers/schedule_policy.py:719–827`：在该隔离副本中为已有返回分支标注精确细因（`total_capacity/real_input_limit/lock_recheck/chunk_budget/prefill_max_reqs/prefill_delayer/host_reload/etc.`）；不改变返回值、算术与控制流。保留 `rem_total_tokens/cur_rem_tokens/rem_input_tokens/rem_chunk_tokens` 每次变化。对于特殊 DLLM/PP/SWA，记录“非主目标条件”并拒绝据此计算 v23 机会。
5. `scheduler.py:2116–2145`：**在真实队列更新前**记录 final `adder.can_run_list`、原计划各 RID 的 `extend_input_len`、new_chunked_req、所有 rem budgets、剩余队列（仅 RID/大小/在线前缀状态）和停止原因；包括 `len(can_run_list)==0` 的结果。若无法从当前字段安全取得 untried candidate input_len，标记 unknown，**不得为探针调用 `req.init_next_round_input` 或 `add_one_req`**。
6. 在 `get_new_batch_prefill` 返回后附带 actual prefill RID 与 batch ID；与原来 v17 的 sort/audit RID 连接。对既有 v21 Shadow 扩展 **只读快照**，不直接用将来实际 evict 结果充当预测证据。

只读内容应包含 `run_id,trace_schema_version,tick,monotonic_ns,configuration_hash`、原先已选 RID/Chunk、终止码、预算、待选 RID 和重复机会键；尽量使用稳定 RID hash/prefix fingerprint，**不记录 prompt 原文、模型输出正文**。记录丢失事件数/采样原因，以便解释抽样分母。

### 只读不等于无开销

不能在 Production 路径中建立复杂 Python heap/二次扫描之后还称“纯观测”。建议首轮只做 O(已排序队列长度) 的数值和事件读取，记录长度上限（例如 top 16 未入批 RID）、总 tick 上限（如 1000，超限累计计数），原始 JSONL 约 1–3 KB/tick 的量级仅为初步估计，最终以真实文件大小和服务开销为准。写日志不要阻塞实际服务热路径（若同步日志无法满足开销预算，停止或降级）。**不能在工具窗口做任何真 KV/lock/队列副作用的 trial admission。**

## 4. 后续短程采集配置（尚未批准、尚未运行）

冻结同一源 PEEK HEAD / 模型、KV 和 client stream：

| 字段 | 计划值 |
|---|---|
| 环境 | rental-sglang 4090D，独占且遵守 `results/.workload_sweep.lock`，不启动之前先核验其他作业 |
| 模型 | Qwen2.5-3B-Instruct，BF16，单卡 |
| 工作负载 | LooGLE 64 个共享前缀组；Poisson 12 RPS；并发 64；**seed1911 + seed1711** |
| 内存/组批 | KV `--max-total-tokens 8192`，`--chunked-prefill-size 512 --enable-mixed-chunk` |
| 初次短采集 | 每 seed 原版 PEEK no-probe / PEEK+readonly-probe 各一臂；64 warmup + 128 scored，且同请求/组分配；只做可观察性/正确性和探针开销，不用于 P99 胜出声明 |
| 隔离 | 独立 C 组 instrumented server 副本，端口和目录与历史结果隔离；原始 PEEK Baseline 不加载 Hook |
| 保护 | 受保护 526 文件改动计数=0；异常/输入不匹配直接停止，保存失败日志 |

若短采集可观察且开销可接受，再单独批准标准的每臂 64 warmup+512 scored 多次 A/A/顺序反转；现阶段**不提交**后续 GPU 工作。

预计观察开销：每个 tick 顺序扫描并输出有限固定大小字段，CPU 时间和 JSONL 大小要实测；建议首轮工程目标是 probing 相对无 probe 的 mean TTFT/Goodput 变化不超过约 2%，但两个短臂误差很大，只能判断有无明显过载，不能据此宣布“开销已统计证明低于 2%”。

### 探针成功与立即停止的条件

**探针合格**：在固定快照下，原版排序和真正 admitted RID/Chunk 与无探针的配对分析保持结构/数量的一致性（考虑动态运行间随机性，不能逐 Tick 强行要求不同运行完全一致）；所有 early return、尝试、拒绝分支和最终 budget 都有值，event join 丢失为 0 或明确入账，探针写日志不致严重干扰运行。

**进入后续 E1+ 的证据门槛**：至少两个真实开发 seed 中都找到多个 **不同请求** 对应的“先前候选非全局 `OTHER/NO_TOKEN` 导致停止、后续更短候选在同 Tick 的资源快照经保守 guard 允许”实例，且其中有等待严重的请求。即便满足，仍需要低副作用的精确入批模拟与未来 KV/批时长 guard，**绝不能直接宣布 Go/性能胜出**。

**停止 A**：完整记录显示所有停止都由 Slot/持续 Chunk/KV/Decode 硬上限导致；或可试探的后续候选在完整 Prefill、现有 Batch 保留、当下不新增 eviction 等硬约束下没有有效例；或精确无副作用模拟必须大规模复制调度器（超课程工作量）；或即使安全候选也只出现在无拥塞状态。停止而非改名或放宽条件。

## 5. 备选 Eviction 路线（仅离线值得性判断）

v21 Shadow 在 **实际 Evict 时刻** 节点顺序 1253/1253 匹配，是实现基础；但 v21 历史访问预测回访 AUC 约 0.564–0.575（8K 数据）较弱，TTL 过度保护代价明显。若 A 停止，B 可以作为独立离线比较“原始被驱逐集合 V0 / 其他等量合法受害集合 V1”的价值预测小实验；必须保留锁与父子级联语义、按 run/时间隔离未来标签、计入替代受害者成本。**目前不授权 B 的实现或 GPU。**

## 6. E0/E1 交付清单

- `V23_SOURCE_MAP.md`：真实函数、行号、原生 vs 假设差异、副作用。
- `V23_TRACE_COVERAGE.md`：22 臂数据库存、6 臂逐 Tick 审计、字段覆盖。
- `V23_OPPORTUNITY_AUDIT.md`：完整“已知/代理/缺失”漏斗、A/A/请求级配对。
- `V23_DECISION.md`：**B / Need instrumentation**、探针方案与严格停机条件。
- `audit_v23_e1.py`：可复现 CPU 脚本。
- `V23_E1_MACHINE_RESULTS.json`、`V23_E1_INVENTORY.json`、`V23_E1_PAIRS.json`：机器可读统计和样例。

**实际动作边界**：本轮未启动 GPU，不修改 `/root/bayes-tmp/peek/` / SGLang wheel / 原版调度逻辑，不创建 v23 admission 策略，只做新的 CPU 分析目录。

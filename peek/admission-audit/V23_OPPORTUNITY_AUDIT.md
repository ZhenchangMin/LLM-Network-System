# V23_OPPORTUNITY_AUDIT — E1 离线机会漏斗、A/A 与请求级证据

更新：2026-11-14。运行了 `audit_v23_e1.py`，从历史真实 GPU 原始文件生成 `V23_E1_MACHINE_RESULTS.json`、`V23_E1_INVENTORY.json`、`V23_E1_PAIRS.json`。**未调用 GPU、未执行真实调度，也没有声称静态重放可以预测反事实 P99 或 Goodput。**

## 1. 机会漏斗：以 v21 原 PEEK + Chunk512 的唯一逐 tick 轨迹为核心

主轨迹：`results/gpu_ablation_v21_seed1911_native_shadow/runs/01_peek_shadow_r1_attempt01/runtime/peek_audit_207338.jsonl`，配置 Qwen2.5-3B BF16、LooGLE64group、seed1911、12RPS、KV8192、**原生 Chunk512+mixed**、64 warmup+512 scored。

| 漏斗层 | 审计数值 | 证据级别 | 解释 |
|---|---:|---|---|
| 所有决策 | **1,036 次可见 Sort**，其中 445 次附有非空 `prefill_batch`；另外 591 次 Sort 无非空 batch 记录 | **部分直接** | 早于 Sort 的 Early Return 不在记录中；591 不能都解释为空间浪费 |
| 有剩余预算 | 445 个非空 Prefill tick 中 **444 个事后 raw free KV>0** | **仅代理** | 这是 allocator raw free，**不是** PrefillAdder 剩余可入批预算；真正数值缺失 |
| 存在未入批候选 | **441 个**非空 Prefill tick 的 sort 队列中仍有未入批 RID | **直接（局部）** | 在这些 tick，有队列后缀；不说明它们是否满足硬约束 |
| 原计划/已有 chunk 不被挤出时仍可入批 | **不可判定** | **缺失** | stop reason、剩余 chunk/Prefill、Running decode reserve、slot 等未记录 |
| 候选完整 Prefill 可在本轮完成 | **不可判定**；简化代理为 **5 次 / 5 个独立 RID** | **仅极弱筛选代理** | 用 `max(total_tokens - main_hit,0) <=512` 且事后 `raw_free_kv > 估计值`，无锁、实际 hit、输出预留校正；**不是合法机会数量** |
| 不增加当下 Eviction | **不可判定** | **缺失** | 仅有原始计划下的真实 Eviction，追加候选的副作用未模拟 |
| 后续 KV/Batch 时间约束 | **不可判定** | **缺失/需模型** | 无保守时间预测、未去重的 decode reservation 和真实前向状态 |

候选统计（**非可行机会**）：该运行共有 **10,794 次“已在 sort 队列但未在本 tick 非空 Prefill 事件入批”的 RID 暴露**；按 RID 去重为 **460 个计分请求**，多余重复暴露 **10,334 次**。其中客户端 TTFT≥2000ms 的计分请求 **205 个**，205 个都至少在一个非空 Batch 后仍等待过；这是排队暴露覆盖率，**不是 205 个潜在可救活请求**。

同场 v21 ticket-shadow（另一处理臂）也有 1,036 Sort / 482 非空 Prefill / 478 带未入批候选的 tick、475 个独立被暴露计分 RID、12,756 次重复暴露；同样的极弱原始 free+512 筛选是 **73 次 / 53 个 RID**。两臂在运行机制与轨迹上不同，**73 与 5 不能差分成 Extension 的新增机会**。

## 2. v17 A/A 与跨探针配置检查

| 轨迹 | Sort | 非空 Prefill | Sort 无 batch 记录 | 非空 Prefill 后有队列后缀的 tick | 去重候选 RID | 候选重复暴露 |
|---|---:|---:|---:|---:|---:|---:|
| v17 PEEK A/A 第1臂 | 340 | 288 | 52 | 283 | 463 | 5,859 |
| v17 PEEK A/A 第2臂 | 348 | 296 | 52 | 290 | 462 | 5,699 |
| v17 PEEK trace / v16 对照 PEEK 臂 | 340 | 287 | 53 | 282 | 448 | 5,754 |
| v17 PEEK trace / v16 对照 v16 臂 | 351 | 290 | 61 | 284 | 458 | 5,484 |
| v21 Chunk512 PEEK native-shadow | 1036 | 445 | 591 | 441 | 460 | 10,334 |
| v21 Chunk512 ticket-shadow | 1036 | 482 | 554 | 478 | 475 | 12,756 |

**禁止用 v17 No-Chunk 的较少 Sort 次数，直接推断 v21 Chunk512 的机制变差**：Chunk continuation 与运行轨迹、探针不同。历史有 6 条可追溯的真实 trace，但只有 1 条原版 PEEK+Chunk512；没有跨 seed 的原生同配置 trace。

### A/A 排队与缓存波动

v17 原 PEEK → 原 PEEK A/A，在同一冻结流量的 **512 个请求索引**配对：

- 第二轮相对第一轮：配对 TTFT 平均差 **−72.56 ms**，差值中位数 **−20.87 ms**；单请求差值 P05/P95 分别约 **−935.95/+881.78 ms**；
- **66 个**请求第二轮至少快 500ms，**42 个**至少慢 500ms；
- 第一轮高命中（≥512 cached tokens）→第二轮低命中（<32）有 **22 个请求**。这发生在完全相同策略的 A/A 比较里，说明正常运行间的 Cache Churn / Admission 差异不能忽略。
- v17 单独的 PEEK trace → v16 KV-audit 比较，有 **30 个**同口径高命中→低命中坍塌；两者配置虽可比，但 **不能使用 30−22=8** 作为因果净损失，因为同一请求的动态系统事件相互依赖，且两个实验时段不是重复随机试验。
- 已有 v17 真实驱逐事件能看到前缀节点被删与后续入批的时间关系，但只能确认**发生了相关的删前缀事件**，不能单靠该事件定义绝对因果。

### 额外的 PEEK+Chunk A/A 波动

v22 每个四臂中都重复原始 PEEK，两次原版 P99 自身差异分别为：

- Cross-section seed1911：**−6.33%**；
- Cross-section seed1711：**−2.73%**；
- Quickdemote seed1911：**−6.10%**。

这三组是不同独立 run 的 **运行级背景尺度**，不允许把每组 512 requests 当 512 个独立 seed，也不能从一个 Extension A/B 差值直接减掉一个 A/A 差值来“去噪”。

## 3. Extension 请求级收益 / 损失分布

所有下面的请求均通过相同冻结流量 `req_id` 配对，并且每轮 512 scored。负数为 Extension 更快；“快/慢≥500ms”按 request-level delta 分类，**用于诊断而非总体独立统计显著性**。

| 对照 pair（同序号请求） | Mean TTFT 差（Ext−PEEK） | 至少快 500ms | 至少慢 500ms | PEEK 高命中→Ext 低命中 |
|---|---:|---:|---:|---:|
| v21 victim seed1911，pair1 | +194.37ms | 65 | **115** | 29 |
| v21 victim seed1911，pair2 | +170.29ms | 72 | **128** | 22 |
| v22 cross seed1911，pair1 | +12.66ms | 81 | 84 | 29 |
| v22 cross seed1911，pair2 | −19.88ms | 43 | **80** | 11 |
| v22 cross seed1711，pair1 | −14.83ms | 23 | 33 | 9 |
| v22 cross seed1711，pair2 | +59.70ms | 45 | **75** | 18 |
| v22 quickdemote seed1911，pair1 | −62.61ms | 76 | 49 | 21 |
| v22 quickdemote seed1911，pair2 | +130.30ms | 38 | **77** | 14 |

单请求巨大 TTFT 净变化与部分 warm 高命中坍塌共同说明：**cold 调度益处和其他请求的服务竞争确实同时出现，但没有严格的单请求随机因果归因。** v21 pair1 的请求差值 P05/P95 约 −2535/+3373ms，表明最极端的受益和受害同时存在；pair2 也是类似量级。v22 的方向还会按重复轮改变。

对全部 22 运行的配对差值、最严重 10 个受益与受害请求、缓存命中变化和索引样例，可直接查询 `V23_E1_PAIRS.json`；避免在正文泄漏原始 prompt。

## 4. 主要拒绝原因的可观察性

| 原生原因 | 源码存在？ | 历史 trace 能定量？ |
|---|---|---|
| Slot / batch_is_full | 是，scheduler.py:2070–2083 | **不能**；无槽位、运行 Batch 大小和拒绝 RID |
| KV/Decode 输出预留不足 `NO_TOKEN` | 是，schedule_policy.py:734–753 | **不能**；无完整 Budget 与 Return branch |
| Prefill/Chunk `OTHER` | 是，schedule_policy.py:747–748,766–767,799–825 | **不能**；无 `rem_input/rem_chunk` 与终止代码 |
| Chunk continuation 占用 | 是，scheduler.py:2045–2047 | **不能**；不记录本 Tick 完整 Chunk 分配 |
| HiCache/LoRA 跳过 | 是，scheduler.py:2054–2068,2085–2089 | **不能**；没有 per-candidate skip reason |
| PrefillDelayer / special CP / Host load | 是，schedule_policy.py:719–778 | **不能**；结果事件未携带 |
| 空队列、batch full 等早退 | 是，scheduler.py:1990–2007 | **不能**；早退前无 Sort 事件 |

因此无法给出可靠的“哪个拒绝原因贡献最多”，也不能给出“保证零额外驱逐的独立机会数”。不应该拿 JSON 中的 5 个粗代理事件或 441 个排队后缀 tick 冒充完整可行性通过数。

## 5. 当前结果是否支持首选路线？

**支持深入采集，不支持立即实现 Extension：**

- 原生源码的 `OTHER/NO_TOKEN → break` 显示存在结构性的“未继续尝试更后面候选”行为；
- 真实 trace 证明 PEEK+Chunk512 场景大量 Sort tick 有未服务后缀，但大多数后缀可能恰恰是因为资源紧张；
- 极弱的“一次完整 Prefill≤512 且 raw free 足够”离线筛选，在唯一 PEEK+Chunk512 trace 中仅出现 **5 次 / 5 RID**，机会可能稀少。但这个筛选既不是充分条件也不是可靠上界：main_hit 与原生瞬时状态会变化；其它 KV 约束与更多回收空间被忽略。
- 缺少本轮 E1 最关键的 PrefillAdder 剩余 Token/Chunk/Slot、第一拒绝及其后续候选状态。此时宣布“有机会”或“无机会”都超出证据。

**决定转到最小只读 instrumentation，而不是直接写动态 admission 策略或启动更多旧版 GPU 改进尝试。**

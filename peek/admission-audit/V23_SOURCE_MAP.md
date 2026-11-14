# V23_SOURCE_MAP — E0 真实源码链与原生准入语义

采集：2026-11-14；只读检查 rental-sglang。**这是代码证据，不是实现授权，也不是性能证据。** 所列行号以该机现存的 Python 安装和 PEEK 快照为准。

## 版本和保护边界

- 原始 PEEK：`/root/bayes-tmp/peek`，`git rev-parse HEAD` = `6fbf2205f1c8bc6fe55746d75860e23779b003a2`，与 v17/v21/v22 的 `metadata/git_before.json` 相符。**不是早期 3aca72b。**
- 当前 tracked git diff 和 staged diff 为空；`git status --porcelain` 有 B 组目录下若干 **untracked** 文件（B 组资料/结果），未接触。
- SGLang 实际执行位置：`/root/bayes-tmp/peek/.venv/lib/python3.12/site-packages/sglang/srt/managers/`。分析的是该安装版本的源码，并与历史 server_command 对齐；不把官方新版本的 API 混入。
- C 组原有 Hook：`/root/bayes-tmp/peek/python/peek/online/engines/sglang/patch_hook.py`；审计版本：`/root/bayes-tmp/peek-c-group/experiment/extension_candidates/v17_audit/python/peek/online/engines/sglang/patch_hook.py`。

## 1. 真实调用链

1. `scheduler.py:1875–1952` 的 `Scheduler.get_next_batch_to_run` 根据运行批次状态进入 `get_new_batch_prefill()`（1921–1924）。当没有 Prefill Batch 时转为 running decode（1935–1944）。
2. `Scheduler.get_new_batch_prefill`（1960–1975）调用 `_get_new_batch_prefill_raw`（1977 起）。
3. `_get_new_batch_prefill_raw` 的早期守卫（1990–2007）可直接返回 None；`self.policy.calc_priority(self.waiting_queue, self.running_batch)` 在 **2013** 完成 PEEK 排序。
4. PEEK 的 Hook `patch_hook.py:534–548` 将 `SchedulePolicy.calc_priority` 替换为 `_patched_calc_priority`；`655–682` 进入 `peek_clpm_sort_inplace`（`python/peek/online/lpm_integration.py:288`）。这是 **排序，不是实际 Admission**。PEEK 先同步待处理前缀树：`patch_hook.py:513–521` 在 `get_next_batch_to_run` 前调用 `_sync`。
5. `scheduler.py:2021–2043` 决定 Chunk 大小并构造 `PrefillAdder`；若已有 `chunked_req`，在 **2045–2047** 首先 `init_next_round_input` 并 `add_chunked_req`，不应被任何候选追加改动挤出。
6. `scheduler.py:2052–2114` 遍历已经排序的 `waiting_queue`，包含 LoRA/HiCache/slot 判断，`req.init_next_round_input(self.tree_cache)` 在 2095，随后 `adder.add_one_req(...)` 在 **2096–2100**。
7. **只要返回结果不为 `AddReqResult.CONTINUE`，2052–2114 的循环即 `break`。** 其中 `NO_TOKEN` 还会使 `batch_is_full` 变为 True（2105–2114）；`OTHER` 也会退出本轮扫描。LoRA 冲突（2054–2068）和 HiCache prefetch 未就绪（2085–2089）等特定分支是 `continue`。
8. `scheduler.py:2116–2165` 更新队列、preemption/continuation、记录时间、创建 `ScheduleBatch`；`2172` 的 `new_batch.prepare_for_extend()` 实际分配资源。若 mixed chunk 打开，`2184–2200` 将 running decode 合入新 Batch。
9. `schedule_batch.py:1449–1505` 的 `prepare_for_extend` 创建 CPU/GPU 张量并调用 `alloc_for_extend(self)`，`1515–1523` 更新每请求的分配和已提交长度。这个时点之后**不允许**无代价重组候选。
10. 正常后续 decode 内存检查 `scheduler.py:2213–2255` / `schedule_batch.py:1834–1837` 可触发 `evict_from_tree_cache` 和 retraction；本轮当下“零额外驱逐”不能保证未来没有负效应。

## 2. 约束与原生扫描行为

| 约束 | 已核对接口、行号 | E0 含义 |
|---|---|---|
| 排序 | `SchedulePolicy.calc_priority` → PEEK `peek_clpm_sort_inplace` | 仅决定尝试顺序；不保证真正入批 |
| 请求 Slot / PP 微批 | `scheduler.py:1954–1958,2070–2083` `get_num_allocatable_reqs` | 已达到 slot 上限则 break；尝试 preemption 的分支需单列 |
| Prefill input 预算 | `scheduler.py:2030–2043` 输入 `max_prefill_tokens`；`schedule_policy.py:393,494–507,747–748,766–767` | `rem_input_tokens` 可能使 `OTHER`；剩余 token 并非仅看 free KV |
| KV / 输出预测预留 | `schedule_policy.py:439–489` `rem_total_tokens` 和 `cur_rem_tokens`；`734–745,750–753` | 使用 allocator available + evictable，扣 running decode 的 `new_token_ratio` 预测和新请求 max_new_tokens；等于/超过可用预算便 `NO_TOKEN` |
| Prefix 锁与分页 | `schedule_policy.py:491–492,618–630,750–766` | 申请锁后容量可能下降；host cache reload 可改变 `prefix_indices` 与 extend input |
| Chunk 预算、Continuation | `scheduler.py:2021–2047`；`schedule_policy.py:591–616,786–825` | 先保留已有 continuation；新候选可被截断创建新的 continuation；本项目首版要求 **完整 Prefill** |
| 请求数/其他守卫 | `schedule_policy.py:719–732`、`769–778` | `prefill_max_requests`、特殊 Context Parallel / Prefill Delayer / DLLM 配置需识别 |
| 原生预算扣减 | `schedule_policy.py:510–526` `_update_prefill_budget` | `extend_input_len` 按页对齐；总预算加新输出预留、当前预算加 Prefill、Chunk 也扣减 |
| Batch 提交/未来解码 | `schedule_batch.py:1449–1523,1834–1837` | 真正 GPU 分配和解码期驱逐在组批后发生 |

**核心判断**：原生 PEEK+SGLang 并不总是“已有空间时无条件扫完整个队列”。遇到 `OTHER` 或 `NO_TOKEN` 常常直接结束，所以后续更小/更适配的请求理论上可能未被尝试。但是：`OTHER` 可能表示实际 chunk/input/slot 等不可逾越的约束，而非有用资源闲置。不能从一个 `break` 推断存在真正安全的补充 Admission。

## 3. 能否无副作用地评估候选？

目前 **没有验证存在可直接复用的“无副作用 Admission 试算”API**：

- `req.init_next_round_input`（scheduler.py:2095）和 `adder.add_one_req`（2096–2100）可能改变请求的内部字段；`schedule_policy.py:750–825` 会临时或持久增加 cache lock ref、加载 host cache、截断 fill_ids、更新预算和已入批列表。
- `ScheduleBatch.prepare_for_extend`（schedule_batch.py:1449–1523）还会进行真正分配。
- 所以不能对原始状态重复调用 `add_one_req`、`prepare_for_extend` 来试算候选；这不是只读操作。
- 首选方式是先**只读记录**真实 `PrefillAdder` 各项守卫、终止原因和预算，然后在独立 CPU 快照上构建保守的状态模拟器。准确实现仍需验证与这些原生状态的等价性；若做不到小范围精确验证，停止 A。

## 4. v21 Shadow 能证明什么，不能证明什么

真实源码：`extension_candidates/v21_shadow_validate/python/peek/online/engines/sglang/native_shadow_probe.py:10–36`：

- 对 **真实 Eviction 函数调用之际** 的 `evictable_leaves` / `eviction_strategy.get_priority` 与 parent cascade 做只读 heap 模拟；
- 真实 GPU 的 `shadow_native_validation` 事件在两臂合计 1253/1253 次与实际 Eviction 节点顺序吻合（详见 v21 JSON）。
- **不能迁移为“更早 Admission 时预测一定正确”**：中间 `calc_priority`、Prefix Lock/Unlock、已有 Chunk、新入批分配、running decode 进展、cache insert/evict、可驱逐叶集合及 parent lock_ref 都可能变化。
- Shadow 也不模拟请求的 `rem_input_tokens`、Slot、Decode 预留、Mixed Chunk 的 Batch 时间。要用于 A，须在真正候选决策点验证快照与之后真实执行的差异。

## 5. 与 v23 假设的真实差异

首选 v23 不是改变 PEEK 的 cLPM 排序，也不是直接替换 Eviction。其假设是：**原生循环因某个候选触发非全局约束而停止后，仍存在不挤掉原定 Batch 的可接纳、且完整 Prefill、当下无额外 Eviction 的其他等待请求**。需要先证明三件事：

1. 有具体退出原因，且不是 request-slot/Running decode 等硬上限；
2. 存在实际可负担的另一候选，完成 full Prefill，不改变已有 chunk 和在途锁；
3. 评估方案有低开销、可复验的只读模拟接口，并能控制未来内存/批时长损失。

当前已证明的是 **原生有提前退出逻辑**；以上三个条件尚未同时证明。

**直接引用入口**：PEEK `python/peek/online/engines/sglang/patch_hook.py`；SGLang wheel 的 `scheduler.py`、`schedule_policy.py`、`schedule_batch.py`；C 组 `extension_candidates/v17_audit/` 与 `v21_shadow_validate/`。所有位置在上述绝对路径下。

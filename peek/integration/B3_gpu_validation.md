# B3 · PEEK Online GPU集成验收报告

## 1. 验收环境

- 日期：2026-11-05
- GPU：NVIDIA RTX 4090 D（24GB）
- Python：3.12.4
- PyTorch：2.9.1+cu128
- SGLang：0.5.9
- PEEK基准Commit：3aca72b63c1dd6433193c0857b965acecdbfbb8a
- B3 CPU阶段Commit：65b6309
- 模型：Qwen2.5-3B-Instruct
- 服务地址：127.0.0.1:30001
- KV Cache容量：8192 Tokens

## 2. PEEK Online配置

使用PEEK_PRESET=peek-online，实际启用：

- cLPM Scheduler
- Group-major
- Dynamic Lane
- Cluster-mode Queue-aware Eviction

服务日志确认安装Scheduler Hook和PeekDemandStrategy。

## 3. 基础集成测试

执行：

B3_TEST_ONLINE=1 python -m pytest \
  b-group/tests/test_peek_integration.py -v -s

结果：7 passed。

验证内容：

- 环境和PEEK基准版本
- 四个Hook方法替换
- HTTP Health
- 基础生成
- 共享前缀请求
- 8路并发请求

## 4. 竞争队列测试

额外构造16个并发请求，分为4组共享前缀。

结果：

- 成功：16/16
- 最大观测Waiting Queue：11
- calc_priority_calls：14增加到28
- calc_priority_fallbacks：0
- Pending Tree insert/discard：41/41
- KV Cache利用率最高观测约98%
- 服务日志中多次出现cached-token大于0

这证明PEEK调度路径在真实排队负载中被调用。

但没有采集排序前后的请求顺序，
因此未单独证明cLPM相对LPM改变了具体排序结果。

## 5. Pending Tree一致性

Scheduler进程PID：1178。

保存的Validate数据：

- sync_checks：51316204
- sync_extra_in_peek：0
- sync_missing_in_peek：0
- sync_token_mismatch：0

Profile包含28次排序调用。
Phase包含41条到达/调度记录。

sync_checks是循环检查计数，不能解释为请求数量。

## 6. Queue-aware Eviction

启动日志显示PeekDemandStrategy已成功注入RadixCache。

在16路竞争测试后观察到：

- peek_eviction_trace_1178.jsonl
- 19条记录
- 记录包含ev_idx、priority_value、
  path_len、levels和num_evicted_this_call等字段

这证明真实运行中进入了Eviction追踪路径。

但现有数据不等同于性能收益证明，
也不能将19条记录直接等同于19次独立Eviction调用。

## 7. 证据文件

目录：

b-group/results/gpu_validation_20261105/

包含：

- integration_online.log
- peek_server.log
- peek_profile_1178.json
- peek_validate_1178.json
- peek_phases_1178.json
- peek_eviction_trace_1178.jsonl

已通过check_peek_evidence.py检查。

## 8. 验收结论与限制

B3已完成PEEK Online与SGLang 0.5.9
在RTX 4090 D上的基础端到端集成验证。

已确认模型推理、共享前缀缓存复用、
真实Waiting Queue、PEEK调度调用、
Pending Tree同步检查及Eviction追踪。

未验证：

1. cLPM对具体请求排序的改变。
2. 与Vanilla LPM相比的吞吐及延迟收益。
3. 每条Eviction Trace对应的实际缓存释放Token数量。

这些不能被报告为已经通过。

## 9. B4交接

B4使用同一模型、KV预算和固定Workload，
在关闭B3_DEBUG后运行正式性能对照。

启动命令：

bash b-group/scripts/start_peek_online.sh

B4不得直接使用带Debug的结果进行性能比较。

A组服务端口为30000，B组为30001；
在单GPU环境下应分时运行。

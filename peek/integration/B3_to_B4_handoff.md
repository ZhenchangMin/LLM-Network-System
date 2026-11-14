# B3 → B4 交接文档：PEEK Online GPU集成与性能评测准备

> 交接日期：2026-11-05
>
> 交接方：B3（PEEK Online / SGLang GPU集成）
>
> 接收方：B4（W1-Lite正式性能评测）
>
> 状态：B3核心集成与GPU验证已完成，正式性能对照待B4执行。

---

## 1. 交接概要

B3已完成PEEK Online与SGLang 0.5.9的集成验证，
并在NVIDIA RTX 4090 D上完成实际推理、并发调度、
KV Cache复用、Pending Tree同步和Eviction路径测试。

B3已完成：

1. PEEK Online运行环境准备。
2. SGLang启动脚本及Hook集成检查。
3. CPU阶段集成验证。
4. GPU端到端在线集成测试。
5. 16路共享前缀竞争队列测试。
6. 调度、同步、缓存复用和Eviction证据采集。
7. GPU验收报告、Git提交和Bundle备份。

B4接下来负责正式W1-Lite性能对照。

需要注意：

- B3验证的是功能可运行性和机制实际执行。
- B3尚未证明PEEK相对Vanilla LPM的性能收益。
- cLPM具体排序变化和Eviction效果仍可进一步分析。
- 正式性能结论应以B4统一条件下的对照实验为准。

---

## 2. 代码版本

| 项目 | Commit |
|---|---|
| PEEK基准版本 | `3aca72b63c1dd6433193c0857b965acecdbfbb8a` |
| B3 CPU阶段提交 | `65b6309` |
| B3 GPU阶段提交 | `8b73d0d` |
| B3最终完整Commit | `8b73d0de632cd168ecdb99995c68240be28456b5` |

当前B3交付内容已包含在最终Commit中。

Git Bundle：

```text
/root/bayes-tmp/peek-b3-final-8b73d0d.bundle
```

该Bundle已通过：

```bash
git bundle verify /root/bayes-tmp/peek-b3-final-8b73d0d.bundle
```

并已下载至B3成员的Mac本地，SHA-256校验一致。

注意：Bundle包含已提交的Git历史，不包含虚拟环境、
模型权重，以及仓库中其他成员尚未提交的文件。

---

## 3. 运行环境

| 项目 | 配置 |
|---|---|
| 项目目录 | `/root/bayes-tmp/peek` |
| 虚拟环境 | `/root/bayes-tmp/peek/.venv` |
| Python | 3.12.4 |
| PyTorch | 2.9.1+cu128 |
| SGLang | 0.5.9 |
| GPU | NVIDIA RTX 4090 D（24GB） |
| 模型 | Qwen2.5-3B-Instruct |
| 模型目录 | `/root/bayes-tmp/kvcache/models/Qwen2.5-3B-Instruct` |
| B组服务端口 | `30001` |
| A组服务端口 | `30000` |
| KV Cache容量 | 8192 Tokens |

模型和虚拟环境均保存在服务器上，不属于Git仓库内容。

如服务器实例发生变化，需要重新核验环境与模型路径。

---

## 4. PEEK Online配置

B3使用以下Preset：

```bash
export PEEK_PRESET=peek-online
```

已检查该Preset启用：

- PEEK Online Scheduler
- cLPM
- Group-major
- Dynamic Lane
- Cluster-mode Queue-aware Eviction

服务启动时已观察到：

- Scheduler Hook安装
- RadixCache Hook安装
- PeekDemandStrategy注入
- PEEK调度路径实际调用

B3验证时保持与A组对照一致的关键配置：

```text
dtype                 = bfloat16
tp-size               = 1
schedule-policy       = lpm
mem-fraction-static   = 0.75
max-total-tokens      = 8192
host                  = 127.0.0.1
port                  = 30001
```

正式评测前，B4应再次确认A/B实际启动参数一致。

---

## 5. B4启动步骤

### 5.1 激活运行环境

```bash
cd /root/bayes-tmp/peek

conda deactivate 2>/dev/null || true
source .venv/bin/activate

python --version
```

### 5.2 启动PEEK Online服务

```bash
bash b-group/scripts/start_peek_online.sh
```

启动脚本位置：

```text
b-group/scripts/start_peek_online.sh
```

正常情况下，服务监听：

```text
http://127.0.0.1:30001
```

### 5.3 健康检查

在另一个SSH终端执行：

```bash
curl -f http://127.0.0.1:30001/health
```

### 5.4 调试模式说明

B3机制验证阶段使用：

```bash
B3_DEBUG=1 bash b-group/scripts/start_peek_online.sh
```

该模式会开启额外的Profile、Validate及Eviction日志采集。

**B4正式性能评测必须关闭B3_DEBUG。**

建议直接使用默认启动方式，不启用额外调试统计，
避免影响吞吐、TTFT和端到端延迟。

还应检查运行环境中是否残留其他调试变量。

---

## 6. B3 GPU验证结果

### 6.1 在线集成测试

执行：

```bash
B3_TEST_ONLINE=1 python -m pytest \
  b-group/tests/test_peek_integration.py \
  -v -s --tb=short
```

已记录结果：

```text
7 passed
```

覆盖：

- Python / SGLang运行环境
- PEEK基准Commit关系
- Hook方法替换
- HTTP健康检查
- 基础文本生成
- 共享前缀请求
- 8路并发推理

### 6.2 16路竞争队列测试

B3额外构造16个并发请求，按4组组织共享前缀。

结果：

| 指标 | 结果 |
|---|---|
| 请求成功 | 16/16 |
| 最大观测Waiting Queue | 11 |
| PEEK排序调用 | 28 |
| 调度回退计数 | 0 |
| Pending Tree插入 | 41 |
| Pending Tree移除 | 41 |
| 最大观测Token Usage | 约98% |
| KV Cache复用 | 已观察到cached-token大于0 |

该测试证明在真实竞争场景中，
PEEK调度路径被调用，并且请求能够正常完成。

没有额外记录排序前后的完整请求序列，
因此不将具体重排序效果标记为已验证。

### 6.3 Pending Tree一致性

运行时Scheduler PID为1178。

保存的验证数据：

```text
sync_checks           = 51316204
sync_extra_in_peek    = 0
sync_missing_in_peek  = 0
sync_token_mismatch   = 0
```

请求阶段记录：

```text
arrivals = 41
picks    = 41
```

注意：

`sync_checks`为内部检查次数，
不能直接解释为请求数量。

### 6.4 KV Cache复用

服务端日志多次观察到：

```text
#cached-token: 269
#cached-token: 1162
#cached-token: 2393
#cached-token: 3588
```

说明共享前缀缓存复用实际发生。

### 6.5 Queue-aware Eviction

B3验证阶段采集到：

```text
peek_eviction_trace_1178.jsonl
```

包含19条Eviction Trace记录。

记录字段包括：

- ev_idx
- priority_value
- path_len
- levels
- last_access_time
- leaf_key_len
- num_evicted_this_call
- heap_size_at_entry

这些记录支持Eviction路径被实际执行的结论。

但19条记录不能直接解释为19次独立Eviction调用，
也不能直接得出相对LRU的性能优势。

---

## 7. 证据与文档位置

### 7.1 GPU验收报告

```text
b-group/docs/B3_gpu_validation.md
```

### 7.2 GPU运行证据

```text
b-group/results/gpu_validation_20261105/
```

包含：

| 文件 | 内容 |
|---|---|
| `integration_online.log` | 在线集成测试结果 |
| `peek_server.log` | SGLang/PEEK服务运行日志 |
| `peek_profile_1178.json` | 调度与同步性能计数 |
| `peek_validate_1178.json` | Pending Tree一致性检查 |
| `peek_phases_1178.json` | 请求到达和调度时间 |
| `peek_eviction_trace_1178.jsonl` | Eviction逐项追踪记录 |

证据验证命令：

```bash
cd /root/bayes-tmp/peek

python b-group/scripts/check_peek_evidence.py \
  --dir b-group/results/gpu_validation_20261105
```

该目录中的证据均来自B3 GPU验证阶段。

文件名中的PID是当时Scheduler的进程号，
不代表后续重新启动时仍使用同一PID。

### 7.3 其他相关文件

```text
b-group/docs/B3_integration_handoff.md
b-group/scripts/check_peek_evidence.py
b-group/scripts/start_peek_online.sh
b-group/tests/test_peek_integration.py
```

---

## 8. B4下一步任务

B4应继续完成：

1. 确认模型和虚拟环境可正常使用。
2. 关闭B3 Debug，启动正式PEEK服务。
3. 确认A组与B组使用相同的模型和KV预算。
4. 对齐W1-Lite数据、请求生成方式、随机种子、
   请求到达速率、并发配置和输出长度等条件。
5. 在单GPU环境下分时运行A/B测试。
6. 记录吞吐、延迟、缓存复用和相关性能指标。
7. 汇总正式对照结果，分析PEEK相对基线的收益及开销。
8. 保留原始日志、运行命令与最终报告，保证结果可复现。

本阶段不要求B4重新实现B3已完成的集成逻辑。

如需修改核心调度代码，应单独记录修改内容及Commit，
避免与B3基准结果混淆。

---

## 9. 共享服务器注意事项

1. A组工作目录为：

   ```text
   /root/bayes-tmp/kvcache
   ```

2. B组工作目录为：

   ```text
   /root/bayes-tmp/peek
   ```

3. 不要擅自修改A组目录。

4. B组仓库中可能存在B1/B2成员尚未提交的文件，
   不要使用`git clean -fd`等命令误删。

5. A/B共享同一GPU时应协调使用，避免互相干扰。

6. B3原服务如仍占用30001端口，
   应确认相关任务结束后再停止。

7. 云服务器磁盘中的文件可能不具备长期持久性，
   正式实验结果需要另外备份。

---

## 10. 交接结论

B3已完成PEEK Online在SGLang 0.5.9上的基础集成、
GPU端到端功能验证及运行时证据归档。

B4可以基于Commit `8b73d0d`
继续进行W1-Lite正式性能对照实验。

B3交付的是经过功能验证的在线集成环境；
最终性能结论由B4通过统一条件下的对照实验给出。

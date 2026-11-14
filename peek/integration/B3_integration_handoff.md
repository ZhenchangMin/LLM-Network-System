# B3 · PEEK Online / SGLang 集成交接说明

## 1. 工作范围

B3负责PEEK Online与SGLang 0.5.9集成，包括独立环境、
启动脚本、Hook验证、在线API测试及运行时证据采集。

B3不修改A组Vanilla环境，不覆盖B1/B2交付内容。
B4负责正式W1-Lite性能评测。

## 2. 固定环境

- PEEK Commit: 3aca72b63c1dd6433193c0857b965acecdbfbb8a
- 仓库: /root/bayes-tmp/peek
- Python: 3.12.4
- 虚拟环境: /root/bayes-tmp/peek/.venv
- SGLang: 0.5.9
- PyTorch: 2.9.1+cu128
- CUDA构建版本: 12.8
- 模型: /root/bayes-tmp/kvcache/models/Qwen2.5-3B-Instruct

当前已完成CPU离线验证；尚未完成GPU端到端验收。

## 3. PEEK Online配置

启动前设置：

- PEEK_PRESET=peek-online
- 正确的sitecustomize及PEEK Python路径

已验证Preset实际启用：

- PEEK_ONLINE_SCHEDULER=1
- PEEK_ONLINE_CLPM=1
- PEEK_ONLINE_CLPM_GROUP_MAJOR=1
- PEEK_ONLINE_CLPM_DYNAMIC_LANE=1
- PEEK_ONLINE_EVICTION=1
- PEEK_ONLINE_EVICTION_MODE=cluster

以上仅证明配置生效，不代表运行时机制已触发。

## 4. 与A组对齐的启动参数

- Model: Qwen2.5-3B-Instruct
- dtype: bfloat16
- TP: 1
- schedule-policy: lpm
- enable-cache-report: enabled
- mem-fraction-static: 0.75
- max-total-tokens: 8192
- A组端口: 30000
- B3端口: 30001

GPU运行后需进一步确认实际KV容量和模型加载情况。

## 5. 已完成的离线验证

- PyTorch、SGLang及PEEK Core导入成功
- pip check: No broken requirements
- B2机制回归测试: 10 passed
- B3集成测试: 3 passed, 4 skipped
- RadixCache及Scheduler相关四个Hook替换验证通过
- start_peek_online.sh Shell检查与Dry Run通过
- B3_DEBUG=1下验证日志采集Hook已安装
- check_peek_evidence.py在CPU环境运行正常

尚无真实GPU推理和缓存淘汰证据。

## 6. B3交付文件

- scripts/start_peek_online.sh
- scripts/check_peek_evidence.py
- tests/test_peek_integration.py
- results/integration.log

以上路径均相对于b-group/。

integration.log当前记录CPU离线结果，
在线联调时需要保存新的GPU验收结果。

## 7. GPU恢复后的验证顺序

1. 检查nvidia-smi与torch.cuda.is_available()
2. 协调A组GPU占用，避免同时启动两个3B服务
3. 用B3_DEBUG=1启动PEEK Online服务
4. 验证/health与Chat Completions API
5. 执行共享前缀及小规模并发测试
6. 采集Profile、Validate、Phase和Eviction日志
7. 核对真实调度调用、等待队列及缓存复用
8. 在实际缓存压力下验证淘汰行为
9. 保存GPU测试结果并更新本交接说明

Debug日志采集会引入开销，不能直接用于正式性能对照。

## 8. 验收判定原则

- Hook替换成功 != Hook被真实请求调用
- 调度函数被调用 != cLPM改变排序顺序
- 缓存命中 != 发生实际缓存淘汰
- 没有淘汰日志 != 淘汰实现有错误
- API返回200 != PEEK端到端机制验证通过

真实运行证据不足的项目应标记为NOT VERIFIED，
不得报告为PASS。

## 9. B3与B4交接边界

B3负责服务可启动、集成正确性及机制运行证据。
B4基于B3通过验收的服务，执行统一W1-Lite负载，
比较Vanilla与PEEK的性能结果。

正式对照须使用A组最终冻结的模型、数据、
KV预算、请求速率、并发参数和随机种子。

## 10. 数据保留注意事项

/root/bayes-tmp为云实例项目盘。
实例释放前需备份重要代码和运行结果。

.venv/和wheels/不应提交到Git。
*.log被当前仓库忽略，提交日志需单独处理。

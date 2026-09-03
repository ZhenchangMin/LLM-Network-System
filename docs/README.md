# LLM Infra Starter List

这是课程 Project 5（KV Cache Management Optimization for LLM Inference）的组内学习清单。

目标是帮助已经学过操作系统、计算机组成、基础编程和数学，但对 LLM / LLM Infra 不熟悉的组员尽快建立共同语言。

## 设计原则

- 保持简单：纯 HTML + CSS，不使用 JavaScript，也没有进度、账号、搜索或筛选功能。
- 面向 Project：只收集理解 LLM inference、KV Cache、PagedAttention、prefix caching、eviction、offloading 和 benchmark 所需要的内容。
- 强调学习方法：页面首先说明如何快速自学陌生系统方向，以及如何使用经典 three-pass method 阅读论文。
- 避免百科化：训练、RLHF、LoRA、分布式训练、复杂 CUDA kernel 等暂时不是前置知识。

## 本地预览

在 `docs/` 目录运行：

```bash
python -m http.server 8000
```

然后访问 `http://localhost:8000`。

## GitHub Pages

仓库使用 `main` 分支的 `/docs` 目录作为 GitHub Pages 来源。

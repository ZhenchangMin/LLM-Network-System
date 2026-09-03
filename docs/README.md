# LLM Infra Learning Hub

一个面向 `LLM-Network-System` 课程 Project 5（KV Cache Management Optimization）的轻量学习站。

## 目标

团队成员已经具备操作系统、计算机组成、基础编程和数学基础，但对 LLM / LLM Infra 缺少统一背景。这个站点不试图系统教授整个 LLM 领域，而是提供一条约 6–8 小时的最短路线：

1. LLM / decoder-only Transformer 高层结构
2. Self-Attention 与 Q/K/V
3. Prefill / Decode
4. KV Cache
5. PagedAttention
6. Prefix Caching
7. KV Eviction / Offloading
8. LLM Serving 常用指标

训练、RLHF、LoRA、分布式训练、复杂 CUDA kernel 等内容暂不作为全员前置知识。

## 本地预览

这是纯静态站点，没有 npm / Python package 依赖。

在 `docs` 目录启动任意静态 HTTP server，例如：

```bash
python -m http.server 8000
```

然后访问：

```text
http://localhost:8000
```

也可以直接打开 `index.html`，但建议使用 HTTP server 预览，行为更接近 GitHub Pages。

## GitHub Pages 部署

当前站点放在仓库的 `docs/` 目录，因此可以直接使用 GitHub Pages 的 branch deployment：

1. GitHub 仓库 → **Settings** → **Pages**
2. `Build and deployment` 选择 **Deploy from a branch**
3. Branch 选择 `main`
4. Folder 选择 `/docs`
5. 保存

之后每次把 `docs/` 的更新 push 到 `main`，Pages 会自动重新部署。

## 文件

```text
docs/
├── index.html      # 页面结构与课程内容
├── styles.css      # 样式与响应式布局
├── app.js          # 资源列表、筛选、进度、主题
├── .nojekyll       # 告诉 GitHub Pages 直接按静态文件发布
└── README.md       # 本说明
```

## 添加资源

资源统一维护在 `app.js` 顶部的 `resources` 数组中。每项包含：

- `title`
- `source`
- `type`: `video | tutorial | paper | docs`
- `priority`: `required | recommended | optional`
- `duration`
- `difficulty`
- `url`
- `description`
- `focus`: 告诉初学者具体看什么、可以跳过什么
- `tags`

新增资源时尽量优先：官方文档、论文原文/会议页面、作者本人教程、可靠技术博客；避免为了数量收集重复或过难材料。

## 内容维护原则

- **少而精**：不是 Awesome List。
- **以 Project 5 为中心**：每项内容应该解释为什么和 KV Cache / LLM serving 有关。
- **标注阅读范围**：论文不默认要求从头读到尾。
- **全员最小共同知识优先**：深入内容留给 A/B/C 小组按职责继续学习。
- **固定实验框架版本**：真正开始 vLLM 实验后，记录使用的 vLLM commit/version，避免上游快速变化影响可复现性。

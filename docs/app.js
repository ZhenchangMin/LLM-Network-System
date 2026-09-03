const resources = [
  {
    id: "r-how-to-read-paper",
    title: "How to Read a Paper????????",
    source: "S. Keshav ? ????????",
    type: "tutorial",
    priority: "required",
    duration: "15?20 min",
    difficulty: "??",
    url: "https://web.stanford.edu/class/cs245/readings/how-to-read-a-paper.pdf",
    description: "????? three-pass method????????????????????????????????? systems ????????????????",
    focus: "??????????? Five Cs????? PagedAttention ????????????????????",
    tags: ["????", "Three-pass", "Research Skill", "????"]
  },
  {
    id: "r-stanford-paper-reading",
    title: "Reading a Paper??????? 6 ???",
    source: "Stanford CS197 ? Computer Science Research",
    type: "tutorial",
    priority: "recommended",
    duration: "10?15 min",
    difficulty: "??",
    url: "https://web.stanford.edu/class/cs197/assignments/a1.html",
    description: "Stanford ????????????????????Problem ? Prior Assumption ? Insight ? Technical Overview ? Proof/Evaluation ? Takeaway?",
    focus: "???? Project 5 ????? 6 ?????????????????????????? related work?",
    tags: ["????", "Research Skill", "Paper Notes", "Related Work"]
  },
  {
    id: "r-hf-transformer",
    title: "Transformers 是如何工作的？",
    source: "Hugging Face LLM Course · 中文",
    type: "tutorial",
    priority: "required",
    duration: "25–35 min",
    difficulty: "入门",
    url: "https://huggingface.co/learn/llm-course/zh-CN/chapter1/4",
    description: "非常适合作为全组统一起点。先建立 Transformer、decoder、attention 的高层结构，不需要先看原始论文。",
    focus: "只需要看懂 decoder-only、attention 和 token 逐步生成；encoder 细节可先跳过。",
    tags: ["Transformer", "Attention", "LLM 基础"]
  },
  {
    id: "r-karpathy",
    title: "Let's build GPT: from scratch",
    source: "Andrej Karpathy · YouTube",
    type: "video",
    priority: "optional",
    duration: "精选 45–60 min",
    difficulty: "入门→适中",
    url: "https://www.youtube.com/watch?v=kCc8FmEb1nY",
    description: "通过代码从 bigram 走到 self-attention 和 GPT。完整视频接近两小时，不建议为了本项目一次看完。",
    focus: "建议重点看 00:42–01:26 的 self-attention、multi-head attention 和 Transformer block；训练部分可略看。",
    tags: ["视频", "Attention", "GPT", "代码"]
  },
  {
    id: "r-nvidia-inference",
    title: "Mastering LLM Techniques: Inference Optimization",
    source: "NVIDIA Technical Blog",
    type: "tutorial",
    priority: "required",
    duration: "25–35 min",
    difficulty: "入门",
    url: "https://developer.nvidia.com/blog/mastering-llm-techniques-inference-optimization/",
    description: "从 serving 视角解释 LLM inference、batching、KV caching 与显存需求，是从模型概念过渡到 Infra 的好材料。",
    focus: "优先读 Key-value caching 和 memory requirement；把 prefill / decode 的差异记下来。",
    tags: ["Inference", "Prefill", "Decode", "KV Cache"]
  },
  {
    id: "r-hf-kv",
    title: "KV Cache Strategies",
    source: "Hugging Face Transformers Docs",
    type: "docs",
    priority: "required",
    duration: "20–30 min",
    difficulty: "入门",
    url: "https://huggingface.co/docs/transformers/main/kv_cache",
    description: "用很直接的方式解释为什么 autoregressive generation 需要 KV Cache，以及 dynamic、static、offloaded、quantized cache 的差别。",
    focus: "先理解 default cache 与 offloading；代码 API 不需要背。",
    tags: ["KV Cache", "Offload", "Memory"]
  },
  {
    id: "r-pagedattention",
    title: "Efficient Memory Management with PagedAttention",
    source: "Kwon et al. · SOSP 2023 / vLLM",
    type: "paper",
    priority: "required",
    duration: "45–60 min 精读",
    difficulty: "适中",
    url: "https://arxiv.org/abs/2309.06180",
    description: "Project 5 最重要的基础论文之一。它把操作系统 paging 思路迁移到 LLM KV Cache，并由此构建 vLLM。",
    focus: "不要从头逐字读。先看 Figure 1–3、Introduction、PagedAttention design；Evaluation 先理解指标和结论。",
    tags: ["PagedAttention", "vLLM", "OS", "Paging"]
  },
  {
    id: "r-vllm-prefix",
    title: "Automatic Prefix Caching",
    source: "vLLM Documentation",
    type: "docs",
    priority: "required",
    duration: "20–30 min",
    difficulty: "适中",
    url: "https://docs.vllm.ai/en/latest/examples/features/automatic_prefix_caching/",
    description: "理解“跨 request 复用 KV”的第一站：如果新请求和旧请求共享长 prefix，可以跳过共享部分的重复 prefill。",
    focus: "先看概念和示例 workload；之后再看 vLLM 的 block hashing / eviction design。",
    tags: ["Prefix Cache", "Reuse", "vLLM"]
  },
  {
    id: "r-vllm-offload",
    title: "KV Offloading Usage Guide",
    source: "vLLM Documentation",
    type: "docs",
    priority: "required",
    duration: "30–40 min",
    difficulty: "适中",
    url: "https://docs.vllm.ai/en/latest/features/kv_offloading_usage/",
    description: "直接对应 Project 5：GPU KV 可以转移到更大但更慢的 CPU tier；当前文档还覆盖多层 tier 和 custom eviction policy。",
    focus: "先看 Overview、Single-Tier、Custom Eviction Policies。Secondary tier 的工程细节先跳过。",
    tags: ["Offload", "Eviction", "LRU", "ARC", "vLLM"]
  },
  {
    id: "r-vllm-bench",
    title: "vLLM Benchmark CLI",
    source: "vLLM Documentation",
    type: "docs",
    priority: "recommended",
    duration: "20–30 min",
    difficulty: "适中",
    url: "https://docs.vllm.ai/en/latest/benchmarking/cli/",
    description: "后续 A/C 组会频繁用到。先认识 TTFT、TPOT/ITL、throughput 和 percentile，不需要现在掌握所有命令行参数。",
    focus: "重点是知道每个指标回答什么问题，而不是记 CLI。",
    tags: ["Benchmark", "TTFT", "TPOT", "Throughput"]
  },
  {
    id: "r-sglang",
    title: "SGLang & RadixAttention",
    source: "Zheng et al. · NeurIPS 2024",
    type: "paper",
    priority: "recommended",
    duration: "35–50 min 精读",
    difficulty: "适中",
    url: "https://proceedings.neurips.cc/paper_files/paper/2024/hash/724be4472168f31ba1c9ac630f15dec8-Abstract-Conference.html",
    description: "另一个重要 serving system。RadixAttention 展示了如何利用 radix tree 管理可复用 prefix KV，对 RAG、多轮对话和 structured workloads 很有启发。",
    focus: "只看 runtime / RadixAttention 相关部分；frontend language 不是 Project 5 的重点。",
    tags: ["SGLang", "RadixAttention", "Prefix Cache"]
  },
  {
    id: "r-lmcache",
    title: "LMCache: KV Cache Management Layer",
    source: "LMCache Documentation",
    type: "docs",
    priority: "recommended",
    duration: "20–30 min",
    difficulty: "适中",
    url: "https://docs.lmcache.ai/zh_CN/",
    description: "从工程系统角度看 KV Cache 如何变成可持久、可跨 serving engine 复用的独立资源层，对长上下文、RAG、agent workload 很相关。",
    focus: "先浏览 Overview 和架构，不需要立刻安装。把它当成 Project 5 的 design-space 参考。",
    tags: ["LMCache", "Multi-tier", "RAG", "Agent"]
  },
  {
    id: "r-mooncake",
    title: "Mooncake: KVCache-centric LLM Serving",
    source: "FAST 2025 · Moonshot AI",
    type: "paper",
    priority: "optional",
    duration: "40–60 min 选读",
    difficulty: "进阶",
    url: "https://www.usenix.org/conference/fast25/presentation/qin",
    description: "把 CPU DRAM、SSD 等资源纳入 KVCache pool，并围绕 KV Cache 重新组织 serving architecture。适合想理解学术界上限的同学。",
    focus: "先读动机和 architecture 图。RDMA、分布式细节不是当前单 GPU Project 的前置知识。",
    tags: ["Mooncake", "Tiering", "Storage", "Advanced"]
  },
  {
    id: "r-continuous-batching",
    title: "Continuous Batching from First Principles",
    source: "Hugging Face Blog",
    type: "tutorial",
    priority: "optional",
    duration: "30–45 min",
    difficulty: "适中",
    url: "https://huggingface.co/blog/continuous_batching",
    description: "把 KV cache、request batching 和 autoregressive serving 放在同一个例子里解释。对想理解‘为什么 serving engine 不只是 model.generate()’很有帮助。",
    focus: "重点看 KV-cache 与 continuous batching 的关系；无需复现全部实现。",
    tags: ["Batching", "KV Cache", "Serving"]
  }
];

const typeLabels = {
  video: "Video",
  tutorial: "Tutorial",
  paper: "Paper",
  docs: "Docs"
};

const priorityLabels = {
  required: "必看",
  recommended: "推荐",
  optional: "选读"
};

const resourceGrid = document.getElementById("resourceGrid");
const emptyState = document.getElementById("emptyState");
const searchInput = document.getElementById("resourceSearch");
const filterButtons = [...document.querySelectorAll(".filter-chip")];
let activeFilter = "all";

function resourceCard(resource) {
  const tags = resource.tags.map(tag => `<span>#${tag}</span>`).join("");
  return `
    <article class="resource-card" id="${resource.id}" data-type="${resource.type}">
      <div class="resource-top">
        <span class="resource-type">${typeLabels[resource.type]}</span>
        <span class="resource-priority ${resource.priority}">${priorityLabels[resource.priority]}</span>
        <span class="resource-duration">${resource.duration}</span>
      </div>
      <h3>${resource.title}</h3>
      <p class="resource-source">${resource.source} · ${resource.difficulty}</p>
      <p>${resource.description}</p>
      <div class="resource-focus"><strong>怎么读：</strong>${resource.focus}</div>
      <div class="resource-footer">
        <div class="resource-tags">${tags}</div>
        <a class="resource-link" href="${resource.url}" target="_blank" rel="noreferrer">打开 ↗</a>
      </div>
    </article>`;
}

function renderResources() {
  const query = searchInput.value.trim().toLowerCase();
  const filtered = resources.filter(resource => {
    const matchesType = activeFilter === "all" || resource.type === activeFilter;
    const haystack = [resource.title, resource.source, resource.description, resource.focus, ...resource.tags].join(" ").toLowerCase();
    return matchesType && haystack.includes(query);
  });
  resourceGrid.innerHTML = filtered.map(resourceCard).join("");
  emptyState.hidden = filtered.length !== 0;
}

filterButtons.forEach(button => {
  button.addEventListener("click", () => {
    activeFilter = button.dataset.filter;
    filterButtons.forEach(item => item.classList.toggle("active", item === button));
    renderResources();
  });
});
searchInput.addEventListener("input", renderResources);
renderResources();

const progressChecks = [...document.querySelectorAll(".progress-check")];
const progressBar = document.getElementById("progressBar");
const progressText = document.getElementById("progressText");
const progressHint = document.getElementById("progressHint");
const progressKey = "llm-infra-learning-progress-v1";

function loadProgress() {
  let saved = {};
  try { saved = JSON.parse(localStorage.getItem(progressKey) || "{}"); } catch (_) { saved = {}; }
  progressChecks.forEach(check => { check.checked = Boolean(saved[check.dataset.progress]); });
  updateProgress(false);
}

function updateProgress(save = true) {
  const completed = progressChecks.filter(check => check.checked).length;
  progressText.textContent = `${completed} / ${progressChecks.length}`;
  progressBar.style.width = `${(completed / progressChecks.length) * 100}%`;
  progressChecks.forEach(check => {
    check.closest(".step-card").classList.toggle("completed", check.checked);
  });
  if (completed === 0) progressHint.textContent = "从 Step 1 开始。完成项会保存在你的浏览器中。";
  else if (completed < 4) progressHint.textContent = "基础模型正在建立。先别急着啃系统论文。";
  else if (completed < 7) progressHint.textContent = "已经进入 LLM Infra 核心：把 OS 知识迁移过来。";
  else if (completed < 8) progressHint.textContent = "只差最后一步：学会用指标解释系统行为。";
  else progressHint.textContent = "核心路线完成。现在可以进入 baseline / profiling / policy design。";

  if (save) {
    const state = Object.fromEntries(progressChecks.map(check => [check.dataset.progress, check.checked]));
    localStorage.setItem(progressKey, JSON.stringify(state));
  }
}

progressChecks.forEach(check => check.addEventListener("change", () => updateProgress(true)));
document.getElementById("resetProgress").addEventListener("click", () => {
  progressChecks.forEach(check => { check.checked = false; });
  localStorage.removeItem(progressKey);
  updateProgress(false);
});
loadProgress();

const themeToggle = document.getElementById("themeToggle");
const themeKey = "llm-infra-learning-theme";
function setTheme(theme) {
  document.documentElement.dataset.theme = theme;
  themeToggle.textContent = theme === "dark" ? "☀" : "◐";
  themeToggle.title = theme === "dark" ? "切换到浅色主题" : "切换到深色主题";
}
const savedTheme = localStorage.getItem(themeKey);
setTheme(savedTheme || (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"));
themeToggle.addEventListener("click", () => {
  const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  localStorage.setItem(themeKey, next);
  setTheme(next);
});

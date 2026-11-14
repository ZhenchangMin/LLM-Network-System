#!/usr/bin/env bash
set -euo pipefail

REPO="/root/bayes-tmp/peek"
PYTHON="$REPO/.venv/bin/python"
EXPECTED_SHA="3aca72b63c1dd6433193c0857b965acecdbfbb8a"

MODEL="/root/bayes-tmp/kvcache/models/Qwen2.5-3B-Instruct"
PORT=30001

LOG_DIR="$REPO/b-group/results"
LOG_FILE="$LOG_DIR/peek_server.log"

cd "$REPO"
mkdir -p "$LOG_DIR"

# 1. 检查独立环境
if [[ ! -x "$PYTHON" ]]; then
    echo "ERROR: B组Python环境不存在"
    exit 1
fi

# 2. 检查PEEK固定版本
CURRENT_SHA="$(git rev-parse HEAD)"

if ! git merge-base --is-ancestor "$EXPECTED_SHA" HEAD; then
    echo "ERROR: 当前HEAD不包含指定的PEEK基准Commit"
    echo "Base:    $EXPECTED_SHA"
    echo "Current: $CURRENT_SHA"
    exit 1
fi

echo "PEEK base commit verified: ${EXPECTED_SHA:0:7}"
echo "Current HEAD: ${CURRENT_SHA:0:7}"

# 3. 启用PEEK Online
export PEEK_PRESET=peek-online
export PYTHONPATH="$REPO/scripts/peek_sitecustomize:$REPO/python:${PYTHONPATH:-}"

# B3 correctness/debug mode; disable for performance benchmarks.
if [[ "${B3_DEBUG:-0}" == "1" ]]; then
    export PEEK_ONLINE_VALIDATE=1
    export PEEK_ONLINE_PROFILE=1
    export PEEK_ONLINE_EVICTION_DEBUG=1
fi

# 4. 设置启动参数
CMD=(
    "$PYTHON" -m sglang.launch_server
    --model-path "$MODEL"
    --dtype bfloat16
    --tp-size 1
    --schedule-policy lpm
    --enable-cache-report
    --mem-fraction-static 0.75
    --max-total-tokens 8192
    --host 127.0.0.1
    --port "$PORT"
)

# 允许附加与A组一致的运行参数
CMD+=("$@")

# 5. 打印启动信息
echo "===== B3 PEEK Online ====="
echo "Time: $(date -Is)"
echo "Repository: $REPO"
echo "Commit: $CURRENT_SHA"
echo "Python: $PYTHON"
echo "PEEK_PRESET: $PEEK_PRESET"
echo "PYTHONPATH: $PYTHONPATH"
echo "Model: $MODEL"
echo "Port: $PORT"

"$PYTHON" -m pip show sglang torch \
    | grep -E '^(Name|Version):'

printf 'Command: '
printf '%q ' "${CMD[@]}"
printf '\n'

# 6. 无GPU模式：只检查，不启动服务
if [[ "${B3_DRY_RUN:-0}" == "1" ]]; then
    echo "DRY RUN: 配置检查完成，未启动SGLang"
    exit 0
fi

# 7. 正式启动前检查GPU
if ! "$PYTHON" -c \
    'import torch; assert torch.cuda.is_available(), "CUDA GPU unavailable"'
then
    echo "ERROR: 当前没有可用GPU，停止启动"
    exit 1
fi

if [[ ! -d "$MODEL" ]]; then
    echo "ERROR: 模型目录不存在"
    exit 1
fi

# 8. 启动并保存日志
echo "Starting PEEK Online..."
"${CMD[@]}" 2>&1 | tee -a "$LOG_FILE"

"""B3 integration tests for PEEK Online + SGLang 0.5.9."""

import os
import subprocess
import sys

import pytest


REPO = "/root/bayes-tmp/peek"
EXPECTED_SHA = "3aca72b63c1dd6433193c0857b965acecdbfbb8a"


def test_environment_versions():
    """Check the B-group Python environment and core dependencies."""
    from importlib.metadata import version

    import torch
    from peek import PendingTree

    assert version("sglang") == "0.5.9"
    assert torch.__version__ == "2.9.1+cu128"
    assert torch.version.cuda == "12.8"
    assert PendingTree is not None


def test_fixed_commit():
    """Check that HEAD descends from the fixed PEEK base commit."""
    result = subprocess.run(
        ["git", "-C", REPO, "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    )

    assert result.stdout.strip()
    ancestor = subprocess.run(
        ["git", "-C", REPO, "merge-base", "--is-ancestor",
         EXPECTED_SHA, "HEAD"],
        capture_output=True,
        text=True,
    )
    assert ancestor.returncode == 0, (
        f"PEEK基准Commit不是当前HEAD的祖先: {ancestor.stderr}"
    )


def test_peek_hook_methods():
    """Verify actual monkey-patched SGLang methods in a new process."""
    code = r'''
from sglang.srt.mem_cache.radix_cache import RadixCache
from sglang.srt.managers.scheduler import Scheduler
from sglang.srt.managers.schedule_policy import SchedulePolicy

checks = {
    "RadixCache.__init__": (
        RadixCache.__init__, "_patched_radix_init"
    ),
    "Scheduler.process_input_requests": (
        Scheduler.process_input_requests, "_patched_process_input"
    ),
    "Scheduler.get_next_batch_to_run": (
        Scheduler.get_next_batch_to_run, "_patched_get_next_batch"
    ),
    "SchedulePolicy.calc_priority": (
        SchedulePolicy.calc_priority, "_patched_calc_priority"
    ),
}

for name, (func, expected) in checks.items():
    assert func.__name__ == expected, (name, func.__name__)
    assert func.__module__ == "peek.online.engines.sglang.patch_hook"
    print("PATCHED:", name, "=>", func.__name__)
'''

    env = os.environ.copy()
    env["PEEK_PRESET"] = "peek-online"
    env["PYTHONPATH"] = os.pathsep.join([
        f"{REPO}/scripts/peek_sitecustomize",
        f"{REPO}/python",
        env.get("PYTHONPATH", ""),
    ])

    result = subprocess.run(
        [sys.executable, "-c", code],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )

    print(result.stdout)

    assert result.returncode == 0, result.stderr
    assert result.stdout.count("PATCHED:") == 4


if __name__ == "__main__":
    raise SystemExit("Run this file using pytest.")


# ===== GPU-only integration tests =====

import json
import urllib.request
from concurrent.futures import ThreadPoolExecutor

ONLINE = os.environ.get("B3_TEST_ONLINE") == "1"
BASE_URL = os.environ.get("B3_BASE_URL", "http://127.0.0.1:30001")
MODEL = "/root/bayes-tmp/kvcache/models/Qwen2.5-3B-Instruct"


def request_json(path, payload=None):
    data = None
    headers = {}

    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = urllib.request.Request(
        BASE_URL + path,
        data=data,
        headers=headers,
        method="POST" if payload is not None else "GET",
    )

    with urllib.request.urlopen(request, timeout=120) as response:
        content = response.read()
        return response.status, json.loads(content) if content else {}


def generate(prompt, max_tokens=32):
    status, response = request_json(
        "/v1/chat/completions",
        {
            "model": MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
            "max_tokens": max_tokens,
            "stream": False,
        },
    )

    assert status == 200
    assert response.get("choices")
    return response


@pytest.mark.skipif(not ONLINE, reason="Requires GPU server")
def test_health():
    status, _ = request_json("/health")
    assert status == 200


@pytest.mark.skipif(not ONLINE, reason="Requires GPU server")
def test_basic_generation():
    result = generate("Say hello in one short sentence.")
    assert result["choices"][0]["message"]["content"] is not None


@pytest.mark.skipif(not ONLINE, reason="Requires GPU server")
def test_shared_prefix():
    prefix = (
        "This document discusses KV cache management, "
        "prefix reuse, and language model inference. "
    ) * 16

    result1 = generate(prefix + "\nQuestion: What is KV cache?")
    result2 = generate(prefix + "\nQuestion: What is prefix reuse?")

    assert result1["choices"]
    assert result2["choices"]

    print("Shared-prefix requests completed.")
    print("Server-side cache-hit evidence still required.")


@pytest.mark.skipif(not ONLINE, reason="Requires GPU server")
def test_concurrency():
    count = int(os.environ.get("B3_CONCURRENCY", "8"))
    assert 1 <= count <= 64

    prefix = "Shared context for PEEK Online testing. " * 16

    def worker(index):
        result = generate(
            prefix + f"Question {index}: Say the number {index}.",
            max_tokens=16,
        )
        return bool(result["choices"])

    with ThreadPoolExecutor(max_workers=count) as executor:
        results = list(executor.map(worker, range(count)))

    assert all(results)
    print(f"Concurrent requests passed: {count}/{count}")

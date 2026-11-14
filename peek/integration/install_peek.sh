#!/usr/bin/env bash
# Run with: bash b-group/scripts/install_peek.sh
set -euo pipefail

PEEK_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$PEEK_ROOT"
mkdir -p b-group/results
exec > >(tee -a b-group/results/cpu_tests.log) 2>&1
trap 'echo "Installation/checks failed at line $LINENO"' ERR

echo "=== B2 installation and CPU verification ==="
date -Is

EXPECTED_SHA=3aca72b63c1dd6433193c0857b965acecdbfbb8a
ACTUAL_SHA="$(git rev-parse HEAD)"
echo "PEEK official base SHA: $EXPECTED_SHA"
echo "Current project HEAD: $ACTUAL_SHA"

# Preserve an EXACT pinned upstream PEEK codebase, even when B-group adds
# downstream test/docs commits. A different HEAD is fine; a change to any
# upstream tracked file is NOT. This is stricter than ancestry alone.
if ! git merge-base --is-ancestor "$EXPECTED_SHA" HEAD; then
    echo "Current HEAD does not descend from the official pinned PEEK commit." >&2
    exit 1
fi
if ! git diff --quiet "$EXPECTED_SHA" -- . ':(exclude)b-group/**'; then
    echo "PEEK upstream tracked code differs from pinned $EXPECTED_SHA; stopping." >&2
    git diff --name-only "$EXPECTED_SHA" -- . ':(exclude)b-group/**' >&2
    exit 1
fi
UNTRACKED_UPSTREAM="$(git ls-files --others --exclude-standard -- . ':(exclude)b-group/**')"
if [[ -n "$UNTRACKED_UPSTREAM" ]]; then
    echo "Untracked files outside b-group could change the pinned implementation:" >&2
    printf '%s\n' "$UNTRACKED_UPSTREAM" >&2
    exit 1
fi
echo "Verified: upstream PEEK source unchanged from pinned commit."

# Use the project environment, never A group's environment.
if [[ ! -x .venv/bin/python ]]; then
    python3.12 -m venv .venv
fi
source .venv/bin/activate
python -c 'import sys; assert sys.version_info[:2] == (3, 12)'

# Resolve the Conda + venv ambiguity encountered during installation.
unset CONDA_PREFIX
export PATH="/root/.cargo/bin:$PATH"
export CARGO_BUILD_JOBS=2

if ! command -v rustup >/dev/null 2>&1; then
    INSTALLER="$(mktemp)"
    curl --fail --location \
        --connect-timeout 15 --max-time 120 \
        https://sh.rustup.rs -o "$INSTALLER"
    sh "$INSTALLER" -y --profile minimal \
        --default-toolchain none --no-modify-path
    rm -f "$INSTALLER"
fi

# Reuse the verified compiler if present; otherwise install that version.
if [[ "$(rustc --version 2>/dev/null)" != "rustc 1.99.1 "* ]]; then
    rustup toolchain install 1.99.1 --profile minimal
    export RUSTUP_TOOLCHAIN=1.99.1
fi

python -m pip install "maturin==1.16.0" "pytest==9.2.0"

python --version
rustc --version
cargo --version
python -m maturin --version
python -m pytest --version

python -m maturin develop --release
python -c 'from peek import PendingTree; print(type(PendingTree()))'
python -m pip show peek

cargo test --release
python -m pytest -m "not gpu" -v -ra \
    tests/online/ b-group/tests/test_peek_mechanisms.py

echo "=== B2 installation and CPU verification completed ==="
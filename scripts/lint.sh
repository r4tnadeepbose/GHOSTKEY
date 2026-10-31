#!/usr/bin/env bash
# Run static checks: ruff (if installed), byte-compile, and unit tests.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"

PY="${PYTHON_BIN:-python3}"

echo "ghostkey :: lint"

if "$PY" -m ruff --version >/dev/null 2>&1; then
    "$PY" -m ruff check .
    "$PY" -m ruff format --check .
else
    echo "  ruff not installed; skipping lint (pip install ruff)"
fi

echo "ghostkey :: compile"
"$PY" -m py_compile scan.py

echo "ghostkey :: tests"
"$PY" -m unittest discover -s tests -v

echo "ok"

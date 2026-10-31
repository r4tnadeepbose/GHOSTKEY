#!/usr/bin/env bash
# Launch Ghostkey using the project virtualenv when available.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"

if [ -x .venv/bin/python ]; then
    exec ./.venv/bin/python scan.py
else
    exec "${PYTHON_BIN:-python3}" scan.py
fi

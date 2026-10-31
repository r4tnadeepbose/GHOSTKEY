#!/usr/bin/env bash
# Create a virtual environment and install Ghostkey dependencies.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"

PYTHON_BIN="${PYTHON_BIN:-python3}"
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
    echo "error: $PYTHON_BIN not found. Install Python 3.10+." >&2
    exit 1
fi

echo "ghostkey :: setup"
echo "  using $($PYTHON_BIN --version)"

if [ ! -d .venv ]; then
    echo "  creating .venv"
    "$PYTHON_BIN" -m venv .venv
fi

./.venv/bin/python -m pip install --upgrade pip
./.venv/bin/python -m pip install -r requirements.txt

if ! ./.venv/bin/python -c "import tkinter" >/dev/null 2>&1; then
    echo "warning: tkinter is missing. Install python3-tk (Debian/Ubuntu) or tk (Arch)." >&2
fi

echo
echo "done. launch with:"
echo "  ./.venv/bin/python scan.py"

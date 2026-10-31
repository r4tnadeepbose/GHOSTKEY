#!/usr/bin/env python3
"""Print an environment report for bug reports (no credentials, no activity)."""

from __future__ import annotations

import os
import platform
import shutil
import sys
from pathlib import Path


def main() -> int:
    print("ghostkey :: environment")
    print(f"  python      {sys.version.split()[0]}")
    print(f"  executable  {sys.executable}")
    print(f"  platform    {platform.platform()}")
    print(f"  machine     {platform.machine()}")

    try:
        import tkinter  # noqa: F401
        print("  tkinter     ok")
    except Exception as exc:  # pragma: no cover - environment dependent
        print(f"  tkinter     MISSING ({exc})")

    try:
        import requests
        print(f"  requests    {requests.__version__}")
    except Exception:
        print("  requests    MISSING (pip install requests)")

    data_dir = Path.home() / ".ghostkey"
    print(f"  data dir    {data_dir} ({'exists' if data_dir.exists() else 'not created yet'})")

    if sys.platform.startswith("linux"):
        print(f"  display     DISPLAY={os.environ.get('DISPLAY', '(unset)')}")
        print(f"  xdotool     {shutil.which('xdotool') or 'missing'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

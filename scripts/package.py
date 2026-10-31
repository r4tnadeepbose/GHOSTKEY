#!/usr/bin/env python3
"""Build a distributable source archive under dist/.

The archive contains the application, docs, scripts, and repo metadata. Runtime
data, virtualenvs, caches, and local config are excluded.
"""

from __future__ import annotations

import re
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"

EXCLUDE_DIRS = {
    ".git", ".venv", "venv", "env", "__pycache__", "dist", "build",
    ".pytest_cache", ".ruff_cache", ".mypy_cache", ".idea", ".vscode",
    ".ghostkey", "exports", "htmlcov",
}
EXCLUDE_NAMES = {
    ".env", "config.json", "events.log", "digests.log", "buffer.txt",
}
EXCLUDE_SUFFIXES = {".pyc", ".pyo", ".log", ".zip"}


def project_version() -> str:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    return match.group(1) if match else "0.0.0"


def iter_files():
    for path in sorted(ROOT.rglob("*")):
        rel = path.relative_to(ROOT)
        if any(part in EXCLUDE_DIRS for part in rel.parts):
            continue
        if path.name in EXCLUDE_NAMES or path.suffix in EXCLUDE_SUFFIXES:
            continue
        if path.is_file():
            yield path, rel


def main() -> int:
    version = project_version()
    DIST.mkdir(exist_ok=True)
    target = DIST / f"ghostkey-{version}.zip"
    files = list(iter_files())
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for path, rel in files:
            archive.write(path, Path("ghostkey") / rel)
    size = target.stat().st_size / 1024
    print(f"built {target} ({len(files)} files, {size:.1f} KiB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

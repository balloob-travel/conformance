#!/usr/bin/env python3
"""Bootstrap a local development environment for the conformance repo."""

from __future__ import annotations

import argparse
import subprocess
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from conformance.implementations import resolve_repo_path
from conformance.paths import repo_root


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--venv", default=str(repo_root() / ".venv"))
    parser.add_argument("--clone", action="store_true")
    return parser


def pick_python() -> str:
    """Return the preferred Python executable for the venv bootstrap."""
    for candidate in ("python3.14", "python3.13", "python3.12", "python3.11"):
        path = shutil.which(candidate)
        if path:
            return path
    return sys.executable


def main() -> int:
    args = build_parser().parse_args()
    root = repo_root()
    venv = Path(args.venv)

    if args.clone:
        subprocess.run([sys.executable, str(root / "scripts" / "setup_repositories.py")], check=True)

    subprocess.run([pick_python(), "-m", "venv", str(venv)], check=True)
    python = venv / "bin" / "python"
    pip = [str(python), "-m", "pip"]
    subprocess.run([*pip, "install", "--upgrade", "pip"], check=True)
    subprocess.run([*pip, "install", "-e", str(root)], check=True)

    aiosendspin_repo = resolve_repo_path("aiosendspin")
    if aiosendspin_repo is not None:
        subprocess.run([*pip, "install", "-e", str(aiosendspin_repo)], check=True)

    print(f"Environment ready: {python}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

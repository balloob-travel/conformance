#!/usr/bin/env python3
"""Clone the implementation repositories used by the conformance suite."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from conformance.implementations import IMPLEMENTATIONS, SUPPORTING_REPOS
from conformance.paths import repo_root


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repos-dir", default=str(repo_root() / "repos"))
    parser.add_argument("--update", action="store_true")
    return parser


def clone_or_update(target: Path, url: str, update: bool) -> None:
    if target.exists():
        if update:
            subprocess.run(["git", "-C", str(target), "pull", "--ff-only"], check=True)
        return
    subprocess.run(["git", "clone", url, str(target)], check=True)


def main() -> int:
    args = build_parser().parse_args()
    repos_dir = Path(args.repos_dir)
    repos_dir.mkdir(parents=True, exist_ok=True)

    for spec in IMPLEMENTATIONS.values():
        clone_or_update(repos_dir / spec.repo_dirname, spec.remote_url, args.update)
    for dirname, url in SUPPORTING_REPOS.values():
        clone_or_update(repos_dir / dirname, url, args.update)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

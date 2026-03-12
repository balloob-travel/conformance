#!/usr/bin/env python3
"""Merge host-specific conformance result directories into one report."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from conformance.merge import merge_results_dirs
from conformance.site import build_site


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--site-dir")
    parser.add_argument("inputs", nargs="+")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    output_dir = Path(args.output_dir)
    site_dir = Path(args.site_dir) if args.site_dir else output_dir
    summary = merge_results_dirs(
        input_dirs=[Path(item) for item in args.inputs],
        output_dir=output_dir,
    )
    build_site(output_dir, site_dir)
    print(
        "Merged "
        f"{summary['input_count']} result directories, "
        f"{summary['result_count']} cases, "
        f"{summary['build_count']} build entries.",
        flush=True,
    )
    print(f"Report written to {(site_dir / 'index.html').resolve()}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Build adapters, run the matrix, and generate the static report."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from conformance.build import build_adapters
from conformance.runner import run_matrix
from conformance.site import build_site


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results-dir", default=str(ROOT / "results"))
    parser.add_argument("--site-dir")
    parser.add_argument("--build-report-path", default=str(ROOT / "artifacts" / "build-report.json"))
    parser.add_argument("--from", dest="from_filter")
    parser.add_argument("--to", dest="to_filter")
    parser.add_argument("--timeout-seconds", type=float, default=40.0)
    parser.add_argument("--jobs", type=int, default=min(4, os.cpu_count() or 1))
    return parser


def main() -> int:
    args = build_parser().parse_args()
    results_dir = Path(args.results_dir)
    site_dir = Path(args.site_dir) if args.site_dir else results_dir

    build_results = build_adapters(Path(args.build_report_path))
    matrix_results = asyncio.run(
        run_matrix(
            results_dir=results_dir,
            from_filter=args.from_filter,
            to_filter=args.to_filter,
            timeout_s=args.timeout_seconds,
            jobs=args.jobs,
        )
    )
    build_site(results_dir, site_dir)
    del build_results
    del matrix_results
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

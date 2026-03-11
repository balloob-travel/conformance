"""Top-level CLI for the conformance harness."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from .runner import run_matrix
from .site import build_site


def build_parser() -> argparse.ArgumentParser:
    """Create the root CLI parser."""
    parser = argparse.ArgumentParser(prog="conformance")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run the current matrix")
    run_parser.add_argument("--results-dir", default="results")
    run_parser.add_argument("--from", dest="from_filter")
    run_parser.add_argument("--to", dest="to_filter")
    run_parser.add_argument("--timeout-seconds", type=float, default=40.0)

    report_parser = subparsers.add_parser("report", help="Generate a static report site")
    report_parser.add_argument("--results-dir", default="results")
    report_parser.add_argument("--site-dir", default="site")
    return parser


def main() -> int:
    """CLI entrypoint."""
    parser = build_parser()
    args = parser.parse_args()
    if args.command == "run":
        asyncio.run(
            run_matrix(
                results_dir=Path(args.results_dir),
                from_filter=args.from_filter,
                to_filter=args.to_filter,
                timeout_s=args.timeout_seconds,
            )
        )
        return 0
    if args.command == "report":
        build_site(Path(args.results_dir), Path(args.site_dir))
        return 0
    parser.error(f"Unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

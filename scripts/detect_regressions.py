#!/usr/bin/env python3
"""Detect test regressions by comparing local results against the published baseline.

Fetches the current index.json from the live GitHub Pages site and compares it
against a local results directory.  A *regression* is any case that was
``passed`` in the baseline but is no longer ``passed`` in the local run.

Exit codes:
    0 – no regressions detected (or baseline unavailable)
    1 – one or more regressions found

Optional outputs:
    --discord-file PATH   write a Discord-ready notification to PATH
    --github-summary      append a Markdown summary to $GITHUB_STEP_SUMMARY
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import textwrap
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from conformance.io import read_json

BASELINE_URL = (
    "https://sendspin.github.io/conformance/data/index.json"
)


def _case_key(result: dict[str, object]) -> tuple[str, str, str]:
    """Unique identity for a matrix cell, ignoring environment."""
    return (
        str(result["scenario_id"]),
        str(result["server_impl"]),
        str(result["client_impl"]),
    )


def fetch_baseline(url: str, timeout: int = 30) -> list[dict[str, object]] | None:
    """Fetch the published baseline index.json, returning None on failure."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "sendspin-conformance-ci"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode())
            return list(payload["results"])
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, KeyError) as exc:
        print(f"Warning: could not fetch baseline from {url}: {exc}", file=sys.stderr)
        return None


def detect_regressions(
    baseline: list[dict[str, object]],
    current: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Return current results that regressed from a passed baseline."""
    baseline_passed: dict[tuple[str, str, str], dict[str, object]] = {}
    for result in baseline:
        key = _case_key(result)
        if result["status"] == "passed":
            baseline_passed[key] = result

    regressions: list[dict[str, object]] = []
    for result in current:
        key = _case_key(result)
        if key in baseline_passed and result["status"] != "passed":
            regressions.append(result)
    return regressions


def format_regression_table(regressions: list[dict[str, object]]) -> str:
    """Format regressions as a human-readable table."""
    lines: list[str] = []
    for r in sorted(regressions, key=_case_key):
        lines.append(
            f"  {r['scenario_id']}  {r['server_impl']} -> {r['client_impl']}  "
            f"[{r['status']}]"
        )
    return "\n".join(lines)


def format_github_summary(regressions: list[dict[str, object]]) -> str:
    """Format regressions as Markdown for $GITHUB_STEP_SUMMARY."""
    lines: list[str] = [
        "## Conformance regressions detected",
        "",
        f"**{len(regressions)}** test(s) that previously passed are now failing.",
        "",
        "| Scenario | Server | Client | Status |",
        "| --- | --- | --- | --- |",
    ]
    for r in sorted(regressions, key=_case_key):
        lines.append(
            f"| {r['scenario_id']} | {r['server_impl']} | {r['client_impl']} "
            f"| {r['status']} |"
        )
    return "\n".join(lines)


def format_discord_message(regressions: list[dict[str, object]]) -> str:
    """Build a Discord notification for regressions found during site publish."""
    count = len(regressions)
    header = (
        f"\u26a0\ufe0f **Conformance regression{'s' if count != 1 else ''} detected** "
        f"— {count} test{'s' if count != 1 else ''} that previously passed "
        f"{'are' if count != 1 else 'is'} now failing."
    )

    rows: list[str] = []
    for r in sorted(regressions, key=_case_key):
        rows.append(
            f"- **{r['scenario_id']}**: {r['server_impl']} \u2192 {r['client_impl']} "
            f"[{r['status']}]"
        )

    body = "\n".join(rows)

    footer = textwrap.dedent("""\
        Review the full report: <https://sendspin.github.io/conformance/>
    """).strip()

    return f"{header}\n\n{body}\n\n{footer}\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--results-dir",
        default=str(ROOT / "artifacts" / "results"),
        help="Path to the local results directory (default: artifacts/results)",
    )
    parser.add_argument(
        "--baseline-url",
        default=BASELINE_URL,
        help="URL of the published baseline index.json",
    )
    parser.add_argument(
        "--discord-file",
        help="Write Discord notification text to this file when regressions are found",
    )
    parser.add_argument(
        "--github-summary",
        action="store_true",
        help="Append regression summary to $GITHUB_STEP_SUMMARY",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()

    results_dir = Path(args.results_dir)
    index_path = results_dir / "data" / "index.json"
    if not index_path.exists():
        print(f"Error: local results not found at {index_path}", file=sys.stderr)
        return 1

    current_results: list[dict[str, object]] = list(read_json(index_path)["results"])
    print(f"Local results: {len(current_results)} cases", flush=True)

    baseline = fetch_baseline(args.baseline_url)
    if baseline is None:
        print("Baseline unavailable — skipping regression check.", flush=True)
        return 0

    passed_in_baseline = sum(1 for r in baseline if r["status"] == "passed")
    print(
        f"Baseline: {len(baseline)} cases ({passed_in_baseline} passed)",
        flush=True,
    )

    regressions = detect_regressions(baseline, current_results)

    if not regressions:
        print("No regressions detected.", flush=True)
        return 0

    print(
        f"\n{len(regressions)} regression(s) detected:\n"
        f"{format_regression_table(regressions)}\n",
        flush=True,
    )

    if args.github_summary:
        summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
        if summary_path:
            with open(summary_path, "a", encoding="utf-8") as fh:
                fh.write("\n" + format_github_summary(regressions) + "\n")

    if args.discord_file:
        discord_path = Path(args.discord_file)
        discord_path.parent.mkdir(parents=True, exist_ok=True)
        discord_path.write_text(format_discord_message(regressions), encoding="utf-8")
        print(f"Discord notification written to {discord_path}", flush=True)

    return 1


if __name__ == "__main__":
    raise SystemExit(main())

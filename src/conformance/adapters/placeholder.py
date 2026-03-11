"""Fail-fast placeholder adapter for unimplemented roles."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from conformance.io import write_json


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--implementation", required=True)
    parser.add_argument("--role", required=True, choices=("server", "client"))
    parser.add_argument("--failure-reason", required=True)
    parser.add_argument("--summary", required=True)
    parser.add_argument("--ready", required=True)
    parser.add_argument("--registry", required=True)
    parser.add_argument("--client-name")
    parser.add_argument("--client-id")
    parser.add_argument("--server-id")
    parser.add_argument("--server-name")
    parser.add_argument("--fixture")
    parser.add_argument("--timeout-seconds")
    parser.add_argument("--scenario-id")
    parser.add_argument("--initiator-role")
    parser.add_argument("--preferred-codec")
    parser.add_argument("--port")
    parser.add_argument("--path")
    parser.add_argument("--log-level")
    return parser


def main() -> int:
    args = build_parser().parse_args()

    summary = {
        "status": "error",
        "implementation": args.implementation,
        "role": args.role,
        "reason": args.failure_reason,
        "peer_hello": None,
    }
    if args.client_name:
        summary["client_name"] = args.client_name
    if args.client_id:
        summary["client_id"] = args.client_id
    if args.server_id:
        summary["server_id"] = args.server_id
    if args.server_name:
        summary["server_name"] = args.server_name
    if args.fixture:
        summary["fixture"] = args.fixture
    if args.scenario_id:
        summary["scenario_id"] = args.scenario_id
    if args.initiator_role:
        summary["initiator_role"] = args.initiator_role
    if args.preferred_codec:
        summary["preferred_codec"] = args.preferred_codec

    write_json(Path(args.ready), {"status": "ready", "implementation": args.implementation})
    write_json(Path(args.summary), summary)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

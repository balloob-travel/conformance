# Sendspin Conformance

Capability-aware conformance harness for local Sendspin implementations.

The first scenario in this repository is intentionally narrow:

- start the server first
- start the client second
- complete discovery and handshake
- stream `almost_silent.flac`
- disconnect cleanly
- compare canonical PCM hashes from both summaries

## Current coverage

- `aiosendspin`: real server adapter and real client adapter
- `sendspin-dotnet`: real client adapter source, server placeholder
- `SendspinKit`: placeholder capability entry for the initial scenario
- `sendspin-js`: placeholder capability entry for the initial scenario
- `sendspin-rs`: placeholder capability entry for the initial scenario

Unsupported matrix cells are reported as `skipped` with an explicit reason.

## Quick start

```bash
python scripts/setup_workspace.py --clone
. .venv/bin/activate
python scripts/run_all.py
```

That flow:

- clones the required repositories
- installs the Python harness and `aiosendspin`
- builds the adapter sources that are available locally
- runs the current matrix
- generates the static HTML report

## Useful commands

Run the full harness:

```bash
python scripts/run_all.py --results-dir results --site-dir site --build-report-path artifacts/build-report.json
```

Run a subset of the matrix:

```bash
conformance run --from aiosendspin,sendspin-rs --to SendspinKit
```

Build the adapter sources only:

```bash
conformance build --report-path artifacts/build-report.json
```

Generate the static site from existing results:

```bash
conformance report --results-dir results --site-dir site
```

## Report site

The generated site includes:

- a global matrix overview
- per-case status and reason
- copied case artifacts for drill-down: `result.json`, client/server summaries, and logs

## Repository layout

- `src/conformance/`: runner, adapters, fixture decoding, report generation
- `adapters/sendspin-dotnet/`: `.NET` client adapter source
- `adapters/README.md`: CLI contract for adapters
- `scripts/setup_repositories.py`: clones implementation repositories
- `scripts/setup_workspace.py`: bootstraps a local Python environment
- `scripts/run_all.py`: build + run + report orchestration
- `.github/workflows/nightly.yml`: nightly CI + GitHub Pages publishing

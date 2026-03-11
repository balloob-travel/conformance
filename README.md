# Sendspin Conformance

Capability-aware conformance harness for local Sendspin implementations.

The initial scenario in this repository is intentionally narrow:

- server-initiated connection
- handshake completes
- server streams the `almost_silent.flac` fixture
- client receives the stream
- both sides emit machine-readable summaries
- the runner compares canonical PCM hashes

The implementation repos are not all at the same maturity level today. This repo models that explicitly:

- `aiosendspin`: real server adapter and real client adapter
- `sendspin-dotnet`: real client adapter, server placeholder
- `SendspinKit`: placeholder capability entry for the initial scenario
- `sendspin-js`: placeholder capability entry for the initial scenario
- `sendspin-rs`: placeholder capability entry for the initial scenario

Unsupported matrix cells are reported as `skipped` with a reason instead of pretending the feature exists.

## Quick start

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python scripts/setup_workspace.py
conformance run --results-dir results
conformance report --results-dir results --site-dir site
```

## Filters

Run a subset of the matrix:

```bash
conformance run --from aiosendspin,sendspin-rs --to SendspinKit
```

The filter syntax matches the requested server-side implementations in `--from` and client-side implementations in `--to`.

## Repository layout

- `src/conformance/`: runner, adapters, fixture decoding, report generation
- `adapters/sendspin-dotnet/`: .NET client adapter source
- `scripts/setup_workspace.py`: clones repos and installs Python dependencies
- `.github/workflows/nightly.yml`: nightly CI + GitHub Pages publishing

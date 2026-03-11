# Sendspin Conformance

Capability-aware conformance harness for local Sendspin implementations.

Current scenarios:

- `client-initiated-pcm`: start the server first, let the client discover/connect to it, negotiate PCM, and compare canonical PCM hashes
- `server-initiated-flac`: start the server first, let the server discover/connect to the client, negotiate FLAC, and compare canonical PCM hashes

## Current coverage

- `aiosendspin`: real server adapter and real client adapter
- `sendspin-dotnet`: real client adapter source, server placeholder
- `SendspinKit`: real client adapter for `client-initiated-pcm`, server placeholder
- `sendspin-js`: real Node.js client adapter for `client-initiated-pcm`, server placeholder
- `sendspin-rs`: real Rust client adapter for `client-initiated-pcm`, server placeholder

Unsupported roles now use fail-fast adapters that emit a summary and exit non-zero, so the matrix records them as `failed` instead of silently skipping them.

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
python scripts/run_all.py --results-dir results --build-report-path artifacts/build-report.json
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
conformance report --results-dir results
```

## Report site

The generated site includes:

- a global matrix overview with one section per test scenario
- the greener client-initiated test listed first on the index page
- a separate static HTML page per test under `results/scenarios/`
- a dedicated static HTML page per pairing under `results/cases/`
- per-case status and reason with explicit server/client labeling
- summary, server, and client tabs on each dedicated case page
- run artifacts under `results/data/`
- the static report at `results/index.html`
- linked case artifacts for drill-down: `result.json`, client/server summaries, and logs

## Repository layout

- `src/conformance/`: runner, adapters, fixture decoding, report generation
- `adapters/sendspin-dotnet/`: `.NET` client adapter source
- `adapters/README.md`: CLI contract for adapters
- `scripts/setup_repositories.py`: clones implementation repositories
- `scripts/setup_workspace.py`: bootstraps a local Python environment
- `scripts/run_all.py`: build + run + report orchestration
- `.github/workflows/nightly.yml`: nightly CI + GitHub Pages publishing

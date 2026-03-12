# Sendspin Conformance

Capability-aware conformance harness for local Sendspin implementations.

Current scenarios:

- `client-initiated-pcm`: start the server first, let the client discover/connect to it, negotiate PCM, and compare canonical PCM hashes
- `server-initiated-pcm`: start the server first, let the client advertise a listener, let the server connect in, negotiate PCM, and compare canonical PCM hashes
- `client-initiated-metadata`: start the server first, let the client connect, receive a metadata snapshot, and compare normalized metadata fields
- `server-initiated-metadata`: start the server first, let the client advertise a listener, let the server connect in, receive a metadata snapshot, and compare normalized metadata fields
- `client-initiated-artwork`: start the server first, let the client connect, receive album artwork bytes, and compare the encoded image hash
- `server-initiated-artwork`: start the server first, let the client advertise a listener, let the server connect in, receive album artwork bytes, and compare the encoded image hash
- `client-initiated-controller`: start the server first, let the client connect, observe controller state, send a control command, and verify the server recorded it
- `server-initiated-controller`: start the server first, let the client advertise a listener, let the server connect in, observe controller state, send a control command, and verify the server recorded it
- `server-initiated-flac`: start the server first, let the server discover/connect to the client, negotiate FLAC, and compare the transported FLAC bytes instead of decoded PCM

## Current coverage

- `aiosendspin`: real server adapter and real client adapter
- `sendspin-dotnet`: real client adapter for client- and server-initiated PCM, metadata, artwork, controller, and server-initiated FLAC; server placeholder
- `SendspinKit`: real client adapter for client-initiated PCM, metadata, artwork, and controller; server placeholder
- `sendspin-go`: real Go client adapter and real Go server adapter for client-initiated PCM and metadata
- `sendspin-js`: real Node.js client adapter for client- and server-initiated PCM, metadata, artwork, controller, and server-initiated FLAC; server placeholder
- `sendspin-rs`: real Rust client adapter for client- and server-initiated PCM, metadata, artwork, controller, and server-initiated FLAC; server placeholder

Unsupported client roles use fail-fast adapters that emit a summary and exit non-zero. Unsupported server roles are filtered out before case creation, so the matrix only shows server rows that can actually run a scenario.

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
- runs the current matrix for the selected host environment
- generates the static HTML report

## Useful commands

Run the full harness:

```bash
python scripts/run_all.py --results-dir results --build-report-path artifacts/build-report.json
```

Run the full harness for an explicit host label:

```bash
python scripts/run_all.py \
  --results-dir results \
  --build-report-path artifacts/build-report.json \
  --environment-id linux \
  --environment-name Linux
```

Run a subset of the matrix:

```bash
conformance run --from aiosendspin,sendspin-rs --to SendspinKit
```

Run the matrix with parallel case execution:

```bash
conformance run --jobs 4
python scripts/run_all.py --jobs 4
```

The runner assigns a dedicated server port and client-listener port to each case,
so parallel cases do not fight over `8927`/`8928`.

Build the adapter sources only:

```bash
conformance build --report-path artifacts/build-report.json
```

Generate the static site from existing results:

```bash
conformance report --results-dir results
```

Merge multiple host result sets into one combined report:

```bash
python scripts/merge_results.py \
  --output-dir artifacts/results \
  artifacts/linux-results \
  artifacts/macos-results
```

## Report site

The generated site includes:

- a global matrix overview with one section per test scenario
- separate Linux/macOS environment groupings when multiple host result sets are merged
- Linux and macOS both build and publish the `sendspin-go` adapters so the merged report includes its supported server/client coverage
- the greener PCM scenarios listed first on the index page
- a separate static HTML page per test under `results/scenarios/`
- a dedicated static HTML page per pairing under `results/cases/`
- per-case status and reason with explicit server/client labeling
- summary, server, client, and build tabs on each dedicated case page when build data exists
- run artifacts under `results/data/`
- the static report at `results/index.html`
- linked case artifacts for drill-down: `result.json`, client/server summaries, and logs

## Repository layout

- `src/conformance/`: runner, adapters, fixture decoding, report generation
- `adapters/sendspin-go/`: Go client/server adapter source
- `adapters/sendspin-dotnet/`: `.NET` client adapter source
- `adapters/README.md`: CLI contract for adapters
- `scripts/setup_repositories.py`: clones implementation repositories
- `scripts/setup_workspace.py`: bootstraps a local Python environment
- `scripts/run_all.py`: build + run + report orchestration
- `scripts/merge_results.py`: merges multiple host result directories into one report
- `.github/workflows/nightly.yml`: Linux/macOS collection + merged GitHub Pages publishing

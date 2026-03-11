# AGENTS.md

## Purpose

This repository is a conformance harness for multiple Sendspin implementations. It does four things:

1. builds adapter CLIs for each implementation/toolchain
2. runs a scenario matrix across `server -> client` implementation pairs
3. records per-case artifacts and summaries
4. generates a static HTML report for GitHub Pages

Treat this repository as infrastructure around the implementations, not as the implementations themselves.

## First read

Start with these files before making changes:

- `README.md`: current user-facing workflow
- `src/conformance/scenarios.py`: canonical list and order of scenarios
- `src/conformance/implementations.py`: implementation registry and role capability metadata
- `src/conformance/runner.py`: matrix execution and artifact layout
- `src/conformance/site.py`: static report generation
- `adapters/README.md`: stable adapter CLI contract

## Core invariants

These are the easiest things to break accidentally.

### Adapter model

Every implementation is modeled as exactly two CLIs:

- `server`
- `client`

Even if an implementation does not support one role, it still needs a CLI surface that the harness can invoke. Unsupported roles should fail fast, emit a summary, and exit non-zero. Do not silently skip unsupported roles inside the runner.

### Scenario model

Scenarios are data-driven. Prefer adding scenario metadata in `src/conformance/scenarios.py` and generic scenario helpers in `src/conformance/models.py` over adding new `if scenario_id == ...` branches throughout the codebase.

Important current scenario traits:

- `initiator_role`
- `preferred_codec`

Adapters should primarily branch on generic traits like `initiator-role`, not on hard-coded scenario IDs, unless the behavior is truly scenario-specific.

### Scenario ordering

Scenario order is explicit and matters:

- run order
- site index order
- user perception of report health

Today `client-initiated-pcm` is intentionally listed first because it is greener. Preserve that unless there is a strong reason to change it.

### Result layout

The report output layout is fixed:

- `results/data/`
- `results/index.html`
- `results/tests/*.html`

Per-case artifacts live under `results/data/<scenario>__<server>__to__<client>/`.

Do not reintroduce multiple top-level report directories or SPA-style routing.

### Report behavior

The site is static HTML, not a SPA. The index page shows all scenario matrices. Each scenario gets its own HTML page. Individual case details are shown inline with tabs driven by small JS in `src/conformance/site.py`.

Keep server/client roles explicit everywhere in the report. Do not regress back to ambiguous `from/to` terminology.

### Summary contract

Successful adapters should print a JSON summary and exit `0`.

Important fields to preserve where available:

- `status`
- `implementation`
- `role`
- `scenario_id`
- `initiator_role`
- `preferred_codec`
- `peer_hello`
- audio hash fields

`peer_hello` should contain the full hello message received from the other party whenever capture is possible.

### Audio fixture

The shared source fixture is `almost_silent.flac` from `sendspin-cli`:

- resolved by `src/conformance/fixtures.py`
- expected at `sendspin-cli/tests/fixtures/almost_silent.flac`

Do not hard-code another fixture path in adapters or tests.

### CI expectation

GitHub Actions should still publish artifacts and GitHub Pages even when the conformance matrix has failing cases. Harness failures are currently expected. Do not add a workflow step that turns expected red matrix cases into a failed workflow.

Build/setup failures are different: those can still be real workflow failures.

## Repository map

### Harness code

- `src/conformance/models.py`: shared dataclasses and scenario capability helpers
- `src/conformance/scenarios.py`: scenario registry and order
- `src/conformance/implementations.py`: implementation registry and role metadata
- `src/conformance/runner.py`: matrix execution and process orchestration
- `src/conformance/build.py`: adapter build checks
- `src/conformance/site.py`: static site generation
- `src/conformance/flac.py` and `src/conformance/pcm.py`: canonical decode/hash helpers

### Adapters

- `src/conformance/adapters/aiosendspin_server.py`: real Python server adapter
- `src/conformance/adapters/aiosendspin_client.py`: real Python client adapter
- `adapters/sendspin-dotnet/client/`: real `.NET` client adapter source
- `src/conformance/adapters/placeholder.py`: generic fail-fast adapter
- `adapters/sendspin-js/*.mjs`: Node-based fail-fast adapters today

### Scripts

- `scripts/setup_repositories.py`: clone/check required repos
- `scripts/setup_workspace.py`: create local venv and install Python deps
- `scripts/run_all.py`: build + run + report orchestration

### CI

- `.github/workflows/nightly.yml`: push-to-main + nightly Pages workflow

## Standard commands

Bootstrap locally:

```bash
python scripts/setup_workspace.py --clone
. .venv/bin/activate
```

Build adapters:

```bash
python -m conformance.cli build
```

Run full matrix:

```bash
python scripts/run_all.py --results-dir results --build-report-path artifacts/build-report.json
```

Run filtered matrix:

```bash
python -m conformance.cli run --results-dir results --from aiosendspin --to aiosendspin,sendspin-dotnet
```

Regenerate report only:

```bash
python -m conformance.cli report --results-dir results
```

Fast sanity checks after edits:

```bash
python -m compileall src scripts
git diff --check
```

If you touched the `.NET` adapter, also run:

```bash
~/.dotnet/dotnet build adapters/sendspin-dotnet/client/Conformance.SendspinDotnet.Client.csproj
```

## How to add a new scenario

Prefer this path:

1. Add a `ScenarioSpec` entry in `src/conformance/scenarios.py`.
2. Reuse generic fields like `initiator_role`, `preferred_codec`, and `extra_cli_args` before inventing new runner conditionals.
3. Extend adapter behavior using generic CLI args when possible.
4. Keep scenario order intentional.
5. Verify the report renders the new scenario on the index page and generates a dedicated page under `results/tests/`.

If a scenario requires new behavior that does not fit the existing generic contract, add the minimum new generic scenario field needed instead of scattering per-scenario string checks.

## How to add or upgrade an implementation adapter

1. Add or update the implementation entry in `src/conformance/implementations.py`.
2. Expose both `server` and `client` roles.
3. If a role is unsupported, wire it to a fail-fast adapter and give a precise `reason`.
4. Keep adapter summaries aligned with the common summary contract.
5. Update `adapters/README.md` if the adapter contract changes.
6. Verify both build-time and run-time behavior.

When adding a real adapter, make it consume harness CLI args rather than making the runner special-case that implementation.

## Editing guidance

- Prefer changing harness behavior in one place over duplicating logic across runner, adapters, and site.
- Preserve explicit naming: `server_impl`, `client_impl`, `initiator_role`.
- Keep result files machine-readable and stable; downstream checks depend on them.
- Treat `results/` as generated output, not source.
- If you change summary fields or artifact paths, update both the site generator and any runner expectations in the same change.

## Verification checklist

After meaningful changes, run the smallest relevant subset plus a syntax/build pass.

Typical minimum:

1. `python -m compileall src scripts`
2. `python -m conformance.cli run --results-dir results --from aiosendspin --to aiosendspin,sendspin-dotnet --timeout-seconds 25`
3. `python -m conformance.cli report --results-dir results`

If you changed CI, read `.github/workflows/nightly.yml` afterward and confirm:

- Pages still uploads from `artifacts/results`
- expected harness failures do not fail the workflow

## Git hygiene

- Make focused commits.
- Push regularly when changes are meaningful.
- Do not rewrite history unless explicitly asked.


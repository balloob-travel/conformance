"""Static HTML report generation."""

from __future__ import annotations

import html
import json
import shutil
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Callable

from .implementations import IMPLEMENTATIONS, implementation_names
from .io import read_json
from .scenarios import SCENARIOS

STYLE = """
:root {
  --bg: #f6efdf;
  --bg-accent: rgba(193, 150, 82, 0.18);
  --ink: #17221f;
  --muted: #5c6762;
  --line: #d8cfbc;
  --card: rgba(255, 251, 242, 0.92);
  --card-strong: #fffdf6;
  --pass: #2e7d4b;
  --fail: #b34535;
  --skip: #8a6a19;
  --link: #0d5c88;
  --shadow: 0 18px 42px rgba(67, 52, 25, 0.08);
}
* {
  box-sizing: border-box;
}
body {
  margin: 0;
  font-family: Georgia, "Iowan Old Style", serif;
  background:
    radial-gradient(circle at top left, var(--bg-accent), transparent 24%),
    linear-gradient(180deg, #fbf6ed 0%, var(--bg) 100%);
  color: var(--ink);
}
a {
  color: var(--link);
}
main {
  max-width: 1260px;
  margin: 0 auto;
  padding: 40px 20px 88px;
}
.page-head {
  display: flex;
  justify-content: space-between;
  gap: 18px;
  align-items: end;
  margin-bottom: 26px;
  flex-wrap: wrap;
}
.eyebrow {
  margin: 0 0 8px;
  text-transform: uppercase;
  letter-spacing: 0.12em;
  font-size: 0.78rem;
  color: var(--muted);
}
h1, h2, h3, h4 {
  margin: 0;
}
h1 {
  font-size: clamp(2.3rem, 3vw, 3.2rem);
}
.lead {
  margin: 10px 0 0;
  max-width: 76ch;
  color: var(--muted);
  line-height: 1.55;
}
.overview,
.scenario-pills,
.case-meta,
.artifact-links {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
}
.pill,
.meta-pill {
  border: 1px solid var(--line);
  border-radius: 999px;
  background: var(--card);
  padding: 9px 14px;
  box-shadow: var(--shadow);
}
.pill strong,
.meta-pill strong {
  color: var(--ink);
}
.overview {
  margin: 26px 0 34px;
}
.scenario-block,
.matrix-card,
.case-card {
  background: var(--card);
  border: 1px solid var(--line);
  border-radius: 22px;
  box-shadow: var(--shadow);
}
.scenario-block {
  padding: 24px;
  margin-bottom: 26px;
}
.scenario-head {
  display: flex;
  justify-content: space-between;
  gap: 18px;
  align-items: start;
  margin-bottom: 20px;
  flex-wrap: wrap;
}
.scenario-head p,
.case-copy,
.panel-copy {
  margin: 10px 0 0;
  color: var(--muted);
  line-height: 1.55;
}
.section-link {
  display: inline-flex;
  align-items: center;
  padding: 10px 14px;
  border-radius: 999px;
  border: 1px solid var(--line);
  background: var(--card-strong);
  text-decoration: none;
  white-space: nowrap;
}
.matrix-card {
  padding: 18px;
}
.matrix-caption {
  margin: 0 0 14px;
  color: var(--muted);
}
table.matrix {
  width: 100%;
  border-collapse: collapse;
  overflow: hidden;
  border-radius: 16px;
  background: var(--card-strong);
}
.matrix th,
.matrix td {
  border: 1px solid var(--line);
  padding: 12px 10px;
  text-align: center;
  vertical-align: middle;
}
.matrix thead th {
  background: rgba(255, 246, 228, 0.85);
}
.matrix th:first-child {
  min-width: 180px;
  text-align: left;
}
.axis-cell,
.row-role {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.axis-label,
.role-label {
  text-transform: uppercase;
  letter-spacing: 0.08em;
  font-size: 0.72rem;
  color: var(--muted);
}
.impl-name {
  font-size: 1rem;
  color: var(--ink);
}
.matrix td a {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  min-height: 46px;
  text-decoration: none;
  color: inherit;
}
.cell-status {
  font-weight: 700;
  text-transform: capitalize;
}
.passed {
  background: rgba(46, 125, 75, 0.13);
  color: var(--pass);
}
.failed {
  background: rgba(179, 69, 53, 0.14);
  color: var(--fail);
}
.skipped {
  background: rgba(138, 106, 25, 0.12);
  color: var(--skip);
}
.empty {
  color: var(--muted);
}
.scenario-grid {
  display: grid;
  gap: 18px;
}
.back-link {
  display: inline-flex;
  margin-bottom: 18px;
  color: var(--muted);
  text-decoration: none;
}
.case-list {
  margin-top: 26px;
}
.case-card {
  margin-bottom: 18px;
  overflow: hidden;
}
.case-card > summary {
  list-style: none;
  cursor: pointer;
  display: flex;
  justify-content: space-between;
  gap: 18px;
  align-items: center;
  padding: 18px 22px;
}
.case-card > summary::-webkit-details-marker {
  display: none;
}
.case-title {
  display: flex;
  flex-wrap: wrap;
  gap: 14px;
  align-items: center;
}
.summary-role {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.summary-arrow {
  color: var(--muted);
}
.status-badge {
  display: inline-flex;
  align-items: center;
  border-radius: 999px;
  padding: 8px 12px;
  font-weight: 700;
  text-transform: capitalize;
  border: 1px solid currentColor;
  background: rgba(255, 255, 255, 0.6);
}
.case-body {
  border-top: 1px solid var(--line);
  padding: 20px 22px 24px;
}
.pairing {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 14px;
  margin-bottom: 18px;
}
.role-card {
  background: var(--card-strong);
  border: 1px solid var(--line);
  border-radius: 18px;
  padding: 16px;
}
.role-card strong {
  display: block;
  margin-top: 6px;
  font-size: 1.12rem;
}
.role-id {
  display: block;
  margin-top: 4px;
  color: var(--muted);
  font-family: "SFMono-Regular", Menlo, Consolas, monospace;
  font-size: 0.92rem;
}
.tabset {
  margin-top: 18px;
}
.tablist {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 14px;
}
.tab-button {
  appearance: none;
  border: 1px solid var(--line);
  background: rgba(255, 255, 255, 0.6);
  color: var(--muted);
  border-radius: 999px;
  padding: 10px 14px;
  cursor: pointer;
  font: inherit;
}
.tab-button.is-active {
  background: var(--card-strong);
  color: var(--ink);
  border-color: rgba(13, 92, 136, 0.35);
}
.tab-panel[hidden] {
  display: none;
}
.panel-grid {
  display: grid;
  gap: 16px;
}
.panel-grid.two-up {
  grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
}
.artifact-block {
  border: 1px solid var(--line);
  border-radius: 18px;
  background: var(--card-strong);
  padding: 14px;
}
.artifact-block h4 {
  margin-bottom: 10px;
}
pre {
  margin: 0;
  padding: 14px;
  overflow: auto;
  border-radius: 14px;
  background: #1a2020;
  color: #f2f0ea;
  line-height: 1.5;
  font-size: 0.92rem;
  font-family: "SFMono-Regular", Menlo, Consolas, monospace;
}
.json-view {
  max-height: 360px;
}
.log-view {
  max-height: 440px;
}
.artifact-links {
  margin-top: 18px;
}
.artifact-links a {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 10px;
  text-decoration: none;
  background: rgba(255, 255, 255, 0.75);
  border: 1px solid var(--line);
  border-radius: 999px;
}
.empty-state {
  padding: 24px;
  border: 1px dashed var(--line);
  border-radius: 18px;
  color: var(--muted);
  background: rgba(255, 255, 255, 0.4);
}
@media (max-width: 760px) {
  main {
    padding: 28px 14px 72px;
  }
  .scenario-block,
  .matrix-card,
  .case-body {
    padding-left: 16px;
    padding-right: 16px;
  }
  .case-card > summary {
    padding: 16px;
  }
  .matrix th:first-child {
    min-width: 140px;
  }
}
"""

TABS_SCRIPT = """
document.querySelectorAll("[data-tabset]").forEach((tabset) => {
  const buttons = Array.from(tabset.querySelectorAll("[data-tab-button]"));
  const panels = Array.from(tabset.querySelectorAll("[data-tab-panel]"));
  const activate = (name) => {
    buttons.forEach((button) => {
      button.classList.toggle("is-active", button.dataset.tabButton === name);
    });
    panels.forEach((panel) => {
      panel.hidden = panel.dataset.tabPanel !== name;
    });
  };
  buttons.forEach((button) => {
    button.addEventListener("click", () => activate(button.dataset.tabButton));
  });
  if (buttons.length > 0) {
    activate(buttons[0].dataset.tabButton);
  }
});

const revealHashTarget = () => {
  const hash = window.location.hash;
  if (!hash) {
    return;
  }
  const target = document.getElementById(hash.slice(1));
  if (!target) {
    return;
  }
  if (target.tagName === "DETAILS") {
    target.open = true;
  }
};

window.addEventListener("hashchange", revealHashTarget);
revealHashTarget();
"""


def _data_dir(results_dir: Path) -> Path:
    data_dir = results_dir / "data"
    if not (data_dir / "index.json").exists():
        raise FileNotFoundError(f"Missing results index at {data_dir / 'index.json'}")
    return data_dir


def _sync_case_artifacts(data_dir: Path, site_dir: Path) -> str:
    target_dir = site_dir / "data"
    if target_dir.resolve() == data_dir.resolve():
        return "data"
    if target_dir.exists():
        shutil.rmtree(target_dir)
    shutil.copytree(data_dir, target_dir)
    return "data"


def _prepare_tests_dir(site_dir: Path) -> Path:
    tests_dir = site_dir / "tests"
    if tests_dir.exists():
        shutil.rmtree(tests_dir)
    tests_dir.mkdir(parents=True, exist_ok=True)
    return tests_dir


def _scenario_results(results: list[dict[str, Any]]) -> list[tuple[str, list[dict[str, Any]]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for result in results:
        grouped[str(result["scenario_id"])].append(result)
    ordered_ids = [scenario_id for scenario_id in SCENARIOS if scenario_id in grouped]
    ordered_ids.extend(sorted(scenario_id for scenario_id in grouped if scenario_id not in SCENARIOS))
    return [(scenario_id, grouped[scenario_id]) for scenario_id in ordered_ids]


def _scenario_name(scenario_id: str) -> str:
    spec = SCENARIOS.get(scenario_id)
    return spec.display_name if spec is not None else scenario_id


def _scenario_description(scenario_id: str) -> str:
    spec = SCENARIOS.get(scenario_id)
    return spec.description if spec is not None else "No scenario description is registered for this test."


def _scenario_page_href(scenario_id: str) -> str:
    return f"tests/{scenario_id}.html"


def _case_anchor(result: dict[str, Any]) -> str:
    return (
        "case-"
        f"{result['scenario_id']}__{result['server_impl']}__to__{result['client_impl']}"
    )


def _implementation_label(name: str) -> str:
    spec = IMPLEMENTATIONS.get(name)
    return spec.display_name if spec is not None else name


def _status_pills(counts: Counter[str], *, total_label: str, total_value: int) -> str:
    return (
        "<section class='overview'>"
        f"<div class='pill'><strong>{total_label}:</strong> {total_value}</div>"
        f"<div class='pill'><strong>Passed:</strong> {counts.get('passed', 0)}</div>"
        f"<div class='pill'><strong>Failed:</strong> {counts.get('failed', 0)}</div>"
        f"<div class='pill'><strong>Skipped:</strong> {counts.get('skipped', 0)}</div>"
        "</section>"
    )


def _render_matrix(
    results: list[dict[str, Any]],
    *,
    caption: str,
    href_builder: Callable[[dict[str, Any]], str],
) -> str:
    impls = implementation_names()
    result_map = {
        (str(result["server_impl"]), str(result["client_impl"])): result for result in results
    }
    rows: list[str] = []
    for server_impl in impls:
        row_cells = [
            (
                "<th scope='row'>"
                "<div class='row-role'>"
                "<span class='role-label'>Server</span>"
                f"<span class='impl-name'>{html.escape(_implementation_label(server_impl))}</span>"
                "</div>"
                "</th>"
            )
        ]
        for client_impl in impls:
            result = result_map.get((server_impl, client_impl))
            if result is None:
                row_cells.append("<td class='empty'>-</td>")
                continue
            status = str(result["status"])
            href = html.escape(href_builder(result), quote=True)
            title = html.escape(
                (
                    f"Server: {_implementation_label(server_impl)} | "
                    f"Client: {_implementation_label(client_impl)} | "
                    f"Status: {status}"
                ),
                quote=True,
            )
            row_cells.append(
                f"<td class='{html.escape(status)}'>"
                f"<a href='{href}' title='{title}' aria-label='{title}'>"
                f"<span class='cell-status'>{html.escape(status)}</span>"
                "</a>"
                "</td>"
            )
        rows.append(f"<tr>{''.join(row_cells)}</tr>")

    column_headers = "".join(
        (
            "<th scope='col'>"
            "<div class='axis-cell'>"
            "<span class='axis-label'>Client</span>"
            f"<span class='impl-name'>{html.escape(_implementation_label(client_impl))}</span>"
            "</div>"
            "</th>"
        )
        for client_impl in impls
    )
    return (
        "<section class='matrix-card'>"
        f"<p class='matrix-caption'>{html.escape(caption)}</p>"
        "<table class='matrix'>"
        "<thead><tr>"
        "<th scope='col'>"
        "<div class='axis-cell'>"
        "<span class='axis-label'>Matrix</span>"
        "<span class='impl-name'>Server \\ Client</span>"
        "</div>"
        "</th>"
        f"{column_headers}"
        "</tr></thead>"
        f"<tbody>{''.join(rows)}</tbody>"
        "</table>"
        "</section>"
    )


def _read_text(path: Path) -> str | None:
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8", errors="replace")


def _read_pretty_json(path: Path) -> str | None:
    if not path.exists():
        return None
    return json.dumps(read_json(path), indent=2, sort_keys=True)


def _artifact_links(case_dir: Path, artifact_href_root: str) -> str:
    links: list[str] = []
    for filename in (
        "result.json",
        "server-summary.json",
        "client-summary.json",
        "server.log",
        "client.log",
    ):
        if (case_dir / filename).exists():
            href = html.escape(f"{artifact_href_root}/{filename}", quote=True)
            links.append(f"<a href='{href}'>{html.escape(filename)}</a>")
    if not links:
        return "<p class='panel-copy'>No downloadable artifacts were written for this case.</p>"
    return f"<div class='artifact-links'>{''.join(links)}</div>"


def _render_code_block(label: str, content: str | None, *, css_class: str) -> str:
    body = content if content is not None else "No artifact was written for this section."
    return (
        "<section class='artifact-block'>"
        f"<h4>{html.escape(label)}</h4>"
        f"<pre class='{html.escape(css_class)}'>{html.escape(body)}</pre>"
        "</section>"
    )


def _render_case(result: dict[str, Any], *, data_dir: Path, artifact_href_root: str) -> str:
    case_name = Path(str(result["case_dir"])).name
    case_dir = data_dir / case_name
    anchor = _case_anchor(result)
    server_impl = str(result["server_impl"])
    client_impl = str(result["client_impl"])
    server_label = _implementation_label(server_impl)
    client_label = _implementation_label(client_impl)
    status = str(result["status"])
    reason = str(result["reason"])
    result_json = _read_pretty_json(case_dir / "result.json") or json.dumps(result, indent=2, sort_keys=True)
    server_summary = _read_pretty_json(case_dir / "server-summary.json")
    client_summary = _read_pretty_json(case_dir / "client-summary.json")
    server_log = _read_text(case_dir / "server.log")
    client_log = _read_text(case_dir / "client.log")
    tab_prefix = anchor.replace(":", "_")
    summary_tab = f"{tab_prefix}--summary"
    server_tab = f"{tab_prefix}--server"
    client_tab = f"{tab_prefix}--client"

    return (
        f"<details id='{html.escape(anchor)}' class='case-card {html.escape(status)}'>"
        "<summary>"
        "<div class='case-title'>"
        f"<span class='summary-role'><span class='role-label'>Server</span> <strong>{html.escape(server_label)}</strong></span>"
        "<span class='summary-arrow'>→</span>"
        f"<span class='summary-role'><span class='role-label'>Client</span> <strong>{html.escape(client_label)}</strong></span>"
        "</div>"
        f"<span class='status-badge'>{html.escape(status)}</span>"
        "</summary>"
        "<div class='case-body'>"
        "<div class='pairing'>"
        "<section class='role-card'>"
        "<span class='role-label'>Server implementation</span>"
        f"<strong>{html.escape(server_label)}</strong>"
        f"<span class='role-id'>{html.escape(server_impl)}</span>"
        "</section>"
        "<section class='role-card'>"
        "<span class='role-label'>Client implementation</span>"
        f"<strong>{html.escape(client_label)}</strong>"
        f"<span class='role-id'>{html.escape(client_impl)}</span>"
        "</section>"
        "</div>"
        f"<p class='case-copy'>{html.escape(reason)}</p>"
        "<div class='case-meta'>"
        f"<div class='meta-pill'><strong>Status:</strong> {html.escape(status)}</div>"
        f"<div class='meta-pill'><strong>Scenario:</strong> {html.escape(str(result['scenario_id']))}</div>"
        f"<div class='meta-pill'><strong>Server exit:</strong> {html.escape(str(result.get('server_exit_code')))}</div>"
        f"<div class='meta-pill'><strong>Client exit:</strong> {html.escape(str(result.get('client_exit_code')))}</div>"
        "</div>"
        f"{_artifact_links(case_dir, f'{artifact_href_root}/{case_name}')}"
        "<div class='tabset' data-tabset>"
        "<div class='tablist'>"
        f"<button type='button' class='tab-button' data-tab-button='{html.escape(summary_tab, quote=True)}'>Summary</button>"
        f"<button type='button' class='tab-button' data-tab-button='{html.escape(server_tab, quote=True)}'>Server: {html.escape(server_label)}</button>"
        f"<button type='button' class='tab-button' data-tab-button='{html.escape(client_tab, quote=True)}'>Client: {html.escape(client_label)}</button>"
        "</div>"
        f"<section class='tab-panel' data-tab-panel='{html.escape(summary_tab, quote=True)}'>"
        "<div class='panel-grid'>"
        "<section class='artifact-block'>"
        "<h4>Case result</h4>"
        "<p class='panel-copy'>This tab summarizes the matrix verdict and links out to the raw files. Use the server and client tabs to inspect the exact hello payloads, summaries, and logs for each side.</p>"
        f"<pre class='json-view'>{html.escape(result_json)}</pre>"
        "</section>"
        "</div>"
        "</section>"
        f"<section class='tab-panel' data-tab-panel='{html.escape(server_tab, quote=True)}' hidden>"
        "<div class='panel-grid two-up'>"
        f"{_render_code_block('Server summary (JSON)', server_summary, css_class='json-view')}"
        f"{_render_code_block('Server log', server_log, css_class='log-view')}"
        "</div>"
        "</section>"
        f"<section class='tab-panel' data-tab-panel='{html.escape(client_tab, quote=True)}' hidden>"
        "<div class='panel-grid two-up'>"
        f"{_render_code_block('Client summary (JSON)', client_summary, css_class='json-view')}"
        f"{_render_code_block('Client log', client_log, css_class='log-view')}"
        "</div>"
        "</section>"
        "</div>"
        "</div>"
        "</details>"
    )


def _page_doc(*, title: str, body: str, back_href: str | None = None) -> str:
    back_link = (
        f"<a class='back-link' href='{html.escape(back_href, quote=True)}'>← Back to overview</a>"
        if back_href is not None
        else ""
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <style>{STYLE}</style>
</head>
<body>
  <main>
    {back_link}
    {body}
  </main>
  <script>{TABS_SCRIPT}</script>
</body>
</html>
"""


def _render_index_page(results: list[dict[str, Any]]) -> str:
    scenario_groups = _scenario_results(results)
    counts = Counter(str(result["status"]) for result in results)
    sections: list[str] = []
    for scenario_id, scenario_results in scenario_groups:
        scenario_name = _scenario_name(scenario_id)
        scenario_description = _scenario_description(scenario_id)
        scenario_counts = Counter(str(result["status"]) for result in scenario_results)
        scenario_link = _scenario_page_href(scenario_id)
        matrix = _render_matrix(
            scenario_results,
            caption="Rows are server implementations. Columns are client implementations.",
            href_builder=lambda result, scenario_id=scenario_id: (
                f"{_scenario_page_href(scenario_id)}#{_case_anchor(result)}"
            ),
        )
        sections.append(
            "<section class='scenario-block'>"
            "<div class='scenario-head'>"
            "<div>"
            "<p class='eyebrow'>Test</p>"
            f"<h2>{html.escape(scenario_name)}</h2>"
            f"<p>{html.escape(scenario_description)}</p>"
            "</div>"
            f"<a class='section-link' href='{html.escape(scenario_link, quote=True)}'>Open test page</a>"
            "</div>"
            "<div class='scenario-pills'>"
            f"<div class='pill'><strong>Cases:</strong> {len(scenario_results)}</div>"
            f"<div class='pill'><strong>Passed:</strong> {scenario_counts.get('passed', 0)}</div>"
            f"<div class='pill'><strong>Failed:</strong> {scenario_counts.get('failed', 0)}</div>"
            f"<div class='pill'><strong>Skipped:</strong> {scenario_counts.get('skipped', 0)}</div>"
            "</div>"
            f"{matrix}"
            "</section>"
        )
    body = (
        "<section class='page-head'>"
        "<div>"
        "<p class='eyebrow'>Static Report</p>"
        "<h1>Sendspin Conformance</h1>"
        "<p class='lead'>Overview of all generated test scenarios. Each test gets its own matrix on this page and a separate static HTML detail page with per-case server and client logs.</p>"
        "</div>"
        "</section>"
        f"{_status_pills(counts, total_label='Tests', total_value=len(scenario_groups))}"
        f"{''.join(sections) if sections else '<div class=\"empty-state\">No scenario results were found.</div>'}"
    )
    return _page_doc(title="Sendspin Conformance", body=body)


def _render_scenario_page(
    scenario_id: str,
    results: list[dict[str, Any]],
    *,
    data_dir: Path,
) -> str:
    scenario_name = _scenario_name(scenario_id)
    scenario_description = _scenario_description(scenario_id)
    counts = Counter(str(result["status"]) for result in results)
    ordered_results = sorted(
        results,
        key=lambda result: (str(result["server_impl"]), str(result["client_impl"])),
    )
    matrix = _render_matrix(
        ordered_results,
        caption="Rows are server implementations. Columns are client implementations. Click a cell to jump to the case below.",
        href_builder=lambda result: f"#{_case_anchor(result)}",
    )
    cases = "".join(
        _render_case(result, data_dir=data_dir, artifact_href_root="../data")
        for result in ordered_results
    )
    body = (
        "<section class='page-head'>"
        "<div>"
        "<p class='eyebrow'>Test Detail</p>"
        f"<h1>{html.escape(scenario_name)}</h1>"
        f"<p class='lead'>{html.escape(scenario_description)}</p>"
        "</div>"
        "</section>"
        f"{_status_pills(counts, total_label='Cases', total_value=len(ordered_results))}"
        f"{matrix}"
        "<section class='case-list'>"
        f"{cases if cases else '<div class=\"empty-state\">No case results were found for this test.</div>'}"
        "</section>"
    )
    return _page_doc(
        title=f"Sendspin Conformance · {scenario_name}",
        body=body,
        back_href="../index.html",
    )


def build_site(results_dir: Path, site_dir: Path) -> None:
    """Generate a static report site with per-scenario detail pages."""
    data_dir = _data_dir(results_dir)
    index_payload = read_json(data_dir / "index.json")
    results: list[dict[str, Any]] = list(index_payload["results"])
    site_dir.mkdir(parents=True, exist_ok=True)
    _sync_case_artifacts(data_dir, site_dir)
    tests_dir = _prepare_tests_dir(site_dir)

    (site_dir / "index.html").write_text(_render_index_page(results), encoding="utf-8")
    for scenario_id, scenario_results in _scenario_results(results):
        (tests_dir / f"{scenario_id}.html").write_text(
            _render_scenario_page(scenario_id, scenario_results, data_dir=data_dir),
            encoding="utf-8",
        )

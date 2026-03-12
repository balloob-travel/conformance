"""Static HTML report generation."""

from __future__ import annotations

import html
import json
import shutil
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

from .implementations import IMPLEMENTATIONS, implementation_names
from .io import read_json
from .scenarios import get_scenario, ordered_scenarios

HEAD_ASSETS = """
  <script src="https://cdn.tailwindcss.com"></script>
  <script>
    tailwind.config = {
      theme: {
        extend: {
          colors: {
            retro: {
              cream: "#f4e7d3",
              paper: "#fbf2e5",
              shell: "#efdcc7",
              line: "#c79e72",
              bark: "#4b2f1b",
              walnut: "#63391d",
              burnt: "#8a471e",
              copper: "#b66531",
              clay: "#d7a16d",
              code: "#2b1f17"
            }
          },
          fontFamily: {
            sans: ["Avenir Next", "Segoe UI", "system-ui", "sans-serif"],
            display: ["Iowan Old Style", "Palatino Linotype", "Book Antiqua", "serif"],
            mono: ["SFMono-Regular", "ui-monospace", "monospace"]
          },
          boxShadow: {
            panel: "0 24px 60px rgba(92, 56, 29, 0.12)",
            soft: "0 12px 24px rgba(92, 56, 29, 0.10)"
          }
        }
      }
    };
  </script>
  <style type="text/tailwindcss">
    @layer base {
      :root {
        --retro-cream: 244 231 211;
        --retro-paper: 251 242 229;
        --retro-shell: 239 220 199;
        --retro-line: 199 158 114;
        --retro-bark: 75 47 27;
        --retro-burnt: 138 71 30;
        --retro-clay: 215 161 109;
        --retro-code: 43 31 23;
      }

      html {
        @apply scroll-smooth;
      }
      body {
        @apply min-h-screen font-sans antialiased;
        background-color: rgb(var(--retro-cream));
        color: rgb(var(--retro-bark));
      }
      h1, h2, h3, h4 {
        @apply font-display;
        color: rgb(var(--retro-bark));
      }
      a {
        @apply transition-colors duration-150;
      }
      pre {
        @apply font-mono text-[13px] leading-6;
      }
      ::selection {
        background-color: rgb(var(--retro-clay) / 0.5);
        color: rgb(var(--retro-bark));
      }
    }

    @layer components {
      .app-shell {
        background:
          radial-gradient(circle at top left, rgba(182, 101, 49, 0.18), transparent 24%),
          radial-gradient(circle at top right, rgba(75, 47, 27, 0.08), transparent 28%),
          linear-gradient(180deg, #f7ecdd 0%, #f2e2cf 100%);
      }

      .panel {
        @apply rounded-[28px] border shadow-panel backdrop-blur;
        border-color: rgb(var(--retro-line) / 0.7);
        background-color: rgb(var(--retro-paper) / 0.92);
      }

      .subpanel {
        @apply rounded-[22px] border;
        border-color: rgb(var(--retro-line) / 0.6);
        background-color: rgb(var(--retro-shell) / 0.72);
      }

      .chip {
        @apply inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-[11px] font-semibold uppercase tracking-[0.18em];
        border-color: rgb(var(--retro-line) / 0.7);
        background-color: rgb(var(--retro-paper) / 0.8);
        color: rgb(var(--retro-bark) / 0.7);
      }

      .status-pill {
        @apply inline-flex items-center rounded-full border px-3 py-1.5 text-xs font-semibold uppercase tracking-[0.16em];
      }

      .status-passed {
        @apply border-amber-800/20 bg-amber-200/60;
        color: rgb(var(--retro-bark));
      }

      .status-failed {
        @apply border-orange-900/20 bg-orange-300/55;
        color: rgb(var(--retro-bark));
      }

      .status-skipped {
        @apply border-stone-500/20 bg-stone-200/70;
        color: rgb(var(--retro-bark));
      }

      .cell-link {
        @apply block rounded-[20px] border px-3 py-3 text-left transition hover:-translate-y-0.5 hover:shadow-soft focus-visible:outline-none focus-visible:ring-2 sm:text-center;
      }

      .cell-link:focus-visible {
        --tw-ring-color: rgb(var(--retro-bark) / 0.5);
      }

      .cell-passed {
        @apply border-amber-800/15 bg-amber-100/80 hover:bg-amber-100;
        color: rgb(var(--retro-bark));
      }

      .cell-failed {
        @apply border-orange-900/15 bg-orange-100/80 hover:bg-orange-100;
        color: rgb(var(--retro-bark));
      }

      .cell-skipped {
        @apply border-stone-500/15 bg-stone-100/80 hover:bg-stone-100;
        color: rgb(var(--retro-bark));
      }

      .nav-item {
        @apply flex items-start justify-between gap-3 rounded-[20px] border border-transparent px-4 py-4 transition;
      }

      .nav-item:hover {
        border-color: rgb(var(--retro-line) / 0.8);
        background-color: rgb(var(--retro-paper) / 0.75);
      }

      .nav-item-active {
        @apply shadow-soft;
        border-color: rgb(var(--retro-burnt) / 0.3);
        background-color: rgb(var(--retro-bark));
        color: rgb(var(--retro-paper));
      }

      .nav-item-active .nav-meta,
      .nav-item-active .nav-copy {
        color: rgb(var(--retro-paper) / 0.68);
      }

      .inbox-row {
        @apply grid gap-3 rounded-[22px] border border-transparent px-4 py-4 transition sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center;
      }

      .inbox-row:hover {
        border-color: rgb(var(--retro-line) / 0.8);
        background-color: rgb(var(--retro-paper) / 0.75);
      }

      .tab-button {
        @apply rounded-full border px-4 py-2.5 text-sm font-semibold transition;
      }

      .tab-idle {
        border-color: rgb(var(--retro-line) / 0.7);
        background-color: rgb(var(--retro-paper) / 0.7);
        color: rgb(var(--retro-bark) / 0.72);
      }

      .tab-idle:hover {
        background-color: rgb(var(--retro-shell));
        color: rgb(var(--retro-bark));
      }

      .tab-active {
        @apply shadow-soft;
        border-color: rgb(var(--retro-bark));
        background-color: rgb(var(--retro-bark));
        color: rgb(var(--retro-paper));
      }

      .code-shell {
        @apply rounded-[22px] border;
        border-color: rgb(var(--retro-line) / 0.6);
        background-color: rgb(var(--retro-paper) / 0.7);
      }

      .code-block {
        @apply max-h-[28rem] overflow-auto rounded-[18px] px-4 py-4;
        background-color: rgb(var(--retro-code));
        color: rgb(var(--retro-paper));
      }
    }
  </style>
"""

TABS_SCRIPT = """
document.querySelectorAll("[data-tabset]").forEach((tabset) => {
  const buttons = Array.from(tabset.querySelectorAll("[data-tab-button]"));
  const panels = Array.from(tabset.querySelectorAll("[data-tab-panel]"));
  const activate = (name) => {
    buttons.forEach((button) => {
      const isActive = button.dataset.tabButton === name;
      button.classList.toggle("tab-active", isActive);
      button.classList.toggle("tab-idle", !isActive);
      button.setAttribute("aria-selected", String(isActive));
    });
    panels.forEach((panel) => {
      panel.hidden = panel.dataset.tabPanel !== name;
    });
  };

  buttons.forEach((button) => {
    button.addEventListener("click", () => activate(button.dataset.tabButton));
  });

  const initial = buttons.find((button) => button.dataset.defaultTab === "true") ?? buttons[0];
  if (initial) {
    activate(initial.dataset.tabButton);
  }
});
"""

STATUS_LABELS = {
    "passed": "Passed",
    "failed": "Failed",
    "skipped": "Skipped",
}

STATUS_CLASSES = {
    "passed": "status-passed",
    "failed": "status-failed",
    "skipped": "status-skipped",
}

CELL_CLASSES = {
    "passed": "cell-passed",
    "failed": "cell-failed",
    "skipped": "cell-skipped",
}

GITHUB_REPO_URL = "https://github.com/balloob-travel/conformance"
SENDSPIN_AUDIO_URL = "https://sendspin-audio.com/"
SCENARIOS_REPO_PATH = "src/conformance/scenarios.py"


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


def _prepare_output_dir(site_dir: Path, dirname: str) -> Path:
    output_dir = site_dir / dirname
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def _clear_legacy_dirs(site_dir: Path) -> None:
    legacy_tests = site_dir / "tests"
    if legacy_tests.exists():
        shutil.rmtree(legacy_tests)


def _scenario_results(results: list[dict[str, Any]]) -> list[tuple[str, list[dict[str, Any]]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for result in results:
        grouped[str(result["scenario_id"])].append(result)

    ordered_ids = [scenario.id for scenario in ordered_scenarios() if scenario.id in grouped]
    ordered_ids.extend(
        sorted(scenario_id for scenario_id in grouped if get_scenario(scenario_id) is None)
    )
    return [(scenario_id, grouped[scenario_id]) for scenario_id in ordered_ids]


def _scenario_name(scenario_id: str) -> str:
    scenario = get_scenario(scenario_id)
    return scenario.display_name if scenario is not None else scenario_id


def _scenario_description(scenario_id: str) -> str:
    scenario = get_scenario(scenario_id)
    if scenario is None:
        return "No scenario description is registered for this test."
    return scenario.description


def _scenario_intro(scenario_id: str) -> str:
    description = _scenario_description(scenario_id).strip()
    first_sentence = description.split(". ")[0].strip()
    if first_sentence.endswith("."):
        return first_sentence
    return f"{first_sentence}."


def _scenario_href(scenario_id: str) -> str:
    return f"scenarios/{scenario_id}.html"


def _external_chip(label: str, href: str) -> str:
    return (
        f"<a class='chip' href='{html.escape(href, quote=True)}' "
        "target='_blank' rel='noreferrer'>"
        f"{html.escape(label)}"
        "</a>"
    )


def _github_blob_url(repo_path: str, *, line: int | None = None) -> str:
    url = f"{GITHUB_REPO_URL}/blob/main/{repo_path}"
    if line is not None:
        return f"{url}#L{line}"
    return url


@lru_cache(maxsize=None)
def _scenario_source_line(scenario_id: str) -> int | None:
    source_path = Path(__file__).resolve().with_name("scenarios.py")
    needle = f'id="{scenario_id}"'
    for line_number, line in enumerate(
        source_path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        if needle in line:
            return line_number
    return None


def _scenario_source_url(scenario_id: str) -> str:
    return _github_blob_url(
        SCENARIOS_REPO_PATH,
        line=_scenario_source_line(scenario_id),
    )


def _case_slug(result: dict[str, Any]) -> str:
    return Path(str(result["case_dir"])).name


def _case_href(result: dict[str, Any]) -> str:
    return f"cases/{_case_slug(result)}.html"


def _case_key(result: dict[str, Any]) -> tuple[str, str]:
    return (str(result["server_impl"]), str(result["client_impl"]))


def _implementation_label(name: str) -> str:
    implementation = IMPLEMENTATIONS.get(name)
    return implementation.display_name if implementation is not None else name


def _implementation_subtitle(name: str) -> str | None:
    label = _implementation_label(name)
    return None if label == name else name


def _implementation_identity(
    name: str,
    *,
    role_label: str | None = None,
    primary_class: str,
    secondary_class: str,
) -> str:
    parts: list[str] = ["<div class='space-y-1'>"]
    if role_label is not None:
        parts.append(
            "<p class='text-[11px] font-semibold uppercase tracking-[0.18em] text-retro-bark/45'>"
            f"{html.escape(role_label)}"
            "</p>"
        )
    parts.append(
        f"<p class='{html.escape(primary_class, quote=True)}'>{html.escape(_implementation_label(name))}</p>"
    )
    subtitle = _implementation_subtitle(name)
    if subtitle is not None:
        parts.append(
            f"<p class='{html.escape(secondary_class, quote=True)}'>{html.escape(subtitle)}</p>"
        )
    parts.append("</div>")
    return "".join(parts)


def _status_label(status: str) -> str:
    return STATUS_LABELS.get(status, status.capitalize())


def _status_classes(status: str) -> str:
    return STATUS_CLASSES.get(status, "status-skipped")


def _cell_classes(status: str) -> str:
    return CELL_CLASSES.get(status, "cell-skipped")


def _escape(value: Any) -> str:
    return html.escape(str(value))


def _safe_json(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True)


def _read_text(path: Path) -> str | None:
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8", errors="replace")


def _read_pretty_json(path: Path) -> str | None:
    if not path.exists():
        return None
    return _safe_json(read_json(path))


def _summary_cards(
    *,
    counts: Counter[str],
    total_label: str,
    total_value: int,
) -> str:
    items = [
        ("Total", total_value),
        ("Passed", counts.get("passed", 0)),
        ("Failed", counts.get("failed", 0)),
        ("Skipped", counts.get("skipped", 0)),
    ]
    cards = "".join(
        (
            "<div class='subpanel px-4 py-4'>"
            f"<p class='text-[11px] font-semibold uppercase tracking-[0.18em] text-retro-bark/55'>{_escape(label)}</p>"
            f"<p class='mt-2 text-2xl font-semibold text-retro-bark'>{_escape(value)}</p>"
            f"<p class='mt-1 text-sm text-retro-bark/58'>{_escape(total_label)}</p>"
            "</div>"
        )
        for label, value in items
    )
    return f"<div class='grid gap-3 sm:grid-cols-2 xl:grid-cols-4'>{cards}</div>"


def _page_shell(
    *,
    title: str,
    body: str,
    include_tabs: bool = False,
) -> str:
    tabs_script = f"<script>{TABS_SCRIPT}</script>" if include_tabs else ""
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="light">
  <title>{html.escape(title)}</title>
{HEAD_ASSETS}
</head>
<body>
  {body}
  {tabs_script}
</body>
</html>
"""


def _nav_scenarios(
    scenario_groups: list[tuple[str, list[dict[str, Any]]]],
    *,
    current_scenario_id: str | None = None,
    href_prefix: str = "",
) -> str:
    items: list[str] = []
    for scenario_id, scenario_results in scenario_groups:
        counts = Counter(str(result["status"]) for result in scenario_results)
        active_class = " nav-item-active" if scenario_id == current_scenario_id else ""
        items.append(
            f"<a class='nav-item{active_class}' href='{html.escape(href_prefix + _scenario_href(scenario_id), quote=True)}'>"
            "<div class='min-w-0'>"
            f"<p class='text-lg leading-tight'>{html.escape(_scenario_name(scenario_id))}</p>"
            f"<p class='nav-copy mt-1 text-sm text-retro-bark/64'>{html.escape(_scenario_intro(scenario_id))}</p>"
            "</div>"
            "<div class='shrink-0 text-right'>"
            f"<p class='nav-meta text-[11px] font-semibold uppercase tracking-[0.18em] text-retro-bark/48'>{counts.get('passed', 0)}/{len(scenario_results)} green</p>"
            f"<p class='nav-meta mt-1 text-sm text-retro-bark/58'>{len(scenario_results)} pairings</p>"
            "</div>"
            "</a>"
        )
    return (
        "<section class='panel p-4 sm:p-5'>"
        "<p class='text-[11px] font-semibold uppercase tracking-[0.22em] text-retro-bark/48'>Tests</p>"
        "<div class='mt-3 space-y-2'>"
        f"{''.join(items)}"
        "</div>"
        "</section>"
    )


def _render_matrix(
    results: list[dict[str, Any]],
    *,
    caption: str,
    href_builder: Callable[[dict[str, Any]], str],
    current_case_slug: str | None = None,
) -> str:
    implementations = implementation_names()
    result_map = {
        (str(result["server_impl"]), str(result["client_impl"])): result for result in results
    }

    rows: list[str] = []
    for server_impl in implementations:
        cells = [
            (
                "<th scope='row' class='sticky left-0 z-10 min-w-[190px] border-b border-retro-line/40 bg-retro-paper/95 px-4 py-4 text-left align-top'>"
                f"{_implementation_identity(server_impl, role_label='Server', primary_class='text-sm font-semibold text-retro-bark', secondary_class='text-xs text-retro-bark/54')}"
                "</th>"
            )
        ]
        for client_impl in implementations:
            result = result_map.get((server_impl, client_impl))
            if result is None:
                cells.append(
                    "<td class='border-b border-retro-line/30 bg-retro-paper/35 px-2 py-2 align-top'>"
                    "<div class='rounded-[18px] border border-dashed border-retro-line/35 px-3 py-3 text-center text-xs uppercase tracking-[0.18em] text-retro-bark/35'>"
                    "No case"
                    "</div>"
                    "</td>"
                )
                continue

            status = str(result["status"])
            case_slug = _case_slug(result)
            current_class = " ring-2 ring-retro-bark/70 shadow-soft" if case_slug == current_case_slug else ""
            title = (
                f"Server: {_implementation_label(server_impl)} | "
                f"Client: {_implementation_label(client_impl)} | "
                f"Status: {_status_label(status)}"
            )
            cells.append(
                "<td class='border-b border-retro-line/30 bg-retro-paper/35 px-2 py-2 align-top'>"
                f"<a class='cell-link {_cell_classes(status)}{current_class}' href='{html.escape(href_builder(result), quote=True)}' title='{html.escape(title, quote=True)}' aria-label='{html.escape(title, quote=True)}'>"
                f"<span class='block text-sm font-semibold'>{html.escape(_status_label(status))}</span>"
                "</a>"
                "</td>"
            )
        rows.append(f"<tr>{''.join(cells)}</tr>")

    headers = "".join(
        (
            "<th scope='col' class='min-w-[140px] border-b border-retro-line/40 bg-retro-shell/85 px-3 py-4 text-left align-bottom sm:text-center'>"
            f"{_implementation_identity(client_impl, role_label='Client', primary_class='text-sm font-semibold text-retro-bark', secondary_class='text-xs text-retro-bark/54')}"
            "</th>"
        )
        for client_impl in implementations
    )

    return (
        "<section class='subpanel overflow-hidden'>"
        "<div class='flex flex-col gap-3 border-b border-retro-line/50 px-4 py-4 sm:flex-row sm:items-end sm:justify-between'>"
        "<div>"
        "<p class='text-[11px] font-semibold uppercase tracking-[0.2em] text-retro-bark/48'>Matrix</p>"
        f"<p class='mt-1 text-sm text-retro-bark/66'>{html.escape(caption)}</p>"
        "</div>"
        "<p class='text-xs uppercase tracking-[0.18em] text-retro-bark/44'>Rows = server · columns = client</p>"
        "</div>"
        "<div class='overflow-x-auto'>"
        "<table class='min-w-[980px] w-full border-separate border-spacing-0 text-sm'>"
        "<thead>"
        "<tr>"
        "<th scope='col' class='sticky left-0 z-20 min-w-[190px] border-b border-retro-line/40 bg-retro-shell px-4 py-4 text-left'>"
        "<p class='text-[11px] font-semibold uppercase tracking-[0.18em] text-retro-bark/45'>Axis</p>"
        "<p class='mt-1 text-sm font-semibold text-retro-bark'>Server \\ Client</p>"
        "</th>"
        f"{headers}"
        "</tr>"
        "</thead>"
        f"<tbody>{''.join(rows)}</tbody>"
        "</table>"
        "</div>"
        "</section>"
    )


def _artifact_links(case_dir: Path, *, href_root: str) -> str:
    filenames = (
        "result.json",
        "server-summary.json",
        "client-summary.json",
        "server.log",
        "client.log",
    )
    links = [
        (
            f"<a class='chip' href='{html.escape(f'{href_root}/{filename}', quote=True)}'>"
            f"{html.escape(filename)}"
            "</a>"
        )
        for filename in filenames
        if (case_dir / filename).exists()
    ]
    if not links:
        return "<p class='text-sm text-retro-bark/58'>No downloadable artifacts were written for this case.</p>"
    return f"<div class='flex flex-wrap gap-2'>{''.join(links)}</div>"


def _render_code_panel(
    *,
    heading: str,
    content: str | None,
    mode: str,
) -> str:
    body = content if content is not None else "No artifact was written for this section."
    whitespace = "whitespace-pre" if mode == "json" else "whitespace-pre-wrap"
    return (
        "<section class='code-shell p-4'>"
        f"<h3 class='text-lg'>{html.escape(heading)}</h3>"
        f"<pre class='code-block mt-3 {whitespace}'>{html.escape(body)}</pre>"
        "</section>"
    )


def _case_payload(result: dict[str, Any], *, data_dir: Path) -> dict[str, Any]:
    case_name = _case_slug(result)
    case_dir = data_dir / case_name
    return {
        "case_name": case_name,
        "case_dir": case_dir,
        "result_json": _read_pretty_json(case_dir / "result.json")
        or _safe_json(result),
        "server_summary_json": _read_pretty_json(case_dir / "server-summary.json"),
        "client_summary_json": _read_pretty_json(case_dir / "client-summary.json"),
        "server_log": _read_text(case_dir / "server.log"),
        "client_log": _read_text(case_dir / "client.log"),
    }


def _sidebar_brand(
    *,
    counts: Counter[str],
    scenario_count: int,
    case_count: int,
) -> str:
    return (
        "<section class='panel p-5 sm:p-6'>"
        "<p class='text-[11px] font-semibold uppercase tracking-[0.22em] text-retro-bark/48'>Sendspin Conformance</p>"
        "<h1 class='mt-3 text-3xl leading-tight sm:text-4xl'>Matrix-first report</h1>"
        "<p class='mt-3 max-w-sm text-sm leading-6 text-retro-bark/64'>"
        "Browse the matrix first, then open a single pairing for the raw summaries and logs. "
        "The report is static, mobile-friendly, and tuned for quick comparison."
        "</p>"
        "<div class='mt-5 flex flex-wrap gap-2'>"
        f"{_external_chip('Conformance source', GITHUB_REPO_URL)}"
        f"{_external_chip('Sendspin-audio.com', SENDSPIN_AUDIO_URL)}"
        "</div>"
        "<div class='mt-5 grid gap-3 sm:grid-cols-3 lg:grid-cols-1'>"
        "<div class='subpanel px-4 py-4'>"
        "<p class='text-[11px] font-semibold uppercase tracking-[0.18em] text-retro-bark/48'>Tests</p>"
        f"<p class='mt-2 text-2xl font-semibold'>{scenario_count}</p>"
        "</div>"
        "<div class='subpanel px-4 py-4'>"
        "<p class='text-[11px] font-semibold uppercase tracking-[0.18em] text-retro-bark/48'>Pairings</p>"
        f"<p class='mt-2 text-2xl font-semibold'>{case_count}</p>"
        "</div>"
        "<div class='subpanel px-4 py-4'>"
        "<p class='text-[11px] font-semibold uppercase tracking-[0.18em] text-retro-bark/48'>Passing</p>"
        f"<p class='mt-2 text-2xl font-semibold'>{counts.get('passed', 0)}</p>"
        f"<p class='mt-1 text-sm text-retro-bark/58'>{counts.get('failed', 0)} failing</p>"
        "</div>"
        "</div>"
        "</section>"
    )


def _render_index_page(results: list[dict[str, Any]]) -> str:
    scenario_groups = _scenario_results(results)
    counts = Counter(str(result["status"]) for result in results)
    sections: list[str] = []
    for scenario_id, scenario_results in scenario_groups:
        scenario_counts = Counter(str(result["status"]) for result in scenario_results)
        sections.append(
            "<section class='panel p-5 sm:p-6'>"
            "<div class='flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between'>"
            "<div class='max-w-3xl'>"
            "<p class='text-[11px] font-semibold uppercase tracking-[0.22em] text-retro-bark/48'>Test</p>"
            f"<h2 class='mt-2 text-2xl sm:text-3xl'>{html.escape(_scenario_name(scenario_id))}</h2>"
            f"<p class='mt-3 text-sm leading-6 text-retro-bark/66 sm:text-base'>{html.escape(_scenario_description(scenario_id))}</p>"
            "</div>"
            "<div class='flex flex-wrap items-center gap-2 xl:justify-end'>"
            f"<span class='status-pill {_status_classes('passed')}'>{scenario_counts.get('passed', 0)} passed</span>"
            f"<span class='status-pill {_status_classes('failed')}'>{scenario_counts.get('failed', 0)} failed</span>"
            f"{_external_chip('View test source', _scenario_source_url(scenario_id))}"
            f"<a class='chip' href='{html.escape(_scenario_href(scenario_id), quote=True)}'>Scenario page</a>"
            "</div>"
            "</div>"
            "<div class='mt-5'>"
            f"{_render_matrix(scenario_results, caption='Select a cell to view that server/client run.', href_builder=_case_href)}"
            "</div>"
            "</section>"
        )

    body = (
        "<div class='app-shell'>"
        "<div class='mx-auto max-w-[1540px] px-4 py-4 sm:px-6 lg:px-8 lg:py-6'>"
        "<div class='grid gap-6 lg:grid-cols-[320px_minmax(0,1fr)]'>"
        "<aside class='space-y-4 lg:sticky lg:top-6 self-start'>"
        f"{_sidebar_brand(counts=counts, scenario_count=len(scenario_groups), case_count=len(results))}"
        f"{_nav_scenarios(scenario_groups)}"
        "</aside>"
        "<main class='space-y-6'>"
        "<section class='panel p-5 sm:p-6'>"
        "<p class='text-[11px] font-semibold uppercase tracking-[0.22em] text-retro-bark/48'>Overview</p>"
        "<h2 class='mt-2 text-2xl sm:text-3xl'>All scenarios at a glance</h2>"
        "<p class='mt-3 max-w-4xl text-sm leading-6 text-retro-bark/64 sm:text-base'>"
        "This view stays matrix-first so each test is understandable before you drill down. "
        "Every cell opens a dedicated case page instead of expanding a long document."
        "</p>"
        f"<div class='mt-5'>{_summary_cards(counts=counts, total_label='all scenarios', total_value=len(results))}</div>"
        "</section>"
        f"{''.join(sections) if sections else '<section class=\"panel p-6 text-sm text-retro-bark/62\">No scenario results were found.</section>'}"
        "</main>"
        "</div>"
        "</div>"
        "</div>"
    )
    return _page_shell(title="Sendspin Conformance", body=body)


def _render_scenario_page(
    scenario_id: str,
    results: list[dict[str, Any]],
    *,
    all_scenarios: list[tuple[str, list[dict[str, Any]]]],
) -> str:
    counts = Counter(str(result["status"]) for result in results)
    ordered_results = sorted(results, key=lambda result: _case_key(result))

    case_rows = []
    for result in ordered_results:
        server_impl = str(result["server_impl"])
        client_impl = str(result["client_impl"])
        case_rows.append(
            f"<a class='inbox-row' href='../{html.escape(_case_href(result), quote=True)}'>"
            "<div class='min-w-0'>"
            "<div class='flex flex-wrap items-center gap-x-2 gap-y-1'>"
            "<span class='chip'>Server</span>"
            f"<span class='text-base font-semibold'>{html.escape(_implementation_label(server_impl))}</span>"
            "<span class='text-retro-bark/35'>→</span>"
            "<span class='chip'>Client</span>"
            f"<span class='text-base font-semibold'>{html.escape(_implementation_label(client_impl))}</span>"
            "</div>"
            f"<p class='mt-2 text-sm leading-6 text-retro-bark/64'>{html.escape(str(result['reason']))}</p>"
            "</div>"
            "<div class='flex items-center gap-3'>"
            f"<span class='status-pill {_status_classes(str(result['status']))}'>{html.escape(_status_label(str(result['status'])))}</span>"
            "<span class='hidden text-xs font-semibold uppercase tracking-[0.18em] text-retro-bark/40 sm:inline'>Open</span>"
            "</div>"
            "</a>"
        )

    body = (
        "<div class='app-shell'>"
        "<div class='mx-auto max-w-[1540px] px-4 py-4 sm:px-6 lg:px-8 lg:py-6'>"
        "<div class='grid gap-6 lg:grid-cols-[320px_minmax(0,1fr)]'>"
        "<aside class='space-y-4 lg:sticky lg:top-6 self-start'>"
        "<section class='panel p-5 sm:p-6'>"
        "<div class='flex flex-wrap gap-2'>"
        f"<a class='chip' href='../index.html'>Back to overview</a>"
        f"{_external_chip('Conformance source', GITHUB_REPO_URL)}"
        f"{_external_chip('Sendspin-audio.com', SENDSPIN_AUDIO_URL)}"
        f"{_external_chip('View test source', _scenario_source_url(scenario_id))}"
        "</div>"
        "<p class='mt-5 text-[11px] font-semibold uppercase tracking-[0.22em] text-retro-bark/48'>Scenario</p>"
        f"<h1 class='mt-2 text-3xl leading-tight'>{html.escape(_scenario_name(scenario_id))}</h1>"
        f"<p class='mt-3 text-sm leading-6 text-retro-bark/64'>{html.escape(_scenario_description(scenario_id))}</p>"
        f"<div class='mt-5'>{_summary_cards(counts=counts, total_label='pairings', total_value=len(ordered_results))}</div>"
        "</section>"
        f"{_nav_scenarios(all_scenarios, current_scenario_id=scenario_id, href_prefix='../')}"
        "</aside>"
        "<main class='space-y-6'>"
        "<section class='panel p-5 sm:p-6'>"
        "<div class='flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between'>"
        "<div>"
        "<p class='text-[11px] font-semibold uppercase tracking-[0.22em] text-retro-bark/48'>Navigator</p>"
        "<h2 class='mt-2 text-2xl'>Scenario matrix</h2>"
        "<p class='mt-2 text-sm leading-6 text-retro-bark/64'>"
        "The matrix is the shortest explanation of what this test covers. Use it as the main navigation surface."
        "</p>"
        "</div>"
        "<div class='flex flex-wrap gap-2'>"
        f"<span class='status-pill {_status_classes('passed')}'>{counts.get('passed', 0)} passed</span>"
        f"<span class='status-pill {_status_classes('failed')}'>{counts.get('failed', 0)} failed</span>"
        "</div>"
        "</div>"
        f"<div class='mt-5'>{_render_matrix(ordered_results, caption='Select a cell to view that server/client run.', href_builder=lambda result: '../' + _case_href(result))}</div>"
        "</section>"
        "<section class='panel p-5 sm:p-6'>"
        "<p class='text-[11px] font-semibold uppercase tracking-[0.22em] text-retro-bark/48'>Pairings</p>"
        "<h2 class='mt-2 text-2xl'>Case inbox</h2>"
        "<p class='mt-2 text-sm leading-6 text-retro-bark/64'>"
        "Each row is one concrete run. Open a row when you want the raw hello payloads, summaries, or logs."
        "</p>"
        "<div class='mt-5 space-y-2'>"
        f"{''.join(case_rows) if case_rows else '<div class=\"subpanel px-4 py-4 text-sm text-retro-bark/60\">No cases were written for this scenario.</div>'}"
        "</div>"
        "</section>"
        "</main>"
        "</div>"
        "</div>"
        "</div>"
    )
    return _page_shell(
        title=f"Sendspin Conformance · {_scenario_name(scenario_id)}",
        body=body,
    )


def _render_case_page(
    result: dict[str, Any],
    *,
    scenario_results: list[dict[str, Any]],
    data_dir: Path,
) -> str:
    scenario_id = str(result["scenario_id"])
    case_name = _case_slug(result)
    payload = _case_payload(result, data_dir=data_dir)
    case_dir = payload["case_dir"]
    server_impl = str(result["server_impl"])
    client_impl = str(result["client_impl"])
    status = str(result["status"])
    server_label = _implementation_label(server_impl)
    client_label = _implementation_label(client_impl)
    ordered_results = sorted(scenario_results, key=lambda item: _case_key(item))

    nav_rows = []
    for sibling in ordered_results:
        sibling_slug = _case_slug(sibling)
        active_class = " nav-item-active" if sibling_slug == case_name else ""
        nav_rows.append(
            f"<a class='nav-item{active_class}' href='../{html.escape(_case_href(sibling), quote=True)}'>"
            "<div class='min-w-0'>"
            "<p class='text-sm font-semibold'>"
            f"{html.escape(_implementation_label(str(sibling['server_impl'])))} → {html.escape(_implementation_label(str(sibling['client_impl'])))}"
            "</p>"
            f"<p class='nav-copy mt-1 text-sm text-retro-bark/60'>{html.escape(str(sibling['reason']))}</p>"
            "</div>"
            f"<span class='status-pill {_status_classes(str(sibling['status']))}'>{html.escape(_status_label(str(sibling['status'])))}</span>"
            "</a>"
        )

    summary_tab = f"{case_name}--summary"
    server_tab = f"{case_name}--server"
    client_tab = f"{case_name}--client"

    body = (
        "<div class='app-shell'>"
        "<div class='mx-auto max-w-[1540px] px-4 py-4 sm:px-6 lg:px-8 lg:py-6'>"
        "<div class='grid gap-6 xl:grid-cols-[340px_minmax(0,1fr)]'>"
        "<aside class='space-y-4 xl:sticky xl:top-6 self-start'>"
        "<section class='panel p-5 sm:p-6'>"
        "<div class='flex flex-wrap gap-2'>"
        f"<a class='chip' href='../index.html'>Overview</a>"
        f"<a class='chip' href='../{html.escape(_scenario_href(scenario_id), quote=True)}'>{html.escape(_scenario_name(scenario_id))}</a>"
        f"{_external_chip('Conformance source', GITHUB_REPO_URL)}"
        f"{_external_chip('Sendspin-audio.com', SENDSPIN_AUDIO_URL)}"
        f"{_external_chip('View test source', _scenario_source_url(scenario_id))}"
        "</div>"
        "<p class='mt-5 text-[11px] font-semibold uppercase tracking-[0.22em] text-retro-bark/48'>Pairing</p>"
        f"<h1 class='mt-2 text-2xl leading-tight'>{html.escape(server_label)} → {html.escape(client_label)}</h1>"
        f"<p class='mt-3 inline-flex status-pill {_status_classes(status)}'>{html.escape(_status_label(status))}</p>"
        f"<p class='mt-3 text-sm leading-6 text-retro-bark/64'>{html.escape(str(result['reason']))}</p>"
        "<div class='mt-5 grid gap-3'>"
        "<div class='subpanel px-4 py-4'>"
        "<p class='text-[11px] font-semibold uppercase tracking-[0.18em] text-retro-bark/48'>Server implementation</p>"
        f"{_implementation_identity(server_impl, primary_class='mt-2 text-lg font-semibold', secondary_class='mt-1 text-sm text-retro-bark/58')}"
        "</div>"
        "<div class='subpanel px-4 py-4'>"
        "<p class='text-[11px] font-semibold uppercase tracking-[0.18em] text-retro-bark/48'>Client implementation</p>"
        f"{_implementation_identity(client_impl, primary_class='mt-2 text-lg font-semibold', secondary_class='mt-1 text-sm text-retro-bark/58')}"
        "</div>"
        "</div>"
        "</section>"
        "<section class='panel p-4 sm:p-5'>"
        "<p class='text-[11px] font-semibold uppercase tracking-[0.22em] text-retro-bark/48'>Matrix navigator</p>"
        f"<div class='mt-4'>{_render_matrix(ordered_results, caption='Current pairing is highlighted. Open another cell to move laterally through the scenario.', href_builder=lambda item: '../' + _case_href(item), current_case_slug=case_name)}</div>"
        "</section>"
        "<section class='panel p-4 sm:p-5'>"
        "<p class='text-[11px] font-semibold uppercase tracking-[0.22em] text-retro-bark/48'>Other pairings</p>"
        "<div class='mt-3 space-y-2'>"
        f"{''.join(nav_rows)}"
        "</div>"
        "</section>"
        "</aside>"
        "<main class='space-y-6'>"
        "<section class='panel p-5 sm:p-6'>"
        "<p class='text-[11px] font-semibold uppercase tracking-[0.22em] text-retro-bark/48'>Case detail</p>"
        f"<h2 class='mt-2 text-3xl'>{html.escape(_scenario_name(scenario_id))}</h2>"
        f"<p class='mt-3 max-w-4xl text-sm leading-6 text-retro-bark/64 sm:text-base'>{html.escape(_scenario_description(scenario_id))}</p>"
        "<div class='mt-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-4'>"
        "<div class='subpanel px-4 py-4'>"
        "<p class='text-[11px] font-semibold uppercase tracking-[0.18em] text-retro-bark/48'>Status</p>"
        f"<p class='mt-2 text-xl font-semibold'>{html.escape(_status_label(status))}</p>"
        "</div>"
        "<div class='subpanel px-4 py-4'>"
        "<p class='text-[11px] font-semibold uppercase tracking-[0.18em] text-retro-bark/48'>Server exit</p>"
        f"<p class='mt-2 text-xl font-semibold'>{html.escape(str(result.get('server_exit_code')))}</p>"
        "</div>"
        "<div class='subpanel px-4 py-4'>"
        "<p class='text-[11px] font-semibold uppercase tracking-[0.18em] text-retro-bark/48'>Client exit</p>"
        f"<p class='mt-2 text-xl font-semibold'>{html.escape(str(result.get('client_exit_code')))}</p>"
        "</div>"
        "<div class='subpanel px-4 py-4'>"
        "<p class='text-[11px] font-semibold uppercase tracking-[0.18em] text-retro-bark/48'>Artifacts</p>"
        f"<div class='mt-2'>{_artifact_links(case_dir, href_root='../data/' + case_name)}</div>"
        "</div>"
        "</div>"
        "</section>"
        "<section class='panel p-5 sm:p-6' data-tabset>"
        "<div class='flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between'>"
        "<div>"
        "<p class='text-[11px] font-semibold uppercase tracking-[0.22em] text-retro-bark/48'>Inspection</p>"
        "<h2 class='mt-2 text-2xl'>Summaries and logs</h2>"
        "</div>"
        "<div class='flex flex-wrap gap-2'>"
        f"<button type='button' class='tab-button tab-idle' data-tab-button='{html.escape(summary_tab, quote=True)}' data-default-tab='true' aria-selected='false'>Summary</button>"
        f"<button type='button' class='tab-button tab-idle' data-tab-button='{html.escape(server_tab, quote=True)}' aria-selected='false'>Server</button>"
        f"<button type='button' class='tab-button tab-idle' data-tab-button='{html.escape(client_tab, quote=True)}' aria-selected='false'>Client</button>"
        "</div>"
        "</div>"
        "<section class='mt-5 space-y-4' data-tab-panel='"
        f"{html.escape(summary_tab, quote=True)}"
        "'>"
        f"{_render_code_panel(heading='Matrix result', content=str(payload['result_json']), mode='json')}"
        "</section>"
        "<section class='mt-5 space-y-4' data-tab-panel='"
        f"{html.escape(server_tab, quote=True)}"
        "' hidden>"
        "<div class='grid gap-4 2xl:grid-cols-2'>"
        f"{_render_code_panel(heading='Server summary (JSON)', content=payload['server_summary_json'], mode='json')}"
        f"{_render_code_panel(heading='Server log', content=payload['server_log'], mode='log')}"
        "</div>"
        "</section>"
        "<section class='mt-5 space-y-4' data-tab-panel='"
        f"{html.escape(client_tab, quote=True)}"
        "' hidden>"
        "<div class='grid gap-4 2xl:grid-cols-2'>"
        f"{_render_code_panel(heading='Client summary (JSON)', content=payload['client_summary_json'], mode='json')}"
        f"{_render_code_panel(heading='Client log', content=payload['client_log'], mode='log')}"
        "</div>"
        "</section>"
        "</section>"
        "</main>"
        "</div>"
        "</div>"
        "</div>"
    )
    return _page_shell(
        title=f"Sendspin Conformance · {_scenario_name(scenario_id)} · {server_label} to {client_label}",
        body=body,
        include_tabs=True,
    )


def build_site(results_dir: Path, site_dir: Path) -> None:
    """Generate a static report site with scenario and case pages."""
    data_dir = _data_dir(results_dir)
    results_payload = read_json(data_dir / "index.json")
    results: list[dict[str, Any]] = list(results_payload["results"])

    site_dir.mkdir(parents=True, exist_ok=True)
    _clear_legacy_dirs(site_dir)
    _sync_case_artifacts(data_dir, site_dir)
    scenarios_dir = _prepare_output_dir(site_dir, "scenarios")
    cases_dir = _prepare_output_dir(site_dir, "cases")

    scenario_groups = _scenario_results(results)

    (site_dir / "index.html").write_text(_render_index_page(results), encoding="utf-8")

    for scenario_id, scenario_results in scenario_groups:
        (scenarios_dir / f"{scenario_id}.html").write_text(
            _render_scenario_page(
                scenario_id,
                scenario_results,
                all_scenarios=scenario_groups,
            ),
            encoding="utf-8",
        )
        for result in scenario_results:
            (cases_dir / f"{_case_slug(result)}.html").write_text(
                _render_case_page(
                    result,
                    scenario_results=scenario_results,
                    data_dir=data_dir,
                ),
                encoding="utf-8",
            )

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
        --retro-walnut: 99 57 29;
        --retro-burnt: 138 71 30;
        --retro-copper: 182 101 49;
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
        background-color: rgb(var(--retro-clay) / 0.45);
        color: rgb(var(--retro-bark));
      }
    }

    @layer components {
      .app-shell {
        background:
          linear-gradient(180deg, rgba(251, 242, 229, 0.7) 0%, rgba(244, 231, 211, 0.86) 100%),
          radial-gradient(circle at top left, rgba(182, 101, 49, 0.14), transparent 26%),
          radial-gradient(circle at top right, rgba(75, 47, 27, 0.08), transparent 28%);
      }

      .surface {
        @apply rounded-xl border backdrop-blur-sm;
        border-color: rgb(var(--retro-line) / 0.56);
        background-color: rgb(var(--retro-paper) / 0.9);
        box-shadow:
          0 1px 0 rgba(255, 255, 255, 0.55) inset,
          0 12px 30px rgba(92, 56, 29, 0.08);
      }

      .surface-muted {
        background-color: rgb(var(--retro-paper) / 0.74);
      }

      .surface-inset {
        @apply rounded-lg border;
        border-color: rgb(var(--retro-line) / 0.46);
        background-color: rgb(var(--retro-shell) / 0.52);
      }

      .page-header {
        @apply rounded-xl border px-5 py-5 sm:px-7 sm:py-6;
        border-color: rgb(var(--retro-line) / 0.62);
        background:
          linear-gradient(180deg, rgba(251, 242, 229, 0.96) 0%, rgba(247, 234, 217, 0.92) 100%);
        box-shadow:
          0 1px 0 rgba(255, 255, 255, 0.55) inset,
          0 22px 46px rgba(92, 56, 29, 0.10);
      }

      .page-header-overview {
        border-top: 4px solid rgb(var(--retro-copper));
      }

      .page-header-scenario {
        border-top: 4px solid rgb(var(--retro-burnt));
      }

      .page-header-case {
        border-top: 4px solid rgb(var(--retro-bark));
      }

      .eyebrow {
        @apply text-[11px] font-semibold uppercase tracking-[0.22em];
        color: rgb(var(--retro-burnt) / 0.78);
      }

      .subtle-copy {
        color: rgb(var(--retro-bark) / 0.68);
      }

      .muted-copy {
        color: rgb(var(--retro-bark) / 0.56);
      }

      .chip {
        @apply inline-flex items-center gap-2 rounded-md border px-3 py-2 text-[11px] font-semibold uppercase tracking-[0.14em];
        border-color: rgb(var(--retro-line) / 0.58);
        background-color: rgb(var(--retro-paper) / 0.82);
        color: rgb(var(--retro-bark) / 0.78);
      }

      .chip:hover {
        background-color: rgb(var(--retro-paper));
        color: rgb(var(--retro-bark));
      }

      .resource-shell {
        @apply overflow-hidden rounded-lg border;
        border-color: rgb(var(--retro-line) / 0.46);
        background-color: rgb(var(--retro-shell) / 0.34);
      }

      .resource-link {
        @apply flex items-center justify-between gap-3 border-b px-4 py-3 transition;
        border-color: rgb(var(--retro-line) / 0.28);
      }

      .resource-link:last-child {
        @apply border-b-0;
      }

      .resource-link:hover {
        background-color: rgb(var(--retro-paper) / 0.72);
      }

      .resource-link-label {
        @apply text-sm font-semibold;
        color: rgb(var(--retro-bark) / 0.88);
      }

      .resource-link-meta {
        @apply text-[11px] font-semibold uppercase tracking-[0.16em];
        color: rgb(var(--retro-burnt) / 0.7);
      }

      .resource-link-arrow {
        @apply text-sm;
        color: rgb(var(--retro-bark) / 0.42);
      }

      .breadcrumb {
        @apply flex flex-wrap items-center gap-x-2 gap-y-1 text-sm;
        color: rgb(var(--retro-bark) / 0.58);
      }

      .breadcrumb-link {
        color: rgb(var(--retro-burnt) / 0.86);
      }

      .breadcrumb-link:hover {
        color: rgb(var(--retro-bark));
      }

      .breadcrumb-current {
        color: rgb(var(--retro-bark));
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

      .status-unsupported {
        @apply border-amber-900/20 bg-amber-300/55;
        color: rgb(var(--retro-bark));
      }

      .cell-link {
        @apply block rounded-md border px-3 py-3 text-left transition focus-visible:outline-none focus-visible:ring-2 sm:text-center;
      }

      .cell-link:focus-visible {
        --tw-ring-color: rgb(var(--retro-bark) / 0.45);
      }

      .cell-link:hover {
        transform: translateY(-1px);
      }

      .cell-passed {
        @apply border-amber-800/15 bg-amber-100/85 hover:bg-amber-100;
        color: rgb(var(--retro-bark));
      }

      .cell-failed {
        @apply border-orange-900/15 bg-orange-100/85 hover:bg-orange-100;
        color: rgb(var(--retro-bark));
      }

      .cell-skipped {
        @apply border-stone-500/15 bg-stone-100/85 hover:bg-stone-100;
        color: rgb(var(--retro-bark));
      }

      .cell-unsupported {
        @apply border-amber-900/15 bg-amber-100/85 hover:bg-amber-100;
        color: rgb(var(--retro-bark));
      }

      .nav-item {
        @apply block rounded-lg border px-4 py-4 transition;
        border-color: transparent;
      }

      .nav-item:hover {
        border-color: rgb(var(--retro-line) / 0.7);
        background-color: rgb(var(--retro-paper) / 0.86);
      }

      .nav-item-active {
        border-color: rgb(var(--retro-bark) / 0.28);
        background-color: rgb(var(--retro-bark));
        color: rgb(var(--retro-paper));
        box-shadow: 0 10px 24px rgba(75, 47, 27, 0.18);
      }

      .nav-item-active .nav-copy,
      .nav-item-active .nav-meta {
        color: rgb(var(--retro-paper) / 0.72);
      }

      .nav-item-compact {
        @apply px-3 py-3;
      }

      .nav-item-title {
        @apply text-sm font-semibold leading-snug;
      }

      .nav-meta-compact {
        @apply mt-2 flex items-center justify-between gap-3 text-[11px] font-semibold uppercase tracking-[0.16em];
        color: rgb(var(--retro-bark) / 0.56);
      }

      .nav-item-active .nav-meta-compact {
        color: rgb(var(--retro-paper) / 0.72);
      }

      .sidebar-tests {
        @apply hidden;
      }

      @media (min-width: 1024px) {
        .sidebar-tests {
          display: block;
        }
      }

      .sidebar-rail {
        @apply space-y-4 self-start;
      }

      @media (min-width: 1024px) {
        .sidebar-rail-lg {
          position: sticky;
          top: 1.5rem;
          max-height: calc(100vh - 3rem);
          overflow-y: auto;
          overscroll-behavior: contain;
          scrollbar-gutter: stable;
          padding-right: 0.35rem;
        }
      }

      @media (min-width: 1280px) {
        .sidebar-rail-xl {
          position: sticky;
          top: 1.5rem;
          max-height: calc(100vh - 3rem);
          overflow-y: auto;
          overscroll-behavior: contain;
          scrollbar-gutter: stable;
          padding-right: 0.35rem;
        }
      }

      .list-shell {
        @apply overflow-hidden rounded-xl border;
        border-color: rgb(var(--retro-line) / 0.56);
        background-color: rgb(var(--retro-paper) / 0.9);
        box-shadow: 0 10px 26px rgba(92, 56, 29, 0.08);
      }

      .list-row {
        @apply block border-b px-4 py-4 transition sm:px-5;
        border-color: rgb(var(--retro-line) / 0.34);
      }

      .list-row:last-child {
        border-bottom: 0;
      }

      .list-row:hover {
        background-color: rgb(var(--retro-paper));
      }

      .detail-card {
        @apply rounded-lg border px-4 py-4;
        border-color: rgb(var(--retro-line) / 0.46);
        background-color: rgb(var(--retro-paper) / 0.72);
      }

      .keyval {
        @apply grid gap-3;
      }

      .keyval-row {
        @apply flex items-start justify-between gap-4 border-b pb-3;
        border-color: rgb(var(--retro-line) / 0.28);
      }

      .keyval-row:last-child {
        @apply border-b-0 pb-0;
      }

      .tab-button {
        @apply rounded-md border px-4 py-2.5 text-sm font-semibold transition;
      }

      .tab-idle {
        border-color: rgb(var(--retro-line) / 0.58);
        background-color: rgb(var(--retro-paper) / 0.82);
        color: rgb(var(--retro-bark) / 0.72);
      }

      .tab-idle:hover {
        background-color: rgb(var(--retro-paper));
        color: rgb(var(--retro-bark));
      }

      .tab-active {
        border-color: rgb(var(--retro-bark));
        background-color: rgb(var(--retro-bark));
        color: rgb(var(--retro-paper));
        box-shadow: 0 8px 18px rgba(75, 47, 27, 0.16);
      }

      .code-shell {
        @apply rounded-lg border;
        border-color: rgb(var(--retro-line) / 0.46);
        background-color: rgb(var(--retro-paper) / 0.76);
      }

      .code-block {
        @apply max-h-[28rem] overflow-auto rounded-b-xl px-4 py-4;
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
    "unsupported": "Unsupported",
}

STATUS_CLASSES = {
    "passed": "status-passed",
    "failed": "status-failed",
    "skipped": "status-skipped",
    "unsupported": "status-unsupported",
}

CELL_CLASSES = {
    "passed": "cell-passed",
    "failed": "cell-failed",
    "skipped": "cell-skipped",
    "unsupported": "cell-unsupported",
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


def _resource_link(label: str, href: str, *, meta: str = "External") -> str:
    return (
        f"<a class='resource-link' href='{html.escape(href, quote=True)}' "
        "target='_blank' rel='noreferrer'>"
        "<span class='min-w-0'>"
        f"<span class='resource-link-label block'>{html.escape(label)}</span>"
        f"<span class='resource-link-meta mt-1 block'>{html.escape(meta)}</span>"
        "</span>"
        "<span aria-hidden='true' class='resource-link-arrow'>&nearr;</span>"
        "</a>"
    )


def _resource_section(*links: str) -> str:
    if not links:
        return ""
    return (
        "<section class='surface p-5'>"
        "<p class='eyebrow'>Resources</p>"
        f"<div class='resource-shell mt-4'>{''.join(links)}</div>"
        "</section>"
    )


def _sidebar_resources(*, scenario_id: str | None = None) -> str:
    links = [
        _resource_link("Conformance source", GITHUB_REPO_URL, meta="GitHub"),
        _resource_link("Sendspin-audio.com", SENDSPIN_AUDIO_URL, meta="Website"),
    ]
    if scenario_id is not None:
        links.append(
            _resource_link(
                "Test source",
                _scenario_source_url(scenario_id),
                meta="Scenario source",
            )
        )
    return _resource_section(*links)


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


def _display_status(result: dict[str, Any]) -> str:
    status = str(result["status"])
    if status != "failed":
        return status

    reason = str(result.get("reason") or "").lower()
    unsupported_markers = (
        "does not support",
        "currently a client library",
        "does not yet expose",
        "not a server implementation",
        "only supports client-initiated",
        "only supports server-initiated",
    )
    if any(marker in reason for marker in unsupported_markers):
        return "unsupported"
    return status


def _status_counts(results: list[dict[str, Any]]) -> Counter[str]:
    return Counter(_display_status(result) for result in results)


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
    items = [("Total", total_value, total_label), ("Passed", counts.get("passed", 0), "passing")]
    if counts.get("unsupported", 0):
        items.append(("Unsupported", counts["unsupported"], "not supported"))
    if counts.get("failed", 0) or not counts.get("unsupported", 0):
        items.append(("Failed", counts.get("failed", 0), "failing"))
    if counts.get("skipped", 0):
        items.append(("Skipped", counts["skipped"], "skipped"))
    cards = "".join(
        (
            "<div class='detail-card'>"
            f"<p class='eyebrow'>{_escape(label)}</p>"
            f"<p class='mt-2 text-2xl font-semibold'>{_escape(value)}</p>"
            f"<p class='mt-1 text-sm muted-copy'>{_escape(subtitle)}</p>"
            "</div>"
        )
        for label, value, subtitle in items
    )
    return f"<div class='grid gap-3 sm:grid-cols-2 xl:grid-cols-5'>{cards}</div>"


def _breadcrumb(items: list[tuple[str, str | None]]) -> str:
    parts: list[str] = []
    for index, (label, href) in enumerate(items):
        if index:
            parts.append("<span aria-hidden='true' class='muted-copy'>&rarr;</span>")
        if href is None:
            parts.append(f"<span class='breadcrumb-current'>{_escape(label)}</span>")
            continue
        parts.append(
            f"<a class='breadcrumb-link' href='{html.escape(href, quote=True)}'>{_escape(label)}</a>"
        )
    return f"<nav class='breadcrumb' aria-label='Breadcrumb'>{''.join(parts)}</nav>"


def _page_header(
    *,
    accent: str,
    breadcrumb: str,
    kicker: str,
    title: str,
    description: str,
    actions: str = "",
    meta: str = "",
) -> str:
    actions_markup = (
        "<div class='flex flex-wrap gap-2 xl:max-w-sm xl:justify-end'>"
        f"{actions}"
        "</div>"
        if actions
        else ""
    )
    meta_markup = f"<div class='mt-5'>{meta}</div>" if meta else ""
    return (
        f"<section class='page-header page-header-{html.escape(accent, quote=True)}'>"
        f"{breadcrumb}"
        "<div class='mt-4 flex flex-col gap-5 xl:flex-row xl:items-start xl:justify-between'>"
        "<div class='min-w-0 max-w-4xl'>"
        f"<p class='eyebrow'>{_escape(kicker)}</p>"
        f"<h1 class='mt-2 text-3xl leading-tight sm:text-4xl'>{_escape(title)}</h1>"
        f"<p class='mt-3 max-w-3xl text-sm leading-6 subtle-copy sm:text-base'>{_escape(description)}</p>"
        f"{meta_markup}"
        "</div>"
        f"{actions_markup}"
        "</div>"
        "</section>"
    )


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
        counts = _status_counts(scenario_results)
        active_class = " nav-item-active" if scenario_id == current_scenario_id else ""
        items.append(
            f"<a class='nav-item nav-item-compact{active_class}' href='{html.escape(href_prefix + _scenario_href(scenario_id), quote=True)}'>"
            "<div class='min-w-0'>"
            f"<p class='nav-item-title'>{html.escape(_scenario_name(scenario_id))}</p>"
            "</div>"
            "<div class='nav-meta nav-meta-compact'>"
            f"<span>{counts.get('passed', 0)}/{len(scenario_results)} green</span>"
            f"<span class='normal-case tracking-normal'>{len(scenario_results)} pairings</span>"
            "</div>"
            "</a>"
        )
    return (
        "<section class='surface p-4 sm:p-5 sidebar-tests'>"
        "<p class='eyebrow'>Tests</p>"
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
    server_implementations, client_implementations = _matrix_axes(results)
    result_map = {
        (str(result["server_impl"]), str(result["client_impl"])): result for result in results
    }

    rows: list[str] = []
    for server_impl in server_implementations:
        cells = [
            (
                "<th scope='row' class='sticky left-0 z-10 min-w-[190px] border-b px-4 py-4 text-left align-top' "
                "style='border-color: rgb(var(--retro-line) / 0.36); background-color: rgb(var(--retro-paper) / 0.97)'>"
                f"{_implementation_identity(server_impl, role_label='Server', primary_class='text-sm font-semibold text-retro-bark', secondary_class='text-xs text-retro-bark/54')}"
                "</th>"
            )
        ]
        for client_impl in client_implementations:
            result = result_map.get((server_impl, client_impl))
            if result is None:
                cells.append(
                    "<td class='border-b px-2 py-2 align-top' style='border-color: rgb(var(--retro-line) / 0.28); background-color: rgb(var(--retro-paper) / 0.4)'>"
                    "<div class='rounded-lg border border-dashed px-3 py-3 text-center text-xs uppercase tracking-[0.18em]' "
                    "style='border-color: rgb(var(--retro-line) / 0.35); color: rgb(var(--retro-bark) / 0.35)'>"
                    "No case"
                    "</div>"
                    "</td>"
                )
                continue

            status = _display_status(result)
            case_slug = _case_slug(result)
            current_class = " ring-2 ring-retro-bark/70" if case_slug == current_case_slug else ""
            title = (
                f"Server: {_implementation_label(server_impl)} | "
                f"Client: {_implementation_label(client_impl)} | "
                f"Status: {_status_label(status)}"
            )
            cells.append(
                "<td class='border-b px-2 py-2 align-top' style='border-color: rgb(var(--retro-line) / 0.28); background-color: rgb(var(--retro-paper) / 0.4)'>"
                f"<a class='cell-link {_cell_classes(status)}{current_class}' href='{html.escape(href_builder(result), quote=True)}' title='{html.escape(title, quote=True)}' aria-label='{html.escape(title, quote=True)}'>"
                f"<span class='block text-sm font-semibold'>{html.escape(_status_label(status))}</span>"
                "</a>"
                "</td>"
            )
        rows.append(f"<tr>{''.join(cells)}</tr>")

    headers = "".join(
        (
            "<th scope='col' class='min-w-[140px] border-b px-3 py-4 text-left align-bottom sm:text-center' "
            "style='border-color: rgb(var(--retro-line) / 0.36); background-color: rgb(var(--retro-shell) / 0.88)'>"
            f"{_implementation_identity(client_impl, role_label='Client', primary_class='text-sm font-semibold text-retro-bark', secondary_class='text-xs text-retro-bark/54')}"
            "</th>"
        )
        for client_impl in client_implementations
    )

    return (
        "<section class='list-shell overflow-hidden'>"
        "<div class='border-b px-4 py-4' "
        "style='border-color: rgb(var(--retro-line) / 0.42)'>"
        "<div>"
        "<p class='eyebrow'>Matrix</p>"
        f"<p class='mt-1 text-sm subtle-copy'>{html.escape(caption)}</p>"
        "</div>"
        "</div>"
        "<div class='overflow-x-auto'>"
        "<table class='min-w-[980px] w-full border-separate border-spacing-0 text-sm'>"
        "<thead>"
        "<tr>"
        "<th scope='col' class='sticky left-0 z-20 min-w-[190px] border-b px-4 py-4 text-left' "
        "style='border-color: rgb(var(--retro-line) / 0.36); background-color: rgb(var(--retro-shell))'>"
        "<p class='eyebrow'>Axis</p>"
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


def _matrix_axes(results: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    if not results:
        return implementation_names(), implementation_names()

    scenario_id = str(results[0]["scenario_id"])
    scenario = get_scenario(scenario_id)
    known_names = implementation_names()

    if scenario is None:
        server_impls = sorted({str(result["server_impl"]) for result in results})
        client_impls = sorted({str(result["client_impl"]) for result in results})
        return server_impls, client_impls

    def supported_for_role(role: str) -> list[str]:
        names: list[str] = []
        for name in known_names:
            implementation = IMPLEMENTATIONS.get(name)
            if implementation is None:
                continue
            role_spec = implementation.server if role == "server" else implementation.client
            if not role_spec.supported:
                continue
            if role_spec.unsupported_reason(
                implementation=name,
                role=role,  # type: ignore[arg-type]
                scenario=scenario,
            ) is None:
                names.append(name)

        extra_names = sorted(
            {
                str(result[f"{role}_impl"])
                for result in results
                if str(result[f"{role}_impl"]) not in IMPLEMENTATIONS
            }
        )
        names.extend(extra_names)
        return names

    return supported_for_role("server"), supported_for_role("client")


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
        return "<p class='text-sm muted-copy'>No downloadable artifacts were written for this case.</p>"
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


def _render_index_page(results: list[dict[str, Any]]) -> str:
    scenario_groups = _scenario_results(results)
    counts = _status_counts(results)
    overview_header = _page_header(
        accent="overview",
        breadcrumb=_breadcrumb([("Overview", None)]),
        kicker="Overview",
        title="Sendspin conformance overview",
        description=(
            "Sendspin is a local-network protocol for discovering peers and exchanging synchronized "
            "audio plus companion data such as metadata, artwork, and controller messages between "
            "servers and clients. This report tests how different Sendspin implementations interoperate "
            "with one another, with each matrix showing which server and client pairings pass the "
            "current conformance scenarios."
        ),
        actions=(
            f"{_external_chip('Conformance source', GITHUB_REPO_URL)}"
            f"{_external_chip('Sendspin-audio.com', SENDSPIN_AUDIO_URL)}"
        ),
        meta=_summary_cards(counts=counts, total_label="all scenarios", total_value=len(results)),
    )
    sections: list[str] = []
    for scenario_id, scenario_results in scenario_groups:
        scenario_counts = _status_counts(scenario_results)
        status_pills = [
            f"<span class='status-pill {_status_classes('passed')}'>{scenario_counts.get('passed', 0)} passed</span>",
        ]
        if scenario_counts.get("unsupported", 0):
            status_pills.append(
                f"<span class='status-pill {_status_classes('unsupported')}'>{scenario_counts.get('unsupported', 0)} unsupported</span>"
            )
        if scenario_counts.get("failed", 0):
            status_pills.append(
                f"<span class='status-pill {_status_classes('failed')}'>{scenario_counts.get('failed', 0)} failed</span>"
            )
        sections.append(
            "<section class='surface p-5 sm:p-6'>"
            "<div class='flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between'>"
            "<div class='max-w-3xl'>"
            "<p class='eyebrow'>Test</p>"
            f"<h2 class='mt-2 text-2xl sm:text-3xl'>{html.escape(_scenario_name(scenario_id))}</h2>"
            f"<p class='mt-3 text-sm leading-6 subtle-copy sm:text-base'>{html.escape(_scenario_description(scenario_id))}</p>"
            "</div>"
            "<div class='flex flex-wrap items-center gap-2 xl:justify-end'>"
            f"{''.join(status_pills)}"
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
        "<main class='space-y-6'>"
        f"{overview_header}"
        f"{''.join(sections) if sections else '<section class=\"surface p-6 text-sm subtle-copy\">No scenario results were found.</section>'}"
        "</main>"
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
    counts = _status_counts(results)
    ordered_results = sorted(results, key=lambda result: _case_key(result))

    case_rows = []
    for result in ordered_results:
        server_impl = str(result["server_impl"])
        client_impl = str(result["client_impl"])
        case_rows.append(
            f"<a class='list-row' href='../{html.escape(_case_href(result), quote=True)}'>"
            "<div class='grid gap-3 lg:grid-cols-[minmax(0,1.2fr)_minmax(0,1.2fr)_auto] lg:items-start'>"
            "<div class='min-w-0'>"
            "<p class='eyebrow'>Server</p>"
            f"<p class='mt-1 text-base font-semibold'>{html.escape(_implementation_label(server_impl))}</p>"
            "</div>"
            "<div class='min-w-0'>"
            "<p class='eyebrow'>Client</p>"
            f"<p class='mt-1 text-base font-semibold'>{html.escape(_implementation_label(client_impl))}</p>"
            "</div>"
            "<div class='flex items-start justify-between gap-3 lg:justify-end'>"
            f"<span class='status-pill {_status_classes(_display_status(result))}'>{html.escape(_status_label(_display_status(result)))}</span>"
            "</div>"
            "</div>"
            f"<p class='mt-3 text-sm leading-6 subtle-copy'>{html.escape(str(result['reason']))}</p>"
            "</a>"
        )

    breadcrumb = _breadcrumb(
        [
            ("Overview", "../index.html"),
            (_scenario_name(scenario_id), None),
        ]
    )
    header_meta = _summary_cards(
        counts=counts,
        total_label="pairings in this test",
        total_value=len(ordered_results),
    )
    scenario_actions = _external_chip("View test source", _scenario_source_url(scenario_id))
    scenario_stat_rows = [
        (
            "<div class='keyval-row'>"
            "<span class='text-sm muted-copy'>Pairings</span>"
            f"<span class='text-sm font-semibold'>{len(ordered_results)}</span>"
            "</div>"
        ),
        (
            "<div class='keyval-row'>"
            "<span class='text-sm muted-copy'>Passed</span>"
            f"<span class='text-sm font-semibold'>{counts.get('passed', 0)}</span>"
            "</div>"
        ),
    ]
    if counts.get("unsupported", 0):
        scenario_stat_rows.append(
            "<div class='keyval-row'>"
            "<span class='text-sm muted-copy'>Unsupported</span>"
            f"<span class='text-sm font-semibold'>{counts.get('unsupported', 0)}</span>"
            "</div>"
        )
    if counts.get("failed", 0):
        scenario_stat_rows.append(
            "<div class='keyval-row'>"
            "<span class='text-sm muted-copy'>Failed</span>"
            f"<span class='text-sm font-semibold'>{counts.get('failed', 0)}</span>"
            "</div>"
        )
    if counts.get("skipped", 0):
        scenario_stat_rows.append(
            "<div class='keyval-row'>"
            "<span class='text-sm muted-copy'>Skipped</span>"
            f"<span class='text-sm font-semibold'>{counts.get('skipped', 0)}</span>"
            "</div>"
        )
    body = (
        "<div class='app-shell'>"
        "<div class='mx-auto max-w-[1360px] px-4 py-4 sm:px-6 lg:px-8 lg:py-6'>"
        "<div class='grid gap-6 xl:grid-cols-[280px_minmax(0,1fr)]'>"
        "<aside class='sidebar-rail sidebar-rail-xl'>"
        "<section class='surface p-5'>"
        "<p class='eyebrow'>Browse</p>"
        "<div class='mt-3 space-y-2'>"
        "<a class='nav-item' href='../index.html'>"
        "<p class='text-sm font-semibold'>Back to overview</p>"
        "<p class='nav-copy mt-1 text-sm subtle-copy'>Return to the full matrix list.</p>"
        "</a>"
        "</div>"
        "</section>"
        f"{_sidebar_resources(scenario_id=scenario_id)}"
        "<section class='surface p-5'>"
        "<p class='eyebrow'>This test</p>"
        f"<h2 class='mt-2 text-xl'>{html.escape(_scenario_name(scenario_id))}</h2>"
        f"<p class='mt-3 text-sm leading-6 subtle-copy'>{html.escape(_scenario_intro(scenario_id))}</p>"
        "<div class='keyval mt-4'>"
        f"{''.join(scenario_stat_rows)}"
        "</div>"
        "</section>"
        f"{_nav_scenarios(all_scenarios, current_scenario_id=scenario_id, href_prefix='../')}"
        "</aside>"
        "<main class='space-y-6'>"
        f"{_page_header(accent='scenario', breadcrumb=breadcrumb, kicker='Test', title=_scenario_name(scenario_id), description=_scenario_description(scenario_id), actions=scenario_actions, meta=header_meta)}"
        "<section class='surface overflow-hidden'>"
        "<div class='border-b px-5 py-5 sm:px-6' style='border-color: rgb(var(--retro-line) / 0.38)'>"
        "<p class='eyebrow'>Runs</p>"
        "<h2 class='mt-2 text-2xl'>Server and client pairings</h2>"
        "<p class='mt-2 max-w-3xl text-sm leading-6 subtle-copy'>"
        "Each row is one concrete run for this test. Open a case to inspect the full hello payloads, summaries, and logs."
        "</p>"
        "</div>"
        "<div class='list-shell rounded-none border-0 shadow-none'>"
        f"{''.join(case_rows) if case_rows else '<div class=\"px-5 py-5 text-sm subtle-copy\">No cases were written for this scenario.</div>'}"
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
    data_dir: Path,
) -> str:
    scenario_id = str(result["scenario_id"])
    case_name = _case_slug(result)
    payload = _case_payload(result, data_dir=data_dir)
    case_dir = payload["case_dir"]
    server_impl = str(result["server_impl"])
    client_impl = str(result["client_impl"])
    status = _display_status(result)
    server_label = _implementation_label(server_impl)
    client_label = _implementation_label(client_impl)

    summary_tab = f"{case_name}--summary"
    server_tab = f"{case_name}--server"
    client_tab = f"{case_name}--client"

    breadcrumb = _breadcrumb(
        [
            ("Overview", "../index.html"),
            (_scenario_name(scenario_id), "../" + _scenario_href(scenario_id)),
            ("Case", None),
        ]
    )
    header_meta = (
        "<div class='grid gap-3 lg:grid-cols-3'>"
        "<div class='detail-card'>"
        "<p class='eyebrow'>Server</p>"
        f"{_implementation_identity(server_impl, primary_class='mt-2 text-lg font-semibold', secondary_class='mt-1 text-sm muted-copy')}"
        "</div>"
        "<div class='detail-card'>"
        "<p class='eyebrow'>Client</p>"
        f"{_implementation_identity(client_impl, primary_class='mt-2 text-lg font-semibold', secondary_class='mt-1 text-sm muted-copy')}"
        "</div>"
        "<div class='detail-card'>"
        "<p class='eyebrow'>Status</p>"
        f"<p class='mt-2'><span class='status-pill {_status_classes(status)}'>{html.escape(_status_label(status))}</span></p>"
        f"<p class='mt-3 text-sm muted-copy'>{html.escape(str(result['reason']))}</p>"
        "</div>"
        "</div>"
    )
    body = (
        "<div class='app-shell'>"
        "<div class='mx-auto max-w-[1320px] px-4 py-4 sm:px-6 lg:px-8 lg:py-6'>"
        "<div class='grid gap-6 xl:grid-cols-[300px_minmax(0,1fr)]'>"
        "<aside class='sidebar-rail sidebar-rail-xl'>"
        "<section class='surface p-5'>"
        "<p class='eyebrow'>Browse</p>"
        "<div class='mt-3 space-y-2'>"
        f"<a class='nav-item' href='../{html.escape(_scenario_href(scenario_id), quote=True)}'>"
        "<p class='text-sm font-semibold'>Back to test</p>"
        "<p class='nav-copy mt-1 text-sm subtle-copy'>Return to the pairing list for this test.</p>"
        "</a>"
        "<a class='nav-item' href='../index.html'>"
        "<p class='text-sm font-semibold'>Back to overview</p>"
        "<p class='nav-copy mt-1 text-sm subtle-copy'>Return to the matrix-first overview.</p>"
        "</a>"
        "</div>"
        "</section>"
        "<section class='surface p-5'>"
        "<p class='eyebrow'>Run facts</p>"
        "<div class='keyval mt-4'>"
        "<div class='keyval-row'>"
        "<span class='text-sm muted-copy'>Case id</span>"
        f"<span class='text-sm font-semibold'>{html.escape(case_name)}</span>"
        "</div>"
        "<div class='keyval-row'>"
        "<span class='text-sm muted-copy'>Server exit</span>"
        f"<span class='text-sm font-semibold'>{html.escape(str(result.get('server_exit_code')))}</span>"
        "</div>"
        "<div class='keyval-row'>"
        "<span class='text-sm muted-copy'>Client exit</span>"
        f"<span class='text-sm font-semibold'>{html.escape(str(result.get('client_exit_code')))}</span>"
        "</div>"
        "<div class='keyval-row'>"
        "<span class='text-sm muted-copy'>Test</span>"
        f"<span class='text-sm font-semibold'>{html.escape(_scenario_name(scenario_id))}</span>"
        "</div>"
        "</div>"
        "</section>"
        "<section class='surface p-5'>"
        "<p class='eyebrow'>Artifacts</p>"
        f"<div class='mt-4'>{_artifact_links(case_dir, href_root='../data/' + case_name)}</div>"
        "</section>"
        f"{_sidebar_resources(scenario_id=scenario_id)}"
        "</aside>"
        "<main class='space-y-6'>"
        f"{_page_header(accent='case', breadcrumb=breadcrumb, kicker='Case', title=f'{server_label} -> {client_label}', description=_scenario_description(scenario_id), meta=header_meta)}"
        "<section class='surface p-5 sm:p-6' data-tabset>"
        "<div class='flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between'>"
        "<div>"
        "<p class='eyebrow'>Inspection</p>"
        "<h2 class='mt-2 text-2xl'>Summaries and logs</h2>"
        "<p class='mt-2 text-sm leading-6 subtle-copy'>"
        "Read the matrix result first, then inspect the server and client summaries and logs in separate tabs."
        "</p>"
        "</div>"
        "<div class='flex flex-wrap gap-2'>"
        f"<button type='button' class='tab-button tab-idle' data-tab-button='{html.escape(summary_tab, quote=True)}' data-default-tab='true' aria-selected='false'>Summary</button>"
        f"<button type='button' class='tab-button tab-idle' data-tab-button='{html.escape(server_tab, quote=True)}' aria-selected='false'>Server: {html.escape(server_label)}</button>"
        f"<button type='button' class='tab-button tab-idle' data-tab-button='{html.escape(client_tab, quote=True)}' aria-selected='false'>Client: {html.escape(client_label)}</button>"
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
                    data_dir=data_dir,
                ),
                encoding="utf-8",
            )

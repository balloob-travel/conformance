"""Static HTML report generation."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from .implementations import implementation_names
from .io import read_json, write_json


def build_site(results_dir: Path, site_dir: Path) -> None:
    """Generate a small static report site."""
    index_payload = read_json(results_dir / "index.json")
    results: list[dict[str, Any]] = list(index_payload["results"])
    site_dir.mkdir(parents=True, exist_ok=True)
    write_json(site_dir / "results.json", index_payload)

    counts = Counter(result["status"] for result in results)
    impls = implementation_names()
    rows: list[str] = []
    for server_impl in impls:
        cells = [f"<th>{server_impl}</th>"]
        for client_impl in impls:
            matching = [
                result
                for result in results
                if result["server_impl"] == server_impl and result["client_impl"] == client_impl
            ]
            if not matching:
                cells.append("<td class='empty'>-</td>")
                continue
            result = matching[0]
            css = result["status"]
            cells.append(
                "<td class='{css}'><a href='#{anchor}'>{status}</a></td>".format(
                    css=css,
                    anchor=f"{result['scenario_id']}__{server_impl}__to__{client_impl}",
                    status=result["status"],
                )
            )
        rows.append(f"<tr>{''.join(cells)}</tr>")

    detail_rows = []
    for result in results:
        anchor = f"{result['scenario_id']}__{result['server_impl']}__to__{result['client_impl']}"
        detail_rows.append(
            """
<details id="{anchor}" class="detail {status}">
  <summary>{scenario} :: {server} -> {client} :: {status}</summary>
  <p>{reason}</p>
  <p><code>{case_dir}</code></p>
</details>
""".strip().format(
                anchor=anchor,
                scenario=result["scenario_id"],
                server=result["server_impl"],
                client=result["client_impl"],
                status=result["status"],
                reason=result["reason"],
                case_dir=result["case_dir"],
            )
        )

    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Sendspin Conformance</title>
  <style>
    :root {{
      --bg: #f7f1e6;
      --ink: #1d2b27;
      --muted: #5f6b67;
      --pass: #2d7d46;
      --fail: #b43f2f;
      --skip: #8a6a19;
      --card: #fffaf0;
      --line: #d7cfbf;
    }}
    body {{
      margin: 0;
      font-family: Georgia, "Iowan Old Style", serif;
      background:
        radial-gradient(circle at top left, rgba(216, 192, 132, 0.28), transparent 30%),
        linear-gradient(180deg, #faf5ec 0%, var(--bg) 100%);
      color: var(--ink);
    }}
    main {{
      max-width: 1100px;
      margin: 0 auto;
      padding: 40px 20px 80px;
    }}
    h1 {{
      margin: 0 0 8px;
      font-size: 2.5rem;
    }}
    p.lead {{
      margin: 0 0 24px;
      color: var(--muted);
      max-width: 70ch;
    }}
    .overview {{
      display: flex;
      gap: 16px;
      margin: 24px 0 32px;
      flex-wrap: wrap;
    }}
    .pill {{
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 10px 14px;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      background: var(--card);
      border: 1px solid var(--line);
      margin-bottom: 32px;
    }}
    th, td {{
      padding: 10px 12px;
      border: 1px solid var(--line);
      text-align: center;
    }}
    th:first-child {{
      text-align: left;
    }}
    td a {{
      color: inherit;
      text-decoration: none;
    }}
    td.passed {{ background: rgba(45, 125, 70, 0.15); color: var(--pass); }}
    td.failed {{ background: rgba(180, 63, 47, 0.15); color: var(--fail); }}
    td.skipped {{ background: rgba(138, 106, 25, 0.14); color: var(--skip); }}
    td.empty {{ color: var(--muted); }}
    details {{
      background: var(--card);
      border: 1px solid var(--line);
      border-left-width: 8px;
      border-radius: 10px;
      padding: 12px 16px;
      margin-bottom: 12px;
    }}
    details.passed {{ border-left-color: var(--pass); }}
    details.failed {{ border-left-color: var(--fail); }}
    details.skipped {{ border-left-color: var(--skip); }}
    code {{ font-family: "SFMono-Regular", "SF Mono", monospace; }}
  </style>
</head>
<body>
  <main>
    <h1>Sendspin Conformance</h1>
    <p class="lead">Current report for the first scenario: server-initiated discovery, handshake, FLAC transport, and canonical PCM hash comparison.</p>
    <section class="overview">
      <div class="pill">Passed: {counts.get("passed", 0)}</div>
      <div class="pill">Failed: {counts.get("failed", 0)}</div>
      <div class="pill">Skipped: {counts.get("skipped", 0)}</div>
    </section>
    <table>
      <thead>
        <tr>
          <th>From \\ To</th>
          {''.join(f'<th>{impl}</th>' for impl in impls)}
        </tr>
      </thead>
      <tbody>
        {''.join(rows)}
      </tbody>
    </table>
    <section>
      {''.join(detail_rows)}
    </section>
  </main>
</body>
</html>
"""
    (site_dir / "index.html").write_text(html, encoding="utf-8")

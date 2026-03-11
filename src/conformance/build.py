"""Adapter build helpers."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from .implementations import resolve_repo_path
from .io import write_json
from .paths import repo_root


BuildResult = dict[str, Any]


def _run_command(cmd: list[str], *, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=str(repo_root()),
        env=env,
        capture_output=True,
        text=True,
    )


def _trim_output(stdout: str, stderr: str, *, limit: int = 4000) -> str:
    combined = (stdout + "\n" + stderr).strip()
    if len(combined) <= limit:
        return combined
    return combined[-limit:]


def _python_build_result() -> BuildResult:
    completed = _run_command([sys.executable, "-m", "compileall", "src", "scripts"])
    return {
        "adapter": "python-adapters",
        "status": "built" if completed.returncode == 0 else "failed",
        "detail": _trim_output(completed.stdout, completed.stderr),
    }


def _dotnet_build_result() -> BuildResult:
    dotnet = shutil.which("dotnet")
    dotnet_repo = resolve_repo_path("sendspin-dotnet")
    dotnet_project = (
        repo_root()
        / "adapters"
        / "sendspin-dotnet"
        / "client"
        / "Conformance.SendspinDotnet.Client.csproj"
    )
    if dotnet is None:
        return {
            "adapter": "sendspin-dotnet-client",
            "status": "skipped",
            "detail": "dotnet executable is not available",
        }
    if dotnet_repo is None:
        return {
            "adapter": "sendspin-dotnet-client",
            "status": "skipped",
            "detail": "sendspin-dotnet repository checkout was not found",
        }

    env = dict(os.environ)
    env["SendspinDotnetRepo"] = str(dotnet_repo)
    completed = _run_command([dotnet, "build", str(dotnet_project)], env=env)
    return {
        "adapter": "sendspin-dotnet-client",
        "status": "built" if completed.returncode == 0 else "failed",
        "detail": _trim_output(completed.stdout, completed.stderr),
    }


def build_adapters(report_path: Path | None = None) -> list[BuildResult]:
    """Build adapter sources when the required toolchains are available."""
    results = [
        _python_build_result(),
        _dotnet_build_result(),
    ]
    if report_path is not None:
        write_json(report_path, {"results": results})
    return results


def build_failed(results: list[BuildResult]) -> bool:
    """Return True when any adapter build failed."""
    return any(result["status"] == "failed" for result in results)

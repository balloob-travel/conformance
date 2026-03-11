"""Adapter build helpers."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from .implementations import ensure_repo_checkout, resolve_repo_path
from .io import write_json
from .paths import repo_root
from .toolchains import find_cargo, find_dotnet, find_swift


BuildResult = dict[str, Any]


def _run_command(
    cmd: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=str(cwd or repo_root()),
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
    dotnet = find_dotnet()
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


def _node_build_result() -> BuildResult:
    node = shutil.which("node")
    if node is None:
        return {
            "adapter": "sendspin-js-adapters",
            "status": "skipped",
            "detail": "node executable is not available",
        }
    sendspin_js_repo = resolve_repo_path("sendspin-js")
    if sendspin_js_repo is None:
        return {
            "adapter": "sendspin-js-adapters",
            "status": "skipped",
            "detail": "sendspin-js repository checkout was not found",
        }

    npm = shutil.which("npm")
    if npm is None:
        return {
            "adapter": "sendspin-js-adapters",
            "status": "skipped",
            "detail": "npm executable is not available",
        }

    install = _run_command([npm, "install"], cwd=sendspin_js_repo)
    if install.returncode != 0:
        return {
            "adapter": "sendspin-js-adapters",
            "status": "failed",
            "detail": _trim_output(install.stdout, install.stderr),
        }

    build = _run_command([npm, "run", "build"], cwd=sendspin_js_repo)
    if build.returncode != 0:
        return {
            "adapter": "sendspin-js-adapters",
            "status": "failed",
            "detail": _trim_output(build.stdout, build.stderr),
        }

    scripts = [
        repo_root() / "adapters" / "sendspin-js" / "client.mjs",
        repo_root() / "adapters" / "sendspin-js" / "server.mjs",
    ]
    completed = _run_command([node, "--check", *[str(script) for script in scripts]])
    return {
        "adapter": "sendspin-js-adapters",
        "status": "built" if completed.returncode == 0 else "failed",
        "detail": _trim_output(completed.stdout, completed.stderr),
    }


def _cargo_build_result() -> BuildResult:
    cargo = find_cargo()
    if cargo is None:
        return {
            "adapter": "sendspin-rs-client",
            "status": "skipped",
            "detail": "cargo executable is not available",
        }

    try:
        ensure_repo_checkout("sendspin-rs")
    except FileNotFoundError as err:
        return {
            "adapter": "sendspin-rs-client",
            "status": "skipped",
            "detail": str(err),
        }

    manifest = repo_root() / "adapters" / "sendspin-rs" / "client" / "Cargo.toml"
    completed = _run_command([cargo, "build", "--manifest-path", str(manifest)])
    return {
        "adapter": "sendspin-rs-client",
        "status": "built" if completed.returncode == 0 else "failed",
        "detail": _trim_output(completed.stdout, completed.stderr),
    }


def _swift_build_result() -> BuildResult:
    swift = find_swift()
    if swift is None:
        return {
            "adapter": "SendspinKit-client",
            "status": "skipped",
            "detail": "swift executable is not available",
        }
    if sys.platform != "darwin":
        return {
            "adapter": "SendspinKit-client",
            "status": "skipped",
            "detail": "SendspinKit client build currently requires macOS",
        }

    try:
        ensure_repo_checkout("SendspinKit")
    except FileNotFoundError as err:
        return {
            "adapter": "SendspinKit-client",
            "status": "skipped",
            "detail": str(err),
        }

    package_dir = repo_root() / "adapters" / "SendspinKit" / "client"
    completed = _run_command([swift, "build", "--package-path", str(package_dir)])
    return {
        "adapter": "SendspinKit-client",
        "status": "built" if completed.returncode == 0 else "failed",
        "detail": _trim_output(completed.stdout, completed.stderr),
    }


def build_adapters(report_path: Path | None = None) -> list[BuildResult]:
    """Build adapter sources when the required toolchains are available."""
    results = [
        _python_build_result(),
        _dotnet_build_result(),
        _cargo_build_result(),
        _swift_build_result(),
        _node_build_result(),
    ]
    if report_path is not None:
        write_json(report_path, {"results": results})
    return results


def build_failed(results: list[BuildResult]) -> bool:
    """Return True when any adapter build failed."""
    return any(result["status"] == "failed" for result in results)

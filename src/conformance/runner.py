"""Matrix runner for Sendspin conformance cases."""

from __future__ import annotations

import asyncio
import os
import shutil
import sys
from pathlib import Path
from typing import Any

from .flac import decode_fixture
from .fixtures import fixture_path
from .implementations import IMPLEMENTATIONS, implementation_names, resolve_repo_path
from .io import read_json, write_json
from .models import CaseResult, ScenarioSpec
from .paths import repo_root
from .process import close_process_log, collect_process, wait_for_file
from .scenarios import SCENARIOS, supports_pair
from .toolchains import find_dotnet


def _parse_filter(raw: str | None) -> list[str]:
    if not raw:
        return implementation_names()
    names = implementation_names()
    selected = [part.strip() for part in raw.split(",") if part.strip()]
    unknown = [name for name in selected if name not in names]
    if unknown:
        raise ValueError(
            "Unknown implementation filter(s): " + ", ".join(sorted(unknown))
        )
    return selected


def _python_adapter_command(module: str, **kwargs: str) -> list[str]:
    cmd = [sys.executable, "-m", module]
    for key, value in kwargs.items():
        cmd.extend([f"--{key.replace('_', '-')}", value])
    return cmd


def _dotnet_adapter_command(project: str, **kwargs: str) -> list[str] | None:
    dotnet = find_dotnet()
    if dotnet is None:
        return None
    cmd = [dotnet, "run", "--project", project, "--"]
    for key, value in kwargs.items():
        cmd.extend([f"--{key.replace('_', '-')}", value])
    return cmd


def _node_adapter_command(script: str, **kwargs: str) -> list[str] | None:
    node = shutil.which("node")
    if node is None:
        return None
    cmd = [node, script]
    for key, value in kwargs.items():
        cmd.extend([f"--{key.replace('_', '-')}", value])
    return cmd


def _build_role_command(
    implementation: str,
    role: str,
    *,
    summary: Path,
    ready: Path,
    registry: Path,
    extra_args: dict[str, str],
) -> list[str] | None:
    spec = IMPLEMENTATIONS[implementation]
    role_spec = spec.server if role == "server" else spec.client
    if role_spec.adapter_kind == "python":
        assert role_spec.entrypoint is not None
        return _python_adapter_command(
            role_spec.entrypoint,
            summary=str(summary),
            ready=str(ready),
            registry=str(registry),
            **extra_args,
        )
    if role_spec.adapter_kind == "dotnet":
        assert role_spec.entrypoint is not None
        return _dotnet_adapter_command(
            str(repo_root() / role_spec.entrypoint),
            summary=str(summary),
            ready=str(ready),
            registry=str(registry),
            **extra_args,
        )
    if role_spec.adapter_kind == "node":
        assert role_spec.entrypoint is not None
        return _node_adapter_command(
            str(repo_root() / role_spec.entrypoint),
            summary=str(summary),
            ready=str(ready),
            registry=str(registry),
            **extra_args,
        )
    if role_spec.adapter_kind == "placeholder":
        assert role_spec.entrypoint is not None
        assert role_spec.reason is not None
        return _python_adapter_command(
            role_spec.entrypoint,
            summary=str(summary),
            ready=str(ready),
            registry=str(registry),
            implementation=implementation,
            role=role,
            failure_reason=role_spec.reason,
            **extra_args,
        )
    return None


def _scenario_role_reason(
    scenario: ScenarioSpec,
    *,
    implementation: str,
    role: str,
) -> str | None:
    role_spec = IMPLEMENTATIONS[implementation].server if role == "server" else IMPLEMENTATIONS[implementation].client
    capability_name = (
        "supports_server_initiated"
        if scenario.initiator_role == "server"
        else "supports_client_initiated"
    )
    if getattr(role_spec, capability_name):
        if scenario.preferred_codec != "flac" or role_spec.supports_flac:
            return None
    if scenario.initiator_role == "server":
        action = "server-initiated discovery and connection"
    else:
        action = "client-initiated connection and server advertising"
    role_label = "server" if role == "server" else "client"
    if not getattr(role_spec, capability_name):
        return (
            f"{implementation} {role_label} adapter does not support the {action} "
            f"required by {scenario.id}."
        )
    if scenario.preferred_codec == "flac" and not role_spec.supports_flac:
        return (
            f"{implementation} {role_label} adapter does not support FLAC transport "
            f"required by {scenario.id}."
        )
    return None


def _scenario_extra_args(
    scenario: ScenarioSpec,
    *,
    server_impl: str,
    client_impl: str,
    timeout_s: float,
) -> tuple[dict[str, str], dict[str, str]]:
    server_name = f"{server_impl} server"
    client_name = f"{client_impl}-client"
    common = {
        "scenario_id": scenario.id,
        "preferred_codec": scenario.preferred_codec,
        "timeout_seconds": str(timeout_s),
    }
    server_args = {
        **common,
        "client_name": client_name,
        "fixture": str(fixture_path()),
        "server_id": f"{server_impl}-server",
        "server_name": server_name,
    }
    client_args = {
        **common,
        "client_name": client_name,
        "client_id": f"{client_impl}-client-id",
        "server_id": f"{server_impl}-server",
        "server_name": server_name,
    }
    return server_args, client_args


def _compare_summaries(server_summary: dict[str, Any], client_summary: dict[str, Any]) -> tuple[bool, str]:
    if server_summary.get("status") != "ok":
        return False, f"Server summary status is {server_summary.get('status')!r}"
    if client_summary.get("status") != "ok":
        return False, f"Client summary status is {client_summary.get('status')!r}"

    source_hash = server_summary["audio"]["source_pcm_sha256"]
    received_hash = client_summary["audio"]["received_pcm_sha256"]
    if not client_summary["audio"]["audio_chunk_count"]:
        return False, "Client summary shows zero audio chunks"
    if source_hash == received_hash:
        return True, "PCM hashes match exactly"

    audio = server_summary["audio"]
    received_sample_count = int(client_summary["audio"]["received_sample_count"])
    fixture = decode_fixture(
        Path(audio["fixture"]),
        max_duration_seconds=float(audio.get("clip_seconds") or 5.0),
    )
    bytes_per_sample = audio["bit_depth"] // 8
    prefix_pcm = fixture.pcm_bytes[: received_sample_count * bytes_per_sample]
    from .pcm import FloatPcmHasher

    prefix_hasher = FloatPcmHasher()
    prefix_hasher.update_from_pcm_bytes(prefix_pcm, bit_depth=audio["bit_depth"])
    prefix_hash = prefix_hasher.hexdigest()
    if prefix_hash == received_hash:
        missing_samples = fixture.frame_count * audio["channels"] - received_sample_count
        return True, f"PCM prefix matches; trailing samples omitted={missing_samples}"

    return (
        False,
        "PCM hash mismatch: "
        f"server={source_hash} client={received_hash}",
    )


async def _run_failfast_role(
    *,
    case_dir: Path,
    scenario_id: str,
    server_impl: str,
    client_impl: str,
    failing_impl: str,
    failing_role: str,
    timeout_s: float,
    extra_args: dict[str, str],
    failure_reason: str | None = None,
) -> CaseResult:
    summary_path = case_dir / f"{failing_role}-summary.json"
    ready_path = case_dir / f"{failing_role}-ready.json"
    log_path = case_dir / f"{failing_role}.log"
    registry_path = case_dir / "registry.json"

    if failure_reason is not None:
        cmd = _python_adapter_command(
            "conformance.adapters.placeholder",
            summary=str(summary_path),
            ready=str(ready_path),
            registry=str(registry_path),
            implementation=failing_impl,
            role=failing_role,
            failure_reason=failure_reason,
            **extra_args,
        )
    else:
        cmd = _build_role_command(
            failing_impl,
            failing_role,
            summary=summary_path,
            ready=ready_path,
            registry=registry_path,
            extra_args=extra_args,
        )
    if cmd is None:
        return CaseResult(
            scenario_id=scenario_id,
            server_impl=server_impl,
            client_impl=client_impl,
            status="failed",
            reason=f"Required runtime toolchain is not available for {failing_impl} {failing_role} adapter",
            case_dir=str(case_dir),
        )

    env = dict(os.environ)
    env["PYTHONUNBUFFERED"] = "1"
    dotnet_repo = resolve_repo_path("sendspin-dotnet")
    if dotnet_repo is not None:
        env["SendspinDotnetRepo"] = str(dotnet_repo)
    process = await collect_process(cmd, cwd=repo_root(), env=env, log_path=log_path)
    try:
        await wait_for_file(ready_path, timeout_s=10)
        await asyncio.wait_for(process.wait(), timeout=5)
    except Exception as err:
        if process.returncode is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
        if process.returncode is None:
            await process.wait()
        return CaseResult(
            scenario_id=scenario_id,
            server_impl=server_impl,
            client_impl=client_impl,
            status="failed",
            reason=str(err),
            case_dir=str(case_dir),
            server_exit_code=process.returncode if failing_role == "server" else None,
            client_exit_code=process.returncode if failing_role == "client" else None,
        )
    finally:
        await close_process_log(process)

    reason = f"{failing_impl} {failing_role} adapter failed without writing a summary"
    if summary_path.exists():
        payload = read_json(summary_path)
        reason = str(payload.get("reason") or reason)

    return CaseResult(
        scenario_id=scenario_id,
        server_impl=server_impl,
        client_impl=client_impl,
        status="failed",
        reason=reason,
        case_dir=str(case_dir),
        server_exit_code=process.returncode if failing_role == "server" else None,
        client_exit_code=process.returncode if failing_role == "client" else None,
    )


async def run_case(
    *,
    results_dir: Path,
    scenario_id: str,
    server_impl: str,
    client_impl: str,
    timeout_s: float,
) -> CaseResult:
    scenario = SCENARIOS[scenario_id]
    case_name = f"{scenario_id}__{server_impl}__to__{client_impl}"
    case_dir = results_dir / case_name
    if case_dir.exists():
        shutil.rmtree(case_dir)
    case_dir.mkdir(parents=True, exist_ok=True)

    skip_reason = supports_pair(scenario_id, server_impl, client_impl)
    if skip_reason is not None:
        result = CaseResult(
            scenario_id=scenario_id,
            server_impl=server_impl,
            client_impl=client_impl,
            status="skipped",
            reason=skip_reason,
            case_dir=str(case_dir),
        )
        write_json(case_dir / "result.json", result.__dict__)
        return result

    server_spec = IMPLEMENTATIONS[server_impl].server
    client_spec = IMPLEMENTATIONS[client_impl].client
    server_args, client_args = _scenario_extra_args(
        scenario,
        server_impl=server_impl,
        client_impl=client_impl,
        timeout_s=timeout_s,
    )
    if not server_spec.supported:
        result = await _run_failfast_role(
            case_dir=case_dir,
            scenario_id=scenario_id,
            server_impl=server_impl,
            client_impl=client_impl,
            failing_impl=server_impl,
            failing_role="server",
            timeout_s=timeout_s,
            extra_args=server_args,
        )
        write_json(case_dir / "result.json", result.__dict__)
        return result
    if not client_spec.supported:
        result = await _run_failfast_role(
            case_dir=case_dir,
            scenario_id=scenario_id,
            server_impl=server_impl,
            client_impl=client_impl,
            failing_impl=client_impl,
            failing_role="client",
            timeout_s=timeout_s,
            extra_args=client_args,
        )
        write_json(case_dir / "result.json", result.__dict__)
        return result
    server_capability_reason = _scenario_role_reason(
        scenario,
        implementation=server_impl,
        role="server",
    )
    if server_capability_reason is not None:
        result = await _run_failfast_role(
            case_dir=case_dir,
            scenario_id=scenario_id,
            server_impl=server_impl,
            client_impl=client_impl,
            failing_impl=server_impl,
            failing_role="server",
            timeout_s=timeout_s,
            extra_args=server_args,
            failure_reason=server_capability_reason,
        )
        write_json(case_dir / "result.json", result.__dict__)
        return result
    client_capability_reason = _scenario_role_reason(
        scenario,
        implementation=client_impl,
        role="client",
    )
    if client_capability_reason is not None:
        result = await _run_failfast_role(
            case_dir=case_dir,
            scenario_id=scenario_id,
            server_impl=server_impl,
            client_impl=client_impl,
            failing_impl=client_impl,
            failing_role="client",
            timeout_s=timeout_s,
            extra_args=client_args,
            failure_reason=client_capability_reason,
        )
        write_json(case_dir / "result.json", result.__dict__)
        return result

    registry_path = case_dir / "registry.json"
    server_summary = case_dir / "server-summary.json"
    client_summary = case_dir / "client-summary.json"
    server_ready = case_dir / "server-ready.json"
    client_ready = case_dir / "client-ready.json"
    server_log = case_dir / "server.log"
    client_log = case_dir / "client.log"

    server_cmd = _build_role_command(
        server_impl,
        "server",
        summary=server_summary,
        ready=server_ready,
        registry=registry_path,
        extra_args=server_args,
    )
    client_cmd = _build_role_command(
        client_impl,
        "client",
        summary=client_summary,
        ready=client_ready,
        registry=registry_path,
        extra_args=client_args,
    )
    if server_cmd is None or client_cmd is None:
        result = CaseResult(
            scenario_id=scenario_id,
            server_impl=server_impl,
            client_impl=client_impl,
            status="failed",
            reason="Required runtime toolchain is not available for this adapter",
            case_dir=str(case_dir),
        )
        write_json(case_dir / "result.json", result.__dict__)
        return result

    env = dict(os.environ)
    env["PYTHONUNBUFFERED"] = "1"

    server_process = await collect_process(server_cmd, cwd=repo_root(), env=env, log_path=server_log)
    client_process: asyncio.subprocess.Process | None = None
    try:
        await wait_for_file(server_ready, timeout_s=10)
        client_process = await collect_process(client_cmd, cwd=repo_root(), env=env, log_path=client_log)
        await wait_for_file(client_ready, timeout_s=10)

        await asyncio.wait_for(server_process.wait(), timeout=timeout_s)
        await asyncio.wait_for(client_process.wait(), timeout=10)
    except Exception as err:
        if server_process.returncode is None:
            try:
                server_process.kill()
            except ProcessLookupError:
                pass
        if client_process is not None and client_process.returncode is None:
            try:
                client_process.kill()
            except ProcessLookupError:
                pass
        if server_process.returncode is None:
            await server_process.wait()
        if client_process is not None and client_process.returncode is None:
            await client_process.wait()
        result = CaseResult(
            scenario_id=scenario_id,
            server_impl=server_impl,
            client_impl=client_impl,
            status="failed",
            reason=str(err),
            case_dir=str(case_dir),
            server_exit_code=server_process.returncode,
            client_exit_code=None if client_process is None else client_process.returncode,
        )
        write_json(case_dir / "result.json", result.__dict__)
        return result
    finally:
        await close_process_log(server_process)
        if client_process is not None:
            await close_process_log(client_process)

    if not server_summary.exists() or not client_summary.exists():
        result = CaseResult(
            scenario_id=scenario_id,
            server_impl=server_impl,
            client_impl=client_impl,
            status="failed",
            reason="Missing summary output",
            case_dir=str(case_dir),
            server_exit_code=server_process.returncode,
            client_exit_code=None if client_process is None else client_process.returncode,
        )
        write_json(case_dir / "result.json", result.__dict__)
        return result

    server_payload = read_json(server_summary)
    client_payload = read_json(client_summary)
    matches, comparison_reason = _compare_summaries(server_payload, client_payload)
    if not matches:
        status = "failed"
        reason = comparison_reason
    elif server_process.returncode != 0 or client_process is None or client_process.returncode != 0:
        status = "failed"
        reason = "One or more adapters exited non-zero"
    else:
        status = "passed"
        reason = comparison_reason

    result = CaseResult(
        scenario_id=scenario_id,
        server_impl=server_impl,
        client_impl=client_impl,
        status=status,
        reason=reason,
        case_dir=str(case_dir),
        server_exit_code=server_process.returncode,
        client_exit_code=None if client_process is None else client_process.returncode,
    )
    write_json(case_dir / "result.json", result.__dict__)
    return result


async def run_matrix(
    *,
    results_dir: Path,
    from_filter: str | None,
    to_filter: str | None,
    timeout_s: float,
) -> list[dict[str, Any]]:
    """Run the current scenario matrix with optional filters."""
    data_dir = results_dir / "data"
    if data_dir.exists():
        shutil.rmtree(data_dir)
    if results_dir.exists():
        for child in results_dir.iterdir():
            if child.name == "data":
                continue
            if child.is_dir() and (child / "result.json").exists():
                shutil.rmtree(child)
        for filename in ("index.json", "results.json"):
            legacy_file = results_dir / filename
            if legacy_file.exists():
                legacy_file.unlink()
    data_dir.mkdir(parents=True, exist_ok=True)
    server_impls = _parse_filter(from_filter)
    client_impls = _parse_filter(to_filter)
    results: list[dict[str, Any]] = []
    for scenario_id in SCENARIOS:
        for server_impl in server_impls:
            for client_impl in client_impls:
                result = await run_case(
                    results_dir=data_dir,
                    scenario_id=scenario_id,
                    server_impl=server_impl,
                    client_impl=client_impl,
                    timeout_s=timeout_s,
                )
                results.append(result.__dict__)
    write_json(data_dir / "index.json", {"results": results})
    return results

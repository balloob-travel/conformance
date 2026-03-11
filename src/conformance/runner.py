"""Matrix runner for Sendspin conformance cases."""

from __future__ import annotations

import asyncio
import os
import shutil
from pathlib import Path
from typing import Any

from .flac import decode_fixture
from .fixtures import fixture_path
from .implementations import IMPLEMENTATIONS, implementation_names
from .io import read_json, write_json
from .models import CaseResult
from .process import close_process_log, collect_process, wait_for_file
from .scenarios import SERVER_INITIATED_FLAC, supports_pair


def _parse_filter(raw: str | None) -> list[str]:
    if not raw:
        return implementation_names()
    return [part.strip() for part in raw.split(",") if part.strip()]


def _python_adapter_command(module: str, **kwargs: str) -> list[str]:
    cmd = [shutil.which("python3") or "python3", "-m", module]
    for key, value in kwargs.items():
        cmd.extend([f"--{key.replace('_', '-')}", value])
    return cmd


def _dotnet_adapter_command(project: str, **kwargs: str) -> list[str] | None:
    dotnet = shutil.which("dotnet")
    if dotnet is None:
        return None
    cmd = [dotnet, "run", "--project", project, "--"]
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
            str(Path(__file__).resolve().parents[2] / role_spec.entrypoint),
            summary=str(summary),
            ready=str(ready),
            registry=str(registry),
            **extra_args,
        )
    return None


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


async def run_case(
    *,
    results_dir: Path,
    server_impl: str,
    client_impl: str,
    timeout_s: float,
) -> CaseResult:
    scenario_id = SERVER_INITIATED_FLAC.id
    case_name = f"{scenario_id}__{server_impl}__to__{client_impl}"
    case_dir = results_dir / case_name
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

    registry_path = case_dir / "registry.json"
    server_summary = case_dir / "server-summary.json"
    client_summary = case_dir / "client-summary.json"
    server_ready = case_dir / "server-ready.json"
    client_ready = case_dir / "client-ready.json"
    server_log = case_dir / "server.log"
    client_log = case_dir / "client.log"

    client_name = f"{client_impl}-client"
    client_id = f"{client_impl}-client-id"

    server_cmd = _build_role_command(
        server_impl,
        "server",
        summary=server_summary,
        ready=server_ready,
        registry=registry_path,
        extra_args={
            "client_name": client_name,
            "fixture": str(fixture_path()),
            "timeout_seconds": str(timeout_s),
            "server_id": f"{server_impl}-server",
            "server_name": f"{server_impl} server",
        },
    )
    client_cmd = _build_role_command(
        client_impl,
        "client",
        summary=client_summary,
        ready=client_ready,
        registry=registry_path,
        extra_args={
            "client_name": client_name,
            "client_id": client_id,
            "timeout_seconds": str(timeout_s),
        },
    )
    if server_cmd is None or client_cmd is None:
        result = CaseResult(
            scenario_id=scenario_id,
            server_impl=server_impl,
            client_impl=client_impl,
            status="skipped",
            reason="Required runtime toolchain is not available for this adapter",
            case_dir=str(case_dir),
        )
        write_json(case_dir / "result.json", result.__dict__)
        return result

    env = dict(os.environ)
    env["PYTHONUNBUFFERED"] = "1"

    server_process = await collect_process(server_cmd, cwd=Path.cwd(), env=env, log_path=server_log)
    client_process: asyncio.subprocess.Process | None = None
    try:
        await wait_for_file(server_ready, timeout_s=10)
        client_process = await collect_process(client_cmd, cwd=Path.cwd(), env=env, log_path=client_log)
        await wait_for_file(client_ready, timeout_s=10)

        await asyncio.wait_for(server_process.wait(), timeout=timeout_s)
        await asyncio.wait_for(client_process.wait(), timeout=5)
    except Exception as err:
        server_process.kill()
        if client_process is not None:
            client_process.kill()
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
    results_dir.mkdir(parents=True, exist_ok=True)
    server_impls = _parse_filter(from_filter)
    client_impls = _parse_filter(to_filter)
    results: list[dict[str, Any]] = []
    for server_impl in server_impls:
        for client_impl in client_impls:
            result = await run_case(
                results_dir=results_dir,
                server_impl=server_impl,
                client_impl=client_impl,
                timeout_s=timeout_s,
            )
            results.append(result.__dict__)
    write_json(results_dir / "index.json", {"results": results})
    return results

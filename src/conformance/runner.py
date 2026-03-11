"""Matrix runner for Sendspin conformance cases."""

from __future__ import annotations

import asyncio
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .flac import decode_fixture
from .fixtures import fixture_path
from .implementations import (
    IMPLEMENTATIONS,
    ensure_repo_checkout,
    implementation_names,
    resolve_repo_path,
)
from .io import read_json, write_json
from .models import CaseResult, RoleName, ScenarioSpec
from .paths import repo_root
from .process import close_process_log, collect_process, wait_for_file
from .scenarios import ordered_scenarios, require_scenario
from .toolchains import find_cargo, find_dotnet, find_swift


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


def _cargo_adapter_command(manifest: str, **kwargs: str) -> list[str] | None:
    cargo = find_cargo()
    if cargo is None:
        return None
    cmd = [cargo, "run", "--quiet", "--manifest-path", manifest, "--"]
    for key, value in kwargs.items():
        cmd.extend([f"--{key.replace('_', '-')}", value])
    return cmd


def _swift_adapter_command(package_path: str, product: str, **kwargs: str) -> list[str] | None:
    swift = find_swift()
    if swift is None:
        return None
    cmd = [swift, "run", "--package-path", package_path, product, "--"]
    for key, value in kwargs.items():
        cmd.extend([f"--{key.replace('_', '-')}", value])
    return cmd


def _build_role_command(
    implementation: str,
    role: RoleName,
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
    if role_spec.adapter_kind == "cargo":
        assert role_spec.entrypoint is not None
        ensure_repo_checkout("sendspin-rs")
        return _cargo_adapter_command(
            str(repo_root() / role_spec.entrypoint),
            summary=str(summary),
            ready=str(ready),
            registry=str(registry),
            **extra_args,
        )
    if role_spec.adapter_kind == "swift":
        assert role_spec.entrypoint is not None
        ensure_repo_checkout("SendspinKit")
        package_path, product = role_spec.entrypoint.rsplit(":", 1)
        return _swift_adapter_command(
            str(repo_root() / package_path),
            product,
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


@dataclass(frozen=True)
class CaseContext:
    """Shared metadata, artifacts, and CLI args for one matrix case."""

    results_dir: Path
    scenario: ScenarioSpec
    server_impl: str
    client_impl: str
    timeout_s: float

    @property
    def case_name(self) -> str:
        return f"{self.scenario.id}__{self.server_impl}__to__{self.client_impl}"

    @property
    def case_dir(self) -> Path:
        return self.results_dir / self.case_name

    @property
    def registry_path(self) -> Path:
        return self.case_dir / "registry.json"

    @property
    def server_name(self) -> str:
        return f"{self.server_impl} server"

    @property
    def server_id(self) -> str:
        return f"{self.server_impl}-server"

    @property
    def client_name(self) -> str:
        return f"{self.client_impl}-client"

    @property
    def client_id(self) -> str:
        return f"{self.client_impl}-client-id"

    def summary_path(self, role: RoleName) -> Path:
        return self.case_dir / f"{role}-summary.json"

    def ready_path(self, role: RoleName) -> Path:
        return self.case_dir / f"{role}-ready.json"

    def log_path(self, role: RoleName) -> Path:
        return self.case_dir / f"{role}.log"

    def implementation(self, role: RoleName) -> str:
        if role == "server":
            return self.server_impl
        return self.client_impl

    def role_spec(self, role: RoleName):
        implementation = IMPLEMENTATIONS[self.implementation(role)]
        if role == "server":
            return implementation.server
        return implementation.client

    def role_args(self, role: RoleName) -> dict[str, str]:
        common = {
            **self.scenario.cli_args(),
            "timeout_seconds": str(self.timeout_s),
        }
        if role == "server":
            return {
                **common,
                "client_name": self.client_name,
                "fixture": str(fixture_path()),
                "server_id": self.server_id,
                "server_name": self.server_name,
            }
        return {
            **common,
            "client_name": self.client_name,
            "client_id": self.client_id,
            "server_id": self.server_id,
            "server_name": self.server_name,
        }

    def capability_failure(self, role: RoleName) -> str | None:
        return self.role_spec(role).unsupported_reason(
            implementation=self.implementation(role),
            role=role,
            scenario=self.scenario,
        )


def _write_result(context: CaseContext, result: CaseResult) -> CaseResult:
    write_json(context.case_dir / "result.json", result.__dict__)
    return result


def _compare_audio_summaries(
    server_summary: dict[str, Any],
    client_summary: dict[str, Any],
) -> tuple[bool, str]:
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


def _compare_metadata_summaries(
    server_summary: dict[str, Any],
    client_summary: dict[str, Any],
) -> tuple[bool, str]:
    if server_summary.get("status") != "ok":
        return False, f"Server summary status is {server_summary.get('status')!r}"
    if client_summary.get("status") != "ok":
        return False, f"Client summary status is {client_summary.get('status')!r}"

    expected = server_summary.get("metadata", {}).get("expected")
    received = client_summary.get("metadata", {}).get("received")
    update_count = int(client_summary.get("metadata", {}).get("update_count") or 0)
    if update_count <= 0:
        return False, "Client summary shows zero metadata updates"
    if expected == received:
        return True, "Metadata snapshot matches"
    return False, f"Metadata mismatch: server={expected!r} client={received!r}"


def _compare_controller_summaries(
    server_summary: dict[str, Any],
    client_summary: dict[str, Any],
) -> tuple[bool, str]:
    if server_summary.get("status") != "ok":
        return False, f"Server summary status is {server_summary.get('status')!r}"
    if client_summary.get("status") != "ok":
        return False, f"Client summary status is {client_summary.get('status')!r}"

    expected = server_summary.get("controller", {}).get("expected_command")
    received = server_summary.get("controller", {}).get("received_command")
    sent = client_summary.get("controller", {}).get("sent_command")
    if received is None:
        return False, "Server summary shows no controller command received"
    if sent is None:
        return False, "Client summary shows no controller command sent"
    if expected == received == sent:
        command_name = expected.get("command") if isinstance(expected, dict) else None
        return True, f"Controller command matched ({command_name})"
    return (
        False,
        "Controller command mismatch: "
        f"expected={expected!r} server={received!r} client={sent!r}",
    )


def _compare_artwork_summaries(
    server_summary: dict[str, Any],
    client_summary: dict[str, Any],
) -> tuple[bool, str]:
    if server_summary.get("status") != "ok":
        return False, f"Server summary status is {server_summary.get('status')!r}"
    if client_summary.get("status") != "ok":
        return False, f"Client summary status is {client_summary.get('status')!r}"

    expected = server_summary.get("artwork", {})
    received = client_summary.get("artwork", {})
    if int(received.get("received_count") or 0) <= 0:
        return False, "Client summary shows zero artwork frames"
    if (
        expected.get("channel") == received.get("channel")
        and expected.get("encoded_sha256") == received.get("received_sha256")
    ):
        return True, "Artwork bytes match"
    return (
        False,
        "Artwork mismatch: "
        f"server={expected.get('encoded_sha256')} client={received.get('received_sha256')}",
    )


def _compare_summaries(
    scenario: ScenarioSpec,
    server_summary: dict[str, Any],
    client_summary: dict[str, Any],
) -> tuple[bool, str]:
    if scenario.verification_mode == "audio-pcm":
        return _compare_audio_summaries(server_summary, client_summary)
    if scenario.verification_mode == "metadata":
        return _compare_metadata_summaries(server_summary, client_summary)
    if scenario.verification_mode == "controller":
        return _compare_controller_summaries(server_summary, client_summary)
    if scenario.verification_mode == "artwork":
        return _compare_artwork_summaries(server_summary, client_summary)
    raise ValueError(f"Unsupported verification mode: {scenario.verification_mode}")


async def _run_failfast_role(
    *,
    context: CaseContext,
    failing_role: RoleName,
    failure_reason: str | None = None,
) -> CaseResult:
    failing_impl = context.implementation(failing_role)
    summary_path = context.summary_path(failing_role)
    ready_path = context.ready_path(failing_role)
    log_path = context.log_path(failing_role)
    registry_path = context.registry_path
    extra_args = context.role_args(failing_role)

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
            scenario_id=context.scenario.id,
            server_impl=context.server_impl,
            client_impl=context.client_impl,
            status="failed",
            reason=f"Required runtime toolchain is not available for {failing_impl} {failing_role} adapter",
            case_dir=str(context.case_dir),
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
            scenario_id=context.scenario.id,
            server_impl=context.server_impl,
            client_impl=context.client_impl,
            status="failed",
            reason=str(err),
            case_dir=str(context.case_dir),
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
        scenario_id=context.scenario.id,
        server_impl=context.server_impl,
        client_impl=context.client_impl,
        status="failed",
        reason=reason,
        case_dir=str(context.case_dir),
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
    scenario = require_scenario(scenario_id)
    context = CaseContext(
        results_dir=results_dir,
        scenario=scenario,
        server_impl=server_impl,
        client_impl=client_impl,
        timeout_s=timeout_s,
    )
    if context.case_dir.exists():
        shutil.rmtree(context.case_dir)
    context.case_dir.mkdir(parents=True, exist_ok=True)

    if not context.role_spec("server").supported:
        return _write_result(
            context,
            await _run_failfast_role(
                context=context,
                failing_role="server",
            ),
        )
    if not context.role_spec("client").supported:
        return _write_result(
            context,
            await _run_failfast_role(
                context=context,
                failing_role="client",
            ),
        )
    server_capability_reason = context.capability_failure("server")
    if server_capability_reason is not None:
        return _write_result(
            context,
            await _run_failfast_role(
                context=context,
                failing_role="server",
                failure_reason=server_capability_reason,
            ),
        )
    client_capability_reason = context.capability_failure("client")
    if client_capability_reason is not None:
        return _write_result(
            context,
            await _run_failfast_role(
                context=context,
                failing_role="client",
                failure_reason=client_capability_reason,
            ),
        )

    server_cmd = _build_role_command(
        context.server_impl,
        "server",
        summary=context.summary_path("server"),
        ready=context.ready_path("server"),
        registry=context.registry_path,
        extra_args=context.role_args("server"),
    )
    client_cmd = _build_role_command(
        context.client_impl,
        "client",
        summary=context.summary_path("client"),
        ready=context.ready_path("client"),
        registry=context.registry_path,
        extra_args=context.role_args("client"),
    )
    if server_cmd is None or client_cmd is None:
        return _write_result(
            context,
            CaseResult(
                scenario_id=scenario_id,
                server_impl=server_impl,
                client_impl=client_impl,
                status="failed",
                reason="Required runtime toolchain is not available for this adapter",
                case_dir=str(context.case_dir),
            ),
        )

    env = dict(os.environ)
    env["PYTHONUNBUFFERED"] = "1"

    server_process = await collect_process(
        server_cmd,
        cwd=repo_root(),
        env=env,
        log_path=context.log_path("server"),
    )
    client_process: asyncio.subprocess.Process | None = None
    try:
        await wait_for_file(context.ready_path("server"), timeout_s=10)
        client_process = await collect_process(
            client_cmd,
            cwd=repo_root(),
            env=env,
            log_path=context.log_path("client"),
        )
        await wait_for_file(context.ready_path("client"), timeout_s=10)

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
        return _write_result(
            context,
            CaseResult(
                scenario_id=scenario_id,
                server_impl=server_impl,
                client_impl=client_impl,
                status="failed",
                reason=str(err),
                case_dir=str(context.case_dir),
                server_exit_code=server_process.returncode,
                client_exit_code=None if client_process is None else client_process.returncode,
            ),
        )
    finally:
        await close_process_log(server_process)
        if client_process is not None:
            await close_process_log(client_process)

    if not context.summary_path("server").exists() or not context.summary_path("client").exists():
        return _write_result(
            context,
            CaseResult(
                scenario_id=scenario_id,
                server_impl=server_impl,
                client_impl=client_impl,
                status="failed",
                reason="Missing summary output",
                case_dir=str(context.case_dir),
                server_exit_code=server_process.returncode,
                client_exit_code=None if client_process is None else client_process.returncode,
            ),
        )

    server_payload = read_json(context.summary_path("server"))
    client_payload = read_json(context.summary_path("client"))
    matches, comparison_reason = _compare_summaries(
        scenario,
        server_payload,
        client_payload,
    )
    if not matches:
        status = "failed"
        reason = comparison_reason
    elif server_process.returncode != 0 or client_process is None or client_process.returncode != 0:
        status = "failed"
        reason = "One or more adapters exited non-zero"
    else:
        status = "passed"
        reason = comparison_reason

    return _write_result(
        context,
        CaseResult(
            scenario_id=scenario_id,
            server_impl=server_impl,
            client_impl=client_impl,
            status=status,
            reason=reason,
            case_dir=str(context.case_dir),
            server_exit_code=server_process.returncode,
            client_exit_code=None if client_process is None else client_process.returncode,
        ),
    )


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
    for scenario in ordered_scenarios():
        for server_impl in server_impls:
            for client_impl in client_impls:
                result = await run_case(
                    results_dir=data_dir,
                    scenario_id=scenario.id,
                    server_impl=server_impl,
                    client_impl=client_impl,
                    timeout_s=timeout_s,
                )
                results.append(result.__dict__)
    write_json(data_dir / "index.json", {"results": results})
    return results

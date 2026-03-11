"""Server-initiated aiosendspin server adapter."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path
from typing import Any

from conformance.flac import decode_fixture
from conformance.io import write_json
from conformance.registry import lookup_endpoint


def _add_repo_to_syspath(dirname: str) -> None:
    from conformance.implementations import resolve_required_repo_path

    repo = resolve_required_repo_path(dirname)
    if str(repo) not in sys.path:
        sys.path.insert(0, str(repo))


def build_parser() -> argparse.ArgumentParser:
    """Create the CLI parser."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--client-name", required=True)
    parser.add_argument("--summary", required=True)
    parser.add_argument("--ready", required=True)
    parser.add_argument("--registry", required=True)
    parser.add_argument("--fixture", required=True)
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    parser.add_argument("--port", type=int, default=8927)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--server-id", default="conformance-server")
    parser.add_argument("--server-name", default="Sendspin Conformance Server")
    parser.add_argument("--log-level", default="INFO")
    parser.add_argument("--enable-mdns", action="store_true")
    parser.add_argument("--clip-seconds", type=float, default=5.0)
    return parser


def _find_connected_client(server: Any, client_name: str) -> Any | None:
    for client in server.connected_clients:
        if client.name == client_name:
            return client
    return None


async def _wait_for_target_client(
    server: Any,
    *,
    client_name: str,
    registry_path: Path,
    timeout_s: float,
) -> tuple[Any, str]:
    from aiosendspin.models.types import ConnectionReason

    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s
    fallback_attempted = False
    while loop.time() < deadline:
        target = _find_connected_client(server, client_name)
        if target is not None:
            method = "registry_fallback" if fallback_attempted else "mdns"
            return target, method

        if not fallback_attempted:
            registry_url = lookup_endpoint(registry_path, client_name)
            if registry_url is not None:
                fallback_attempted = True
                await server.connect_to_client_and_wait(
                    registry_url,
                    connection_reason=ConnectionReason.PLAYBACK,
                )
                continue

        await asyncio.sleep(0.1)

    raise TimeoutError(f"Timed out waiting for client {client_name!r}")


def _iter_pcm_blocks(
    pcm_bytes: bytes,
    *,
    sample_rate: int,
    channels: int,
    bit_depth: int,
    block_ms: int = 100,
) -> list[tuple[bytes, int]]:
    bytes_per_frame = channels * (bit_depth // 8)
    frames_per_block = max(1, round(sample_rate * (block_ms / 1000.0)))
    bytes_per_block = frames_per_block * bytes_per_frame
    chunks: list[tuple[bytes, int]] = []
    for offset in range(0, len(pcm_bytes), bytes_per_block):
        chunk = pcm_bytes[offset : offset + bytes_per_block]
        frame_count = len(chunk) // bytes_per_frame
        duration_us = int(frame_count * 1_000_000 / sample_rate)
        chunks.append((chunk, duration_us))
    return chunks


async def _run(args: argparse.Namespace) -> int:
    _add_repo_to_syspath("aiosendspin")

    from aiosendspin.server.audio import AudioFormat
    from aiosendspin.server.server import SendspinServer

    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO))

    summary_path = Path(args.summary)
    ready_path = Path(args.ready)
    registry_path = Path(args.registry)
    fixture = decode_fixture(Path(args.fixture), max_duration_seconds=args.clip_seconds)

    loop = asyncio.get_running_loop()
    server = SendspinServer(loop, server_id=args.server_id, server_name=args.server_name)

    try:
        await server.start_server(
            port=args.port,
            host=args.host,
            advertise_addresses=["127.0.0.1"] if args.enable_mdns else [],
            discover_clients=args.enable_mdns,
        )
        write_json(
            ready_path,
            {
                "status": "ready",
                "server_id": args.server_id,
                "server_name": args.server_name,
            },
        )
        client, discovery_method = await _wait_for_target_client(
            server,
            client_name=args.client_name,
            registry_path=registry_path,
            timeout_s=args.timeout_seconds,
        )

        stream = client.group.start_stream()
        audio_format = AudioFormat(
            sample_rate=fixture.sample_rate,
            bit_depth=fixture.bit_depth,
            channels=fixture.channels,
        )
        next_play_start_us = server.clock.now_us() + 250_000
        total_duration_us = 0
        for chunk, duration_us in _iter_pcm_blocks(
            fixture.pcm_bytes,
            sample_rate=fixture.sample_rate,
            channels=fixture.channels,
            bit_depth=fixture.bit_depth,
        ):
            stream.prepare_audio(chunk, audio_format)
            play_start_us = await stream.commit_audio(play_start_us=next_play_start_us)
            next_play_start_us = play_start_us + duration_us
            total_duration_us += duration_us

        await asyncio.sleep((total_duration_us / 1_000_000.0) + 0.75)
        await client.group.stop()

        summary = {
            "status": "ok",
            "implementation": "aiosendspin",
            "role": "server",
            "server_id": args.server_id,
            "server_name": args.server_name,
            "discovery_method": discovery_method,
            "client": {
                "client_id": client.client_id,
                "name": client.name,
                "supported_roles": list(client.info.supported_roles),
                "active_roles": list(client.negotiated_roles),
            },
            "audio": {
                "fixture": str(fixture.path),
                "source_flac_sha256": fixture.source_flac_sha256,
                "source_pcm_sha256": fixture.source_pcm_sha256,
                "clip_seconds": args.clip_seconds,
                "sample_rate": fixture.sample_rate,
                "channels": fixture.channels,
                "bit_depth": fixture.bit_depth,
                "frame_count": fixture.frame_count,
                "duration_seconds": fixture.duration_seconds,
            },
        }
        write_json(summary_path, summary)
        print(Path(args.summary).read_text(encoding="utf-8"), end="")
        return 0
    except Exception as err:
        write_json(
            summary_path,
            {
                "status": "error",
                "reason": str(err),
            },
        )
        return 1
    finally:
        await server.close()


def main() -> int:
    """CLI entrypoint."""
    args = build_parser().parse_args()
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())

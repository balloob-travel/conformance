"""aiosendspin server adapter for conformance scenarios."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from hashlib import sha256
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from conformance.flac import decode_fixture
from conformance.io import write_json
from conformance.registry import lookup_endpoint, register_endpoint


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
    parser.add_argument("--scenario-id", default="server-initiated-flac")
    parser.add_argument("--initiator-role", choices=("server", "client"), default="server")
    parser.add_argument("--preferred-codec", default="flac")
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    parser.add_argument("--port", type=int, default=8927)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--server-id", default="conformance-server")
    parser.add_argument("--server-name", default="Sendspin Conformance Server")
    parser.add_argument("--log-level", default="INFO")
    parser.add_argument("--enable-mdns", action="store_true")
    parser.add_argument("--clip-seconds", type=float, default=5.0)
    parser.add_argument("--metadata-title", default="Almost Silent")
    parser.add_argument("--metadata-artist", default="Sendspin Conformance")
    parser.add_argument("--metadata-album-artist", default="Sendspin")
    parser.add_argument("--metadata-album", default="Protocol Fixtures")
    parser.add_argument("--metadata-artwork-url", default="https://example.invalid/almost-silent.jpg")
    parser.add_argument("--metadata-year", type=int, default=2026)
    parser.add_argument("--metadata-track", type=int, default=1)
    parser.add_argument("--metadata-repeat", default="all")
    parser.add_argument("--metadata-shuffle", default="false")
    parser.add_argument("--metadata-track-progress", type=int, default=12_000)
    parser.add_argument("--metadata-track-duration", type=int, default=180_000)
    parser.add_argument("--metadata-playback-speed", type=int, default=1_000)
    parser.add_argument("--controller-command", default="next")
    parser.add_argument("--artwork-format", default="jpeg")
    parser.add_argument("--artwork-width", type=int, default=256)
    parser.add_argument("--artwork-height", type=int, default=256)
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


async def _wait_for_incoming_client(
    server: Any,
    *,
    client_name: str,
    timeout_s: float,
) -> tuple[Any, str]:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s
    while loop.time() < deadline:
        target = _find_connected_client(server, client_name)
        if target is not None:
            return target, "registry_advertised"
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


def _bool_from_cli(raw: str) -> bool:
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _metadata_snapshot(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "title": args.metadata_title,
        "artist": args.metadata_artist,
        "album_artist": args.metadata_album_artist,
        "album": args.metadata_album,
        "artwork_url": args.metadata_artwork_url,
        "year": args.metadata_year,
        "track": args.metadata_track,
        "repeat": args.metadata_repeat,
        "shuffle": _bool_from_cli(args.metadata_shuffle),
        "progress": {
            "track_progress": args.metadata_track_progress,
            "track_duration": args.metadata_track_duration,
            "playback_speed": args.metadata_playback_speed,
        },
    }


def _reference_artwork_image() -> Image.Image:
    image = Image.new("RGB", (320, 200), "#e8d4b8")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 320, 60), fill="#c9783b")
    draw.rectangle((0, 60, 320, 130), fill="#935228")
    draw.rectangle((0, 130, 320, 200), fill="#4b2f1b")
    draw.ellipse((24, 22, 114, 112), fill="#f3e5cf", outline="#4b2f1b", width=4)
    draw.rectangle((150, 36, 280, 54), fill="#f3e5cf")
    draw.rectangle((150, 74, 252, 88), fill="#e7c49f")
    draw.rectangle((150, 102, 264, 116), fill="#e7c49f")
    draw.rectangle((150, 140, 296, 166), fill="#d7a16d")
    draw.line((152, 153, 292, 153), fill="#4b2f1b", width=3)
    return image


def _picture_format(raw: str) -> Any:
    from aiosendspin.models.types import PictureFormat

    normalized = raw.strip().lower()
    if normalized == "jpeg":
        return PictureFormat.JPEG
    if normalized == "png":
        return PictureFormat.PNG
    if normalized == "bmp":
        return PictureFormat.BMP
    raise ValueError(f"Unsupported artwork format: {raw}")


async def _disconnect_client(client: Any) -> None:
    connection = client.connection
    if connection is None:
        return
    await connection.disconnect(retry_connection=False)


def _controller_command_payload(command: str) -> dict[str, Any]:
    return {"command": command}


def _controller_event_to_command(event: Any) -> dict[str, Any] | None:
    name = type(event).__name__
    if name == "ControllerPlayEvent":
        return {"command": "play"}
    if name == "ControllerPauseEvent":
        return {"command": "pause"}
    if name == "ControllerStopEvent":
        return {"command": "stop"}
    if name == "ControllerNextEvent":
        return {"command": "next"}
    if name == "ControllerPreviousEvent":
        return {"command": "previous"}
    if name == "ControllerSwitchEvent":
        return {"command": "switch"}
    if name == "ControllerRepeatEvent":
        mode = getattr(event, "mode", None)
        return {"command": f"repeat_{str(mode.value if mode is not None else mode)}"}
    if name == "ControllerShuffleEvent":
        shuffle = bool(getattr(event, "shuffle", False))
        return {"command": "shuffle" if shuffle else "unshuffle"}
    if name == "ControllerVolumeEvent":
        return {"command": "volume", "volume": int(getattr(event, "volume", 0))}
    if name == "ControllerMuteEvent":
        return {"command": "mute", "mute": bool(getattr(event, "muted", False))}
    return None


def _client_snapshot(client: Any) -> dict[str, Any]:
    return {
        "client_id": client.client_id,
        "name": client.name,
        "supported_roles": list(client.info.supported_roles),
        "active_roles": list(client.negotiated_roles),
    }


def _base_summary(
    args: argparse.Namespace,
    *,
    discovery_method: str,
    client: Any,
) -> dict[str, Any]:
    return {
        "status": "ok",
        "implementation": "aiosendspin",
        "role": "server",
        "server_id": args.server_id,
        "server_name": args.server_name,
        "scenario_id": args.scenario_id,
        "initiator_role": args.initiator_role,
        "preferred_codec": args.preferred_codec,
        "discovery_method": discovery_method,
        "peer_hello": {
            "type": "client/hello",
            "payload": client.info.to_dict(),
        },
        "client": _client_snapshot(client),
    }


async def _run_audio_scenario(args: argparse.Namespace, *, server: Any, client: Any) -> dict[str, Any]:
    from aiosendspin.server.audio import AudioFormat

    fixture = decode_fixture(Path(args.fixture), max_duration_seconds=args.clip_seconds)
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
    return {
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
        }
    }


async def _run_metadata_scenario(args: argparse.Namespace, *, client: Any) -> dict[str, Any]:
    from aiosendspin.models.types import RepeatMode
    from aiosendspin.server.roles.metadata import MetadataGroupRole

    metadata_group_role = client.group.group_role("metadata")
    if not isinstance(metadata_group_role, MetadataGroupRole):
        raise RuntimeError("Metadata group role is not active for this client")

    repeat = RepeatMode(args.metadata_repeat)
    expected = _metadata_snapshot(args)
    metadata_group_role.update(
        title=args.metadata_title,
        artist=args.metadata_artist,
        album_artist=args.metadata_album_artist,
        album=args.metadata_album,
        artwork_url=args.metadata_artwork_url,
        year=args.metadata_year,
        track=args.metadata_track,
        repeat=repeat,
        shuffle=_bool_from_cli(args.metadata_shuffle),
        track_progress=args.metadata_track_progress,
        track_duration=args.metadata_track_duration,
        playback_speed=args.metadata_playback_speed,
    )
    await asyncio.sleep(0.5)
    await _disconnect_client(client)
    return {"metadata": {"expected": expected}}


async def _run_controller_scenario(args: argparse.Namespace, *, client: Any) -> dict[str, Any]:
    from aiosendspin.models.types import MediaCommand
    from aiosendspin.server.roles.controller import ControllerGroupRole

    controller_group_role = client.group.group_role("controller")
    if not isinstance(controller_group_role, ControllerGroupRole):
        raise RuntimeError("Controller group role is not active for this client")

    expected_command = _controller_command_payload(args.controller_command)
    event_future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()

    def on_group_event(_group: Any, event: Any) -> None:
        command = _controller_event_to_command(event)
        if command is not None and not event_future.done():
            event_future.set_result(command)

    unsubscribe = client.group.add_event_listener(on_group_event)
    try:
        controller_group_role.set_supported_commands([MediaCommand(args.controller_command)])
        received_command = await asyncio.wait_for(event_future, timeout=args.timeout_seconds)
    finally:
        unsubscribe()

    await asyncio.sleep(0.2)
    await _disconnect_client(client)
    return {
        "controller": {
            "expected_command": expected_command,
            "received_command": received_command,
            "supported_commands": [command.value for command in controller_group_role._get_supported_commands()],  # noqa: SLF001
            "volume": controller_group_role.volume,
            "muted": controller_group_role.muted,
        }
    }


async def _run_artwork_scenario(args: argparse.Namespace, *, client: Any) -> dict[str, Any]:
    from aiosendspin.server.roles.artwork import ArtworkGroupRole

    artwork_group_role = client.group.group_role("artwork")
    if not isinstance(artwork_group_role, ArtworkGroupRole):
        raise RuntimeError("Artwork group role is not active for this client")

    image = _reference_artwork_image()
    art_format = _picture_format(args.artwork_format)
    encoded = artwork_group_role._process_and_encode_image(  # noqa: SLF001
        image.copy(),
        args.artwork_width,
        args.artwork_height,
        art_format,
    )
    await artwork_group_role.set_album_artwork(image)
    await asyncio.sleep(0.5)
    await _disconnect_client(client)
    return {
        "artwork": {
            "channel": 0,
            "source": "album",
            "format": args.artwork_format.lower(),
            "width": args.artwork_width,
            "height": args.artwork_height,
            "encoded_sha256": sha256(encoded).hexdigest(),
            "byte_count": len(encoded),
        }
    }


async def _scenario_payload(
    args: argparse.Namespace,
    *,
    server: Any,
    client: Any,
) -> dict[str, Any]:
    if args.scenario_id in {"client-initiated-pcm", "server-initiated-flac"}:
        return await _run_audio_scenario(args, server=server, client=client)
    if args.scenario_id == "client-initiated-metadata":
        return await _run_metadata_scenario(args, client=client)
    if args.scenario_id == "client-initiated-controller":
        return await _run_controller_scenario(args, client=client)
    if args.scenario_id == "client-initiated-artwork":
        return await _run_artwork_scenario(args, client=client)
    raise ValueError(f"Unsupported scenario for aiosendspin server adapter: {args.scenario_id}")


async def _run(args: argparse.Namespace) -> int:
    _add_repo_to_syspath("aiosendspin")

    from aiosendspin.server.server import SendspinServer

    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO))

    summary_path = Path(args.summary)
    ready_path = Path(args.ready)
    registry_path = Path(args.registry)

    loop = asyncio.get_running_loop()
    server = SendspinServer(loop, server_id=args.server_id, server_name=args.server_name)

    try:
        await server.start_server(
            port=args.port,
            host=args.host,
            advertise_addresses=["127.0.0.1"] if args.enable_mdns else [],
            discover_clients=args.enable_mdns,
        )
        server_url = f"ws://127.0.0.1:{args.port}/sendspin"
        if args.initiator_role == "client":
            register_endpoint(
                registry_path,
                args.server_name,
                server_url,
            )
        write_json(
            ready_path,
            {
                "status": "ready",
                "server_id": args.server_id,
                "server_name": args.server_name,
                "scenario_id": args.scenario_id,
                "initiator_role": args.initiator_role,
                "url": server_url,
            },
        )

        if args.initiator_role == "client":
            client, discovery_method = await _wait_for_incoming_client(
                server,
                client_name=args.client_name,
                timeout_s=args.timeout_seconds,
            )
        else:
            client, discovery_method = await _wait_for_target_client(
                server,
                client_name=args.client_name,
                registry_path=registry_path,
                timeout_s=args.timeout_seconds,
            )

        payload = await _scenario_payload(args, server=server, client=client)
        summary = {
            **_base_summary(args, discovery_method=discovery_method, client=client),
            **payload,
        }
        write_json(summary_path, summary)
        print(Path(args.summary).read_text(encoding="utf-8"), end="")
        return 0
    except Exception as err:
        write_json(
            summary_path,
            {
                "status": "error",
                "implementation": "aiosendspin",
                "role": "server",
                "scenario_id": args.scenario_id,
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

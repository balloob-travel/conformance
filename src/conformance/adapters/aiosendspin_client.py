"""Server-initiated aiosendspin client adapter."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

from conformance.flac import StreamingFlacDecoder
from conformance.io import write_json
from conformance.pcm import FloatPcmHasher, sha256_hex
from conformance.registry import register_endpoint


def _add_repo_to_syspath(dirname: str) -> None:
    from conformance.implementations import resolve_required_repo_path

    repo = resolve_required_repo_path(dirname)
    if str(repo) not in sys.path:
        sys.path.insert(0, str(repo))


def build_parser() -> argparse.ArgumentParser:
    """Create the CLI parser."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--client-name", required=True)
    parser.add_argument("--client-id", required=True)
    parser.add_argument("--summary", required=True)
    parser.add_argument("--ready", required=True)
    parser.add_argument("--registry", required=True)
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    parser.add_argument("--port", type=int, default=8928)
    parser.add_argument("--path", default="/sendspin")
    parser.add_argument("--log-level", default="INFO")
    parser.add_argument("--enable-mdns", action="store_true")
    return parser


async def _run(args: argparse.Namespace) -> int:
    _add_repo_to_syspath("aiosendspin")

    from aiosendspin.client import ClientListener, SendspinClient
    from aiosendspin.models.player import ClientHelloPlayerSupport, SupportedAudioFormat
    from aiosendspin.models.types import AudioCodec, PlayerCommand, Roles

    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO))

    summary_path = Path(args.summary)
    ready_path = Path(args.ready)
    registry_path = Path(args.registry)
    disconnect_event = asyncio.Event()
    received_hasher = FloatPcmHasher()
    encoded_accumulator = bytearray()
    state: dict[str, Any] = {
        "audio_chunk_count": 0,
        "stream": None,
        "server_info": None,
        "disconnect_reason": "server_disconnect",
    }
    current_decoder: StreamingFlacDecoder | None = None
    received_server_hello: dict[str, Any] | None = None

    def flush_decoder() -> None:
        if current_decoder is None:
            return
        pcm = current_decoder.flush()
        if pcm:
            received_hasher.update_from_pcm_bytes(pcm, bit_depth=16)

    player_support = ClientHelloPlayerSupport(
        supported_formats=[
            SupportedAudioFormat(
                codec=AudioCodec.FLAC,
                channels=1,
                sample_rate=8_000,
                bit_depth=16,
            ),
            SupportedAudioFormat(
                codec=AudioCodec.PCM,
                channels=1,
                sample_rate=8_000,
                bit_depth=16,
            ),
            SupportedAudioFormat(
                codec=AudioCodec.FLAC,
                channels=2,
                sample_rate=44_100,
                bit_depth=16,
            ),
            SupportedAudioFormat(
                codec=AudioCodec.FLAC,
                channels=2,
                sample_rate=48_000,
                bit_depth=16,
            ),
            SupportedAudioFormat(
                codec=AudioCodec.PCM,
                channels=2,
                sample_rate=44_100,
                bit_depth=16,
            ),
            SupportedAudioFormat(
                codec=AudioCodec.PCM,
                channels=2,
                sample_rate=48_000,
                bit_depth=16,
            ),
        ],
        buffer_capacity=2_000_000,
        supported_commands=[PlayerCommand.VOLUME, PlayerCommand.MUTE],
    )

    client = SendspinClient(
        client_id=args.client_id,
        client_name=args.client_name,
        roles=[Roles.PLAYER],
        player_support=player_support,
    )

    original_handle_server_hello = client._handle_server_hello

    def capture_server_hello(payload: Any) -> None:
        nonlocal received_server_hello
        received_server_hello = {
            "type": "server/hello",
            "payload": payload.to_dict(),
        }
        original_handle_server_hello(payload)

    client._handle_server_hello = capture_server_hello

    def on_stream_start(message: Any) -> None:
        nonlocal current_decoder
        player = message.payload.player
        if player is None:
            return
        codec_header = None
        if player.codec_header:
            import base64

            codec_header = base64.b64decode(player.codec_header)
        state["stream"] = {
            "codec": player.codec.value,
            "sample_rate": player.sample_rate,
            "channels": player.channels,
            "bit_depth": player.bit_depth,
        }
        if player.codec.value == "flac":
            current_decoder = StreamingFlacDecoder(
                sample_rate=player.sample_rate,
                channels=player.channels,
                bit_depth=player.bit_depth,
                codec_header=codec_header,
            )
        else:
            current_decoder = None

    def on_audio_chunk(timestamp_us: int, payload: bytes, audio_format: Any) -> None:
        del timestamp_us
        state["audio_chunk_count"] += 1
        encoded_accumulator.extend(payload)
        codec = audio_format.codec.value
        if codec == "flac":
            if current_decoder is None:
                raise RuntimeError("Received FLAC before stream/start")
            pcm = current_decoder.decode(payload)
            received_hasher.update_from_pcm_bytes(pcm, bit_depth=audio_format.pcm_format.bit_depth)
            return
        if codec == "pcm":
            received_hasher.update_from_pcm_bytes(payload, bit_depth=audio_format.pcm_format.bit_depth)
            return
        raise RuntimeError(f"Unsupported codec for this adapter: {codec}")

    def on_disconnect() -> None:
        flush_decoder()
        disconnect_event.set()

    def on_stream_end(_roles: list[str] | None) -> None:
        flush_decoder()

    client.add_stream_start_listener(on_stream_start)
    client.add_audio_chunk_listener(on_audio_chunk)
    client.add_stream_end_listener(on_stream_end)
    client.add_disconnect_listener(on_disconnect)

    async def handle_connection(ws: Any) -> None:
        await client.attach_websocket(ws)
        state["server_info"] = (
            asdict(client.server_info) if client.server_info is not None else None
        )
        await disconnect_event.wait()

    listener = ClientListener(
        client_id=args.client_id,
        client_name=args.client_name,
        on_connection=handle_connection,
        port=args.port,
        path=args.path,
        advertise_mdns=args.enable_mdns,
    )

    try:
        await listener.start()
        register_endpoint(
            registry_path,
            args.client_name,
            f"ws://127.0.0.1:{args.port}{args.path}",
        )
        write_json(
            ready_path,
            {
                "status": "ready",
                "url": f"ws://127.0.0.1:{args.port}{args.path}",
            },
        )
        await asyncio.wait_for(disconnect_event.wait(), timeout=args.timeout_seconds)
    except TimeoutError:
        write_json(
            summary_path,
            {
                "status": "error",
                "reason": "Timed out waiting for server disconnect",
            },
        )
        return 1
    finally:
        await listener.stop()

    summary = {
        "status": "ok",
        "implementation": "aiosendspin",
        "role": "client",
        "client_name": args.client_name,
        "client_id": args.client_id,
        "peer_hello": received_server_hello,
        "server": state["server_info"],
        "stream": state["stream"],
        "audio": {
            "audio_chunk_count": state["audio_chunk_count"],
            "received_encoded_sha256": sha256_hex(bytes(encoded_accumulator)),
            "received_pcm_sha256": received_hasher.hexdigest(),
            "received_sample_count": received_hasher.sample_count,
        },
    }
    write_json(summary_path, summary)
    print(Path(args.summary).read_text(encoding="utf-8"), end="")
    return 0


def main() -> int:
    """CLI entrypoint."""
    args = build_parser().parse_args()
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())

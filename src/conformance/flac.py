"""FLAC fixture decoding and streaming FLAC frame decoding helpers."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

import av

from .pcm import FloatPcmHasher, sha256_hex

_FLAC_HEADER_PREFIX_SIZE = 8


@dataclass(frozen=True)
class DecodedFixture:
    """Decoded source fixture used by the server adapter."""

    path: Path
    pcm_bytes: bytes
    sample_rate: int
    channels: int
    bit_depth: int
    frame_count: int
    duration_seconds: float
    source_flac_sha256: str
    source_pcm_sha256: str


def flac_encoder_frame_samples(*, sample_rate: int, bit_depth: int, channels: int) -> int:
    """Return the FLAC encoder frame size for the given audio format."""
    encoder = av.AudioCodecContext.create("flac", "w")
    encoder.sample_rate = sample_rate
    encoder.layout = "stereo" if channels == 2 else "mono"
    encoder.format = f"s{bit_depth}"
    with av.logging.Capture():
        encoder.open()
    return int(encoder.frame_size or 0)


def trim_fixture_to_frame_multiple(
    fixture: DecodedFixture,
    *,
    frame_samples: int,
) -> tuple[DecodedFixture, int]:
    """Trim a decoded fixture down to a whole number of codec frames."""
    if frame_samples <= 0:
        return fixture, 0

    trimmed_frames = fixture.frame_count % frame_samples
    if trimmed_frames == 0:
        return fixture, 0

    kept_frames = fixture.frame_count - trimmed_frames
    bytes_per_frame = fixture.channels * (fixture.bit_depth // 8)
    pcm_bytes = fixture.pcm_bytes[: kept_frames * bytes_per_frame]
    hasher = FloatPcmHasher()
    hasher.update_from_pcm_bytes(pcm_bytes, bit_depth=fixture.bit_depth)
    trimmed_fixture = DecodedFixture(
        path=fixture.path,
        pcm_bytes=pcm_bytes,
        sample_rate=fixture.sample_rate,
        channels=fixture.channels,
        bit_depth=fixture.bit_depth,
        frame_count=kept_frames,
        duration_seconds=kept_frames / fixture.sample_rate if fixture.sample_rate else 0.0,
        source_flac_sha256=fixture.source_flac_sha256,
        source_pcm_sha256=hasher.hexdigest(),
    )
    return trimmed_fixture, trimmed_frames


class StreamingFlacDecoder:
    """Decode FLAC frames using the stream/start codec header."""

    def __init__(
        self,
        *,
        sample_rate: int,
        channels: int,
        bit_depth: int,
        codec_header: bytes | None,
    ) -> None:
        self._sample_rate = sample_rate
        self._channels = channels
        self._bit_depth = bit_depth
        self._codec_ctx = av.CodecContext.create("flac", "r")
        self._codec_ctx.extradata = self._build_extradata(codec_header)
        self._codec_ctx.open()

    def decode(self, flac_frame: bytes) -> bytes:
        """Decode a FLAC frame into packed little-endian PCM bytes."""
        packet = av.Packet(flac_frame)
        frames = self._codec_ctx.decode(packet)
        return self._frames_to_pcm(frames)

    def flush(self) -> bytes:
        """Flush buffered decoder output, if any."""
        frames = self._codec_ctx.decode(None)
        return self._frames_to_pcm(frames)

    def _frames_to_pcm(self, frames: list[av.AudioFrame]) -> bytes:
        """Convert decoded frames into packed little-endian PCM bytes."""
        if not frames:
            return b""

        pcm_parts: list[bytes] = []
        resampler = av.AudioResampler(
            format=f"s{self._bit_depth}",
            layout="stereo" if self._channels == 2 else "mono",
            rate=self._sample_rate,
        )
        for frame in frames:
            for out_frame in resampler.resample(frame):
                plane = out_frame.planes[0]
                bytes_per_sample = self._bit_depth // 8
                expected = out_frame.samples * out_frame.layout.nb_channels * bytes_per_sample
                pcm_parts.append(bytes(plane)[:expected])
        return b"".join(pcm_parts)

    def _build_extradata(self, codec_header: bytes | None) -> bytes:
        if codec_header and len(codec_header) >= _FLAC_HEADER_PREFIX_SIZE + 34:
            return codec_header[_FLAC_HEADER_PREFIX_SIZE : _FLAC_HEADER_PREFIX_SIZE + 34]

        streaminfo = bytearray(34)
        block_size = 4096
        streaminfo[0:2] = struct.pack(">H", block_size)
        streaminfo[2:4] = struct.pack(">H", block_size)
        packed = (
            (self._sample_rate << 12)
            | ((self._channels - 1) << 9)
            | ((self._bit_depth - 1) << 4)
        )
        streaminfo[10:14] = struct.pack(">I", packed)
        return bytes(streaminfo)


def decode_fixture(flac_path: Path, *, max_duration_seconds: float | None = 5.0) -> DecodedFixture:
    """Decode a FLAC fixture into canonical s16le PCM for streaming and hashing."""
    container = av.open(str(flac_path))
    stream = container.streams.audio[0]
    sample_rate = int(stream.codec_context.sample_rate or stream.sample_rate or 44_100)
    channels = int(stream.codec_context.channels or 2)
    bit_depth = 16
    layout = "stereo" if channels == 2 else "mono"
    resampler = av.AudioResampler(format="s16", layout=layout, rate=sample_rate)

    pcm_parts: list[bytes] = []
    frame_count = 0
    hasher = FloatPcmHasher()
    max_frames = None
    if max_duration_seconds is not None:
        max_frames = int(sample_rate * max_duration_seconds)
    for frame in container.decode(stream):
        for out_frame in resampler.resample(frame):
            plane = out_frame.planes[0]
            expected = out_frame.samples * out_frame.layout.nb_channels * 2
            pcm = bytes(plane)[:expected]
            if max_frames is not None and frame_count + out_frame.samples > max_frames:
                remaining_frames = max_frames - frame_count
                if remaining_frames <= 0:
                    container.close()
                    pcm_bytes = b"".join(pcm_parts)
                    duration = frame_count / sample_rate if sample_rate else 0.0
                    return DecodedFixture(
                        path=flac_path,
                        pcm_bytes=pcm_bytes,
                        sample_rate=sample_rate,
                        channels=channels,
                        bit_depth=bit_depth,
                        frame_count=frame_count,
                        duration_seconds=duration,
                        source_flac_sha256=sha256_hex(flac_path.read_bytes()),
                        source_pcm_sha256=hasher.hexdigest(),
                    )
                pcm = pcm[: remaining_frames * out_frame.layout.nb_channels * 2]
                out_samples = remaining_frames
            else:
                out_samples = out_frame.samples
            pcm_parts.append(pcm)
            frame_count += out_samples
            hasher.update_from_pcm_bytes(pcm, bit_depth=16)
            if max_frames is not None and frame_count >= max_frames:
                container.close()
                pcm_bytes = b"".join(pcm_parts)
                duration = frame_count / sample_rate if sample_rate else 0.0
                return DecodedFixture(
                    path=flac_path,
                    pcm_bytes=pcm_bytes,
                    sample_rate=sample_rate,
                    channels=channels,
                    bit_depth=bit_depth,
                    frame_count=frame_count,
                    duration_seconds=duration,
                    source_flac_sha256=sha256_hex(flac_path.read_bytes()),
                    source_pcm_sha256=hasher.hexdigest(),
                )
    container.close()

    pcm_bytes = b"".join(pcm_parts)
    duration = frame_count / sample_rate if sample_rate else 0.0
    return DecodedFixture(
        path=flac_path,
        pcm_bytes=pcm_bytes,
        sample_rate=sample_rate,
        channels=channels,
        bit_depth=bit_depth,
        frame_count=frame_count,
        duration_seconds=duration,
        source_flac_sha256=sha256_hex(flac_path.read_bytes()),
        source_pcm_sha256=hasher.hexdigest(),
    )

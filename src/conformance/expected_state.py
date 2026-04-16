"""Canonical expected-state dicts built from ScenarioSpec.

Adapters read these to drive their outbound messages and to compare received
state, so the same dict shape lives in exactly one place instead of being
rebuilt by every language adapter.
"""

from __future__ import annotations

from typing import Any

from .models import ScenarioSpec


_TRUTHY = {"1", "true", "yes", "on"}


def _bool_from_str(raw: str) -> bool:
    return raw.strip().lower() in _TRUTHY


def _metadata_block(args: dict[str, str]) -> dict[str, Any]:
    return {
        "title": args["metadata_title"],
        "artist": args["metadata_artist"],
        "album_artist": args["metadata_album_artist"],
        "album": args["metadata_album"],
        "artwork_url": args["metadata_artwork_url"],
        "year": int(args["metadata_year"]),
        "track": int(args["metadata_track"]),
        "repeat": args["metadata_repeat"],
        "shuffle": _bool_from_str(args["metadata_shuffle"]),
        "progress": {
            "track_progress": int(args["metadata_track_progress"]),
            "track_duration": int(args["metadata_track_duration"]),
            "playback_speed": int(args["metadata_playback_speed"]),
        },
    }


def _controller_block(args: dict[str, str]) -> dict[str, Any]:
    return {
        "expected_command": {"command": args["controller_command"]},
    }


def _artwork_block(args: dict[str, str]) -> dict[str, Any]:
    return {
        "channel": 0,
        "source": "album",
        "format": args["artwork_format"].lower(),
        "width": int(args["artwork_width"]),
        "height": int(args["artwork_height"]),
    }


def build_expected_state(scenario: ScenarioSpec) -> dict[str, Any]:
    """Build the canonical expected-state dict for a scenario.

    The dict always contains the same top-level keys so adapters can read it
    without branching on scenario_id — they just read the block that matches
    their verification_mode.
    """
    args = dict(scenario.extra_cli_args)
    state: dict[str, Any] = {
        "scenario_id": scenario.id,
        "verification_mode": scenario.verification_mode,
        "preferred_codec": scenario.preferred_codec,
        "initiator_role": scenario.initiator_role,
        "metadata": None,
        "controller": None,
        "artwork": None,
    }
    if scenario.verification_mode == "metadata":
        state["metadata"] = _metadata_block(args)
    elif scenario.verification_mode == "controller":
        state["controller"] = _controller_block(args)
    elif scenario.verification_mode == "artwork":
        state["artwork"] = _artwork_block(args)
    return state

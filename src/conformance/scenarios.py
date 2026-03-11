"""Scenario registry and capability checks."""

from __future__ import annotations

from .models import ScenarioSpec


SERVER_INITIATED_FLAC = ScenarioSpec(
    id="server-initiated-flac",
    display_name="Server Initiated FLAC",
    description=(
        "Start the server first, then the client, let the server discover/connect, "
        "stream FLAC derived from almost_silent.flac, and compare canonical PCM hashes."
    ),
)


SCENARIOS: dict[str, ScenarioSpec] = {
    SERVER_INITIATED_FLAC.id: SERVER_INITIATED_FLAC,
}


def supports_pair(scenario_id: str, server_impl: str, client_impl: str) -> str | None:
    """Return a skip reason when a pair cannot be evaluated at all."""
    if scenario_id != SERVER_INITIATED_FLAC.id:
        return f"Unknown scenario: {scenario_id}"
    return None

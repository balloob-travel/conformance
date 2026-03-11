"""Scenario registry and capability checks."""

from __future__ import annotations

from .models import ScenarioSpec


CLIENT_INITIATED_PCM = ScenarioSpec(
    id="client-initiated-pcm",
    display_name="Client Initiated PCM",
    description=(
        "Start the server first, then the client. The client discovers or looks up the "
        "server, initiates the WebSocket connection, negotiates PCM transport, streams "
        "audio derived from almost_silent.flac, and compares canonical PCM hashes."
    ),
    initiator_role="client",
    preferred_codec="pcm",
)


SERVER_INITIATED_FLAC = ScenarioSpec(
    id="server-initiated-flac",
    display_name="Server Initiated FLAC",
    description=(
        "Start the server first, then the client, let the server discover/connect, "
        "stream FLAC derived from almost_silent.flac, and compare canonical PCM hashes."
    ),
    initiator_role="server",
    preferred_codec="flac",
)


SCENARIOS: dict[str, ScenarioSpec] = {
    CLIENT_INITIATED_PCM.id: CLIENT_INITIATED_PCM,
    SERVER_INITIATED_FLAC.id: SERVER_INITIATED_FLAC,
}


def supports_pair(scenario_id: str, server_impl: str, client_impl: str) -> str | None:
    """Return a skip reason when a pair cannot be evaluated at all."""
    del server_impl, client_impl
    if scenario_id not in SCENARIOS:
        return f"Unknown scenario: {scenario_id}"
    return None

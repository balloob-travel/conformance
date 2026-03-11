"""Scenario registry and capability checks."""

from __future__ import annotations

from .implementations import IMPLEMENTATIONS
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
    """Return a skip reason when a pair does not support a scenario."""
    if scenario_id != SERVER_INITIATED_FLAC.id:
        return f"Unknown scenario: {scenario_id}"

    server = IMPLEMENTATIONS[server_impl].server
    client = IMPLEMENTATIONS[client_impl].client

    if not server.supported:
        return server.reason or f"{server_impl} does not expose a runnable server adapter"
    if not server.supports_discovery:
        return f"{server_impl} server adapter does not support discovery"
    if not server.supports_flac:
        return f"{server_impl} server adapter does not support FLAC output"
    if not client.supported:
        return client.reason or f"{client_impl} does not expose a runnable client adapter"
    if not client.supports_server_initiated:
        return f"{client_impl} client adapter does not support server-initiated connections"
    if not client.supports_flac:
        return f"{client_impl} client adapter does not support FLAC receive"
    return None

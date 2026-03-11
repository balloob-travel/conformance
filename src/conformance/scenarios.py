"""Scenario registry and lookup helpers."""

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


SCENARIO_LIST: tuple[ScenarioSpec, ...] = (
    CLIENT_INITIATED_PCM,
    SERVER_INITIATED_FLAC,
)

SCENARIOS: dict[str, ScenarioSpec] = {scenario.id: scenario for scenario in SCENARIO_LIST}


def ordered_scenarios() -> tuple[ScenarioSpec, ...]:
    """Return scenarios in display/run order."""
    return SCENARIO_LIST


def get_scenario(scenario_id: str) -> ScenarioSpec | None:
    """Return a registered scenario by ID."""
    return SCENARIOS.get(scenario_id)


def require_scenario(scenario_id: str) -> ScenarioSpec:
    """Resolve a scenario or raise a descriptive error."""
    scenario = get_scenario(scenario_id)
    if scenario is None:
        raise ValueError(f"Unknown scenario: {scenario_id}")
    return scenario

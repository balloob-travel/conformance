"""Host environment helpers for conformance runs."""

from __future__ import annotations

import platform
from dataclasses import dataclass


@dataclass(frozen=True)
class EnvironmentSpec:
    """Stable identifier and display name for one host environment."""

    id: str
    name: str


def default_environment() -> EnvironmentSpec:
    """Return the current host environment in a stable display form."""
    system = platform.system()
    if system == "Darwin":
        return EnvironmentSpec(id="macos", name="macOS")
    if system == "Linux":
        return EnvironmentSpec(id="linux", name="Linux")
    if system == "Windows":
        return EnvironmentSpec(id="windows", name="Windows")
    normalized = system.lower() or "unknown"
    return EnvironmentSpec(id=normalized, name=system or "Unknown")


def resolve_environment(
    *,
    environment_id: str | None = None,
    environment_name: str | None = None,
) -> EnvironmentSpec:
    """Resolve an explicit or current host environment."""
    current = default_environment()
    return EnvironmentSpec(
        id=environment_id or current.id,
        name=environment_name or current.name,
    )


def build_log_filename(environment_id: str, adapter: str) -> str:
    """Return the published build log filename for one environment/adapter pair."""
    return f"{environment_id}__{adapter}.log"

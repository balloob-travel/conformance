"""Resolve the shared FLAC fixture used by the conformance suite."""

from __future__ import annotations

from pathlib import Path

from .implementations import resolve_required_repo_path


def fixture_path() -> Path:
    """Return the almost_silent.flac fixture path."""
    sendspin_cli = resolve_required_repo_path("sendspin-cli")
    fixture = sendspin_cli / "tests" / "fixtures" / "almost_silent.flac"
    if not fixture.exists():
        raise FileNotFoundError(f"Fixture not found: {fixture}")
    return fixture

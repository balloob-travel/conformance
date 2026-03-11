"""Simple shared registry file used as a CI-safe discovery fallback."""

from __future__ import annotations

from pathlib import Path

from .io import read_json, write_json


def register_endpoint(registry_path: Path, client_name: str, url: str) -> None:
    """Register a client listener URL under a friendly name."""
    payload: dict[str, dict[str, str]] = {}
    if registry_path.exists():
        payload = dict(read_json(registry_path))
    payload[client_name] = {"url": url}
    write_json(registry_path, payload)


def lookup_endpoint(registry_path: Path, client_name: str) -> str | None:
    """Return a registered URL for a client name, if present."""
    if not registry_path.exists():
        return None
    payload = read_json(registry_path)
    entry = payload.get(client_name)
    if not isinstance(entry, dict):
        return None
    url = entry.get("url")
    return url if isinstance(url, str) else None

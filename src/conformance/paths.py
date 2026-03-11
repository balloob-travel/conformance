"""Path resolution helpers for local implementation repositories."""

from __future__ import annotations

import os
from pathlib import Path


def repo_root() -> Path:
    """Return the conformance repository root."""
    return Path(__file__).resolve().parents[2]


def workspace_root() -> Path:
    """Return the parent workspace that may already contain sibling repos."""
    return repo_root().parent


def env_repo_override_key(name: str) -> str:
    """Return the environment variable used to override a repo path."""
    safe = name.upper().replace("-", "_")
    return f"CONFORMANCE_REPO_{safe}"


def candidate_repo_paths(dirname: str) -> list[Path]:
    """Return candidate locations for a repository checkout."""
    paths: list[Path] = []
    env_value = os.environ.get(env_repo_override_key(dirname))
    if env_value:
        paths.append(Path(env_value).expanduser().resolve())
    paths.append((repo_root() / "repos" / dirname).resolve())
    paths.append((workspace_root() / dirname).resolve())
    return paths


def first_existing_path(paths: list[Path]) -> Path | None:
    """Return the first existing path from a candidate list."""
    for candidate in paths:
        if candidate.exists():
            return candidate
    return None

"""Toolchain discovery helpers."""

from __future__ import annotations

import shutil
from pathlib import Path


def find_dotnet() -> str | None:
    """Return a usable dotnet executable path."""
    dotnet = shutil.which("dotnet")
    if dotnet:
        return dotnet

    fallback = Path.home() / ".dotnet" / "dotnet"
    if fallback.exists():
        return str(fallback)
    return None

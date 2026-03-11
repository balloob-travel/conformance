"""Shared dataclasses for the conformance harness."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


AdapterKind = Literal["python", "dotnet", "none"]
CaseStatus = Literal["passed", "failed", "skipped"]


@dataclass(frozen=True)
class RoleSpec:
    """Capabilities and launch metadata for one implementation role."""

    supported: bool
    adapter_kind: AdapterKind
    entrypoint: str | None = None
    supports_server_initiated: bool = False
    supports_client_initiated: bool = False
    supports_flac: bool = False
    supports_discovery: bool = False
    reason: str | None = None


@dataclass(frozen=True)
class ImplementationSpec:
    """Conformance metadata for one implementation repository."""

    name: str
    display_name: str
    repo_dirname: str
    remote_url: str
    client: RoleSpec
    server: RoleSpec


@dataclass(frozen=True)
class ScenarioSpec:
    """Describes a runnable scenario in the matrix."""

    id: str
    display_name: str
    description: str


@dataclass
class CaseResult:
    """A single scenario result for one server/client pair."""

    scenario_id: str
    server_impl: str
    client_impl: str
    status: CaseStatus
    reason: str
    case_dir: str
    server_exit_code: int | None = None
    client_exit_code: int | None = None

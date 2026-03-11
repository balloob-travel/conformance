"""Implementation registry and adapter metadata."""

from __future__ import annotations

from pathlib import Path

from .models import ImplementationSpec, RoleSpec
from .paths import candidate_repo_paths, first_existing_path


IMPLEMENTATIONS: dict[str, ImplementationSpec] = {
    "aiosendspin": ImplementationSpec(
        name="aiosendspin",
        display_name="aiosendspin",
        repo_dirname="aiosendspin",
        remote_url="https://github.com/balloob-travel/aiosendspin.git",
        client=RoleSpec(
            supported=True,
            adapter_kind="python",
            entrypoint="conformance.adapters.aiosendspin_client",
            supports_server_initiated=True,
            supports_flac=True,
            supports_discovery=True,
        ),
        server=RoleSpec(
            supported=True,
            adapter_kind="python",
            entrypoint="conformance.adapters.aiosendspin_server",
            supports_server_initiated=True,
            supports_flac=True,
            supports_discovery=True,
        ),
    ),
    "sendspin-dotnet": ImplementationSpec(
        name="sendspin-dotnet",
        display_name="sendspin-dotnet",
        repo_dirname="sendspin-dotnet",
        remote_url="https://github.com/Sendspin/sendspin-dotnet.git",
        client=RoleSpec(
            supported=True,
            adapter_kind="dotnet",
            entrypoint="adapters/sendspin-dotnet/client/Conformance.SendspinDotnet.Client.csproj",
            supports_server_initiated=True,
            supports_flac=True,
            supports_discovery=True,
        ),
        server=RoleSpec(
            supported=False,
            adapter_kind="placeholder",
            entrypoint="conformance.adapters.placeholder",
            reason="The checked-in .NET SDK exposes client host mode, not a server implementation.",
        ),
    ),
    "SendspinKit": ImplementationSpec(
        name="SendspinKit",
        display_name="SendspinKit",
        repo_dirname="SendspinKit",
        remote_url="https://github.com/Sendspin/SendspinKit.git",
        client=RoleSpec(
            supported=False,
            adapter_kind="placeholder",
            entrypoint="conformance.adapters.placeholder",
            reason="SendspinKit currently exposes client-initiated connection APIs, not the server-initiated listener required by the first scenario.",
        ),
        server=RoleSpec(
            supported=False,
            adapter_kind="placeholder",
            entrypoint="conformance.adapters.placeholder",
            reason="SendspinKit is currently a client library in this workspace.",
        ),
    ),
    "sendspin-js": ImplementationSpec(
        name="sendspin-js",
        display_name="sendspin-js",
        repo_dirname="sendspin-js",
        remote_url="https://github.com/Sendspin/sendspin-js.git",
        client=RoleSpec(
            supported=False,
            adapter_kind="node",
            entrypoint="adapters/sendspin-js/client.mjs",
            reason="sendspin-js currently expects a direct server URL and does not expose the server-initiated listener flow required by the first scenario.",
        ),
        server=RoleSpec(
            supported=False,
            adapter_kind="node",
            entrypoint="adapters/sendspin-js/server.mjs",
            reason="sendspin-js is currently a client library in this workspace.",
        ),
    ),
    "sendspin-rs": ImplementationSpec(
        name="sendspin-rs",
        display_name="sendspin-rs",
        repo_dirname="sendspin-rs",
        remote_url="https://github.com/Sendspin/sendspin-rs.git",
        client=RoleSpec(
            supported=False,
            adapter_kind="placeholder",
            entrypoint="conformance.adapters.placeholder",
            reason="sendspin-rs does not yet expose the server-initiated listener and FLAC receive path required by the first scenario.",
        ),
        server=RoleSpec(
            supported=False,
            adapter_kind="placeholder",
            entrypoint="conformance.adapters.placeholder",
            reason="sendspin-rs does not yet expose a server implementation in this workspace.",
        ),
    ),
}


SUPPORTING_REPOS: dict[str, tuple[str, str]] = {
    "sendspin-cli": ("sendspin-cli", "https://github.com/balloob-travel/sendspin-cli.git"),
    "spec": ("spec", "https://github.com/Sendspin/spec.git"),
}


def implementation_names() -> list[str]:
    """Return implementation names in stable order."""
    return sorted(IMPLEMENTATIONS)


def resolve_repo_path(dirname: str) -> Path | None:
    """Resolve a repository checkout by its directory name."""
    return first_existing_path(candidate_repo_paths(dirname))


def resolve_required_repo_path(dirname: str) -> Path:
    """Resolve a repository checkout or raise a descriptive error."""
    repo = resolve_repo_path(dirname)
    if repo is None:
        raise FileNotFoundError(
            f"Could not find repository {dirname!r}. "
            f"Checked: {', '.join(str(path) for path in candidate_repo_paths(dirname))}"
        )
    return repo

"""Implementation registry and adapter metadata."""

from __future__ import annotations

from pathlib import Path

from .models import ImplementationSpec, RoleSpec
from .paths import candidate_repo_paths, first_existing_path, repo_root


IMPLEMENTATIONS: dict[str, ImplementationSpec] = {
    "aiosendspin": ImplementationSpec(
        name="aiosendspin",
        display_name="aiosendspin",
        repo_dirname="aiosendspin",
        remote_url="https://github.com/balloob-travel/aiosendspin.git",
        client=RoleSpec(
            supported=True,
            adapter_kind="python",
            build_adapter="python-adapters",
            entrypoint="conformance.adapters.aiosendspin_client",
            supports_server_initiated=True,
            supports_client_initiated=True,
            supports_flac=True,
            supports_discovery=True,
            supported_role_families=("player", "metadata", "controller", "artwork"),
        ),
        server=RoleSpec(
            supported=True,
            adapter_kind="python",
            build_adapter="python-adapters",
            entrypoint="conformance.adapters.aiosendspin_server",
            supports_server_initiated=True,
            supports_client_initiated=True,
            supports_flac=True,
            supports_discovery=True,
            supported_role_families=("player", "metadata", "controller", "artwork"),
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
            build_adapter="sendspin-dotnet-client",
            entrypoint="adapters/sendspin-dotnet/client/Conformance.SendspinDotnet.Client.csproj",
            supports_server_initiated=True,
            supports_client_initiated=True,
            supports_flac=True,
            supports_discovery=True,
            supported_role_families=("player", "metadata", "controller", "artwork"),
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
            supported=True,
            adapter_kind="swift",
            build_adapter="SendspinKit-client",
            entrypoint="adapters/SendspinKit/client:ConformanceSendspinKitClient",
            supports_client_initiated=True,
            supports_flac=True,
            supported_role_families=("player", "metadata", "controller", "artwork"),
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
            supported=True,
            adapter_kind="node",
            build_adapter="sendspin-js-adapters",
            entrypoint="adapters/sendspin-js/client.mjs",
            supports_server_initiated=True,
            supports_client_initiated=True,
            supports_flac=True,
            supported_role_families=("player", "metadata", "controller", "artwork"),
        ),
        server=RoleSpec(
            supported=False,
            adapter_kind="node",
            build_adapter="sendspin-js-adapters",
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
            supported=True,
            adapter_kind="cargo",
            build_adapter="sendspin-rs-client",
            entrypoint="adapters/sendspin-rs/client/Cargo.toml",
            supports_server_initiated=True,
            supports_client_initiated=True,
            supports_flac=True,
            supported_role_families=("player", "metadata", "controller", "artwork"),
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


def ensure_repo_checkout(dirname: str) -> Path:
    """Ensure a stable checkout path under repos/ exists and return it."""
    checkout = resolve_required_repo_path(dirname)
    managed_path = (repo_root() / "repos" / dirname).resolve()
    if managed_path == checkout.resolve():
        return managed_path

    managed_path.parent.mkdir(parents=True, exist_ok=True)
    if managed_path.exists():
        return managed_path

    try:
        managed_path.symlink_to(checkout, target_is_directory=True)
        return managed_path
    except OSError:
        return checkout

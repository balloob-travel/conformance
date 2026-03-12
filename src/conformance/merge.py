"""Merge multiple host-specific conformance result directories."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from .io import read_json, write_json


def _resolve_data_dir(root: Path) -> Path | None:
    if (root / "data" / "index.json").exists():
        return root / "data"
    if (root / "index.json").exists():
        return root
    return None


def _copy_build_logs(source_dir: Path, target_dir: Path) -> None:
    builds_dir = source_dir / "builds"
    if not builds_dir.exists():
        return
    for build_log in builds_dir.iterdir():
        if not build_log.is_file():
            continue
        target_path = target_dir / build_log.name
        if target_path.exists():
            raise ValueError(f"Duplicate build log while merging: {build_log.name}")
        shutil.copy2(build_log, target_path)


def merge_results_dirs(
    *,
    input_dirs: list[Path],
    output_dir: Path,
) -> dict[str, Any]:
    """Merge multiple results directories into one combined raw data directory."""
    resolved_inputs = [(input_dir, _resolve_data_dir(input_dir)) for input_dir in input_dirs]
    valid_inputs = [(root, data_dir) for root, data_dir in resolved_inputs if data_dir is not None]
    if not valid_inputs:
        raise FileNotFoundError("No result directories with data/index.json were found to merge.")

    if output_dir.exists():
        shutil.rmtree(output_dir)
    data_dir = output_dir / "data"
    builds_dir = data_dir / "builds"
    builds_dir.mkdir(parents=True, exist_ok=True)

    merged_results: list[dict[str, Any]] = []
    merged_builds: list[dict[str, Any]] = []
    merged_repositories: list[dict[str, Any]] = []
    repository_index: dict[tuple[str, str], dict[str, Any]] = {}
    seen_cases: set[str] = set()

    for _, source_data_dir in valid_inputs:
        assert source_data_dir is not None
        payload = read_json(source_data_dir / "index.json")
        source_results = payload.get("results")
        if not isinstance(source_results, list):
            continue

        for result in source_results:
            if not isinstance(result, dict):
                continue
            case_name = Path(str(result.get("case_dir") or "")).name
            if not case_name:
                continue
            if case_name in seen_cases:
                raise ValueError(f"Duplicate case directory while merging: {case_name}")
            seen_cases.add(case_name)

            source_case_dir = source_data_dir / case_name
            target_case_dir = data_dir / case_name
            if source_case_dir.exists():
                shutil.copytree(source_case_dir, target_case_dir)

            merged_result = dict(result)
            merged_result["case_dir"] = str(target_case_dir)
            merged_results.append(merged_result)
            if (target_case_dir / "result.json").exists():
                write_json(target_case_dir / "result.json", merged_result)

        build_report = source_data_dir / "build-report.json"
        if build_report.exists():
            build_payload = read_json(build_report)
            build_results = build_payload.get("results")
            if isinstance(build_results, list):
                merged_builds.extend(
                    result for result in build_results if isinstance(result, dict)
                )

        repositories_report = source_data_dir / "repositories.json"
        if repositories_report.exists():
            repositories_payload = read_json(repositories_report)
            repositories = repositories_payload.get("repositories")
            if isinstance(repositories, list):
                for repository in repositories:
                    if not isinstance(repository, dict):
                        continue
                    key = str(repository.get("key") or "")
                    identity = str(
                        repository.get("commit_sha")
                        or repository.get("reason")
                        or repository.get("repo_path")
                        or "unknown"
                    )
                    index_key = (key, identity)
                    if index_key in repository_index:
                        existing = repository_index[index_key]
                        existing_envs = existing.setdefault("environments", [])
                        incoming_envs = repository.get("environments")
                        if isinstance(incoming_envs, list):
                            for environment in incoming_envs:
                                if (
                                    isinstance(environment, dict)
                                    and environment not in existing_envs
                                ):
                                    existing_envs.append(environment)
                        continue
                    merged_repository = dict(repository)
                    repository_index[index_key] = merged_repository
                    merged_repositories.append(merged_repository)

        _copy_build_logs(source_data_dir, builds_dir)

    write_json(data_dir / "index.json", {"results": merged_results})
    if merged_builds:
        write_json(data_dir / "build-report.json", {"results": merged_builds})
    if merged_repositories:
        write_json(data_dir / "repositories.json", {"repositories": merged_repositories})

    return {
        "input_count": len(valid_inputs),
        "result_count": len(merged_results),
        "build_count": len(merged_builds),
        "output_dir": str(output_dir),
    }

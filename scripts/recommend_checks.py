#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


@dataclass
class Recommendation:
    command: str
    reason: str
    required: bool


def _run_git_list(repo: Path, args: list[str]) -> list[str]:
    proc = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return []
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def detect_changed_files(repo: Path) -> list[str]:
    changed = set()
    changed.update(_run_git_list(repo, ["diff", "--name-only", "--diff-filter=ACMR"]))
    changed.update(_run_git_list(repo, ["diff", "--cached", "--name-only", "--diff-filter=ACMR"]))
    changed.update(_run_git_list(repo, ["ls-files", "--others", "--exclude-standard"]))
    return sorted(changed)


def has_prefix(path: str, prefix: str) -> bool:
    return path == prefix or path.startswith(prefix + "/")


def is_docs_only(paths: Iterable[str]) -> bool:
    for path in paths:
        if path in {"README.md", "AGENTS.md", "TODO.md"}:
            continue
        if path.endswith(".md") and (has_prefix(path, "docs") or "/docs/" in path):
            continue
        return False
    return True


def posting_related(path: str) -> bool:
    posting_paths = {
        "src/auto_post/poster.py",
        "src/auto_post/instagram.py",
        "src/auto_post/threads.py",
        "src/auto_post/x_twitter.py",
        "src/auto_post/notion_db.py",
        "src/auto_post/cli.py",
        "src/auto_post/token_manager.py",
    }
    return has_prefix(path, "tools/publish") or path in posting_paths


def gallery_related(path: str) -> bool:
    return (
        has_prefix(path, "tools/gallery-build")
        or has_prefix(path, "apps/gallery-web")
        or path == "src/auto_post/gallery_exporter.py"
    )


def ingest_related(path: str) -> bool:
    return (
        has_prefix(path, "tools/ingest")
        or path == "src/auto_post/importer.py"
        or path == "src/auto_post/grouping.py"
    )


def python_related(path: str) -> bool:
    if path.endswith(".py"):
        return True
    return path in {"pyproject.toml", "Makefile", ".pre-commit-config.yaml"}


def build_recommendations(paths: list[str], strict: bool = False) -> list[Recommendation]:
    recs: list[Recommendation] = []

    def add(command: str, reason: str, required: bool) -> None:
        if any(r.command == command for r in recs):
            return
        recs.append(Recommendation(command=command, reason=reason, required=required))

    if not paths:
        return recs

    if is_docs_only(paths):
        add(
            command="make check-monorepo",
            reason="quick structure guard for documentation-only changes",
            required=False,
        )
        return recs

    add(
        command="make check-monorepo",
        reason="ensure repository layout contracts remain valid",
        required=True,
    )

    if any(python_related(path) for path in paths):
        add(
            command="make check-changed-python",
            reason="run Ruff and mypy only for changed Python files",
            required=True,
        )

    if any(has_prefix(path, "src/auto_post") for path in paths):
        add(
            command="make test",
            reason="run Python tests for core CLI/runtime changes",
            required=True,
        )

    if any(posting_related(path) for path in paths):
        add(
            command="make publish-dry",
            reason="validate posting flow with dry-run",
            required=False,
        )

    if any(gallery_related(path) for path in paths):
        add(
            command="make gallery-export",
            reason="validate gallery export path",
            required=False,
        )

    if any(ingest_related(path) for path in paths):
        add(
            command="make ingest-preview TAKEOUT_DIR=./takeout-photos",
            reason="validate ingest path with preview mode",
            required=False,
        )

    if any(has_prefix(path, "apps/admin-web") for path in paths):
        add(
            command="make admin-smoke",
            reason="run admin UI smoke test",
            required=False,
        )

    if any(has_prefix(path, "apps/worker-api") for path in paths):
        add(
            command="make worker-dry",
            reason="run Worker deploy dry-run",
            required=False,
        )

    runtime_scopes = 0
    if any(has_prefix(path, "src") for path in paths):
        runtime_scopes += 1
    if any(has_prefix(path, "tools") for path in paths):
        runtime_scopes += 1
    if any(has_prefix(path, "apps") for path in paths):
        runtime_scopes += 1

    if runtime_scopes >= 2 or any(
        path in {"pyproject.toml", "Makefile", ".env.example"}
        or has_prefix(path, ".github/workflows")
        for path in paths
    ):
        add(
            command="make check-fast",
            reason="cross-cutting/config changes; run before release or merge when feasible",
            required=strict,
        )

    return recs


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Recommend validation commands for media-platform changes."
    )
    parser.add_argument("--repo", default=".", help="Path to the media-platform repository")
    parser.add_argument("--paths", nargs="*", help="Explicit changed paths (skip git detection)")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Mark cross-cutting checks as required",
    )
    parser.add_argument("--json", action="store_true", help="Print JSON output")
    args = parser.parse_args()

    repo = Path(args.repo).resolve()
    paths = sorted(set(args.paths)) if args.paths else detect_changed_files(repo)
    recs = build_recommendations(paths, strict=args.strict)

    payload = {
        "repo": str(repo),
        "changed_files": paths,
        "recommendations": [asdict(item) for item in recs],
    }

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    print(f"Repository: {repo}")
    if not paths:
        print("Changed files: 0")
        print("No recommendations (clean tree).")
        return 0

    print(f"Changed files: {len(paths)}")
    for path in paths:
        print(f"- {path}")

    if not recs:
        print("No command recommendations.")
        return 0

    print("\nRecommended commands:")
    for idx, item in enumerate(recs, start=1):
        tag = "required" if item.required else "optional"
        print(f"{idx}. [{tag}] {item.command}")
        print(f"   reason: {item.reason}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

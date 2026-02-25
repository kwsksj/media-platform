#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from recommend_checks import build_recommendations, detect_changed_files


def run_command(command: str, repo: Path) -> int:
    print(f"\n>>> {command}")
    proc = subprocess.run(command, cwd=repo, shell=True, check=False)
    return proc.returncode


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run required recommended checks for media-platform."
    )
    parser.add_argument("--repo", default=".", help="Path to the media-platform repository")
    parser.add_argument("--paths", nargs="*", help="Explicit changed paths (skip git detection)")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Treat cross-cutting checks as required",
    )
    parser.add_argument(
        "--include-optional",
        action="store_true",
        help="Run optional recommendations in addition to required ones",
    )
    parser.add_argument(
        "--stop-on-fail",
        action="store_true",
        help="Stop immediately after first failure",
    )
    args = parser.parse_args()

    repo = Path(args.repo).resolve()
    try:
        paths = sorted(set(args.paths)) if args.paths else detect_changed_files(repo)
        recs = build_recommendations(paths, strict=args.strict)
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    if args.include_optional:
        targets = recs
    else:
        targets = [item for item in recs if item.required]

    if not targets:
        print("No commands to run.")
        return 0

    print(f"Repository: {repo}")
    print(f"Selected commands: {len(targets)}")

    failures: list[tuple[str, int]] = []
    for item in targets:
        code = run_command(item.command, repo)
        if code != 0:
            failures.append((item.command, code))
            if args.stop_on_fail:
                break

    if not failures:
        print("\nAll selected commands passed.")
        return 0

    print("\nFailures:")
    for command, code in failures:
        print(f"- exit={code}: {command}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

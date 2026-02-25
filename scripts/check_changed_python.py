#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
from pathlib import Path

from recommend_checks import detect_changed_files


def run_command(repo: Path, command: list[str]) -> int:
    print(f">>> {shlex.join(command)}")
    proc = subprocess.run(command, cwd=repo, check=False)
    return proc.returncode


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run Ruff/mypy for changed Python files in this repository."
    )
    parser.add_argument("--repo", default=".", help="Path to repository root")
    parser.add_argument("--paths", nargs="*", help="Explicit changed paths (skip git detection)")
    parser.add_argument(
        "--python",
        default=sys.executable,
        help="Python executable used to run ruff/mypy modules",
    )
    parser.add_argument("--fix", action="store_true", help="Apply Ruff fixes and format in-place")
    args = parser.parse_args()

    repo = Path(args.repo).resolve()

    try:
        changed_paths = sorted(set(args.paths)) if args.paths else detect_changed_files(repo)
    except RuntimeError as exc:
        print(f"Error detecting changed files: {exc}", file=sys.stderr)
        return 2

    changed_py_files = [path for path in changed_paths if path.endswith(".py")]

    if not changed_py_files:
        print("No changed Python files.")
        return 0

    print("Changed Python files:")
    for path in changed_py_files:
        print(path)

    python = args.python

    if args.fix:
        command_groups: list[list[str]] = [
            [python, "-m", "ruff", "check", "--fix", *changed_py_files],
            [python, "-m", "ruff", "format", *changed_py_files],
        ]
    else:
        command_groups = [
            [python, "-m", "ruff", "check", *changed_py_files],
            [python, "-m", "ruff", "format", "--check", *changed_py_files],
        ]
        src_py_files = [path for path in changed_py_files if path.startswith("src/")]
        if src_py_files:
            command_groups.append([python, "-m", "mypy", *src_py_files])
        else:
            print("No changed files under src/ for mypy.")

    for command in command_groups:
        exit_code = run_command(repo, command)
        if exit_code != 0:
            return exit_code

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

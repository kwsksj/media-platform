#!/usr/bin/env python3
"""Fetch and summarize PR comments/review threads via GitHub GraphQL."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

QUERY = """\
query(
  $owner: String!,
  $repo: String!,
  $number: Int!,
  $commentsCursor: String,
  $reviewsCursor: String,
  $threadsCursor: String
) {
  repository(owner: $owner, name: $repo) {
    pullRequest(number: $number) {
      number
      url
      title
      state

      comments(first: 100, after: $commentsCursor) {
        pageInfo { hasNextPage endCursor }
        nodes {
          id
          body
          createdAt
          updatedAt
          author { login }
        }
      }

      reviews(first: 100, after: $reviewsCursor) {
        pageInfo { hasNextPage endCursor }
        nodes {
          id
          state
          body
          submittedAt
          author { login }
        }
      }

      reviewThreads(first: 100, after: $threadsCursor) {
        pageInfo { hasNextPage endCursor }
        nodes {
          id
          isResolved
          isOutdated
          path
          line
          startLine
          originalLine
          originalStartLine
          resolvedBy { login }
          comments(first: 100) {
            nodes {
              id
              body
              createdAt
              updatedAt
              author { login }
            }
          }
        }
      }
    }
  }
}
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch and summarize PR comments/review threads.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--repo", default=".", help="Path inside the Git repository.")
    parser.add_argument(
        "--pr",
        default=None,
        help="PR number or URL. Defaults to current branch PR.",
    )
    parser.add_argument("--json", action="store_true", help="Print full JSON payload.")
    parser.add_argument(
        "--include-resolved",
        action="store_true",
        help="Include resolved review threads in summary mode.",
    )
    parser.add_argument(
        "--include-outdated",
        action="store_true",
        help="Include outdated threads in summary mode.",
    )
    parser.add_argument(
        "--max-threads",
        type=int,
        default=30,
        help="Max thread lines to print in summary mode.",
    )
    return parser.parse_args()


def run_cmd(
    cmd: list[str],
    *,
    cwd: Path,
    stdin: str | None = None,
) -> str:
    process = subprocess.run(
        cmd,
        cwd=cwd,
        input=stdin,
        text=True,
        capture_output=True,
    )
    if process.returncode != 0:
        message = process.stderr.strip() or process.stdout.strip()
        raise RuntimeError(message or f"Command failed: {' '.join(cmd)}")
    return process.stdout


def run_json(
    cmd: list[str],
    *,
    cwd: Path,
    stdin: str | None = None,
) -> dict[str, Any]:
    out = run_cmd(cmd, cwd=cwd, stdin=stdin)
    try:
        payload = json.loads(out)
    except json.JSONDecodeError as error:
        raise RuntimeError(f"Failed to parse JSON: {error}") from error
    if not isinstance(payload, dict):
        raise RuntimeError("Unexpected JSON shape.")
    return payload


def find_git_root(start: Path) -> Path:
    output = run_cmd(["git", "rev-parse", "--show-toplevel"], cwd=start)
    return Path(output.strip())


def ensure_gh_auth(repo_root: Path) -> None:
    run_cmd(["gh", "auth", "status"], cwd=repo_root)


def resolve_repo(owner_repo: str) -> tuple[str, str]:
    parts = owner_repo.split("/", maxsplit=1)
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise RuntimeError(f"Invalid repo slug: {owner_repo}")
    return parts[0], parts[1]


def resolve_owner_repo(repo_root: Path) -> tuple[str, str]:
    slug = run_cmd(
        ["gh", "repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner"],
        cwd=repo_root,
    ).strip()
    return resolve_repo(slug)


def resolve_pr_number(repo_root: Path, pr: str | None) -> int:
    cmd = ["gh", "pr", "view"]
    if pr:
        cmd.append(pr)
    cmd.extend(["--json", "number", "--jq", ".number"])
    out = run_cmd(cmd, cwd=repo_root).strip()
    try:
        return int(out)
    except ValueError as error:
        raise RuntimeError(f"Failed to resolve PR number: {out}") from error


def fetch_page(
    *,
    owner: str,
    repo: str,
    number: int,
    repo_root: Path,
    comments_cursor: str | None,
    reviews_cursor: str | None,
    threads_cursor: str | None,
) -> dict[str, Any]:
    cmd = [
        "gh",
        "api",
        "graphql",
        "-F",
        "query=@-",
        "-F",
        f"owner={owner}",
        "-F",
        f"repo={repo}",
        "-F",
        f"number={number}",
    ]
    if comments_cursor:
        cmd.extend(["-F", f"commentsCursor={comments_cursor}"])
    if reviews_cursor:
        cmd.extend(["-F", f"reviewsCursor={reviews_cursor}"])
    if threads_cursor:
        cmd.extend(["-F", f"threadsCursor={threads_cursor}"])

    payload = run_json(cmd, cwd=repo_root, stdin=QUERY)
    errors = payload.get("errors")
    if errors:
        raise RuntimeError(f"GitHub GraphQL error: {json.dumps(errors, ensure_ascii=False)}")
    return payload


def fetch_all(owner: str, repo: str, number: int, repo_root: Path) -> dict[str, Any]:
    conversation_comments: list[dict[str, Any]] = []
    reviews: list[dict[str, Any]] = []
    review_threads: list[dict[str, Any]] = []

    comments_cursor: str | None = None
    reviews_cursor: str | None = None
    threads_cursor: str | None = None
    pr_meta: dict[str, Any] | None = None

    while True:
        payload = fetch_page(
            owner=owner,
            repo=repo,
            number=number,
            repo_root=repo_root,
            comments_cursor=comments_cursor,
            reviews_cursor=reviews_cursor,
            threads_cursor=threads_cursor,
        )

        pr = payload["data"]["repository"]["pullRequest"]
        if pr_meta is None:
            pr_meta = {
                "number": pr["number"],
                "url": pr["url"],
                "title": pr["title"],
                "state": pr["state"],
                "owner": owner,
                "repo": repo,
            }

        comments = pr["comments"]
        reviews_node = pr["reviews"]
        threads = pr["reviewThreads"]

        conversation_comments.extend(comments.get("nodes") or [])
        reviews.extend(reviews_node.get("nodes") or [])
        review_threads.extend(threads.get("nodes") or [])

        comments_cursor = (
            comments["pageInfo"]["endCursor"] if comments["pageInfo"]["hasNextPage"] else None
        )
        reviews_cursor = (
            reviews_node["pageInfo"]["endCursor"]
            if reviews_node["pageInfo"]["hasNextPage"]
            else None
        )
        threads_cursor = (
            threads["pageInfo"]["endCursor"] if threads["pageInfo"]["hasNextPage"] else None
        )

        if not (comments_cursor or reviews_cursor or threads_cursor):
            break

    if pr_meta is None:
        raise RuntimeError("No PR metadata returned.")

    return {
        "pull_request": pr_meta,
        "conversation_comments": conversation_comments,
        "reviews": reviews,
        "review_threads": review_threads,
    }


def normalize_space(text: str) -> str:
    return " ".join(text.split())


def excerpt(text: str, max_chars: int = 120) -> str:
    compact = normalize_space(text or "")
    if len(compact) <= max_chars:
        return compact
    return f"{compact[: max_chars - 1]}…"


def thread_location(thread: dict[str, Any]) -> str:
    path = thread.get("path") or "(unknown path)"
    line = thread.get("line") or thread.get("startLine") or thread.get("originalLine")
    if line:
        return f"{path}:{line}"
    return path


def render_summary(
    result: dict[str, Any],
    *,
    include_resolved: bool,
    include_outdated: bool,
    max_threads: int,
) -> None:
    pr = result["pull_request"]
    comments = result.get("conversation_comments", [])
    reviews = result.get("reviews", [])
    threads = result.get("review_threads", [])

    unresolved_threads = [t for t in threads if not t.get("isResolved")]
    unresolved_outdated_threads = [t for t in unresolved_threads if t.get("isOutdated")]
    actionable_threads = [t for t in unresolved_threads if not t.get("isOutdated")]

    if include_resolved:
        candidate_threads = threads
    else:
        candidate_threads = unresolved_threads
    if include_outdated:
        visible_threads = candidate_threads
    else:
        visible_threads = [t for t in candidate_threads if not t.get("isOutdated")]

    print(f"PR #{pr['number']}: {pr['title']}")
    print(f"URL: {pr['url']}")
    print(f"State: {pr['state']}")
    print(
        "Counts: "
        f"conversation_comments={len(comments)}, "
        f"reviews={len(reviews)}, "
        f"review_threads={len(threads)}, "
        f"unresolved_threads={len(unresolved_threads)}, "
        f"unresolved_outdated_threads={len(unresolved_outdated_threads)}, "
        f"actionable_threads={len(actionable_threads)}"
    )

    request_changes = [r for r in reviews if (r.get("state") or "") == "CHANGES_REQUESTED"]
    if request_changes:
        print("\nCHANGES_REQUESTED reviews:")
        for idx, review in enumerate(request_changes, start=1):
            author = (review.get("author") or {}).get("login") or "unknown"
            body = excerpt(review.get("body") or "")
            print(f"{idx}. {author}: {body}")

    if not visible_threads:
        print("\nNo review threads to show.")
        return

    print("\nReview threads:")
    for idx, thread in enumerate(visible_threads[:max_threads], start=1):
        location = thread_location(thread)
        status = "resolved" if thread.get("isResolved") else "unresolved"
        outdated = " outdated" if thread.get("isOutdated") else ""
        comments_in_thread = (thread.get("comments") or {}).get("nodes") or []
        latest = comments_in_thread[-1] if comments_in_thread else {}
        author = (latest.get("author") or {}).get("login") or "unknown"
        body = excerpt(latest.get("body") or "")
        print(f"{idx}. [{status}{outdated}] {location} {author}: {body}")

    if len(visible_threads) > max_threads:
        remainder = len(visible_threads) - max_threads
        print(f"... {remainder} more thread(s) omitted. Use --max-threads to expand.")


def main() -> int:
    args = parse_args()
    try:
        repo_root = find_git_root(Path(args.repo))
        ensure_gh_auth(repo_root)
        owner, repo = resolve_owner_repo(repo_root)
        number = resolve_pr_number(repo_root, args.pr)
        result = fetch_all(owner, repo, number, repo_root)
    except RuntimeError as error:
        print(str(error), file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        render_summary(
            result,
            include_resolved=args.include_resolved,
            include_outdated=args.include_outdated,
            max_threads=max(1, args.max_threads),
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

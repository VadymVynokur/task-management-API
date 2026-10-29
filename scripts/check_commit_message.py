"""Validate Conventional Commit messages for the local hook and GitHub Actions."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ALLOWED_TYPES = {
    "feat",
    "fix",
    "refactor",
    "perf",
    "style",
    "test",
    "docs",
    "build",
    "ops",
    "chore",
}
SUBJECT_RE = re.compile(
    r"^(?P<type>[a-z]+)(?:\((?P<scope>[a-z0-9][a-z0-9-]*)\))?"
    r"(?P<breaking>!)?: (?P<description>[a-z][^\n]*)$"
)


def validate_message(message: str) -> list[str]:
    """Return validation errors for a single commit message."""
    lines = message.replace("\r\n", "\n").split("\n")
    while lines and not lines[-1].strip():
        lines.pop()

    if not lines:
        return ["commit message is empty"]

    subject = lines[0].strip()
    if subject.startswith("Merge "):
        return []

    match = SUBJECT_RE.match(subject)
    if match is None:
        return [
            "subject must match '<type>(<optional-scope>): <lowercase description>'; "
            f"got {subject!r}"
        ]

    errors: list[str] = []
    if match.group("type") not in ALLOWED_TYPES:
        errors.append(
            f"type {match.group('type')!r} is not allowed; "
            f"use one of: {', '.join(sorted(ALLOWED_TYPES))}"
        )
    if match.group("description").endswith("."):
        errors.append("description must not end with a period")
    if match.group("breaking") and not any(
        line.startswith("BREAKING CHANGE:") for line in lines[1:]
    ):
        errors.append("breaking changes require a 'BREAKING CHANGE:' footer")
    return errors


def _strip_git_comments(message: str) -> str:
    return "\n".join(
        line for line in message.replace("\r\n", "\n").split("\n") if not line.startswith("#")
    )


def _messages_from_range(rev_range: str) -> list[str]:
    result = subprocess.run(
        ["git", "log", "--format=%x1e%B", rev_range],
        check=True,
        capture_output=True,
        text=True,
    )
    return [part.strip("\n") for part in result.stdout.split("\x1e") if part.strip()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--file", type=Path, help="commit message file from the commit-msg hook")
    source.add_argument("--message", help="single commit message or PR title")
    source.add_argument("--range", dest="rev_range", help="git revision range, e.g. base..HEAD")
    args = parser.parse_args(argv)

    if args.file is not None:
        messages = [_strip_git_comments(args.file.read_text(encoding="utf-8"))]
    elif args.message is not None:
        messages = [args.message]
    else:
        messages = _messages_from_range(args.rev_range)

    failures: list[str] = []
    for message in messages:
        errors = validate_message(message)
        if errors:
            failures.append(
                f"Invalid commit message:\n{message}\n" + "\n".join(f"  - {e}" for e in errors)
            )

    if failures:
        print("\n\n".join(failures), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""CLI adapter for recording a human-confirmed application submission."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))

from apply import application_status  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Mark one application as applied after the human submits it."
    )
    parser.add_argument("application", help="existing application folder")
    parser.add_argument(
        "--date",
        dest="applied_on",
        help="submission date in YYYY-MM-DD form (default: today)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = application_status.mark_applied(args.application, args.applied_on)
    except application_status.ApplicationStatusError as error:
        print(f"mark-applied: error: {error}", file=sys.stderr)
        return 1

    action = "marked" if result.changed else "already marked"
    print(f"{result.application}: {action} applied on {result.date_applied}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

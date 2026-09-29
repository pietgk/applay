#!/usr/bin/env python3
"""Thin CLI adapter for the bounded CV draft workflow."""

import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))
# Import the sibling tool through the package path in both modes (script and
# ``tools.cv_workflow``). Importing it as a bare top-level module would give it a
# second identity whenever ``tools/`` is also on sys.path, so patches applied to
# one copy would silently miss the copy this module actually calls.
sys.path.insert(0, str(HERE.parent))

from apply import workflow  # noqa: E402
from tools import new_application  # noqa: E402


def _common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("application", help="existing application folder")
    parser.add_argument(
        "--profile",
        help="profile source (default: repository profile/master-profile.yaml)",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="bounded CV draft/check/finalize workflow")
    commands = parser.add_subparsers(dest="command", required=True)

    start = commands.add_parser(
        "start", help="create cv-analysis.md, cv-feedback.md, and a draft scaffold"
    )
    _common(start)
    start.add_argument(
        "--force", action="store_true", help="replace non-placeholder draft files (with .bak)"
    )

    create = commands.add_parser(
        "create", help="import/scaffold an application and initialize its CV draft workflow"
    )
    create.add_argument("company", nargs="?")
    create.add_argument("--role", default="")
    create.add_argument("--date", help="application date (default: today)")
    create.add_argument("--from-report", help="import from a JSONL shortlist")
    create.add_argument("--job-id", help="stable job ID from the JSONL shortlist")
    create.add_argument("--job-index", type=int, help="1-based line number in the JSONL shortlist")
    create.add_argument("--match", help="case-insensitive company/title match in the shortlist")
    create.add_argument("--refresh", action="store_true", help="fetch current JobTech detail")
    create.add_argument("--force", action="store_true", help="replace imported source and drafts")
    create.add_argument(
        "--profile", help="profile source (default: repository profile/master-profile.yaml)"
    )

    check = commands.add_parser(
        "check", help="run gates, render cv-draft.pdf, and write cv-review.md"
    )
    _common(check)

    finalize = commands.add_parser("finalize", help="promote a passing draft to cv.md/cv.pdf")
    _common(finalize)
    finalize.add_argument(
        "--approve", action="store_true", help="explicitly approve promotion after all gates pass"
    )

    approve = commands.add_parser(
        "approve", help="rerun all gates and promote a passing draft after explicit approval"
    )
    _common(approve)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "start":
            paths = workflow.start(args.application, args.profile, args.force)
            print(f"initialized draft workflow in {paths.application}")
            print(
                f"edit {paths.analysis} and {paths.feedback}, generate/revise {paths.draft}, "
                "then run cv-check"
            )
            return 0
        if args.command == "create":
            folder = new_application.create_from_source(
                args.company,
                args.role,
                args.date,
                args.from_report,
                args.job_id,
                args.job_index,
                args.match,
                args.refresh,
                args.force,
            )
            paths = workflow.start(folder, args.profile, args.force)
            print(f"created application and initialized draft workflow in {paths.application}")
            print(
                f"edit {paths.analysis} and {paths.feedback}, generate/revise {paths.draft}, "
                "then run cv-check"
            )
            return 0
        if args.command == "check":
            result = workflow.check(args.application, args.profile)
            print(f"cv-check: {'PASS' if result.passed else 'FAIL'}")
            for gate in result.gates:
                print(f"  {'PASS' if gate.passed else 'FAIL'} {gate.name}: {gate.detail}")
            print(f"review: {result.paths.review}")
            return 0 if result.passed else 1
        if args.command == "approve":
            result = workflow.finalize(args.application, args.profile, approve=True)
        else:
            result = workflow.finalize(args.application, args.profile, args.approve)
        print(f"finalized {result.paths.final} and {result.paths.final_pdf}")
        print(f"review: {result.paths.review}")
        return 0
    except workflow.WorkflowError as error:
        print(f"cv-workflow: error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

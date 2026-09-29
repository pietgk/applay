#!/usr/bin/env python3
"""List applications whose CV draft needs (re)generating (read-only).

Rule A: an application needs a draft when its application status is ``draft``
(or missing on a legacy record), it is not finalized, and its ``cv-draft.md``
still has scaffold placeholders or ``cv-feedback.md`` is newer than
``cv-draft.md``. Applied, interview, offer, rejected, and withdrawn applications
are excluded. This query never writes. The draft itself is written by an agent
running ``tools/cv-tailor.md`` (see the ``apply-refresh-drafts`` skill).
"""

from __future__ import annotations

import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))

from apply import drafts  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="List CV drafts that need (re)generating (read-only)."
    )
    parser.add_argument(
        "--applications-root",
        default=os.path.join(HERE, "..", "applications"),
        help="Applications directory to scan (default: ./applications)",
    )
    args = parser.parse_args(argv)

    stale = drafts.stale_drafts(args.applications_root)
    if not stale:
        print("All drafts up to date.")
        return 0
    print(f"{len(stale)} draft(s) need attention:")
    for item in stale:
        print(f"  {item.identifier} — {item.reason}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

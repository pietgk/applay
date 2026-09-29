#!/usr/bin/env python3
"""
ats_lint.py — score a CV draft against a job description BEFORE rendering.

Usage:  python3 ats_lint.py job.md cv.md
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))

from apply import ats as core  # noqa: E402

# Preserve the pure helper surface exposed by the original CLI module.
STOP = core.STOP
TECH_HINT = core.TECH_HINT
_clean = core._clean
tokens = core.tokens
phrases = core.phrases
section_map = core.section_map
evaluate = core.evaluate
format_report = core.format_report


def main() -> None:
    if len(sys.argv) != 3:
        print("usage: ats_lint.py job.md cv.md")
        sys.exit(1)
    with open(sys.argv[1], encoding="utf-8") as handle:
        job = handle.read()
    with open(sys.argv[2], encoding="utf-8") as handle:
        cv = handle.read()
    print(format_report(evaluate(job, cv)))


if __name__ == "__main__":
    main()

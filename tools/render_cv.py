#!/usr/bin/env python3
"""
render_cv.py — convert a cv.md to a clean, ATS-safe, auto-fitted 1-page PDF.

Usage:  python3 render_cv.py path/to/cv.md [-o path/to/cv.pdf]
"""

import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))

from apply import rendering as core  # noqa: E402

CSS_PATH = os.path.join(HERE, "..", "templates", "cv.css")
PLACEHOLDER_MARKERS = core.PLACEHOLDER_MARKERS
find_placeholders = core.find_placeholders
md_to_body = core.md_to_body
page_count = core.page_count


def _css_text() -> str:
    with open(CSS_PATH, encoding="utf-8") as handle:
        return handle.read()


def build_html(body_html: str, scale: float) -> str:
    """Retain the original CLI helper signature while using package logic."""
    return core.build_html(body_html, _css_text(), scale)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("md_path")
    parser.add_argument("-o", "--out")
    parser.add_argument("--min-scale", type=float, default=0.82)
    args = parser.parse_args()

    with open(args.md_path, encoding="utf-8") as handle:
        text = handle.read()

    placeholders = find_placeholders(text)
    if placeholders:
        markers = "\n".join(f"  - {marker}" for marker in placeholders)
        raise SystemExit(
            f"refusing to render {args.md_path}: scaffold placeholders remain:\n{markers}\n"
            "Fill cv.md using tools/cv-tailor.md, then render again."
        )

    result = core.render_document(text, _css_text(), args.min_scale)
    out = args.out or os.path.splitext(args.md_path)[0] + ".pdf"
    core.write_pdf(result, out)
    print(f"wrote {out}  ({result.fit_message})")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""CLI adapter for clipboard ingest into the persistent job catalog.

macOS only for clipboard reads (``pbpaste``). The helper never calls a
provider — an agent proposes ``{title, company, location}`` in-conversation
(see ``tools/jobs-ingest.md``); flags or interactive prompts supply the
confirmed fields (ADR-0005).
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))

from apply import ingest as ingest_core  # noqa: E402
from apply import jobs as jobs_core  # noqa: E402

CFG = os.path.join(HERE, "jobs_sources.yaml")
PREFS = os.path.join(HERE, "preferences.yaml")
ROOT = os.path.join(HERE, "..")


def load_yaml(path: str):
    import yaml

    with open(path, encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def read_clipboard() -> str:
    """Read the macOS clipboard. Other OSes are out of scope."""
    if sys.platform != "darwin":
        raise SystemExit(
            "clipboard ingest requires macOS pbpaste; pass --text-file on other systems"
        )
    try:
        completed = subprocess.run(
            ["pbpaste"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise SystemExit(f"failed to read clipboard via pbpaste: {error}") from error
    return completed.stdout


def _prompt(label: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{label}{suffix}: ").strip()
    return value if value else default


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Ingest a pasted job description into the catalog (macOS clipboard)."
    )
    parser.add_argument("--url", default=None, help="Posting URL (provenance only; never fetched)")
    parser.add_argument("--title", default=None, help="Confirmed job title (skips prompt)")
    parser.add_argument("--company", default=None, help="Confirmed company (skips prompt)")
    parser.add_argument("--location", default=None, help="Confirmed location (skips prompt)")
    parser.add_argument(
        "--triage",
        choices=["interested", "open"],
        default="interested",
        help="Initial triage state (default: interested)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Replace an existing ingest for the same URL, writing a .bak",
    )
    parser.add_argument(
        "--text-file",
        default=None,
        help="Read paste from a file instead of the clipboard (testing / non-macOS)",
    )
    args = parser.parse_args(argv)

    if args.text_file:
        with open(args.text_file, encoding="utf-8") as handle:
            text = handle.read()
    else:
        text = read_clipboard()

    policy = load_yaml(PREFS)
    config = load_yaml(CFG)
    min_chars = int((policy.get("ingest") or {}).get("min_chars", ingest_core.DEFAULT_MIN_CHARS))

    try:
        warnings = ingest_core.sanity_check(text, min_chars=min_chars)
    except ingest_core.IngestError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    for warning in warnings:
        print(f"warning: {warning}", file=sys.stderr)

    preview = text.strip().replace("\n", " ")
    if len(preview) > 160:
        preview = preview[:157] + "..."
    print(f"clipboard: {len(text.strip())} chars — {preview}")

    url = args.url if args.url is not None else _prompt("Posting URL (blank allowed)")
    title = args.title if args.title is not None else _prompt("Title")
    company = args.company if args.company is not None else _prompt("Company")
    location = args.location if args.location is not None else _prompt("Location", "")

    try:
        result = ingest_core.ingest(
            ROOT,
            text,
            title=title,
            company=company,
            location=location,
            url=url,
            triage=args.triage,
            force=args.force,
            policy=policy,
            angles=config["angles"],
            min_chars=min_chars,
        )
    except ingest_core.IngestError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    for warning in result.warnings:
        # sanity warnings already printed; skip duplicates from the helper
        if warning in warnings:
            continue
        print(f"warning: {warning}", file=sys.stderr)

    record = result.record
    action = "created" if result.created else ("replaced" if result.backup_path else "unchanged")
    print(
        f"{action} {record['job_id']} — {record['title']} @ {record['company']} "
        f"(triage={record['triage']}, angle={record.get('angle') or '—'}, "
        f"fit={record.get('fit_score', 0)})"
    )
    if result.backup_path:
        print(f"backup: {result.backup_path}")
    print(f"attrs: {jobs_core.fmt_attrs(record.get('attrs') or {})}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

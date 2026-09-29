#!/usr/bin/env python3
"""Validate canonical apply skills and their Codex discovery links."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

import yaml

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
MAX_SKILL_NAME_LENGTH = 64
MAX_DESCRIPTION_LENGTH = 1024
ALLOWED_FRONTMATTER = {"name", "description", "license", "allowed-tools", "metadata"}


def _frontmatter(skill: Path) -> tuple[dict[str, Any] | None, str | None]:
    skill_md = skill / "SKILL.md"
    if not skill_md.is_file():
        return None, "SKILL.md not found"
    content = skill_md.read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
    if match is None:
        return None, "invalid or missing YAML frontmatter"
    try:
        values = yaml.safe_load(match.group(1))
    except yaml.YAMLError as error:
        return None, f"invalid YAML in frontmatter: {error}"
    if not isinstance(values, dict):
        return None, "frontmatter must be a YAML mapping"
    return {str(key): value for key, value in values.items()}, None


def validate_skill(skill: Path) -> str | None:
    """Return an error for an invalid skill, otherwise ``None``."""

    frontmatter, error = _frontmatter(skill)
    if error is not None or frontmatter is None:
        return error

    unexpected = set(frontmatter) - ALLOWED_FRONTMATTER
    if unexpected:
        return f"unexpected frontmatter keys: {', '.join(sorted(unexpected))}"

    name = frontmatter.get("name")
    if not isinstance(name, str) or not name.strip():
        return "name must be a non-empty string"
    name = name.strip()
    if re.fullmatch(r"[a-z0-9-]+", name) is None:
        return "name must use lowercase letters, digits, and hyphens only"
    if name.startswith("-") or name.endswith("-") or "--" in name:
        return "name cannot start/end with a hyphen or contain consecutive hyphens"
    if len(name) > MAX_SKILL_NAME_LENGTH:
        return f"name exceeds {MAX_SKILL_NAME_LENGTH} characters"
    if name != skill.name:
        return f"frontmatter name {name!r} does not match folder {skill.name!r}"

    description = frontmatter.get("description")
    if not isinstance(description, str) or not description.strip():
        return "description must be a non-empty string"
    description = description.strip()
    if "<" in description or ">" in description:
        return "description cannot contain angle brackets"
    if len(description) > MAX_DESCRIPTION_LENGTH:
        return f"description exceeds {MAX_DESCRIPTION_LENGTH} characters"
    return None


def validate_apply_skills(source_root: Path, codex_root: Path) -> list[str]:
    """Validate every canonical apply skill and its Codex symlink."""

    errors: list[str] = []
    skills = sorted(path for path in source_root.glob("apply-*") if path.is_dir())
    if not skills:
        return [f"no apply skills found under {source_root}"]

    for skill in skills:
        error = validate_skill(skill)
        if error is not None:
            errors.append(f"{skill.name}: {error}")
            continue

        codex_skill = codex_root / skill.name
        if not codex_skill.is_symlink():
            errors.append(f"{skill.name}: missing Codex symlink {codex_skill}")
            continue
        try:
            target = codex_skill.resolve(strict=True)
        except OSError as link_error:
            errors.append(f"{skill.name}: broken Codex symlink: {link_error}")
            continue
        if target != skill.resolve():
            errors.append(
                f"{skill.name}: Codex symlink points to {target}, expected {skill.resolve()}"
            )
    return errors


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate apply skills and their .agents/skills discovery links."
    )
    parser.add_argument(
        "--source-root",
        type=Path,
        default=REPO_ROOT / ".claude" / "skills",
        help="canonical skill root (default: .claude/skills)",
    )
    parser.add_argument(
        "--codex-root",
        type=Path,
        default=REPO_ROOT / ".agents" / "skills",
        help="Codex discovery root (default: .agents/skills)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    errors = validate_apply_skills(args.source_root, args.codex_root)
    if errors:
        for error in errors:
            print(f"skills-check: error: {error}", file=sys.stderr)
        return 1

    skills = sorted(path.name for path in args.source_root.glob("apply-*") if path.is_dir())
    for name in skills:
        print(f"{name}: valid and available to Codex")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

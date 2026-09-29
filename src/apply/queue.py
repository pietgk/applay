"""App-wide command queue: UI enqueues; the agent drains (ADR-0008).

The UI writes a ``queued`` request file under top-level ``queue/`` and nothing
else. Lifecycle beyond ``queued`` (claim → ``running`` → ``done`` | ``failed``)
belongs to the drain skill and is out of scope here.
"""

from __future__ import annotations

import datetime
import os
import re
import secrets
from pathlib import Path
from typing import Any

import yaml

#: Closed command-type enum. Seed values are non-binding; grow deliberately.
COMMAND_TYPES: tuple[str, ...] = (
    "capture-email",
    "refresh-draft",
    "re-check",
    "fetch-jobs",
    "refresh-drafts",
)

#: Types that target an Application folder (``app: <folder>``).
APPLICATION_COMMAND_TYPES: frozenset[str] = frozenset(
    {"capture-email", "refresh-draft", "re-check"}
)

#: Types that target the Jobs catalog as a whole (no per-job id).
JOBS_CATALOG_COMMAND_TYPES: frozenset[str] = frozenset({"fetch-jobs", "refresh-drafts"})

_APP_TARGET_RE = re.compile(r"^app:\s*(.+)$")
_JOB_TARGET_RE = re.compile(r"^job:\s*(.+)$")
_STATE_QUEUED = "queued"
_TARGET_NONE = "none"
_TARGET_APP = "app"
_TARGET_JOB = "job"


class QueueError(ValueError):
    """Raised when a queue request cannot be formed or written."""


def queue_dir(repo_root: str | Path) -> Path:
    """Return the app-wide ``queue/`` directory under ``repo_root``."""
    return Path(repo_root).expanduser().resolve() / "queue"


def app_target(identifier: str) -> str:
    """Format an Application-folder target string."""
    folder = str(identifier).strip()
    if not folder:
        raise QueueError("application target requires a non-empty folder name")
    return f"app: {folder}"


def job_target(job_id: str) -> str:
    """Format a catalog-job target string."""
    value = str(job_id).strip()
    if not value:
        raise QueueError("job target requires a non-empty job id")
    return f"job: {value}"


def normalize_target(target: str | None) -> str | None:
    """Normalize a target to ``app: …``, ``job: …``, or ``None`` (none)."""
    if target is None:
        return None
    text = str(target).strip()
    if not text or text.lower() == "none":
        return None
    app_match = _APP_TARGET_RE.match(text)
    if app_match:
        return app_target(app_match.group(1))
    job_match = _JOB_TARGET_RE.match(text)
    if job_match:
        return job_target(job_match.group(1))
    raise QueueError(
        f"unknown queue target {target!r}; expected 'app: <folder>', 'job: <id>', or none"
    )


def _target_kind(target: str | None) -> str:
    if target is None:
        return _TARGET_NONE
    if target.startswith("app: "):
        return _TARGET_APP
    if target.startswith("job: "):
        return _TARGET_JOB
    raise QueueError(
        f"unknown queue target {target!r}; expected 'app: <folder>', 'job: <id>', or none"
    )


def _validate_command_target(command_type: str, target: str | None) -> None:
    kind = _target_kind(target)
    if command_type in APPLICATION_COMMAND_TYPES and kind != _TARGET_APP:
        raise QueueError(f"queue command {command_type!r} requires an application target")
    if command_type in JOBS_CATALOG_COMMAND_TYPES and kind != _TARGET_NONE:
        raise QueueError(f"queue command {command_type!r} does not accept a target")


def enqueue(
    repo_root: str | Path,
    command_type: str,
    *,
    target: str | None = None,
    args: dict[str, Any] | None = None,
    when: datetime.datetime | None = None,
) -> Path:
    """Write one ``state: queued`` request file under top-level ``queue/``.

    Returns the path of the new request file. Does not touch application
    ``meta.yaml``, ``events:``, or any other path outside ``queue/``.
    """
    if command_type not in COMMAND_TYPES:
        raise QueueError(
            f"unknown command type {command_type!r}; expected one of {', '.join(COMMAND_TYPES)}"
        )
    normalized = normalize_target(target)
    _validate_command_target(command_type, normalized)
    if args is not None and not isinstance(args, dict):
        raise QueueError("queue args must be a mapping when provided")

    stamped = when or datetime.datetime.now(datetime.UTC)
    if stamped.tzinfo is None:
        stamped = stamped.replace(tzinfo=datetime.UTC)
    else:
        stamped = stamped.astimezone(datetime.UTC)
    stamp = stamped.strftime("%Y%m%dT%H%M%SZ")
    token = secrets.token_hex(4)
    filename = f"{stamp}-{command_type}-{token}.yaml"

    payload: dict[str, Any] = {
        "type": command_type,
        "target": normalized,
        "state": _STATE_QUEUED,
    }
    if args:
        payload["args"] = args

    directory = queue_dir(repo_root)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / filename
    if path.exists():
        raise QueueError(f"queue request already exists: {path.name}")

    text = yaml.safe_dump(payload, sort_keys=False, allow_unicode=True, width=100)
    temporary = f"{path}.tmp"
    with open(temporary, "w", encoding="utf-8") as handle:
        handle.write(text)
    os.replace(temporary, path)
    return path

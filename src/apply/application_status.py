"""Deterministic lifecycle updates for application metadata."""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from pathlib import Path

from apply import applications


class ApplicationStatusError(ValueError):
    """Raised when an application status transition is invalid or unsafe."""


@dataclass(frozen=True)
class AppliedUpdate:
    application: Path
    date_applied: str
    changed: bool


def mark_applied(
    application: str | Path,
    applied_on: str | None = None,
    *,
    today: datetime.date | None = None,
) -> AppliedUpdate:
    """Record the human-confirmed ``draft -> applied`` transition.

    Repeating the transition is safe: an existing application date is preserved.
    Supplying a different explicit date is rejected instead of silently rewriting history.
    """

    application_path = Path(application)
    if not application_path.is_dir():
        raise ApplicationStatusError(f"application folder does not exist: {application_path}")

    metadata_path = application_path / "meta.yaml"
    try:
        result = applications.confirm_applied(
            str(metadata_path),
            applied_on,
            today=today,
        )
    except (applications.MetaEventError, OSError) as error:
        raise ApplicationStatusError(str(error)) from error
    return AppliedUpdate(application_path, result.date_applied, result.changed)

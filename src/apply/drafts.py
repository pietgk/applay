"""Which application CV drafts need (re)generating — rule A, read-only.

An application needs a draft when its application ``status`` is ``draft`` (or
missing on a legacy record), it is **not finalized**, and either its
``cv-draft.md`` still holds scaffold placeholders (never drafted) or its
``cv-feedback.md`` is newer than ``cv-draft.md`` (human left feedback since the
last generation). Applied, interview, offer, rejected, and withdrawn
applications are never drafted. "Finalized" means ``workflow_state ==
"finalized"`` *or* a promoted, placeholder-free ``cv.md`` already exists — the
latter catches older applications completed before ``workflow_state`` was
recorded, so a finished CV is never re-drafted. The determination reuses
``workflow.scaffold_placeholders`` and ordinary filesystem mtimes, so it holds
no new state of its own.

This module only *reports*. The draft itself is written by an agent running
``tools/cv-tailor.md`` (see the ``apply-refresh-drafts`` skill); nothing here
calls a model or mutates an application.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import applications, workflow

FINALIZED_STATE = "finalized"
FINAL_CV_NAME = "cv.md"
DRAFTABLE_APPLICATION_STATUSES = {"", "draft"}


@dataclass(frozen=True)
class StaleDraft:
    identifier: str
    reason: str


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _has_final_cv(application: Path) -> bool:
    """True when a promoted, placeholder-free ``cv.md`` already exists."""
    cv_path = application / FINAL_CV_NAME
    if not cv_path.is_file():
        return False
    try:
        text = cv_path.read_text(encoding="utf-8")
    except OSError:
        return False
    return not workflow.scaffold_placeholders(text)


def draft_status(application_dir: str | Path) -> StaleDraft | None:
    """Return a ``StaleDraft`` when this application needs a (re)draft, else None."""
    application = Path(application_dir)
    meta = applications.read_meta(str(application / "meta.yaml"))
    application_status = str(meta.get("status", "")).strip().lower()
    if application_status not in DRAFTABLE_APPLICATION_STATUSES:
        return None
    if str(meta.get("workflow_state", "")) == FINALIZED_STATE:
        return None
    if _has_final_cv(application):
        return None
    draft_path = application / workflow.DRAFT_NAME
    feedback_path = application / workflow.FEEDBACK_NAME
    try:
        draft_text = draft_path.read_text(encoding="utf-8")
    except OSError:
        draft_text = ""
    if workflow.scaffold_placeholders(draft_text):
        return StaleDraft(application.name, "needs first draft")
    if feedback_path.is_file() and _mtime(feedback_path) > _mtime(draft_path):
        return StaleDraft(application.name, "new feedback since last draft")
    return None


def stale_drafts(applications_root: str | Path) -> list[StaleDraft]:
    """List every application under ``applications_root`` that needs a (re)draft."""
    root = Path(applications_root)
    results: list[StaleDraft] = []
    if not root.is_dir():
        return results
    for entry in sorted(root.iterdir()):
        if not entry.is_dir() or not (entry / "meta.yaml").is_file():
            continue
        status = draft_status(entry)
        if status is not None:
            results.append(status)
    return results

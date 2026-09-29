"""Clipboard ingest — admit a manually pasted posting into the job catalog.

The deterministic helper never calls a provider. An agent may propose
``{title, company, location}`` in-conversation (cv-tailor pattern); the human
confirms or corrects before anything is written (ADR-0005). Clipboard and
prompt I/O live in the thin CLI wrapper.
"""

from __future__ import annotations

import datetime
import re
import shutil
from dataclasses import dataclass, field
from typing import Any

from . import catalog, jobs

DEFAULT_MIN_CHARS = 200

# Soft signal that pasted text looks like a job posting. Missing these only
# warns — the human may still ingest after confirming fields.
_POSTING_WORDS = (
    "responsibilit",
    "requirement",
    "qualification",
    "experience",
    "about the role",
    "about the job",
    "we are looking",
    "we're looking",
    "you will",
    "you'll",
    "apply",
    "salary",
    "benefits",
    "what you'll do",
    "what you will do",
    "the role",
    "job description",
    "position",
)

_BARE_URL = re.compile(r"^https?://\S+$", re.IGNORECASE)


class IngestError(ValueError):
    """Hard rejection of clipboard text before any catalog write."""


@dataclass
class IngestResult:
    """Outcome of one ingest write into the catalog."""

    record: dict[str, Any]
    warnings: list[str] = field(default_factory=list)
    created: bool = True
    backup_path: str | None = None


def sanity_check(text: str, *, min_chars: int = DEFAULT_MIN_CHARS) -> list[str]:
    """Validate pasted text. Hard-rejects empty / short / bare URL; may warn."""
    stripped = text.strip()
    if not stripped:
        raise IngestError("clipboard is empty")
    if _BARE_URL.fullmatch(stripped):
        raise IngestError("clipboard holds a bare URL; paste the job description instead")
    if len(stripped) < min_chars:
        raise IngestError(
            f"clipboard text is too short ({len(stripped)} chars; need at least {min_chars})"
        )
    lower = stripped.lower()
    if not any(word in lower for word in _POSTING_WORDS):
        return [
            "pasted text lacks common posting words "
            "(responsibilities, requirements, experience, …); continuing anyway"
        ]
    return []


def ingest(
    repo_root: str,
    text: str,
    *,
    title: str,
    company: str,
    location: str = "",
    url: str = "",
    triage: str = "interested",
    force: bool = False,
    policy: dict[str, Any],
    angles: dict[str, Any],
    min_chars: int = DEFAULT_MIN_CHARS,
    ingested_at: str | None = None,
) -> IngestResult:
    """Admit a confirmed paste into the catalog. Gates warn; they never drop."""
    if triage not in catalog.TRIAGE_STATES:
        raise IngestError(
            f"unknown triage state {triage!r}; expected one of {catalog.TRIAGE_STATES}"
        )
    if not title.strip() or not company.strip():
        raise IngestError("title and company are required")

    warnings = list(sanity_check(text, min_chars=min_chars))
    paste = text  # retain verbatim, including leading/trailing whitespace
    if ingested_at is None:
        ingested_at = datetime.datetime.now(datetime.UTC).isoformat()

    job: dict[str, Any] = {
        "source": "ingest",
        "title": title.strip(),
        "company": company.strip(),
        "location": location.strip(),
        "url": url.strip(),
        "source_url": url.strip(),
        "desc": paste,
        "description_source": "manual-paste",
    }
    job_id = jobs.stable_job_id(job)

    existing = catalog.load_record(repo_root, job_id)
    backup_path: str | None = None
    if existing is not None and not force:
        # Idempotent re-ingest: return the stored record unchanged.
        return IngestResult(
            record=existing,
            warnings=warnings + ["catalog already has this ingest id; pass --force to replace"],
            created=False,
        )
    if existing is not None and force:
        path = catalog.record_path(repo_root, job_id)
        backup_path = f"{path}.bak"
        shutil.copy2(path, backup_path)

    attrs = jobs.extract(job, policy)
    keep, reason = jobs.location_verdict(attrs)
    if not keep:
        warnings.append(f"location/timezone gate would drop ({reason}); admitting anyway")

    classified = jobs.classify_angle(job, angles)
    if classified is None:
        warnings.append("angle weak-floor gate would drop (no qualifying angle); admitting anyway")
        angle = ""
        fit_score: int | float = 0
        fit_breakdown: dict[str, Any] = {}
        hits: list[str] = []
    else:
        angle = classified["angle"]
        fit_score = classified["fit_score"]
        fit_breakdown = classified["fit_breakdown"]
        hits = classified["hits"]

    weights = policy["weights"]
    score = jobs.pref_score(
        attrs,
        weights,
        policy["pay"],
        posted="",
        first_seen=ingested_at,
        now=ingested_at,
    )

    job.update(
        {
            "job_id": job_id,
            "attrs": attrs,
            "score": score,
            "angle": angle,
            "fit_score": fit_score,
            "fit_breakdown": fit_breakdown,
            "hits": hits,
            "raw_paste": paste,
            "ingested_at": ingested_at,
            "parsed_by": "agent",
            "parse_confirmed": True,
            "triage": triage,
            "apply_url": "",
            "listing_url": "",
            "detail_url": "",
            "posted": "",
            "deadline": "",
            "source_id": "",
            "source_ref": "",
            "source_queries": [],
            "hn_thread_id": "",
        }
    )

    record = catalog.record_from_job(job, ingested_at)
    # Preserve lifecycle + triage across forced re-ingest; --force replaces the
    # paste and confirmed fields, not the human's triage decision.
    if existing is not None:
        record["first_seen"] = existing["first_seen"]
        record["triage"] = existing["triage"]
        record["skip_reason"] = existing.get("skip_reason", "")
        record["application"] = existing.get("application", "")

    catalog.put_record(repo_root, record)
    return IngestResult(
        record=record,
        warnings=warnings,
        created=existing is None,
        backup_path=backup_path,
    )

"""Persistent job catalog — the source of truth for every admitted job.

One JSON record per job lives under ``data/jobs/by-id/`` (gitignored,
file-based per ADR-0001) plus a thin ``index.json`` for cheap scans.  Fetches
upsert into the catalog; lifecycle dates and triage decisions survive across
runs.  The record shape carries an explicit ``schema_version`` per ADR-0007.

Cross-source duplicates are clustered (not collapsed) by normalized employer
apply URL: one file per source ``job_id``, mates share a derived
``cluster_id``, and views pick a display winner without merging fields back.
"""

import datetime
import hashlib
import json
import os
import re
from typing import Any

from . import jobs

SCHEMA_VERSION = 3
TRIAGE_STATES = ("open", "interested", "skipped", "applied")
STALE_AFTER_DAYS = 30
CLOSING_SOON_DAYS = 14

# Fields recomputed from the latest advert text on every fetch hit.
_RECOMPUTED_FIELDS = ("score", "attrs", "hits", "angle", "fit_score", "fit_breakdown")
# Fields where the newer non-empty value wins.
_NEWER_NON_EMPTY_FIELDS = (
    "company",
    "title",
    "location",
    "url",
    "apply_url",
    "listing_url",
    "detail_url",
    "hn_thread_id",
)


def jobs_dir(repo_root: str) -> str:
    return os.path.join(repo_root, "data", "jobs")


def _index_path(repo_root: str) -> str:
    return os.path.join(jobs_dir(repo_root), "index.json")


def watermark_path(repo_root: str) -> str:
    return os.path.join(jobs_dir(repo_root), "last_fetch_at")


def load_watermark(repo_root: str) -> str:
    path = watermark_path(repo_root)
    if not os.path.exists(path):
        return ""
    with open(path, encoding="utf-8") as handle:
        return handle.read().strip()


def write_watermark(repo_root: str, retrieved_at: str) -> None:
    """Persist the fetch watermark (ISO timestamp) after a successful run."""
    os.makedirs(jobs_dir(repo_root), exist_ok=True)
    with open(watermark_path(repo_root), "w", encoding="utf-8") as handle:
        handle.write(retrieved_at)


def record_path(repo_root: str, job_id: str) -> str:
    """Map a job id onto a filesystem-safe per-job record path."""
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", job_id).strip("-.")
    digest = hashlib.sha1(job_id.encode("utf-8")).hexdigest()[:8]
    return os.path.join(jobs_dir(repo_root), "by-id", f"{slug}-{digest}.json")


def load_record(repo_root: str, job_id: str) -> dict[str, Any] | None:
    path = record_path(repo_root, job_id)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def load_records(repo_root: str) -> list[dict[str, Any]]:
    """Return every catalog record, ordered by job id for determinism."""
    by_id = os.path.join(jobs_dir(repo_root), "by-id")
    if not os.path.isdir(by_id):
        return []
    records = []
    for name in os.listdir(by_id):
        if name.endswith(".json"):
            with open(os.path.join(by_id, name), encoding="utf-8") as handle:
                records.append(json.load(handle))
    return sorted(records, key=lambda record: record["job_id"])


def _write_record(repo_root: str, record: dict[str, Any]) -> None:
    # Central write chokepoint owns the schema stamp (ADR-0007: stamp v3 on write).
    record["schema_version"] = SCHEMA_VERSION
    path = record_path(repo_root, record["job_id"])
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(record, handle, ensure_ascii=False, indent=1)


def _write_index(repo_root: str, records: list[dict[str, Any]]) -> None:
    entries = {
        record["job_id"]: {
            "file": os.path.relpath(record_path(repo_root, record["job_id"]), jobs_dir(repo_root)),
            "company": record.get("company", ""),
            "title": record.get("title", ""),
            "triage": record["triage"],
            "first_seen": record["first_seen"],
            "last_seen": record["last_seen"],
            "score": record.get("score", 0),
            "angle": record.get("angle", ""),
            "fit_score": record.get("fit_score", 0),
            "cluster_id": record.get("cluster_id", ""),
        }
        for record in records
    }
    os.makedirs(jobs_dir(repo_root), exist_ok=True)
    with open(_index_path(repo_root), "w", encoding="utf-8") as handle:
        json.dump(
            {"schema_version": SCHEMA_VERSION, "jobs": entries},
            handle,
            ensure_ascii=False,
            indent=1,
        )


def save_records(repo_root: str, records: list[dict[str, Any]]) -> None:
    """Persist a full set of catalog records and refresh the index."""
    for record in records:
        _write_record(repo_root, record)
    _write_index(repo_root, records)


def cluster_id_for_urls(urls: list[str] | tuple[str, ...] | list[Any]) -> str:
    """Derive ``cluster_id`` from the first eligible normalized apply URL."""
    for url in urls:
        normalized = jobs.normalize_apply_url(str(url or ""))
        if normalized:
            return hashlib.sha1(normalized.encode("utf-8")).hexdigest()
    return ""


def cluster_urls_for_record(record: dict[str, Any]) -> list[str]:
    """Candidate apply URLs in preference order for clustering."""
    return [
        str(record.get("apply_url") or ""),
        str(record.get("url") or ""),
        str(record.get("source_url") or ""),
    ]


def _mates_for_cluster(
    repo_root: str, cluster_id: str, *, exclude_job_id: str = ""
) -> list[dict[str, Any]]:
    return [
        mate
        for mate in load_records(repo_root)
        if mate.get("cluster_id") == cluster_id
        and (not exclude_job_id or mate.get("job_id") != exclude_job_id)
    ]


def _adopt_cluster_triage(record: dict[str, Any], mates: list[dict[str, Any]]) -> None:
    """Joining a cluster adopts an existing mate's triage; never rewrites mates."""
    if not mates:
        return
    mate = mates[0]
    record["triage"] = mate.get("triage", "open")
    record["skip_reason"] = mate.get("skip_reason", "") if mate.get("triage") == "skipped" else ""
    record["application"] = mate.get("application", "")
    # Acknowledgement is cluster-wide: a new mate inherits it so the cluster
    # cannot resurface as New once any mate has been acknowledged.
    acknowledged = next(
        (mate.get("acknowledged_at", "") for mate in mates if mate.get("acknowledged_at")), ""
    )
    if acknowledged:
        record["acknowledged_at"] = acknowledged


def assign_cluster(repo_root: str, record: dict[str, Any]) -> dict[str, Any]:
    """Recompute ``cluster_id`` and adopt mate triage when newly joining."""
    stored = load_record(repo_root, record["job_id"])
    previous = stored.get("cluster_id", "") if stored is not None else record.get("cluster_id", "")
    cluster_id = cluster_id_for_urls(cluster_urls_for_record(record))
    record["cluster_id"] = cluster_id
    if not cluster_id:
        return record
    mates = _mates_for_cluster(repo_root, cluster_id, exclude_job_id=record.get("job_id", ""))
    # Adopt only when joining (or rejoining) a cluster that already has mates.
    if mates and previous != cluster_id:
        _adopt_cluster_triage(record, mates)
    return record


def pick_display_winner(mates: list[dict[str, Any]]) -> dict[str, Any]:
    """Richest description → newest last_seen → stable job_id order."""
    ordered = sorted(mates, key=lambda record: record["job_id"])
    ordered.sort(key=lambda record: record.get("last_seen") or "", reverse=True)
    ordered.sort(key=lambda record: len(record.get("description") or ""), reverse=True)
    return ordered[0]


def view_record_for_cluster(mates: list[dict[str, Any]]) -> dict[str, Any]:
    """Build a view-only row for one cluster (never written back to the catalog).

    Ranking chrome uses ``cluster_fit_score`` (max across mates). The winner's own
    ``fit_score`` / angle / breakdown stay intact for detail and scaffolding.
    When a manual-paste mate supplies the display description, its provenance
    (``description_source`` + paste fields) travels with the text so the view
    never labels paste content as another source (ADR-0003).
    """
    winner = pick_display_winner(mates)
    view = dict(winner)
    paste = next(
        (mate for mate in mates if mate.get("description_source") == "manual-paste"),
        None,
    )
    if paste is not None:
        view["description"] = paste.get("description", "")
        view["description_source"] = "manual-paste"
        view["source_url"] = paste.get("source_url", "")
        view["raw_paste"] = paste.get("raw_paste", "")
    view["cluster_fit_score"] = max(mate.get("fit_score") or 0 for mate in mates)
    return view


def rank_fit_score(record: dict[str, Any]) -> int | float:
    """Fit used for ranking chrome: cluster max when present, else the record's own.

    Kept as ``int | float`` so half-weight RN cues survive lexicographic ranking.
    """
    if "cluster_fit_score" in record:
        return record.get("cluster_fit_score") or 0
    return record.get("fit_score") or 0


def cluster_view_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse clustered mates to one view-only row; singletons pass through."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    singles: list[dict[str, Any]] = []
    for record in records:
        cluster_id = record.get("cluster_id") or ""
        if not cluster_id:
            singles.append(record)
            continue
        grouped.setdefault(cluster_id, []).append(record)
    views = list(singles)
    for mates in grouped.values():
        views.append(view_record_for_cluster(mates))
    # Singletons get an explicit cluster_fit_score equal to their own fit for
    # uniform ranking chrome in reports and the UI.
    for index, record in enumerate(views):
        if "cluster_fit_score" not in record:
            views[index] = dict(record)
            views[index]["cluster_fit_score"] = record.get("fit_score") or 0
    return views


def resolve_display_record(repo_root: str, job_id: str) -> dict[str, Any] | None:
    """Load a record, resolving clustered ids to the view-only display winner."""
    record = load_record(repo_root, job_id)
    if record is None:
        return None
    cluster_id = record.get("cluster_id") or ""
    if not cluster_id:
        return record
    mates = _mates_for_cluster(repo_root, cluster_id)
    if not mates:
        return record
    return view_record_for_cluster(mates)


def record_from_job(job: dict[str, Any], retrieved_at: str) -> dict[str, Any]:
    """Normalize one scored job onto the persistent catalog record shape."""
    return {
        "schema_version": SCHEMA_VERSION,
        "job_id": job["job_id"],
        "company": job.get("company", ""),
        "title": job.get("title", ""),
        "location": job.get("location", ""),
        "url": job.get("url", ""),
        "apply_url": job.get("apply_url", ""),
        "listing_url": job.get("listing_url", ""),
        "description": job.get("desc", ""),
        "posted": job.get("posted", ""),
        "deadline": job.get("deadline", ""),
        "source": job.get("source", ""),
        "source_id": job.get("source_id", ""),
        "source_ref": job.get("source_ref", ""),
        "source_queries": sorted(set(job.get("source_queries", []))),
        "description_source": job.get("description_source", ""),
        "detail_url": job.get("detail_url", ""),
        "hn_thread_id": job.get("hn_thread_id", ""),
        "source_url": job.get("source_url", ""),
        "raw_paste": job.get("raw_paste", ""),
        "ingested_at": job.get("ingested_at", ""),
        "parsed_by": job.get("parsed_by", ""),
        "parse_confirmed": job.get("parse_confirmed", False),
        "retrieved_at": retrieved_at,
        "first_seen": retrieved_at,
        "last_seen": retrieved_at,
        "score": job.get("score", 0),
        "angle": job.get("angle", ""),
        "fit_score": job.get("fit_score", 0),
        "fit_breakdown": job.get("fit_breakdown", {}),
        "attrs": job.get("attrs", {}),
        "hits": job.get("hits", []),
        "triage": job.get("triage", "open"),
        "skip_reason": job.get("skip_reason", ""),
        "application": job.get("application", ""),
        "acknowledged_at": job.get("acknowledged_at", ""),
        "cluster_id": "",
    }


def put_record(repo_root: str, record: dict[str, Any]) -> None:
    """Persist one catalog record and refresh the index."""
    assign_cluster(repo_root, record)
    _write_record(repo_root, record)
    _write_index(repo_root, load_records(repo_root))


def _merge(stored: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    """Fold a fresh fetch hit into a stored record, preserving its lifecycle
    dates and triage decisions."""
    previous_retrieved_at = stored.get("retrieved_at", "")
    stored["last_seen"] = incoming["last_seen"]
    stored["retrieved_at"] = incoming["retrieved_at"]
    for field in _NEWER_NON_EMPTY_FIELDS:
        if incoming.get(field):
            stored[field] = incoming[field]
    stored["posted"] = jobs.prefer_earlier_date(
        stored.get("posted", ""), incoming.get("posted", "")
    )
    # Deadline: keep the first structured value; never invent or scrape prose.
    if not stored.get("deadline") and incoming.get("deadline"):
        stored["deadline"] = incoming["deadline"]
    # Manual-paste descriptions are authoritative: fetches never overwrite them.
    # Otherwise prefer newer non-empty; longer description wins only on true ties
    # (same retrieved_at as the value stored before this merge).
    if stored.get("description_source") != "manual-paste" and incoming.get("description"):
        incoming_desc = incoming["description"]
        stored_desc = stored.get("description", "")
        same_moment = (incoming.get("retrieved_at") or "") == (previous_retrieved_at or "")
        if not stored_desc:
            stored["description"] = incoming_desc
            stored["description_source"] = incoming["description_source"]
        elif not same_moment:
            stored["description"] = incoming_desc
            stored["description_source"] = incoming["description_source"]
        elif len(incoming_desc) > len(stored_desc):
            stored["description"] = incoming_desc
            stored["description_source"] = incoming["description_source"]
    stored["source_queries"] = sorted(
        set(stored.get("source_queries", [])) | set(incoming["source_queries"])
    )
    for field in _RECOMPUTED_FIELDS:
        stored[field] = incoming[field]
    stored["schema_version"] = SCHEMA_VERSION
    return stored


def discard_incompatible_records(repo_root: str) -> int:
    """Remove catalog files older than schema v2 (ADR-0007: discard, no migrate)."""
    removed = 0
    for record in list(load_records(repo_root)):
        version = int(record.get("schema_version") or 1)
        if version < 2:
            path = record_path(repo_root, record["job_id"])
            if os.path.exists(path):
                os.remove(path)
                removed += 1
    if removed:
        _write_index(repo_root, load_records(repo_root))
    return removed


def is_stale(record: dict[str, Any], now: str, *, days: int = STALE_AFTER_DAYS) -> bool:
    """True when ``last_seen`` is older than ``days`` relative to ``now``."""
    last_seen = jobs.parse_job_date(record.get("last_seen", ""))
    current = jobs.parse_job_date(now)
    if last_seen is None or current is None:
        return False
    return (current - last_seen).days >= days


def freshness_label(record: dict[str, Any], watermark: str) -> str:
    """Derived New/Updated/Unchanged/Stale label — never a triage status.

    Acknowledgement clears New without inventing a triage status.
    """
    if is_stale(record, watermark):
        return "Stale"
    if record.get("first_seen") == watermark and not record.get("acknowledged_at"):
        return "New"
    if record.get("last_seen") == watermark and record.get("first_seen") != watermark:
        return "Updated"
    return "Unchanged"


def acknowledge(repo_root: str, job_id: str, *, at: str) -> dict[str, Any]:
    """Persist acknowledgement so New clears; propagates cluster-wide."""
    record = load_record(repo_root, job_id)
    if record is None:
        raise ValueError(f"no catalog record for job id {job_id!r}")
    cluster_id = record.get("cluster_id") or ""
    targets = _mates_for_cluster(repo_root, cluster_id) if cluster_id else [record]
    for target in targets:
        if target.get("acknowledged_at"):
            continue
        target["acknowledged_at"] = at
        _write_record(repo_root, target)
    _write_index(repo_root, load_records(repo_root))
    return load_record(repo_root, job_id) or record


def days_until_deadline(record: dict[str, Any], now: str) -> int | None:
    """Whole days until a structured deadline, or None when unknown/unparseable."""
    deadline = jobs.parse_job_date(record.get("deadline", ""))
    current = jobs.parse_job_date(now)
    if deadline is None or current is None:
        return None
    return (deadline.date() - current.date()).days


def is_closing_soon(
    record: dict[str, Any], now: str, *, within_days: int = CLOSING_SOON_DAYS
) -> bool:
    """True when a structured deadline falls in ``[0, within_days]`` from ``now``."""
    remaining = days_until_deadline(record, now)
    return remaining is not None and 0 <= remaining <= within_days


def set_triage(
    repo_root: str,
    job_id: str,
    triage: str,
    *,
    skip_reason: str = "",
    application: str = "",
    at: str | None = None,
) -> dict[str, Any]:
    """Record a triage decision; fetches never overwrite what is set here.

    Triage writes propagate to every current cluster mate (status, skip reason,
    application link). Triaging also acknowledges the job so its derived New
    label clears (#14: New clears once a job is triaged/acknowledged).
    """
    if triage not in TRIAGE_STATES:
        raise ValueError(f"unknown triage state {triage!r}; expected one of {TRIAGE_STATES}")
    if triage == "skipped" and not skip_reason:
        raise ValueError("triage 'skipped' requires a skip_reason")
    record = load_record(repo_root, job_id)
    if record is None:
        raise ValueError(f"no catalog record for job id {job_id!r}")
    acknowledged_at = at or datetime.datetime.now(datetime.UTC).isoformat()
    cluster_id = record.get("cluster_id") or ""
    targets = _mates_for_cluster(repo_root, cluster_id) if cluster_id else [record]
    for target in targets:
        target["triage"] = triage
        target["skip_reason"] = skip_reason if triage == "skipped" else ""
        if application:
            target["application"] = application
        if not target.get("acknowledged_at"):
            target["acknowledged_at"] = acknowledged_at
        _write_record(repo_root, target)
    _write_index(repo_root, load_records(repo_root))
    return load_record(repo_root, job_id) or record


def upsert_fetch(
    repo_root: str, jobs: list[dict[str, Any]], retrieved_at: str
) -> list[dict[str, Any]]:
    """Merge one fetch's admitted jobs into the catalog and refresh the index."""
    discard_incompatible_records(repo_root)
    for job in jobs:
        incoming = record_from_job(job, retrieved_at)
        stored = load_record(repo_root, job["job_id"])
        record = _merge(stored, incoming) if stored else incoming
        record["schema_version"] = SCHEMA_VERSION
        assign_cluster(repo_root, record)
        _write_record(repo_root, record)
    records = load_records(repo_root)
    _write_index(repo_root, records)
    return records

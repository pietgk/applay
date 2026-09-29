"""Fetch-run orchestration behind an injected transport.

The command-line adapter owns HTTP requests, TLS trust, and argument parsing.
This module owns the rest of a fetch run — source dispatch, dedupe, scoring,
and report writing — so recorded payloads can drive a complete run offline.
"""

import datetime
import json
import os
import re
import urllib.error
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from . import catalog, jobs

# A transport takes a URL and returns the decoded JSON payload.
Transport = Callable[[str], Any]


def greenhouse(get: Transport, token: str, company: str) -> list[dict[str, Any]]:
    payload = get(f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true")
    return jobs.greenhouse_jobs(payload, token, company)


def lever(get: Transport, token: str, company: str) -> list[dict[str, Any]]:
    payload = get(f"https://api.lever.co/v0/postings/{token}?mode=json")
    return jobs.lever_jobs(payload, token, company)


def ashby(get: Transport, token: str, company: str) -> list[dict[str, Any]]:
    payload = get(f"https://api.ashbyhq.com/posting-api/job-board/{token}?includeCompensation=true")
    return jobs.ashby_jobs(payload, token, company)


def jobtech_search(get: Transport, spec: dict[str, Any]) -> list[dict[str, Any]]:
    params = {"q": spec.get("q", ""), "limit": min(int(spec.get("limit", 50)), 100)}
    if spec.get("remote"):
        params["remote"] = "true"
    url = "https://jobsearch.api.jobtechdev.se/search?" + urllib.parse.urlencode(params)
    return jobs.jobtech_jobs(get(url), spec)


def jobtech_ad(get: Transport, ad_id: str) -> dict[str, Any]:
    ad_id = str(ad_id)
    if not re.fullmatch(r"\d+", ad_id):
        raise ValueError(f"invalid JobTech ad ID: {ad_id!r}")
    return jobs.jobtech_detail(get(f"https://jobsearch.api.jobtechdev.se/ad/{ad_id}"), ad_id)


def remotive_search(get: Transport, spec: dict[str, Any]) -> list[dict[str, Any]]:
    category = str(spec.get("category", "") or "")
    if not category:
        raise ValueError("remotive search requires a category")
    params = urllib.parse.urlencode({"category": category})
    url = f"https://remotive.com/api/remote-jobs?{params}"
    return jobs.remotive_jobs(get(url), spec)


def _hn_newest_thread_id(get: Transport) -> str:
    params = urllib.parse.urlencode(
        {
            "tags": "story,author_whoishiring",
            "query": "Ask HN: Who is hiring",
            "hitsPerPage": 5,
        }
    )
    payload = get(f"https://hn.algolia.com/api/v1/search_by_date?{params}")
    for hit in payload.get("hits") or []:
        title = str(hit.get("title") or "")
        if "Who is hiring?" not in title:
            continue
        thread_id = str(hit.get("objectID") or "")
        if thread_id:
            return thread_id
    raise ValueError("no Ask HN: Who is hiring? thread found")


def hn_search(get: Transport, spec: dict[str, Any]) -> tuple[list[dict[str, Any]], int]:
    """Fetch top-level Who's Hiring comments; return (jobs, parse_failures)."""
    thread_id = spec.get("thread_id")
    if thread_id in (None, "", "null"):
        thread_id = _hn_newest_thread_id(get)
    else:
        thread_id = str(thread_id)
    payload = get(f"https://hn.algolia.com/api/v1/items/{thread_id}")
    return jobs.hn_jobs(payload, thread_id)


SEARCH_FETCHERS = {
    "jobtech": jobtech_search,
    "remotive": remotive_search,
    "hn": hn_search,
}
BOARD_FETCHERS = {"greenhouse": greenhouse, "lever": lever, "ashby": ashby}

# The report JSONL row shape — the transitional shim that keeps report-based
# scaffolding (`new --from-report`) working until it is catalog-native.
REPORT_FIELDS = (
    "job_id",
    "company",
    "title",
    "location",
    "url",
    "apply_url",
    "listing_url",
    "description",
    "posted",
    "deadline",
    "source",
    "source_id",
    "source_ref",
    "source_query",
    "source_queries",
    "description_source",
    "detail_url",
    "retrieved_at",
    "score",
    "angle",
    "fit_score",
    "fit_breakdown",
    "attrs",
    "hits",
    "cluster_id",
)


@dataclass
class SourceStats:
    """Per configured search/board entry admission counts."""

    key: str
    scanned: int = 0
    kept: int = 0
    hard_dropped: int = 0
    no_angle_dropped: int = 0


@dataclass
class FetchRun:
    """Outcome of one complete fetch run, after reports are written."""

    kept: list[dict[str, Any]]
    dropped: list[dict[str, Any]]
    scanned: int
    errors: list[str]
    markdown_path: str
    jsonl_path: str
    parse_failures: int = 0
    source_stats: list[SourceStats] | None = None


def _search_account_key(search: dict[str, Any]) -> str:
    source = str(search.get("source") or "search")
    if source == "remotive":
        return f"remotive/{search.get('category') or 'unknown'}"
    if source == "jobtech":
        return f"jobtech/{search.get('q') or 'query'}"
    if source == "hn":
        thread = search.get("thread_id")
        if thread in (None, "", "null"):
            return "hn"
        return f"hn/{thread}"
    label = search.get("q") or search.get("category") or search.get("thread_id") or ""
    return f"{source}/{label}" if label else source


def _board_account_key(board: dict[str, Any]) -> str:
    source = str(board.get("source") or "board")
    token = board.get("token") or board.get("company") or "board"
    return f"{source}/{token}"


def _gather(
    config: dict[str, Any], get: Transport
) -> tuple[list[dict[str, Any]], list[str], int, list[str]]:
    """Fetch all sources; tag each job with ``_account_key`` for first-producer accounting."""
    raw: list[dict[str, Any]] = []
    errors: list[str] = []
    parse_failures = 0
    entry_order: list[str] = []
    for search in config.get("searches", []) or []:
        key = _search_account_key(search)
        if key not in entry_order:
            entry_order.append(key)
        fetcher = SEARCH_FETCHERS.get(search["source"])
        if not fetcher:
            errors.append(f"unknown search source {search['source']}")
            continue
        try:
            result = fetcher(get, search)
            if isinstance(result, tuple):
                batch, failures = result
                parse_failures += int(failures)
            else:
                batch = result
            for job in batch:
                job["_account_key"] = key
            raw += batch
        except (urllib.error.URLError, urllib.error.HTTPError, ValueError) as error:
            label = search.get("q") or search.get("category") or search.get("thread_id") or ""
            errors.append(f"search {search['source']} q={label!r}: {error}")
    for board in config.get("boards", []) or []:
        key = _board_account_key(board)
        if key not in entry_order:
            entry_order.append(key)
        fetcher = BOARD_FETCHERS.get(board["source"])
        if not fetcher:
            errors.append(f"unknown source {board['source']}")
            continue
        try:
            batch = fetcher(get, board["token"], board.get("company", board["token"]))
            for job in batch:
                job["_account_key"] = key
            raw += batch
        except (urllib.error.URLError, urllib.error.HTTPError, ValueError) as error:
            errors.append(
                f"{board.get('company', board['token'])} ({board['source']}/{board['token']}): {error}"
            )
    return raw, errors, parse_failures, entry_order


def _dedupe(raw: list[dict[str, Any]], retrieved_at: str) -> list[dict[str, Any]]:
    all_jobs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for job in raw:
        job["job_id"] = jobs.stable_job_id(job)
        job["retrieved_at"] = retrieved_at
        job.setdefault("description_source", "search")
        if job.get("source") == "jobtech" and job.get("source_id"):
            job["detail_url"] = f"https://jobsearch.api.jobtechdev.se/ad/{job['source_id']}"
        job["source_queries"] = [job["source_query"]] if job.get("source_query") else []
        if job["job_id"] in seen:
            existing = next(item for item in all_jobs if item["job_id"] == job["job_id"])
            existing["source_queries"] = sorted(
                set(existing.get("source_queries", [])) | set(job.get("source_queries", []))
            )
            if job.get("tags") or existing.get("tags"):
                existing["tags"] = sorted(
                    set(existing.get("tags") or []) | set(job.get("tags") or [])
                )
            if len(job.get("desc", "")) > len(existing.get("desc", "")):
                existing["desc"] = job["desc"]
            for field in ("apply_url", "listing_url", "posted"):
                if not existing.get(field) and job.get(field):
                    existing[field] = job[field]
            # First producer keeps ``_account_key``; later hits only enrich fields.
            continue
        seen.add(job["job_id"])
        all_jobs.append(job)
    return all_jobs


def _empty_stats(entry_order: list[str]) -> dict[str, SourceStats]:
    return {key: SourceStats(key=key) for key in entry_order}


def run(
    config: dict[str, Any],
    policy: dict[str, Any],
    *,
    get: Transport,
    repo_root: str,
    today: str | None = None,
    retrieved_at: str | None = None,
) -> FetchRun:
    """Run one complete fetch — sources in, catalog upserted, shortlist views out."""
    weights = policy["weights"]
    angles = config["angles"]
    if retrieved_at is None:
        retrieved_at = datetime.datetime.now(datetime.UTC).isoformat()
    if today is None:
        today = datetime.date.today().isoformat()

    raw, errors, parse_failures, entry_order = _gather(config, get)
    all_jobs = _dedupe(raw, retrieved_at)
    stats = _empty_stats(entry_order)

    kept, dropped = [], []
    for job in all_jobs:
        key = str(job.get("_account_key") or job.get("source") or "unknown")
        if key not in stats:
            stats[key] = SourceStats(key=key)
            entry_order.append(key)
        # ``scanned`` counts each source's *distinct contribution*: cross-source
        # duplicates were folded in ``_dedupe`` under their first producer, so a
        # later source that only re-returned known jobs shows scanned 0 here.
        stats[key].scanned += 1
        attrs = jobs.extract(job, policy)
        keep, reason = jobs.location_verdict(attrs)
        job["attrs"] = attrs
        if not keep:
            job["drop_reason"] = reason
            dropped.append(job)
            stats[key].hard_dropped += 1
            continue
        classified = jobs.classify_angle(job, angles)
        if classified is None:
            job["drop_reason"] = "no qualifying angle"
            dropped.append(job)
            stats[key].no_angle_dropped += 1
            continue
        stored = catalog.load_record(repo_root, job["job_id"])
        first_seen = stored["first_seen"] if stored else retrieved_at
        # Provisional attrs score for admission ordering; recomputed from the
        # merged catalog record after upsert so posted-date preference applies once.
        job["score"] = jobs.pref_score(
            attrs,
            weights,
            policy["pay"],
            posted=job.get("posted", ""),
            first_seen=first_seen,
            now=retrieved_at,
        )
        job["angle"] = classified["angle"]
        job["fit_score"] = classified["fit_score"]
        job["fit_breakdown"] = classified["fit_breakdown"]
        job["hits"] = classified["hits"]
        kept.append(job)
        stats[key].kept += 1
    kept.sort(key=lambda item: (item["fit_score"], item["score"]), reverse=True)

    # Strip accounting tags before catalog persistence.
    for job in kept:
        job.pop("_account_key", None)
    for job in dropped:
        job.pop("_account_key", None)

    # Admitted jobs merge into the persistent catalog; hard drops never enter.
    records = catalog.upsert_fetch(repo_root, kept, retrieved_at)
    catalog.write_watermark(repo_root, retrieved_at)

    # Recompute attribute scores from merged posted/first_seen (single date policy).
    kept_ids = {job["job_id"] for job in kept}
    changed = False
    for record in records:
        if record["job_id"] not in kept_ids:
            continue
        record["score"] = jobs.pref_score(
            record["attrs"],
            weights,
            policy["pay"],
            posted=record.get("posted", ""),
            first_seen=record["first_seen"],
            now=retrieved_at,
        )
        changed = True
    if changed:
        catalog.save_records(repo_root, records)

    # The shortlist reports are post-fetch views over the catalog: open and
    # interested records ranked fit-then-attrs, skipped and stale excluded.
    # Cluster mates collapse to one display-winner row (view-only). Uncapped,
    # so every admitted live job stays reachable through the JSONL scaffold shim.
    view = [
        record
        for record in catalog.cluster_view_records(records)
        if record["triage"] in ("open", "interested") and not catalog.is_stale(record, retrieved_at)
    ]
    view.sort(
        key=lambda record: (catalog.rank_fit_score(record), record.get("score", 0)),
        reverse=True,
    )

    source_stats = [stats[key] for key in entry_order if key in stats]
    hard_drops = [job for job in dropped if job.get("drop_reason") != "no qualifying angle"]
    no_angle_drops = [job for job in dropped if job.get("drop_reason") == "no qualifying angle"]

    reports_dir = os.path.join(repo_root, "reports")
    os.makedirs(reports_dir, exist_ok=True)
    markdown_path = os.path.join(reports_dir, f"jobs-{today}.md")
    jsonl_path = os.path.join(reports_dir, f"jobs-{today}.jsonl")
    with open(markdown_path, "w", encoding="utf-8") as handle:
        summary = (
            f"# Job shortlist — {today}\n\n{len(view)} listed (open + interested) of "
            f"{len(records)} in catalog · fetch: {len(kept)} admitted · "
            f"{len(hard_drops)} hard-dropped · {len(no_angle_drops)} no-angle · "
            f"{len(all_jobs)} scanned"
        )
        # Report HN extraction health whenever an HN source ran, including zero
        # failures, so a clean run is visible rather than silently omitted (#14 §19).
        hn_configured = any(
            str(search.get("source")) == "hn" for search in config.get("searches", []) or []
        )
        if hn_configured:
            summary += f" · hn parse failures: {parse_failures}"
        handle.write(summary + "\n\n")
        if source_stats:
            handle.write("### Per source\n")
            for row in source_stats:
                handle.write(
                    f"- {row.key}: scanned {row.scanned} · kept {row.kept} · "
                    f"hard-dropped {row.hard_dropped} · no-angle {row.no_angle_dropped}\n"
                )
            handle.write("\n")
        report_jsonl = f"reports/jobs-{today}.jsonl"
        for record in view:
            attrs = record["attrs"]
            breakdown = record.get("fit_breakdown") or {}
            breakdown_line = (
                f"angle:{breakdown.get('angle', 0)} / "
                f"seniority:{breakdown.get('seniority', 0)} / "
                f"rn:{breakdown.get('rn', 0)}"
            )
            label = catalog.freshness_label(record, retrieved_at)
            rank_fit = catalog.rank_fit_score(record)
            handle.write(f"## [fit {rank_fit}] {record['title']} — {record['company']}\n")
            if label in ("New", "Updated"):
                handle.write(f"label: {label}\n")
            handle.write(
                f"angle: {record.get('angle', '')} · fit: {record.get('fit_score', 0)} "
                f"({breakdown_line})\n"
                f"{jobs.fmt_attrs(attrs)}\n{record['location']}  ·  {record['url']}\n"
                f"source: {record.get('source', '?')} · job-id: {record['job_id']}\n"
            )
            if record.get("posted"):
                handle.write(f"posted: {record['posted']}\n")
            if record.get("deadline"):
                handle.write(f"deadline: {record['deadline']}\n")
            if record["triage"] != "open":
                handle.write(f"triage: {record['triage']}\n")
            if record.get("source_queries"):
                handle.write(f"found-by: {', '.join(record['source_queries'])}\n")
            handle.write(f"matched: {', '.join(record.get('hits') or [])}\n")
            missing_info = jobs.missing(attrs)
            if missing_info:
                handle.write(f"missing-info (check the posting): {', '.join(missing_info)}\n")
            handle.write(
                f"scaffold: `mise run new --from-report {jobs.shell_quote(report_jsonl)} --job-id {jobs.shell_quote(record['job_id'])}`\n\n"
            )
        if hard_drops:
            handle.write(
                "\n---\n### Dropped — location/timezone (loosen preferences.yaml to keep)\n"
            )
            for job in hard_drops[:40]:
                handle.write(
                    f"- {job['title']} — {job['company']} ({job['location']}): {job['drop_reason']}\n"
                )
        if no_angle_drops:
            handle.write("\n### Dropped — no qualifying angle\n")
            for job in no_angle_drops[:40]:
                handle.write(
                    f"- {job['title']} — {job['company']} ({job['location']}): {job['drop_reason']}\n"
                )
        if errors:
            handle.write(
                "\n### Fetch errors\n" + "\n".join(f"- {error}" for error in errors) + "\n"
            )
    with open(jsonl_path, "w", encoding="utf-8") as handle:
        for record in view:
            report = {field: record.get(field, "") for field in REPORT_FIELDS}
            handle.write(json.dumps(report, ensure_ascii=False) + "\n")
    return FetchRun(
        kept=kept,
        dropped=dropped,
        scanned=len(all_jobs),
        errors=errors,
        markdown_path=markdown_path,
        jsonl_path=jsonl_path,
        parse_failures=parse_failures,
        source_stats=source_stats,
    )

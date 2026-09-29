"""Application-folder records, import operations, and the event timeline.

All writes remain in the existing application folder layout.  The CLI adapter
supplies the fetch function for optional detail refreshes, keeping this module
usable without network access.

``meta.yaml`` stays the single source of truth for an application. ``update_meta``
keeps its line-oriented handling of ordinary flat fields (preserving comments
and hand-written text), ``append_event`` adds non-status history, and
``set_status`` atomically updates the status caches and appends their audit
event. Freshness (``last_activity_at``) is derived on read and never stored.
"""

import datetime
import fcntl
import hashlib
import json
import os
import re
import threading
import unicodedata
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml

from . import catalog

CV_STUB = """# PIET GROOT KORMELINK
%%headline%% <headline_variant from master-profile.yaml>
%%contact%% piet.groot.kormelink@gmail.com · github.com/pietgk · linkedin.com/in/pietgrootkormelink · Röfors, Sweden · Remote · CET

## SUMMARY
<3-5 line summary assembled from summary_atoms matching this role's angle>

## CORE SKILLS
- **Backend:** ...
- **Frontend:** ...
- **Architecture:** ...
- **Quality & Delivery:** ...

## EXPERIENCE

### Mindler — Technical Lead · Stockholm, Sweden (Hybrid) · ~2022–2026
*Consumer healthtech: RN + Expo app, Next.js web, Node/TypeScript + GraphQL, Postgres/MySQL — small teams, live regulated product.*
- ...
- ...

## EDUCATION
Saxion University of Applied Sciences — Computer Technology (ing.)

## LANGUAGES
Dutch (native) · English (fluent) · German (fluent) · Swedish (learning)
"""

META_STUB = """company: {company}
role: {role}
angle: ""            # one of: full_stack_lead | product_engineer | backend_principal | mobile_product | ai_native
fit_score: 0         # 0-5, see profile/positioning.md job-fit quick test
status: draft        # draft | applied | interview | offer | accepted | rejected | withdrawn
source: ""           # e.g. LinkedIn alert | Ashby | referral
url: ""
date_created: "{date}"
date_applied: ""
summary: ""          # standing fit rationale; dated observations are `note` events
job_id: ""
source_id: ""
source_query: ""
listing_url: ""
detail_url: ""
description_source: ""
discovery_score: 0
date_fetched: ""
"""

JOB_PLACEHOLDER = "<paste job description / recruiter email here>"
PROVENANCE_FIELDS = {
    "source",
    "url",
    "job_id",
    "source_id",
    "source_query",
    "listing_url",
    "detail_url",
    "description_source",
    "date_fetched",
}
STATUS_CACHE_FIELDS = frozenset(("status", "date_applied"))
_META_WRITE_LOCKS: dict[str, threading.Lock] = {}
_META_WRITE_LOCKS_GUARD = threading.Lock()


@contextmanager
def _meta_write_transaction(path: str) -> Iterator[None]:
    lock_key = os.path.realpath(path)
    with _META_WRITE_LOCKS_GUARD:
        process_lock = _META_WRITE_LOCKS.setdefault(lock_key, threading.Lock())
    with process_lock:
        directory_fd = os.open(os.path.dirname(lock_key), os.O_RDONLY)
        try:
            fcntl.flock(directory_fd, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(directory_fd, fcntl.LOCK_UN)
            os.close(directory_fd)


def slug(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "", name.title())


def short_job_id_fragment(job_id: str) -> str:
    """Filesystem-safe fragment for disambiguating application folders."""
    tail = job_id.rsplit(":", 1)[-1]
    cleaned = re.sub(r"[^A-Za-z0-9]+", "", tail)
    if cleaned:
        return cleaned[:16]
    return hashlib.sha1(job_id.encode("utf-8")).hexdigest()[:8]


def application_identifier(
    day: str,
    company: str,
    role: str,
    job_id: str,
    apps_root: str,
) -> str:
    """Prefer ``YYYY-MM-DD_Company``; disambiguate on conflict; never clobber another job."""
    company_slug = slug(company) or "Company"
    role_slug = slug(role) or "Role"
    job_frag = short_job_id_fragment(job_id)
    candidates = [
        f"{day}_{company_slug}",
        f"{day}_{company_slug}_{role_slug}",
        f"{day}_{company_slug}_{role_slug}_{job_frag}",
        f"{day}_{company_slug}_{job_frag}",
    ]
    seen: set[str] = set()
    for identifier in candidates:
        if identifier in seen:
            continue
        seen.add(identifier)
        folder = os.path.join(apps_root, identifier)
        if not os.path.isdir(folder):
            return identifier
        existing = str(read_meta(os.path.join(folder, "meta.yaml")).get("job_id") or "")
        if existing == job_id:
            return identifier
    # Exhausted preferred shapes — always unique vs any other job_id.
    digest = short_job_id_fragment(job_id)
    suffix = 2
    while True:
        identifier = f"{day}_{company_slug}_{role_slug}_{digest}_{suffix}"
        folder = os.path.join(apps_root, identifier)
        if not os.path.isdir(folder):
            return identifier
        existing = str(read_meta(os.path.join(folder, "meta.yaml")).get("job_id") or "")
        if existing == job_id:
            return identifier
        suffix += 1


def yaml_quote(value: Any) -> str:
    return json.dumps(str(value), ensure_ascii=False)


def yaml_scalar(value: Any) -> str:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    return yaml_quote(value)


def read_meta(path: str) -> dict[str, Any]:
    """Read an application's additive metadata without imposing a schema."""
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as handle:
            values = yaml.safe_load(handle) or {}
    except (OSError, yaml.YAMLError):
        return {}
    if not isinstance(values, dict):
        return {}
    return {str(key): value for key, value in values.items()}


def load_report(path: str) -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    with open(path, encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                job = json.loads(line)
            except json.JSONDecodeError as error:
                raise SystemExit(
                    f"invalid JSONL in {path} at line {line_number}: {error}"
                ) from error
            if not isinstance(job, dict):
                raise SystemExit(f"expected an object in {path} at line {line_number}")
            jobs.append(job)
    if not jobs:
        raise SystemExit(f"report contains no jobs: {path}")
    return jobs


def select_report_job(
    jobs: list[dict[str, Any]], job_id: str = "", job_index: int | None = None, match: str = ""
) -> dict[str, Any]:
    if job_id:
        matches = [job for job in jobs if str(job.get("job_id", "")) == job_id]
    elif job_index is not None:
        if job_index < 1 or job_index > len(jobs):
            raise SystemExit(f"job index must be between 1 and {len(jobs)}")
        matches = [jobs[job_index - 1]]
    elif match:
        needle = match.casefold()
        exact = [
            job
            for job in jobs
            if needle
            in {str(job.get("company", "")).casefold(), str(job.get("title", "")).casefold()}
        ]
        matches = exact or [
            job
            for job in jobs
            if needle in str(job.get("company", "")).casefold()
            or needle in str(job.get("title", "")).casefold()
        ]
    elif len(jobs) == 1:
        matches = jobs
    else:
        raise SystemExit("select a report job with --job-id, --job-index, or --match")
    if not matches:
        raise SystemExit(f"no job matched {job_id or match!r}")
    if len(matches) > 1:
        choices = "\n".join(
            f"- {job.get('job_id', '?')}: {job.get('company', '?')} — {job.get('title', '?')}"
            for job in matches
        )
        raise SystemExit(f"multiple jobs matched; choose a stable job ID:\n{choices}")
    return matches[0]


def imported_job_markdown(company: str, role: str, report_path: str, job: dict[str, Any]) -> str:
    description = str(job.get("description", "")).strip() or JOB_PLACEHOLDER
    description = re.sub(r"[\u200b\u200c\u200d\ufeff]", "", description)
    description = description.replace("\r\n", "\n").replace("\r", "\n")
    origin = job.get("description_source") or ("report" if report_path else "detail")
    comments = [
        f"<!-- imported from {report_path or job.get('detail_url', 'JobTech')} -->",
        f"<!-- job-id: {job.get('job_id', '')} -->",
        f"<!-- source: {job.get('source', '')} -->",
        f"<!-- description-source: {origin} -->",
    ]
    if job.get("apply_url") or job.get("url"):
        comments.append(f"<!-- apply-url: {job.get('apply_url') or job.get('url')} -->")
    if job.get("detail_url"):
        comments.append(f"<!-- detail-url: {job['detail_url']} -->")
    return f"# {company} — {role}\n\n{'\n'.join(comments)}\n\n{description}\n"


def normalize_for_compare(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = re.sub(r"[\u200b\u200c\u200d\ufeff]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def job_body(content: str) -> str:
    body = [line for line in content.splitlines()[1:] if not line.lstrip().startswith("<!--")]
    return "\n".join(body).strip()


def existing_matches_source(content: str, source_path: str) -> bool:
    if not os.path.exists(source_path):
        return False
    try:
        with open(source_path, encoding="utf-8") as handle:
            source = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return False
    old_description = source.get("description", "")
    return bool(old_description) and normalize_for_compare(
        job_body(content)
    ) == normalize_for_compare(old_description)


def is_job_placeholder(content: str, company: str, role: str) -> bool:
    if not content.strip():
        return True
    meaningful = [
        line.strip()
        for line in content.splitlines()
        if line.strip() and not line.lstrip().startswith("<!--")
    ]
    return meaningful == [f"# {company} — {role}", JOB_PLACEHOLDER]


def _update_flat_lines(
    lines: list[str],
    values: dict[str, Any],
    *,
    force: bool,
    refresh: bool,
) -> None:
    """Apply line-oriented flat-field updates without writing the file."""
    for key, value in values.items():
        if value in (None, ""):
            continue
        replacement = f"{key}: {yaml_scalar(value)}"
        found = False
        for index, line in enumerate(lines):
            if not re.match(rf"^{re.escape(key)}:", line):
                continue
            found = True
            current = line.split(":", 1)[1].split("#", 1)[0].strip()
            should_update = force or current in ("", '""', "''", "0")
            should_update = should_update or (refresh and key in PROVENANCE_FIELDS)
            if should_update:
                comment = f" {line[line.index('#') :]}" if "#" in line else ""
                lines[index] = replacement + comment
            break
        if not found:
            lines.append(replacement)


def update_meta(
    path: str, values: dict[str, Any], force: bool = False, refresh: bool = False
) -> None:
    owned = STATUS_CACHE_FIELDS.intersection(values)
    if owned:
        raise MetaEventError(
            f"write {', '.join(sorted(owned))} with set_status so status history cannot drift"
        )
    with _meta_write_transaction(path):
        if os.path.exists(path):
            with open(path, encoding="utf-8") as handle:
                text = handle.read()
        else:
            text = ""
        lines = text.splitlines()
        _update_flat_lines(lines, values, force=force, refresh=refresh)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("\n".join(lines).rstrip() + "\n")


# --- Application events ------------------------------------------------------
#
# An application's history is an append-only ``events:`` list in its own
# ``meta.yaml`` — there is no second index file.  ``kind`` is a closed enum;
# adding a kind is a deliberate ADR change, not an ad-hoc string.
# Bulky payloads (email bodies, saved pages) live as sibling files under the
# application's ``events/`` folder and are referenced by ``ref`` so that
# ``meta.yaml`` stays skimmable.

EVENTS_DIRNAME = "events"

#: ``kind`` -> (required fields, optional fields).  Closed ``kind`` values are
#: named in ADR-0007's application-events amendment; this map is the
#: authoritative per-kind field shape. ``ref`` is produced by the writer from
#: the caller's payload body.
EVENT_FIELDS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "status_changed": (("from", "to"), ()),
    "email": (("direction", "from", "to", "subject", "ref"), ("msg_id",)),
    "link": (("url", "label"), ("ref",)),
    "note": (("text",), ()),
}
EVENT_KINDS: tuple[str, ...] = tuple(EVENT_FIELDS)
#: Kinds whose payload body is written as a sibling ``events/`` file.
PAYLOAD_EVENT_KINDS: tuple[str, ...] = ("email", "link")
EMAIL_DIRECTIONS: tuple[str, ...] = ("incoming", "outgoing")

APPLICATION_STATUSES: tuple[str, ...] = (
    "draft",
    "applied",
    "interview",
    "offer",
    "accepted",
    "rejected",
    "withdrawn",
)
ADVISORY_STATUS_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "draft": ("applied", "withdrawn"),
    "applied": ("interview", "rejected", "withdrawn"),
    "interview": ("offer", "rejected", "withdrawn"),
    "offer": ("accepted", "rejected", "withdrawn"),
    "accepted": (),
    "rejected": (),
    "withdrawn": (),
}


def advisory_next_statuses(status: str) -> tuple[str, ...]:
    """Return the forward-natural next statuses without restricting other picks."""
    try:
        return ADVISORY_STATUS_TRANSITIONS[status]
    except KeyError as error:
        raise MetaEventError(
            f"unknown application status {status!r}; expected one of "
            f"{', '.join(APPLICATION_STATUSES)}"
        ) from error


#: The fixed set of flat dated workflow fields.  These *are* workflow events:
#: they render as timeline facts directly and are never duplicated into
#: ``events:``, so each fact has exactly one representation.
FLAT_DATED_FIELDS: tuple[str, ...] = (
    "date_fetched",
    "date_created",
    "date_applied",
    "draft_started_at",
    "last_checked_at",
    "finalized_at",
)

EPOCH = datetime.datetime.min.replace(tzinfo=datetime.UTC)


class MetaEventError(ValueError):
    """Raised when an event is malformed or ``meta.yaml`` cannot be extended safely."""


def event_timestamp(now: datetime.datetime | None = None) -> str:
    """Canonical ``when`` for a new event: whole-second UTC ISO 8601."""
    moment = now or datetime.datetime.now(datetime.UTC)
    return moment.astimezone(datetime.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_timestamp(value: Any) -> datetime.datetime | None:
    """Read one stored timestamp as an aware UTC datetime; ``None`` when unusable.

    Handles every shape ``meta.yaml`` carries today: quoted ``YYYY-MM-DD`` days,
    ``...Z`` and ``...+00:00`` instants, and the ``date``/``datetime`` objects
    PyYAML produces for unquoted values.  Naive values are read as UTC.
    """
    if isinstance(value, datetime.datetime):
        parsed = value
    elif isinstance(value, datetime.date):
        parsed = datetime.datetime.combine(value, datetime.time.min)
    else:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            parsed = datetime.datetime.fromisoformat(text)
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.UTC)
    return parsed.astimezone(datetime.UTC)


_DATE_ONLY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_BASIC_DATE_ONLY = re.compile(r"^\d{8}$")


def _aware_event_datetime(value: Any) -> datetime.datetime | None:
    if isinstance(value, datetime.datetime):
        parsed = value
    elif isinstance(value, datetime.date):
        return None
    else:
        text = str(value or "").strip()
        if not text or _DATE_ONLY.match(text) or _BASIC_DATE_ONLY.match(text):
            return None
        try:
            parsed = datetime.datetime.fromisoformat(text)
        except ValueError:
            return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def _system_local_timezone(*, require_rules: bool) -> datetime.tzinfo:
    configured_zone = os.environ.get("TZ", "")
    zone_name = configured_zone.removeprefix(":")
    if configured_zone:
        if not zone_name:
            raise MetaEventError(f"unsupported TZ setting {configured_zone!r}")
        try:
            return ZoneInfo(zone_name)
        except (ValueError, ZoneInfoNotFoundError):
            if os.path.isfile(zone_name):
                try:
                    with open(zone_name, "rb") as handle:
                        return ZoneInfo.from_file(handle)
                except (OSError, ValueError):
                    pass
            raise MetaEventError(f"unsupported TZ setting {configured_zone!r}") from None
    try:
        with open("/etc/localtime", "rb") as handle:
            return ZoneInfo.from_file(handle)
    except (OSError, ValueError):
        if require_rules:
            raise MetaEventError("date-only events require a rule-bearing local timezone") from None
        return datetime.datetime.now().astimezone().tzinfo or datetime.UTC


def _event_moment_and_date(
    when: str | None,
    *,
    now: datetime.datetime | None = None,
    local_timezone: datetime.tzinfo | None = None,
) -> tuple[datetime.datetime, datetime.date]:
    """Return a UTC event instant and its source calendar date."""
    if when is None:
        timezone = local_timezone or _system_local_timezone(require_rules=False)
        local_now = now.astimezone(timezone) if now is not None else datetime.datetime.now(timezone)
        local_now = local_now.replace(microsecond=0)
        return local_now.astimezone(datetime.UTC), local_now.date()
    if _DATE_ONLY.match(when.strip()):
        timezone = local_timezone or _system_local_timezone(require_rules=True)
        if not isinstance(timezone, ZoneInfo):
            raise MetaEventError("date-only events require a rule-bearing local timezone")
        local_now = now.astimezone(timezone) if now is not None else datetime.datetime.now(timezone)
        local_now = local_now.replace(microsecond=0)
        try:
            calendar_date = datetime.date.fromisoformat(when.strip())
        except ValueError as error:
            raise MetaEventError(
                f"invalid event timestamp {when!r}; expected an ISO 8601 date or time"
            ) from error
        local_moment = datetime.datetime.combine(
            calendar_date,
            local_now.time(),
            tzinfo=timezone,
        )
        return local_moment.astimezone(datetime.UTC), calendar_date

    text = when.strip()
    if _BASIC_DATE_ONLY.match(text):
        raise MetaEventError(
            f"invalid event timestamp {when!r}; use YYYY-MM-DD for a calendar date"
        )
    source_moment = _aware_event_datetime(text)
    if source_moment is None:
        raise MetaEventError(
            f"invalid event timestamp {when!r}; expected a timezone-aware ISO 8601 instant"
        )
    return source_moment.astimezone(datetime.UTC).replace(microsecond=0), source_moment.date()


@dataclass(frozen=True)
class _EventTimeRequest:
    instant: datetime.datetime | None
    calendar_date: datetime.date | None


def _event_time_request(when: str | None) -> _EventTimeRequest:
    if when is None:
        return _EventTimeRequest(None, None)
    text = when.strip()
    if _DATE_ONLY.match(text):
        try:
            calendar_date = datetime.date.fromisoformat(text)
        except ValueError as error:
            raise MetaEventError(
                f"invalid event timestamp {when!r}; expected an ISO 8601 date or time"
            ) from error
        return _EventTimeRequest(None, calendar_date)
    instant, calendar_date = _event_moment_and_date(text)
    return _EventTimeRequest(instant, calendar_date)


def _resolve_event_time(
    request: _EventTimeRequest,
) -> tuple[datetime.datetime, datetime.date]:
    if request.instant is not None and request.calendar_date is not None:
        return request.instant, request.calendar_date
    if request.calendar_date is not None:
        return _event_moment_and_date(request.calendar_date.isoformat())
    return _event_moment_and_date(None)


def indexed_events(meta: dict[str, Any]) -> list[tuple[int, dict[str, Any]]]:
    """Every valid event paired with its stable stored index, oldest first.

    Reading stays tolerant - a meta with no ``events:`` list yields ``[]`` and
    malformed entries are skipped - so applications written before the event
    model existed keep working.  Validation belongs to :func:`append_event`.
    """
    stored = meta.get("events")
    if not isinstance(stored, list):
        return []
    parsed = [(index, entry) for index, entry in enumerate(stored) if isinstance(entry, dict)]
    return sorted(parsed, key=lambda entry: parse_timestamp(entry[1].get("when")) or EPOCH)


def events(meta: dict[str, Any]) -> list[dict[str, Any]]:
    """Every event in a parsed ``meta.yaml``, oldest first."""
    return [event for _, event in indexed_events(meta)]


def last_activity_at(meta: dict[str, Any]) -> datetime.datetime | None:
    """When this application last moved: the newest flat dated field or event.

    Pure and derived on read — nothing stores it — so it can never drift from
    the facts it summarizes.  ``None`` means the meta carries no usable date.
    """
    moments = [parse_timestamp(meta.get(field)) for field in FLAT_DATED_FIELDS]
    moments += [parse_timestamp(event.get("when")) for event in events(meta)]
    known = [moment for moment in moments if moment is not None]
    return max(known) if known else None


def summary(meta: dict[str, Any]) -> str:
    """The standing fit rationale, reading pre-rename ``notes:`` metas as well.

    Distinct from dated ``note`` events: this is the one-line "why this job"
    the job-card header shows.
    """
    return str(meta.get("summary") or meta.get("notes") or "").strip()


def activity_sort_key(identifier: str, meta: dict[str, Any]) -> tuple[datetime.datetime, str]:
    """Sort key for the Applications list — use with ``reverse=True``.

    Newest activity first; on an identical timestamp the later folder name wins,
    which for date-prefixed folders means the newest-created application.
    """
    return (last_activity_at(meta) or EPOCH, identifier)


def _validated_event(kind: str, fields: dict[str, Any], when: str) -> dict[str, Any]:
    if kind not in EVENT_FIELDS:
        raise MetaEventError(
            f"unknown event kind {kind!r}; expected one of {', '.join(EVENT_KINDS)}"
        )
    if _aware_event_datetime(when) is None:
        raise MetaEventError(
            f"invalid event timestamp {when!r}; expected a timezone-aware ISO 8601 instant"
        )

    required, optional = EVENT_FIELDS[kind]
    unknown = sorted(set(fields) - set(required) - set(optional))
    if unknown:
        raise MetaEventError(f"unexpected field(s) for {kind} event: {', '.join(unknown)}")

    event: dict[str, Any] = {"when": when, "kind": kind}
    for field in required:
        value = str(fields.get(field, "") or "").strip()
        if not value:
            raise MetaEventError(f"{kind} event requires a non-empty {field!r}")
        event[field] = value
    for field in optional:
        value = str(fields.get(field, "") or "").strip()
        if value:
            event[field] = value

    if kind == "status_changed":
        for field in ("from", "to"):
            if event[field] not in APPLICATION_STATUSES:
                raise MetaEventError(
                    f"unknown application status {event[field]!r}; expected one of "
                    f"{', '.join(APPLICATION_STATUSES)}"
                )
        if event["from"] == event["to"]:
            raise MetaEventError("status_changed event endpoints must differ")
    if kind == "email" and event["direction"] not in EMAIL_DIRECTIONS:
        raise MetaEventError(
            f"email direction must be one of {', '.join(EMAIL_DIRECTIONS)}; "
            f"got {event['direction']!r}"
        )
    return event


def _payload_path(folder: str, when: str, kind: str, suffix: str) -> str:
    """A collision-free ``events/`` payload path, relative to the application folder."""
    stamp = re.sub(r"[^0-9A-Za-z]", "", when) or "event"
    for attempt in range(1, 100):
        tail = "" if attempt == 1 else f"-{attempt}"
        relative = f"{EVENTS_DIRNAME}/{stamp}-{kind}{tail}{suffix}"
        if not os.path.exists(os.path.join(folder, relative)):
            return relative
    raise MetaEventError(f"could not find a free {EVENTS_DIRNAME}/ payload name for {stamp}")


def _events_insertion_point(lines: list[str]) -> int | None:
    """Index just past the last line of the ``events:`` block, or ``None`` if absent.

    Normalizes an empty inline list (``events: []``) into a block header in
    ``lines`` so an item can follow it; refuses a populated inline list rather
    than rewriting one.
    """
    start = None
    for index, line in enumerate(lines):
        if re.match(r"^events\s*:", line):
            start = index
            break
    if start is None:
        return None
    inline = lines[start].split(":", 1)[1].split("#", 1)[0].strip()
    if inline not in ("", "[]"):
        raise MetaEventError("cannot append to an inline events list; write it as a YAML block")
    lines[start] = "events:"
    end = start + 1
    for index in range(start + 1, len(lines)):
        line = lines[index]
        if line.strip() and not (line.startswith((" ", "\t", "-"))):
            break
        end = index + 1
    while end > start + 1 and not lines[end - 1].strip():
        end -= 1
    return end


def _rendered_event(event: dict[str, Any]) -> list[str]:
    dumped = yaml.safe_dump(event, sort_keys=False, allow_unicode=True, width=100)
    body = dumped.rstrip("\n").splitlines()
    # Blank lines inside a folded scalar stay blank rather than carrying indent.
    return [f"  - {body[0]}"] + [f"    {line}" if line.strip() else "" for line in body[1:]]


def _event_update_text(
    meta_path: str,
    text: str,
    before: dict[str, Any],
    event: dict[str, Any] | None,
    flat_updates: dict[str, str] | None = None,
) -> str:
    """Render and verify optional flat cache updates plus at most one event append."""
    prior_events = before.get("events") or []
    if not isinstance(prior_events, list):
        raise MetaEventError(f"application events must be a YAML list: {meta_path}")

    flat_updates = flat_updates or {}
    lines = text.splitlines()
    _update_flat_lines(lines, flat_updates, force=True, refresh=False)
    if event is not None:
        end = _events_insertion_point(lines)
        if end is None:
            while lines and not lines[-1].strip():
                lines.pop()
            lines += ["events:"] + _rendered_event(event)
        else:
            lines[end:end] = _rendered_event(event)
    updated = "\n".join(lines).rstrip("\n") + "\n"

    try:
        after = yaml.safe_load(updated) or {}
    except yaml.YAMLError as error:  # pragma: no cover - defensive
        raise MetaEventError(f"appending the event would corrupt {meta_path}: {error}") from error
    expected = dict(before)
    expected.update(flat_updates)
    if event is not None:
        expected["events"] = [*prior_events, event]
    if after != expected:
        raise MetaEventError(f"appending the event would disturb metadata in {meta_path}")
    return updated


def append_event(
    meta_path: str,
    kind: str,
    fields: dict[str, Any] | None = None,
    *,
    when: str | None = None,
    body: str | None = None,
    body_suffix: str = ".md",
) -> dict[str, Any]:
    """Append one event to ``meta.yaml``'s ``events:`` list and return it as written.

    The list-aware counterpart to :func:`update_meta`: it appends to the events
    block as text, so every flat field, comment, and block scalar in the file
    survives byte-for-byte.  For ``email``/``link``, ``body`` is written as a
    sibling file under ``events/`` and referenced by the event's ``ref``.

    Status changes use :func:`set_status`, which combines the event append with
    its flat cache updates. Raises :class:`MetaEventError` for an unknown kind,
    a missing or unexpected field, or a ``meta.yaml`` that does not parse.
    """
    folder = os.path.dirname(os.path.abspath(meta_path))
    fields = dict(fields or {})
    event_time_request = _event_time_request(when)

    if body is not None:
        if kind not in PAYLOAD_EVENT_KINDS:
            raise MetaEventError(
                f"{kind} events carry no payload body; only {', '.join(PAYLOAD_EVENT_KINDS)} do"
            )
        if fields.get("ref"):
            raise MetaEventError("pass either a payload body or an explicit ref, not both")
    with _meta_write_transaction(meta_path):
        event_moment, _ = _resolve_event_time(event_time_request)
        event_when = event_timestamp(event_moment)
        if body is not None:
            fields["ref"] = _payload_path(folder, event_when, kind, body_suffix)
        event = _validated_event(kind, fields, event_when)

        if not os.path.exists(meta_path):
            raise MetaEventError(f"missing application metadata: {meta_path}")
        with open(meta_path, encoding="utf-8") as handle:
            text = handle.read()
        try:
            before = yaml.safe_load(text) or {}
        except yaml.YAMLError as error:
            raise MetaEventError(f"could not parse {meta_path}: {error}") from error
        if not isinstance(before, dict):
            raise MetaEventError(f"application metadata must be a YAML mapping: {meta_path}")

        if kind == "status_changed":
            raise MetaEventError(
                "write status_changed events with set_status so the head cannot drift"
            )
        updated = _event_update_text(meta_path, text, before, event)
        payload_path: str | None = None
        events_dir_created = False
        committed = False
        try:
            if body is not None:
                payload_path = os.path.join(folder, event["ref"])
                events_dir = os.path.dirname(payload_path)
                events_dir_created = not os.path.isdir(events_dir)
                os.makedirs(events_dir, exist_ok=True)
                if body and not body.endswith("\n"):
                    body += "\n"
                with open(payload_path, "w", encoding="utf-8") as handle:
                    handle.write(body)
            _atomic_write(meta_path, updated)
            committed = True
        finally:
            if not committed and payload_path is not None:
                try:
                    os.remove(payload_path)
                except OSError:
                    pass
                if events_dir_created:
                    events_dir = os.path.dirname(payload_path)
                    try:
                        if os.path.isdir(events_dir) and not os.listdir(events_dir):
                            os.rmdir(events_dir)
                    except OSError:
                        pass
    return event


@dataclass(frozen=True)
class AppliedStatusUpdate:
    date_applied: str
    changed: bool


@dataclass(frozen=True)
class _StatusWrite:
    event: dict[str, Any] | None
    date_applied: str
    changed: bool


@dataclass(frozen=True)
class _StatusHistoryEvent:
    moment: datetime.datetime
    from_status: str
    to_status: str


def _validated_application_date(value: str) -> datetime.date:
    try:
        parsed = datetime.date.fromisoformat(value)
    except ValueError as error:
        raise MetaEventError(f"invalid application date {value!r}; expected YYYY-MM-DD") from error
    if parsed.isoformat() != value:
        raise MetaEventError(f"invalid application date {value!r}; expected YYYY-MM-DD")
    return parsed


def _validated_status_history(meta: dict[str, Any]) -> list[_StatusHistoryEvent]:
    stored = meta.get("events")
    if stored is None:
        stored = []
    if not isinstance(stored, list):
        raise MetaEventError("malformed status history: application events must be a list")
    history: list[_StatusHistoryEvent] = []
    expected_fields = {"when", "kind", "from", "to"}
    for index, stored_event in enumerate(stored):
        if not isinstance(stored_event, dict) or stored_event.get("kind") != "status_changed":
            continue
        unknown = [key for key in stored_event if key not in expected_fields]
        missing = expected_fields.difference(stored_event)
        if unknown or missing:
            details = []
            if missing:
                details.append(f"missing {', '.join(sorted(missing))}")
            if unknown:
                details.append(f"unexpected {', '.join(sorted(repr(key) for key in unknown))}")
            raise MetaEventError(f"malformed status history event {index}: {'; '.join(details)}")
        stored_when = stored_event["when"]
        stored_moment = _aware_event_datetime(stored_when)
        if stored_moment is None:
            raise MetaEventError(
                f"malformed status history event {index}: "
                "when must be a timezone-aware full instant"
            )
        moment = stored_moment.astimezone(datetime.UTC)
        try:
            _validated_event(
                "status_changed",
                {"from": stored_event["from"], "to": stored_event["to"]},
                event_timestamp(moment),
            )
        except MetaEventError as error:
            raise MetaEventError(f"malformed status history event {index}: {error}") from error
        history.append(
            _StatusHistoryEvent(
                moment,
                str(stored_event["from"]),
                str(stored_event["to"]),
            )
        )
    return sorted(history, key=lambda event: event.moment)


def _write_status_locked(
    meta_path: str,
    status: str,
    *,
    event_time_request: _EventTimeRequest,
    applied_on: datetime.date | None,
    human_confirmed: bool,
    confirmation_only: bool,
    reject_date_conflict: bool,
) -> _StatusWrite:
    if not os.path.exists(meta_path):
        raise MetaEventError(f"missing application metadata: {meta_path}")
    with open(meta_path, encoding="utf-8") as handle:
        text = handle.read()
    try:
        before = yaml.safe_load(text) or {}
    except yaml.YAMLError as error:
        raise MetaEventError(f"could not parse {meta_path}: {error}") from error
    if not isinstance(before, dict):
        raise MetaEventError(f"application metadata must be a YAML mapping: {meta_path}")

    current = str(before.get("status") or "").strip()
    if current not in APPLICATION_STATUSES:
        raise MetaEventError(
            f"unknown current application status {current!r}; expected one of "
            f"{', '.join(APPLICATION_STATUSES)}"
        )
    if confirmation_only and current not in {"draft", "applied"}:
        raise MetaEventError(f"cannot mark status {current!r} as applied; expected 'draft'")
    if current == "draft" and status == "applied" and not human_confirmed:
        raise MetaEventError("draft to applied requires explicit human confirmation")

    on_record = str(before.get("date_applied") or "").strip()
    if confirmation_only and on_record:
        on_record = _validated_application_date(on_record).isoformat()
    if (
        reject_date_conflict
        and applied_on is not None
        and on_record
        and applied_on.isoformat() != on_record
    ):
        raise MetaEventError(
            f"application is already marked applied on {on_record}; "
            f"refusing to replace it with {applied_on.isoformat()}"
        )

    status_history: list[_StatusHistoryEvent] = []
    if current != status or (status == "applied" and not on_record):
        status_history = _validated_status_history(before)

    event_time: tuple[datetime.datetime, datetime.date] | None = None
    first_applied_date: str | None = None
    if status == "applied" and not on_record:
        has_prior_applied_event = any(event.to_status == "applied" for event in status_history)
        if has_prior_applied_event:
            if current == status:
                raise MetaEventError(
                    "cannot repair date_applied from status history: "
                    "the first submission calendar day was not recorded"
                )
        elif current == status and status_history:
            raise MetaEventError(
                "cannot repair date_applied: status history has no transition entering applied"
            )
        else:
            if applied_on is None:
                if event_time_request.calendar_date is not None:
                    applied_on = event_time_request.calendar_date
                else:
                    event_time = _resolve_event_time(event_time_request)
                    applied_on = event_time[1]
            first_applied_date = applied_on.isoformat()

    if current == status:
        if first_applied_date is None:
            return _StatusWrite(None, on_record, False)
        updated = _event_update_text(
            meta_path, text, before, None, {"date_applied": first_applied_date}
        )
        _atomic_write(meta_path, updated)
        return _StatusWrite(None, first_applied_date, True)

    event_time = event_time or _resolve_event_time(event_time_request)
    latest_status_moment = status_history[-1].moment if status_history else None
    if latest_status_moment is not None and event_time[0] < latest_status_moment:
        raise MetaEventError(
            f"status timestamp {event_timestamp(event_time[0])} precedes latest status event "
            f"{event_timestamp(latest_status_moment)}"
        )
    event = _validated_event(
        "status_changed",
        {"from": current, "to": status},
        event_timestamp(event_time[0]),
    )
    flat_updates = {"status": status}
    if first_applied_date is not None:
        flat_updates["date_applied"] = first_applied_date
    updated = _event_update_text(meta_path, text, before, event, flat_updates)
    _atomic_write(meta_path, updated)
    return _StatusWrite(event, on_record or first_applied_date or "", True)


def set_status(
    meta_path: str,
    status: str,
    *,
    when: str | None = None,
    applied_on: str | None = None,
    human_confirmed: bool = False,
) -> dict[str, Any] | None:
    """Atomically write the status head and append its audit event.

    Every status is selectable regardless of the advisory transition graph.
    The sole gate is ``draft`` to ``applied``, which requires explicit human
    confirmation. A genuinely first entry into ``applied`` fills an empty
    ``date_applied`` in the same file replacement; a date already on record is
    the day of the first real submission and is never overwritten, so
    re-applying after a rejection shows up as its own ``status_changed`` event
    rather than as a new date. When history has already entered ``applied`` but
    the cache is missing, a real transition still appends its event and leaves
    the empty cache untouched rather than inventing a submission day.
    ``applied_on`` carries that calendar date independently from the event's
    ``when`` instant.

    Picking the status the application already has is not a transition: no
    event is appended and ``None`` is returned. The one write that pick can
    still make is filling a legacy ``applied`` head's empty ``date_applied``
    cache when no prior transition into ``applied`` exists. Canonical UTC event
    history cannot prove the separately supplied submission calendar day, so
    an event-backed same-status repair is refused.
    """
    if status not in APPLICATION_STATUSES:
        raise MetaEventError(
            f"unknown application status {status!r}; expected one of "
            f"{', '.join(APPLICATION_STATUSES)}"
        )
    if applied_on is not None and status != "applied":
        raise MetaEventError("applied_on is only valid when setting status to applied")
    parsed_applied_on = _validated_application_date(applied_on) if applied_on is not None else None
    event_time_request = _event_time_request(when)

    with _meta_write_transaction(meta_path):
        result = _write_status_locked(
            meta_path,
            status,
            event_time_request=event_time_request,
            applied_on=parsed_applied_on,
            human_confirmed=human_confirmed,
            confirmation_only=False,
            reject_date_conflict=parsed_applied_on is not None,
        )
    return result.event


def confirm_applied(
    meta_path: str,
    applied_on: str | None = None,
    *,
    today: datetime.date | None = None,
) -> AppliedStatusUpdate:
    explicit_date = _validated_application_date(applied_on) if applied_on is not None else None
    with _meta_write_transaction(meta_path):
        requested_date = explicit_date or today or datetime.date.today()
        result = _write_status_locked(
            meta_path,
            "applied",
            event_time_request=_EventTimeRequest(None, None),
            applied_on=requested_date,
            human_confirmed=True,
            confirmation_only=True,
            reject_date_conflict=explicit_date is not None,
        )
    return AppliedStatusUpdate(result.date_applied, result.changed)


def _atomic_write(path: str, text: str) -> None:
    temporary = f"{path}.tmp"
    with open(temporary, "w", encoding="utf-8") as handle:
        handle.write(text)
    os.replace(temporary, path)


def scaffold_from_report(
    folder: str,
    company: str,
    role: str,
    report_path: str,
    job: dict[str, Any],
    force: bool = False,
    refresh: bool = False,
) -> None:
    job_path = os.path.join(folder, "job.md")
    if os.path.exists(job_path):
        with open(job_path, encoding="utf-8") as handle:
            content = handle.read()
    else:
        content = ""
    source_path = os.path.join(folder, "source.json")
    if (
        force
        or is_job_placeholder(content, company, role)
        or existing_matches_source(content, source_path)
    ):
        if force and content.strip() and not is_job_placeholder(content, company, role):
            with open(job_path + ".bak", "w", encoding="utf-8") as handle:
                handle.write(content)
        with open(job_path, "w", encoding="utf-8") as handle:
            handle.write(imported_job_markdown(company, role, report_path, job))
    else:
        candidate_path = job_path + ".new"
        with open(candidate_path, "w", encoding="utf-8") as handle:
            handle.write(imported_job_markdown(company, role, report_path, job))
        print(f"preserved existing job.md; wrote refreshed description to {candidate_path}")

    update_meta(
        os.path.join(folder, "meta.yaml"),
        {
            "company": company,
            "role": role,
            "source": job.get("source", ""),
            "url": job.get("apply_url") or job.get("url", ""),
            "job_id": job.get("job_id", ""),
            "source_id": job.get("source_id", ""),
            "source_query": ", ".join(job.get("source_queries", [])) or job.get("source_query", ""),
            "listing_url": job.get("listing_url", ""),
            "detail_url": job.get("detail_url", ""),
            "description_source": job.get("description_source", ""),
            "discovery_score": job.get("score", 0),
            "angle": job.get("angle", ""),
            "fit_score": job.get("fit_score", 0),
            "date_fetched": job.get("retrieved_at", ""),
        },
        force=force,
        refresh=refresh,
    )
    source_needs_update = False
    if os.path.exists(source_path) and not (force or refresh):
        try:
            with open(source_path, encoding="utf-8") as handle:
                old_source = json.load(handle)
            source_needs_update = not old_source.get("job_id") or "description" not in old_source
        except (OSError, json.JSONDecodeError):
            source_needs_update = True
    if force or refresh or not os.path.exists(source_path) or source_needs_update:
        with open(source_path, "w", encoding="utf-8") as handle:
            json.dump(job, handle, ensure_ascii=False, indent=2)
            handle.write("\n")


def jobtech_ad_id(job_id: str) -> str:
    match = re.fullmatch(r"jobtech:jobsearch\.api\.jobtechdev\.se:(\d+)", job_id)
    if not match:
        raise ValueError(
            "only JobTech IDs like jobtech:jobsearch.api.jobtechdev.se:31215727 are supported"
        )
    return match.group(1)


def refresh_job(
    job: dict[str, Any], fetch_detail: Callable[[str], dict[str, Any]]
) -> dict[str, Any]:
    if job.get("source") != "jobtech":
        raise ValueError(f"refresh is not implemented for source {job.get('source', '?')!r}")
    ad_id = str(job.get("source_id", "")) or jobtech_ad_id(str(job.get("job_id", "")))
    refreshed = fetch_detail(ad_id)
    for key in ("score", "attrs", "hits", "source_query", "source_queries"):
        if key in job:
            refreshed[key] = job[key]
    return refreshed


def create_application(folder: str, company: str, role: str, date: str) -> None:
    """Create the current four-file application scaffold if files are absent."""
    os.makedirs(folder, exist_ok=True)
    files = {
        "job.md": f"# {company} — {role or 'role'}\n\n{JOB_PLACEHOLDER}\n",
        "cv.md": CV_STUB,
        "cover-letter.md": "",
        "meta.yaml": META_STUB.format(
            company=yaml_quote(company), role=yaml_quote(role), date=date
        ),
    }
    for filename, content in files.items():
        path = os.path.join(folder, filename)
        if not os.path.exists(path):
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(content)


def _catalog_day(value: Any) -> str:
    """Calendar day from a catalog timestamp or date string; empty when unusable."""
    moment = parse_timestamp(value)
    if moment is not None:
        return moment.date().isoformat()
    text = str(value or "").strip()
    return text[:10] if len(text) >= 10 and text[4] == "-" and text[7] == "-" else ""


def genesis_note_text(record: dict[str, Any], interested_day: str) -> str:
    """Free-form ``note`` text carrying catalog provenance into a new Application.

    The Application must stand alone after a later catalog GC, so this captures
    discovered day (``first_seen``), interested day, fit, and angle — the facts
    the domain model names for the genesis seed. Reuses the ``note`` kind; no
    new event kind and no catalog schema change.
    """
    discovered = _catalog_day(record.get("first_seen") or record.get("retrieved_at") or "")
    interested = _catalog_day(interested_day) or str(interested_day or "").strip()
    fit = record.get("fit_score", "")
    if fit is None or fit == "":
        fit_bit = "fit unknown"
    else:
        fit_bit = f"fit {fit}"
    angle = str(record.get("angle") or "").strip()
    angle_bit = f"{angle} angle" if angle else "unclassified angle"
    parts = ["Discovered in catalog"]
    if discovered:
        parts.append(f"first seen {discovered}")
    if interested:
        parts.append(f"interested {interested}")
    parts.append(f"{fit_bit}, {angle_bit}")
    return " · ".join(parts)


def _write_genesis_note(
    identifier: str, meta_path: str, record: dict[str, Any], interested_day: str
) -> None:
    """Append the single genesis ``note`` when the Application has no events yet.

    Runs last in :func:`scaffold_from_catalog`, after triage, so a meta this
    writer cannot extend never leaves the user's Interested action half-applied.
    A failure still surfaces — an Application without provenance must be visible
    to be retried or repaired — naming the application and the underlying cause.
    """
    if events(read_meta(meta_path)):
        return
    discovered_when = parse_timestamp(record.get("first_seen") or record.get("retrieved_at"))
    when = event_timestamp(discovered_when) if discovered_when is not None else None
    try:
        append_event(
            meta_path,
            "note",
            {"text": genesis_note_text(record, interested_day)},
            when=when,
        )
    except (MetaEventError, OSError) as error:
        raise MetaEventError(
            f"application {identifier!r} is scaffolded and triaged, but its genesis note "
            f"could not be written: {error}"
        ) from error


def scaffold_from_catalog(
    repo_root: str,
    job_id: str,
    *,
    date: str | None = None,
    applications_root: str | None = None,
) -> str:
    """Scaffold an application from a catalog record and mark triage applied.

    Returns the application folder name. Uses the cluster display winner's
    ``job_id`` but loads that winner's stored record unmodified (never a
    view-only hybrid). Catalog access and triage writes go through
    ``apply.catalog``; this is the core seam the local UI and CLI share for
    Interested → scaffold.

    Writes exactly one genesis ``note`` event carrying catalog provenance
    (discovered/interested day, fit, angle) so the Application stands alone
    if the ``by-id`` record is later garbage-collected.
    """
    view = catalog.resolve_display_record(repo_root, job_id)
    if view is None:
        raise ValueError(f"no catalog record for job id {job_id!r}")
    # Scaffolding always uses the cluster display winner's job_id and its
    # source-native catalog file — not the view-only paste/fit overlay.
    job_id = view["job_id"]
    record = catalog.load_record(repo_root, job_id)
    if record is None:
        raise ValueError(f"no catalog record for job id {job_id!r}")
    company = str(record.get("company", "")).strip()
    if not company:
        raise ValueError(f"catalog record {job_id!r} has no company")
    role = str(record.get("title", "")).strip() or "role"
    day = date or datetime.date.today().isoformat()
    apps_root = applications_root or os.path.join(repo_root, "applications")
    identifier = application_identifier(day, company, role, job_id, apps_root)
    folder = os.path.join(apps_root, identifier)
    # Refuse to write into a folder that belongs to a different job.
    if os.path.isdir(folder):
        existing = str(read_meta(os.path.join(folder, "meta.yaml")).get("job_id") or "")
        if existing and existing != job_id:
            raise ValueError(
                f"application folder {identifier!r} belongs to job {existing!r}, not {job_id!r}"
            )
    create_application(folder, company, role, day)
    scaffold_from_report(folder, company, role, "", dict(record), force=False, refresh=True)
    catalog.set_triage(repo_root, job_id, "applied", application=identifier)
    _write_genesis_note(identifier, os.path.join(folder, "meta.yaml"), record, day)
    return identifier

"""Local Flask UI adapter for the file-backed application workflow."""

from __future__ import annotations

import datetime
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import markdown
import yaml
from flask import Flask, abort, current_app, redirect, render_template, request, send_file, url_for
from markupsafe import Markup

from . import applications, catalog, jobs, queue, workflow

HEALTH_PATH = "/healthz"
HEALTH_TOKEN = "apply-local-ui"
TEXT_ARTIFACTS = (
    "job.md",
    "meta.yaml",
    "cv-analysis.md",
    "cv-feedback.md",
    "cv-draft.md",
    "cv-review.md",
    "cv.md",
)
EDITABLE_ARTIFACTS = frozenset({"cv-analysis.md", "cv-feedback.md"})
PDF_ARTIFACTS = frozenset({"cv-draft.pdf", "cv.pdf"})
DESCRIPTION_PREVIEW_CHARS = 240
CARD_BLURB_CHARS = 150
TRIAGE_BUCKETS = ("open", "closing", "interested", "skipped")
DEFAULT_TRIAGE_BUCKETS = ("open", "closing", "interested")
TRIAGE_SUBMITTED_PARAM = "triage_submitted"
TRIAGE_SUBMITTED_VALUE = "1"
PINNED_JOB_PARAM = "pin"
JOB_SORTS = ("fit", "deadline", "newest")
INTENT_SCREENS = ("jobs", "applications", "application")
APPLICATION_EVENT_INTENT_KEYS = {
    **{kind: f"event_{kind}" for kind in applications.EVENT_KINDS},
    "event": "event_event",
}
APPLICATION_MOMENT_INTENT_KEYS = {
    **{field: f"moment_{field}" for field in applications.FLAT_DATED_FIELDS},
    "workspace": "moment_workspace",
}
SCREEN_INTENT_KEYS = {
    "jobs": frozenset({"screen", "filters", "feed", "detail"}),
    "applications": frozenset({"screen", "application_list", "status", "workflow", "fit"}),
    "application": frozenset(
        {
            "screen",
            "job_card",
            "status",
            "events",
            *APPLICATION_EVENT_INTENT_KEYS.values(),
            *APPLICATION_MOMENT_INTENT_KEYS.values(),
        }
    ),
}
_NUMERIC_CLAIM_RE = re.compile(
    r"(?<!\w)(?:~\s*)?\d+(?:[.,]\d+)?\s*(?:years?|months?|weeks?|days?|%|x)\b",
    flags=re.IGNORECASE,
)
_REVIEW_GATE_RE = re.compile(r"^- \*\*(PASS|FAIL) — (.+?):\*\* (.+)$")
_REVIEW_ACTION_RE = re.compile(r"^  - Action: (.+)$")

FLAT_MOMENT_PRESENTATION = {
    "date_fetched": ("Posting fetched", "JF"),
    "date_created": ("Application created", "AC"),
    "date_applied": ("Application submitted", "AS"),
    "draft_started_at": ("Draft started", "DR"),
    "last_checked_at": ("Draft checked", "CK"),
    "finalized_at": ("Application finalized", "FN"),
}

SHELL_DEMO_ROWS = (
    {
        "key": "rail",
        "title": "Rail column",
        "caption": "40% · skim surface",
        "body": (
            "The left column is a nested scroll container holding rows. A screen fills the "
            "rail block; the shell owns the width, the scroller, and the row chrome."
        ),
    },
    {
        "key": "detail",
        "title": "Detail column",
        "caption": "60% · read surface",
        "body": (
            "The right column reads the selected row. Selection is a plain server-rendered "
            "navigation: no client-side framework holds any state."
        ),
    },
    {
        "key": "place-keeping",
        "title": "Place-keeping",
        "caption": "fragments + PRG anchors",
        "body": (
            "Each row links to its own #anchor, so after the full-page reload the browser "
            "scrolls the clicked row back into view inside the rail. Writes redirect to the "
            "same anchored URL, so a refresh never re-submits."
        ),
    },
)


def anchor_id(prefix: str, value: str) -> str:
    """Stable fragment id for a rail row, safe for both a URL and a DOM id."""
    slug = re.sub(r"[^A-Za-z0-9_-]+", "-", str(value)).strip("-")
    return f"{prefix}-{slug}" if slug else prefix


def anchored_url(endpoint: str, anchor: str, **values: Any) -> str:
    """URL for `endpoint` with the rail anchor attached, for links and PRG redirects."""
    return f"{url_for(endpoint, **values)}#{anchor}"


def application_event_url(identifier: str, selected_key: str, **values: Any) -> str:
    """Application detail URL that keeps the selected timeline row across PRG."""
    if not selected_key:
        return url_for("view_application", identifier=identifier, **values)
    return anchored_url(
        "view_application",
        anchor_id("event", selected_key),
        identifier=identifier,
        event=selected_key,
        **values,
    )


@dataclass(frozen=True)
class ApplicationSummary:
    """Metadata needed to choose an application from the local index."""

    identifier: str
    company: str
    role: str
    status: str
    workflow_state: str
    fit_score: str
    draft_iteration: str
    apply_url: str
    standing_summary: str


@dataclass(frozen=True)
class TimelineItem:
    """One rail row sourced from a flat workflow moment or stored event."""

    key: str
    when: str
    when_label: str
    sort_at: datetime.datetime
    title: str
    subtitle: str
    lead: str
    source: str
    kind: str
    field: str
    event: dict[str, Any]
    info_key: str


@dataclass(frozen=True)
class IntentEntry:
    """Authored what/why/how copy for one screen element."""

    what: str
    why: str
    how: str
    ref: str


@dataclass(frozen=True)
class ScreenIntent:
    """One screen's element intents and rendered narrative body."""

    elements: dict[str, IntentEntry]
    narrative_html: Markup


def load_screen_intent(path: str | Path) -> ScreenIntent:
    """Load one Markdown-with-YAML-frontmatter screen intent at request time."""
    source = Path(path).read_text(encoding="utf-8")
    if not source.startswith("---\n"):
        raise ValueError(f"intent file has no YAML frontmatter: {path}")
    frontmatter, separator, narrative = source[4:].partition("\n---\n")
    if not separator:
        raise ValueError(f"intent file has no closing frontmatter delimiter: {path}")
    raw_elements = yaml.safe_load(frontmatter)
    if not isinstance(raw_elements, dict) or not raw_elements:
        raise ValueError(f"intent frontmatter must be an element-keyed map: {path}")
    required = ("what", "why", "how", "ref")
    elements: dict[str, IntentEntry] = {}
    for key, raw_entry in raw_elements.items():
        if not isinstance(key, str) or not isinstance(raw_entry, dict):
            raise ValueError(f"intent element {key!r} must be a map: {path}")
        missing = [field for field in required if not isinstance(raw_entry.get(field), str)]
        if missing:
            raise ValueError(
                f"intent element {key!r} is missing string fields {', '.join(missing)}: {path}"
            )
        elements[key] = IntentEntry(**{field: raw_entry[field] for field in required})
    return ScreenIntent(
        elements=elements,
        narrative_html=Markup(markdown.markdown(narrative.strip(), extensions=["extra"])),
    )


@dataclass(frozen=True)
class JobFeedFilters:
    """Validated query-parameter state for the Jobs feed.

    ``pinned_job_id`` keeps one job in the feed regardless of its triage bucket,
    so a row acted on from the detail pane keeps its `#job-<id>` place without
    widening the buckets the user asked for.
    """

    angles: tuple[str, ...] = ()
    min_fit: int = 0
    triage: tuple[str, ...] = DEFAULT_TRIAGE_BUCKETS
    sort: str = "fit"
    pinned_job_id: str = ""

    def url_values(self) -> dict[str, Any]:
        """Query values for `url_for`; `None` entries are dropped from the URL."""
        return {
            "angle": self.angles,
            "min_fit": self.min_fit,
            "triage": self.triage,
            TRIAGE_SUBMITTED_PARAM: None if self.triage else TRIAGE_SUBMITTED_VALUE,
            "sort": self.sort,
            PINNED_JOB_PARAM: self.pinned_job_id or None,
        }


def _metadata_text(metadata: dict[str, Any], key: str) -> str:
    value = metadata.get(key, "")
    return "" if value is None else str(value)


def _summary_for_path(path: Path, metadata: dict[str, Any] | None = None) -> ApplicationSummary:
    if metadata is None:
        metadata = applications.read_meta(str(path / "meta.yaml"))
    return ApplicationSummary(
        identifier=path.name,
        company=_metadata_text(metadata, "company") or path.name,
        role=_metadata_text(metadata, "role"),
        status=_metadata_text(metadata, "status") or "unknown",
        workflow_state=_metadata_text(metadata, "workflow_state") or "unknown",
        fit_score=_metadata_text(metadata, "fit_score") or "—",
        draft_iteration=_metadata_text(metadata, "draft_iteration") or "1",
        apply_url=_metadata_text(metadata, "url") or _metadata_text(metadata, "listing_url"),
        standing_summary=applications.summary(metadata),
    )


def _timeline_when_label(value: Any) -> str:
    moment = applications.parse_timestamp(value)
    if moment is None:
        return str(value or "Unknown time")
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(value)):
        return moment.strftime("%d %b %Y")
    return moment.strftime("%d %b %Y, %H:%M UTC")


def _event_presentation(event: dict[str, Any]) -> tuple[str, str, str]:
    kind = str(event.get("kind") or "event")
    if kind == "status_changed":
        before = str(event.get("from") or "unknown").capitalize()
        after = str(event.get("to") or "unknown").capitalize()
        return "Status changed", f"{before} to {after}", "ST"
    if kind == "email":
        subject = str(event.get("subject") or "Email")
        direction = str(event.get("direction") or "Email").capitalize()
        correspondent = event.get("from") if direction == "Incoming" else event.get("to")
        subtitle = f"{direction}"
        if correspondent:
            subtitle += (
                f" from {correspondent}" if direction == "Incoming" else f" to {correspondent}"
            )
        return subject, subtitle, "EM"
    if kind == "link":
        return str(event.get("label") or "Saved link"), "External link", "LK"
    if kind == "note":
        text = re.sub(r"\s+", " ", str(event.get("text") or "Note")).strip()
        title = text if len(text) <= 54 else f"{text[:51].rstrip()}..."
        return title, "Note", "NT"
    return kind.replace("_", " ").capitalize(), "Application event", "EV"


def application_timeline(metadata: dict[str, Any]) -> tuple[TimelineItem, ...]:
    """Combine flat dated moments and stored events into one newest-first rail."""
    items: list[tuple[datetime.datetime, int, TimelineItem]] = []
    order = 0
    for field in applications.FLAT_DATED_FIELDS:
        value = metadata.get(field)
        if value in (None, ""):
            continue
        title, lead = FLAT_MOMENT_PRESENTATION[field]
        when = str(value)
        sort_at = applications.parse_timestamp(value) or applications.EPOCH
        item = TimelineItem(
            key=f"moment-{field}",
            when=when,
            when_label=_timeline_when_label(value),
            sort_at=sort_at,
            title=title,
            subtitle="Workflow moment",
            lead=lead,
            source="moment",
            kind="workflow",
            field=field,
            event={},
            info_key=APPLICATION_MOMENT_INTENT_KEYS[field],
        )
        items.append((sort_at, order, item))
        order += 1

    for index, event in applications.indexed_events(metadata):
        title, subtitle, lead = _event_presentation(event)
        value = event.get("when")
        sort_at = applications.parse_timestamp(value) or applications.EPOCH
        item = TimelineItem(
            key=f"event-{index}",
            when=str(value or ""),
            when_label=_timeline_when_label(value),
            sort_at=sort_at,
            title=title,
            subtitle=subtitle,
            lead=lead,
            source="event",
            kind=str(event.get("kind") or "event"),
            field="",
            event=event,
            info_key=APPLICATION_EVENT_INTENT_KEYS.get(
                str(event.get("kind") or "event"), APPLICATION_EVENT_INTENT_KEYS["event"]
            ),
        )
        items.append((sort_at, order, item))
        order += 1

    items.sort(key=lambda entry: (entry[0], entry[1]), reverse=True)
    # Always expose one stable files/workspace entry so artifact editors and
    # workflow actions are reachable even when dated moments exist but
    # draft/check/finalize have not been written yet.
    workspace = TimelineItem(
        key="moment-workspace",
        when="",
        when_label="Files and workflow",
        sort_at=applications.EPOCH,
        title="Application workspace",
        subtitle="Files and actions",
        lead="AP",
        source="moment",
        kind="workflow",
        field="workspace",
        event={},
        info_key=APPLICATION_MOMENT_INTENT_KEYS["workspace"],
    )
    return (*(item for _, _, item in items), workspace)


def read_event_payload(application: str | Path, event: dict[str, Any]) -> str:
    """Read a selected event's sibling payload without allowing path traversal."""
    ref = str(event.get("ref") or "").strip()
    if not ref:
        return ""
    root = Path(application).resolve()
    candidate = (root / ref).resolve()
    if candidate == root or root not in candidate.parents or not candidate.is_file():
        return ""
    try:
        return candidate.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return ""


def analysis_draft_findings(analysis: str, draft: str) -> tuple[str, ...]:
    """Return advisory numeric claims present in analysis but absent from draft."""
    draft_text = draft.casefold()
    findings = []
    seen: set[str] = set()
    for match in _NUMERIC_CLAIM_RE.finditer(analysis):
        claim = re.sub(r"\s+", " ", match.group(0)).strip()
        normalized = claim.casefold()
        if normalized in seen or normalized in draft_text:
            continue
        seen.add(normalized)
        findings.append(
            f'cv-analysis.md mentions "{claim}", but cv-draft.md does not include it. '
            "The check will not transfer it automatically."
        )
    return tuple(findings)


def final_snapshot_status(application: Path, draft: str) -> dict[str, str]:
    """Describe whether the approved Markdown snapshot matches the current draft."""
    final_path = application / workflow.FINAL_NAME
    if not final_path.is_file():
        return {
            "kind": "missing",
            "label": "No final snapshot",
            "detail": "cv.md has not been created yet; approval will create it from the passing draft.",
        }
    try:
        current = final_path.read_text(encoding="utf-8")
    except OSError:
        return {
            "kind": "warning",
            "label": "Final snapshot unavailable",
            "detail": "cv.md could not be read for comparison.",
        }
    if current == draft:
        return {
            "kind": "current",
            "label": "Final snapshot matches draft",
            "detail": "cv.md currently matches cv-draft.md. A later draft edit will make the final snapshot stale.",
        }
    return {
        "kind": "stale",
        "label": "Final snapshot is stale",
        "detail": "cv.md differs from cv-draft.md. The approved final PDF does not represent the current draft until approval is run again.",
    }


def read_review_result(application: str | Path) -> workflow.CheckResult | None:
    """Read the latest persisted gate report without running the workflow again."""
    review_path = Path(application) / workflow.REVIEW_NAME
    if not review_path.is_file():
        return None
    try:
        lines = review_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    gates: list[workflow.Gate] = []
    current: workflow.Gate | None = None
    for line in lines:
        match = _REVIEW_GATE_RE.match(line)
        if match:
            if current is not None:
                gates.append(current)
            current = workflow.Gate(
                match.group(2),
                match.group(1) == "PASS",
                match.group(3),
            )
            continue
        action = _REVIEW_ACTION_RE.match(line)
        if action and current is not None:
            current = workflow.Gate(
                current.name,
                current.passed,
                current.detail,
                (*current.findings, action.group(1)),
            )
    if current is not None:
        gates.append(current)
    if not gates:
        return None
    return workflow.CheckResult(workflow.WorkflowPaths.for_application(application), tuple(gates))


def list_applications(root: str | Path) -> tuple[ApplicationSummary, ...]:
    """List immediate application folders, newest activity first."""
    applications_root = Path(root).expanduser()
    if not applications_root.is_dir():
        return ()
    ranked_summaries = []
    for path in applications_root.iterdir():
        if not path.is_dir() or path.name.startswith("."):
            continue
        metadata = applications.read_meta(str(path / "meta.yaml"))
        ranked_summaries.append(
            (
                applications.activity_sort_key(path.name, metadata),
                _summary_for_path(path, metadata),
            )
        )
    ranked_summaries.sort(key=lambda entry: entry[0], reverse=True)
    return tuple(summary for _, summary in ranked_summaries)


def list_draft_versions(application: str | Path) -> tuple[dict[str, str], ...]:
    """List archived draft directories without creating or mutating versions."""
    versions_root = Path(application) / "drafts"
    if not versions_root.is_dir():
        return ()
    versions = []
    for path in sorted(versions_root.iterdir(), key=lambda item: item.name):
        if not path.is_dir():
            continue
        versions.append(
            {
                "identifier": path.name,
                "draft": "present" if (path / "cv-draft.md").is_file() else "missing",
                "pdf": "present" if (path / "cv-draft.pdf").is_file() else "missing",
            }
        )
    return tuple(versions)


def application_path(root: str | Path, identifier: str) -> Path:
    """Resolve one immediate application folder without allowing traversal."""
    applications_root = Path(root).expanduser().resolve()
    candidate = (applications_root / identifier).resolve()
    if candidate.parent != applications_root or not candidate.is_dir():
        raise KeyError(identifier)
    return candidate


def read_artifacts(application: str | Path) -> dict[str, str]:
    """Read the text artifacts exposed by the local UI."""
    application_dir = Path(application)
    return {
        filename: (
            (application_dir / filename).read_text(encoding="utf-8")
            if (application_dir / filename).is_file()
            else ""
        )
        for filename in TEXT_ARTIFACTS
    }


def save_editable_artifact(application: str | Path, filename: str, content: str) -> Path:
    """Persist only the two human-editable workflow artifacts."""
    if filename not in EDITABLE_ARTIFACTS:
        raise ValueError("only cv-analysis.md and cv-feedback.md can be edited")
    path = Path(application) / filename
    if not path.parent.is_dir():
        raise FileNotFoundError(path.parent)
    path.write_text(content, encoding="utf-8")
    return path


def _render_application(
    application: Path,
    *,
    selected_key: str = "",
    message: str = "",
    error: str = "",
    check_result: workflow.CheckResult | None = None,
    status_code: int = 200,
):
    metadata = applications.read_meta(str(application / "meta.yaml"))
    summary = _summary_for_path(application, metadata)
    timeline = application_timeline(metadata)
    selected = next((item for item in timeline if item.key == selected_key), None)
    if selected is None and timeline:
        selected = timeline[0]
    artifacts = read_artifacts(application)
    displayed_check_result = check_result or read_review_result(application)
    intent = _screen_intent(current_app, "application")
    try:
        natural_statuses = applications.advisory_next_statuses(summary.status)
    except applications.MetaEventError:
        natural_statuses = ()
    return (
        render_template(
            "application.html",
            summary=summary,
            timeline=timeline,
            selected=selected,
            status_options=tuple(
                {
                    "value": status,
                    "natural": status in natural_statuses,
                }
                for status in applications.APPLICATION_STATUSES
            ),
            artifacts=artifacts,
            editable_artifacts=EDITABLE_ARTIFACTS,
            pdf_available={
                filename: (application / filename).is_file() for filename in PDF_ARTIFACTS
            },
            message=message,
            error=error,
            check_result=displayed_check_result,
            draft_versions=list_draft_versions(application),
            alignment_findings=analysis_draft_findings(
                artifacts["cv-analysis.md"], artifacts["cv-draft.md"]
            ),
            final_snapshot=final_snapshot_status(application, artifacts["cv-draft.md"]),
            event_payload=(
                read_event_payload(application, selected.event)
                if selected is not None and selected.source == "event"
                else ""
            ),
            screen_intent=intent,
        ),
        status_code,
    )


def catalog_now(app: Flask) -> str:
    """Clock for closing-soon / stale views; tests inject ``CATALOG_NOW``."""
    configured = app.config.get("CATALOG_NOW")
    if configured:
        return str(configured)
    return datetime.datetime.now(datetime.UTC).replace(microsecond=0).isoformat()


def parse_job_feed_filters(args: Any) -> JobFeedFilters:
    """Parse and validate the Jobs screen's repeated query parameters."""
    angles = tuple(dict.fromkeys(value for value in args.getlist("angle") if value))
    requested_triage = tuple(
        dict.fromkeys(value for value in args.getlist("triage") if value in TRIAGE_BUCKETS)
    )
    # Unchecking every Triage box submits the sentinel and no bucket: an empty
    # feed the user asked for, not "no preference expressed".
    submitted = bool(requested_triage) or args.get(TRIAGE_SUBMITTED_PARAM) == TRIAGE_SUBMITTED_VALUE
    triage = requested_triage if submitted else DEFAULT_TRIAGE_BUCKETS
    try:
        min_fit = int(args.get("min_fit", 0))
    except (TypeError, ValueError):
        min_fit = 0
    min_fit = min(max(min_fit, 0), 5)
    requested_sort = args.get("sort", "fit")
    sort = requested_sort if requested_sort in JOB_SORTS else "fit"
    return JobFeedFilters(
        angles=angles,
        min_fit=min_fit,
        triage=triage,
        sort=sort,
        pinned_job_id=args.get(PINNED_JOB_PARAM, ""),
    )


def job_triage_bucket(record: dict[str, Any], now: str) -> str:
    """Map one flat catalog record to its mutually exclusive UI filter bucket."""
    triage = record.get("triage", "open")
    if triage in ("interested", "applied"):
        return "interested"
    if triage == "skipped":
        return "skipped"
    if catalog.is_closing_soon(record, now):
        return "closing"
    return "open"


def sort_job_feed(records: list[dict[str, Any]], sort: str, now: str) -> list[dict[str, Any]]:
    """Sort a flat feed deterministically by the user-selected ranking."""
    if sort == "deadline":
        return sorted(
            records,
            key=lambda item: (
                (remaining := catalog.days_until_deadline(item, now)) is None or remaining < 0,
                remaining if remaining is not None and remaining >= 0 else 10**9,
                -catalog.rank_fit_score(item),
                item.get("job_id", ""),
            ),
        )
    if sort == "newest":
        return sorted(
            records,
            key=lambda item: (
                item.get("first_seen") or "",
                catalog.rank_fit_score(item),
                item.get("score", 0),
                item.get("job_id", ""),
            ),
            reverse=True,
        )
    ordered = sorted(records, key=lambda item: item.get("job_id", ""))
    ordered.sort(key=lambda item: item.get("first_seen") or "", reverse=True)
    ordered.sort(key=lambda item: item.get("score", 0), reverse=True)
    ordered.sort(key=catalog.rank_fit_score, reverse=True)
    return ordered


def is_pinned_job(record: dict[str, Any], filters: JobFeedFilters) -> bool:
    """True for the single job pinned into the feed by a Skip redirect."""
    return bool(filters.pinned_job_id) and record.get("job_id") == filters.pinned_job_id


def filter_job_feed(
    records: list[dict[str, Any]], filters: JobFeedFilters, now: str
) -> list[dict[str, Any]]:
    """Filter and sort active catalog view records into one ranked feed."""
    filtered = [
        record
        for record in records
        if is_pinned_job(record, filters)
        or (
            (not filters.angles or record.get("angle", "") in filters.angles)
            and catalog.rank_fit_score(record) >= filters.min_fit
            and job_triage_bucket(record, now) in filters.triage
        )
    ]
    return sort_job_feed(filtered, filters.sort, now)


def job_feed_empty_reason(
    catalog_records: list[dict[str, Any]], view_records: list[dict[str, Any]]
) -> str:
    """Which empty state to explain, so the advice matches what actually helps.

    Filters can only ever widen over the non-stale records the feed is built from,
    so an all-stale catalog needs a fetch, not a wider filter.
    """
    if not catalog_records:
        return "no-catalog"
    if not view_records:
        return "all-stale"
    return "filtered"


def description_blurb(record: dict[str, Any]) -> str:
    """Return a compact, whitespace-normalized posting preview for a feed card."""
    description = " ".join(str(record.get("description") or "").split())
    if len(description) <= CARD_BLURB_CHARS:
        return description
    shortened = description[:CARD_BLURB_CHARS].rsplit(" ", 1)[0].rstrip(" .")
    return f"{shortened}..."


def fit_breakdown_line(record: dict[str, Any]) -> str:
    breakdown = record.get("fit_breakdown") or {}
    return (
        f"angle:{breakdown.get('angle', 0)} / "
        f"seniority:{breakdown.get('seniority', 0)} / "
        f"rn:{breakdown.get('rn', 0)}"
    )


def attrs_line(record: dict[str, Any]) -> str:
    attrs = record.get("attrs") or {}
    if not attrs:
        return ""
    try:
        return jobs.fmt_attrs(attrs)
    except (KeyError, TypeError):
        return ""


def job_detail_context(record: dict[str, Any], watermark: str, now: str) -> dict[str, Any]:
    """Presentation fields for the /jobs right pane."""
    description = str(record.get("description") or "")
    remaining = catalog.days_until_deadline(record, now)
    label = catalog.freshness_label(record, watermark)
    return {
        "record": record,
        "fit_breakdown_line": fit_breakdown_line(record),
        "attrs_line": attrs_line(record),
        "freshness": label,
        "is_new": label == "New" and record.get("triage", "open") == "open",
        "is_updated": label == "Updated",
        "is_closing_soon": catalog.is_closing_soon(record, now),
        "days_left": remaining,
        "description": description,
        "description_preview": description[:DESCRIPTION_PREVIEW_CHARS],
        "description_long": len(description) > DESCRIPTION_PREVIEW_CHARS,
        "posting_url": record.get("apply_url") or record.get("url") or "",
    }


def jobs_page_context(
    repo_root: str | Path,
    *,
    selected_job_id: str = "",
    now: str,
    filters: JobFeedFilters | None = None,
    error: str = "",
) -> dict[str, Any]:
    root = str(Path(repo_root).expanduser().resolve())
    watermark = catalog.load_watermark(root)
    active_filters = filters or JobFeedFilters()
    catalog_records = catalog.load_records(root)
    view_records = [
        record
        for record in catalog.cluster_view_records(catalog_records)
        if not catalog.is_stale(record, now)
    ]
    feed_records = filter_job_feed(view_records, active_filters, now)
    selected = None
    if selected_job_id:
        selected = next(
            (record for record in feed_records if record["job_id"] == selected_job_id),
            None,
        )
        if selected is None:
            selected = catalog.resolve_display_record(root, selected_job_id)
    if selected is None and feed_records:
        selected = feed_records[0]
    detail = job_detail_context(selected, watermark, now) if selected else None
    return {
        "feed": [
            {
                **job_detail_context(record, watermark, now),
                "blurb": description_blurb(record),
                "triage_bucket": job_triage_bucket(record, now),
            }
            for record in feed_records
        ],
        "selected": detail,
        "selected_job_id": selected["job_id"] if selected else "",
        "watermark": watermark,
        "job_count": len(feed_records),
        "feed_empty_reason": job_feed_empty_reason(catalog_records, view_records),
        "filters": active_filters,
        "filter_query": active_filters.url_values(),
        "angle_options": tuple(
            sorted({str(record.get("angle")) for record in view_records if record.get("angle")})
        ),
        "min_fit_options": tuple(range(6)),
        "triage_options": TRIAGE_BUCKETS,
        "sort_options": JOB_SORTS,
        "error": error,
    }


def _render_jobs(
    app: Flask,
    *,
    selected_job_id: str = "",
    filters: JobFeedFilters | None = None,
    error: str = "",
    status_code: int = 200,
):
    active_filters = filters or parse_job_feed_filters(request.args)
    context = jobs_page_context(
        app.config["REPO_ROOT"],
        selected_job_id=selected_job_id,
        now=catalog_now(app),
        filters=active_filters,
        error=error,
    )
    return (
        render_template(
            "jobs.html",
            **context,
            screen_intent=_screen_intent(app, "jobs"),
        ),
        status_code,
    )


def _screen_intent(app: Flask, screen: str) -> ScreenIntent:
    """Resolve a canonical screen's authored intent from the active repository."""
    if screen not in INTENT_SCREENS:
        raise ValueError(f"unknown canonical screen: {screen}")
    path = Path(app.config["INTENT_ROOT"]) / f"{screen}.md"
    if not path.is_file():
        path = Path(app.config["FALLBACK_INTENT_ROOT"]) / f"{screen}.md"
    intent = load_screen_intent(path)
    missing = SCREEN_INTENT_KEYS[screen].difference(intent.elements)
    if missing:
        raise ValueError(f"intent file is missing UI elements {', '.join(sorted(missing))}: {path}")
    return intent


def create_app(repo_root: str | Path) -> Flask:
    """Create the local UI, rooted at one repository and its applications folder."""
    root = Path(repo_root).expanduser().resolve()
    template_root = Path(__file__).resolve().parents[2] / "templates" / "local_ui"
    app = Flask(
        __name__,
        template_folder=str(template_root),
        static_folder=str(template_root / "static"),
        static_url_path="/static",
    )
    app.config.update(
        REPO_ROOT=root,
        APPLICATIONS_ROOT=root / "applications",
        INTENT_ROOT=root / "docs" / "intent",
        FALLBACK_INTENT_ROOT=Path(__file__).resolve().parents[2] / "docs" / "intent",
        PROFILE_PATH=None,
        CATALOG_NOW=None,
        STATUS_NOW=None,
    )
    app.jinja_env.globals["anchor_id"] = anchor_id

    def current_application(identifier: str) -> Path:
        try:
            return application_path(app.config["APPLICATIONS_ROOT"], identifier)
        except KeyError:
            abort(404)

    @app.get("/healthz")
    def healthz():
        """Identify this server as the apply UI, not merely something on the port."""
        return HEALTH_TOKEN, 200, {"Content-Type": "text/plain; charset=utf-8"}

    @app.get("/")
    def index():
        return render_template(
            "index.html",
            applications=list_applications(app.config["APPLICATIONS_ROOT"]),
            screen_intent=_screen_intent(app, "applications"),
        )

    @app.get("/shell")
    def shell_demo():
        """Render the shared two-pane shell standalone, with example rows only."""
        requested = request.args.get("item", "")
        selected = next(
            (row for row in SHELL_DEMO_ROWS if row["key"] == requested),
            SHELL_DEMO_ROWS[0],
        )
        return render_template(
            "shell_demo.html",
            items=SHELL_DEMO_ROWS,
            selected=selected,
        )

    @app.get("/jobs")
    def jobs_index():
        return _render_jobs(app)

    @app.get("/jobs/<path:job_id>")
    def jobs_detail(job_id: str):
        root = str(app.config["REPO_ROOT"])
        record = catalog.resolve_display_record(root, job_id)
        if record is None:
            abort(404)
        try:
            catalog.acknowledge(root, record["job_id"], at=catalog_now(app))
        except ValueError:
            abort(404)
        return _render_jobs(app, selected_job_id=record["job_id"])

    @app.post("/jobs/<path:job_id>/interested")
    def jobs_interested(job_id: str):
        try:
            identifier = applications.scaffold_from_catalog(
                str(app.config["REPO_ROOT"]),
                job_id,
                applications_root=str(app.config["APPLICATIONS_ROOT"]),
            )
        except ValueError as error:
            return _render_jobs(
                app,
                selected_job_id=job_id,
                error=str(error),
                status_code=400,
            )
        return redirect(url_for("view_application", identifier=identifier))

    @app.post("/jobs/<path:job_id>/skip")
    def jobs_skip(job_id: str):
        reason = (request.form.get("reason") or "").strip()
        if not reason:
            return _render_jobs(
                app,
                selected_job_id=job_id,
                error="Skip requires a reason",
                status_code=400,
            )
        try:
            catalog.set_triage(
                str(app.config["REPO_ROOT"]),
                job_id,
                "skipped",
                skip_reason=reason,
            )
        except ValueError as error:
            return _render_jobs(
                app,
                selected_job_id=job_id,
                error=str(error),
                status_code=400,
            )
        # PRG: answer the write with a redirect to the anchored detail URL, so a
        # refresh cannot re-submit the skip and the row keeps its place in the rail.
        # The skipped job is pinned rather than its bucket unhidden, so the filters
        # the user submitted stay exactly as they were.
        filters = parse_job_feed_filters(request.args)
        redirect_filters = replace(filters, pinned_job_id=job_id)
        return redirect(
            anchored_url(
                "jobs_detail",
                anchor_id("job", job_id),
                job_id=job_id,
                **redirect_filters.url_values(),
            )
        )

    @app.post("/jobs/enqueue")
    def enqueue_jobs_command():
        """Drop a Jobs-target queue request; never calls a provider or skill."""
        command_type = (request.form.get("type") or "").strip()
        if command_type not in queue.JOBS_CATALOG_COMMAND_TYPES:
            return _render_jobs(
                app,
                error=(
                    f"unknown Jobs queue command {command_type!r}; expected one of "
                    f"{', '.join(sorted(queue.JOBS_CATALOG_COMMAND_TYPES))}"
                ),
                status_code=400,
            )
        try:
            queue.enqueue(app.config["REPO_ROOT"], command_type, target=None)
        except queue.QueueError as error:
            return _render_jobs(app, error=str(error), status_code=400)
        filters = parse_job_feed_filters(request.args)
        return redirect(url_for("jobs_index", **filters.url_values()))

    @app.get("/applications/<identifier>")
    def view_application(identifier: str):
        return _render_application(
            current_application(identifier),
            selected_key=request.args.get("event", ""),
        )

    @app.post("/applications/<identifier>/enqueue")
    def enqueue_application_command(identifier: str):
        """Drop an Application-target queue request; never calls a provider or skill."""
        application = current_application(identifier)
        selected_key = request.form.get("selected_event", "")
        command_type = (request.form.get("type") or "").strip()
        if command_type not in queue.APPLICATION_COMMAND_TYPES:
            return _render_application(
                application,
                selected_key=selected_key,
                error=(
                    f"unknown Application queue command {command_type!r}; expected one of "
                    f"{', '.join(sorted(queue.APPLICATION_COMMAND_TYPES))}"
                ),
                status_code=400,
            )
        try:
            queue.enqueue(
                app.config["REPO_ROOT"],
                command_type,
                target=queue.app_target(identifier),
            )
        except queue.QueueError as error:
            return _render_application(
                application,
                selected_key=selected_key,
                error=str(error),
                status_code=400,
            )
        return redirect(application_event_url(identifier, selected_key))

    @app.post("/applications/<identifier>/status")
    def update_application_status(identifier: str):
        application = current_application(identifier)
        status = request.form.get("status", "")
        metadata = applications.read_meta(str(application / "meta.yaml"))
        stored_events = metadata.get("events")
        event_index = len(stored_events) if isinstance(stored_events, list) else 0
        try:
            event = applications.set_status(
                str(application / "meta.yaml"),
                status,
                when=app.config["STATUS_NOW"],
                human_confirmed=True,
            )
        except applications.MetaEventError as error:
            return _render_application(
                application,
                selected_key=request.form.get("selected_event", ""),
                error=str(error),
                status_code=400,
            )
        if event is None:
            return redirect(
                application_event_url(identifier, request.form.get("selected_event", ""))
            )
        selected_key = f"event-{event_index}"
        return redirect(application_event_url(identifier, selected_key))

    @app.post("/applications/<identifier>/artifacts/<filename>")
    def edit_artifact(identifier: str, filename: str):
        application = current_application(identifier)
        selected_key = request.form.get("selected_event", "")
        try:
            save_editable_artifact(application, filename, request.form.get("content", ""))
        except ValueError as error:
            return _render_application(
                application,
                selected_key=selected_key,
                error=str(error),
                status_code=400,
            )
        return _render_application(
            application,
            selected_key=selected_key,
            message=f"Saved {filename}.",
        )

    @app.post("/applications/<identifier>/check")
    def check_application(identifier: str):
        application = current_application(identifier)
        selected_key = request.form.get("selected_event", "")
        try:
            result = workflow.check(
                application,
                profile_path=app.config["PROFILE_PATH"],
            )
        except workflow.WorkflowError as error:
            return _render_application(
                application,
                selected_key=selected_key,
                error=str(error),
                status_code=409,
            )
        return _render_application(
            application,
            selected_key=selected_key,
            message="Check completed.",
            check_result=result,
        )

    @app.post("/applications/<identifier>/approve")
    def approve_application(identifier: str):
        application = current_application(identifier)
        selected_key = request.form.get("selected_event", "")
        if request.form.get("confirm") != "approve":
            return _render_application(
                application,
                selected_key=selected_key,
                error="Explicit approval confirmation is required.",
                status_code=400,
            )
        try:
            result = workflow.finalize(
                application,
                profile_path=app.config["PROFILE_PATH"],
                approve=True,
            )
        except workflow.WorkflowError as error:
            failed_result = None
            try:
                failed_result = workflow.check(
                    application,
                    profile_path=app.config["PROFILE_PATH"],
                )
            except workflow.WorkflowError:
                pass
            return _render_application(
                application,
                selected_key=selected_key,
                error=str(error),
                check_result=failed_result,
                status_code=409,
            )
        return _render_application(
            application,
            selected_key=selected_key,
            message="Approval completed: cv.md and cv.pdf were promoted.",
            check_result=result,
        )

    @app.get("/applications/<identifier>/files/<filename>")
    def pdf_artifact(identifier: str, filename: str):
        if filename not in PDF_ARTIFACTS:
            abort(404)
        path = current_application(identifier) / filename
        if not path.is_file():
            abort(404)
        return send_file(path, mimetype="application/pdf", as_attachment=False)

    return app

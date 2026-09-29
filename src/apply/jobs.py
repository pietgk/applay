"""Job records, import normalization, and shortlist scoring.

The command-line adapter owns HTTP requests; ``apply.fetch`` orchestrates a
full run and writes the reports.  This module keeps the stable record
transformations and scoring rules independent of those edges so they can be
reused by other interfaces later.
"""

import datetime
import hashlib
import html
import re
import shlex
import urllib.parse
from typing import Any

# Board / permalink hosts are never cluster keys — only employer apply URLs.
_CLUSTER_DENYLIST_HOSTS = frozenset(
    {
        "remotive.com",
        "www.remotive.com",
        "jobsearch.api.jobtechdev.se",
        "arbetsformedlingen.se",
        "www.arbetsformedlingen.se",
        "news.ycombinator.com",
        "www.news.ycombinator.com",
        "hn.algolia.com",
        # Social / media hosts are never job-specific apply URLs.
        "twitter.com",
        "www.twitter.com",
        "x.com",
        "www.x.com",
        "facebook.com",
        "www.facebook.com",
        "instagram.com",
        "www.instagram.com",
        "youtube.com",
        "www.youtube.com",
        "tiktok.com",
        "www.tiktok.com",
    }
)
_URL_IN_TEXT_RE = re.compile(
    r"""https?://[^\s<>\"']+|href\s*=\s*["'](https?://[^"']+)["']""",
    re.I,
)
# Marketing / policy pages are never job-specific apply URLs — denylist them so
# unrelated roles sharing only a company's homepage-adjacent link never cluster.
_REJECT_PATH_RE = re.compile(
    r"/(privacy|privacypolicy|terms|tos|about|blog|login|signup|cookie|cookies|"
    r"legal|help|support|press|news|team|contact)(/|$)",
    re.I,
)


def is_clusterable_apply_path(path: str) -> bool:
    """True when a URL path can key a cross-source cluster.

    A bare homepage or a known marketing/policy page is never a job-specific
    apply URL. Everything else is eligible — custom ATS pages routinely use an
    opaque slug without ``/jobs/``, so we denylist known-bad paths rather than
    allowlist job-shaped ones (which would drop real clusters).
    """
    normalized = path or ""
    if normalized != "/" and normalized.endswith("/"):
        normalized = normalized.rstrip("/")
    if normalized in ("", "/"):
        return False
    return not _REJECT_PATH_RE.search(normalized)


def normalize_apply_url(url: str) -> str:
    """Normalize an employer/apply URL, or return '' when missing/ineligible."""
    raw = (url or "").strip()
    if not raw:
        return ""
    parsed = urllib.parse.urlparse(raw)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return ""
    host = parsed.hostname.casefold() if parsed.hostname else ""
    if not host or host in _CLUSTER_DENYLIST_HOSTS:
        return ""
    if host.startswith("www."):
        host = host[4:]
        if host in _CLUSTER_DENYLIST_HOSTS:
            return ""
    path = parsed.path or ""
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    if not is_clusterable_apply_path(path):
        return ""
    query = parsed.query
    normalized = urllib.parse.urlunparse(("https", host, path, "", query, ""))
    return normalized.casefold()


def first_eligible_url_from_text(text: str) -> str:
    """Return the first clusterable http(s) URL found in HTML or plain text."""
    for match in _URL_IN_TEXT_RE.finditer(text or ""):
        candidate = match.group(1) if match.lastindex else match.group(0)
        candidate = candidate.rstrip(").,;]'\"")
        if normalize_apply_url(candidate):
            return candidate
    return ""


def strip_html(value: str | None) -> str:
    return re.sub(r"<[^>]+>", " ", html.unescape(value or "")).strip()


def clean_job_description(value: str | None) -> str:
    """Normalize transport noise while preserving readable advert text."""
    text = html.unescape(value or "")
    text = re.sub(r"[\u200b\u200c\u200d\ufeff]", "", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    cleaned: list[str] = []
    blank = False
    for line in lines:
        if line:
            cleaned.append(line)
            blank = False
        elif not blank:
            cleaned.append("")
            blank = True
    return "\n".join(cleaned).strip()


def greenhouse_jobs(payload: dict[str, Any], token: str, company: str) -> list[dict[str, Any]]:
    out = []
    for job in payload.get("jobs", []):
        location = (job.get("location") or {}).get("name", "")
        url = job.get("absolute_url", "")
        out.append(
            dict(
                company=company,
                title=job.get("title", ""),
                location=location,
                url=url,
                apply_url=url,
                listing_url=url,
                desc=strip_html(job.get("content", "")),
                posted=job.get("updated_at", ""),
                commitment="",
                workplace="",
                remote_flag=None,
                source="greenhouse",
                source_id=str(job.get("id", "")),
                source_query="",
                source_ref=token,
            )
        )
    return out


def lever_jobs(payload: list[dict[str, Any]], token: str, company: str) -> list[dict[str, Any]]:
    out = []
    for job in payload:
        categories = job.get("categories", {}) or {}
        location = categories.get("location", "") or ", ".join(
            categories.get("allLocations", []) or []
        )
        workplace_type = (job.get("workplaceType", "") or "").lower()
        workplace = {"on-site": "onsite", "on_site": "onsite"}.get(workplace_type, workplace_type)
        hosted_url = job.get("hostedUrl", "")
        out.append(
            dict(
                company=company,
                title=job.get("text", ""),
                location=location,
                url=hosted_url,
                apply_url=job.get("applyUrl", "") or hosted_url,
                listing_url=hosted_url,
                desc=job.get("descriptionPlain", ""),
                posted=str(job.get("createdAt", "")),
                commitment=categories.get("commitment", ""),
                workplace=workplace,
                remote_flag=(workplace == "remote") or None,
                source="lever",
                source_id=str(job.get("id", "")),
                source_query="",
                source_ref=token,
            )
        )
    return out


def ashby_jobs(payload: dict[str, Any], token: str, company: str) -> list[dict[str, Any]]:
    out = []
    for job in payload.get("jobs", []):
        job_url = job.get("jobUrl") or job.get("applyUrl", "")
        apply_url = job.get("applyUrl", "") or job_url
        out.append(
            dict(
                company=company,
                title=job.get("title", ""),
                location=job.get("location", ""),
                url=job_url,
                apply_url=apply_url,
                listing_url=job.get("jobUrl", "") or apply_url,
                desc=job.get("descriptionPlain") or strip_html(job.get("descriptionHtml", "")),
                posted=job.get("publishedAt", ""),
                commitment=job.get("employmentType", ""),
                workplace="remote" if job.get("isRemote") else "",
                remote_flag=job.get("isRemote"),
                source="ashby",
                source_id=str(job.get("id", "")),
                source_query="",
                source_ref=token,
            )
        )
    return out


def _jobtech_employment(employment_label: str, duration_label: str) -> str:
    text = f"{employment_label} {duration_label}".lower()
    if any(
        word in text
        for word in [
            "tidsbegränsad",
            "vikariat",
            "behovs",
            "säsong",
            "projekt",
            "konsult",
            "bemanning",
            "inhyrd",
        ]
    ):
        return "contract"
    if any(word in text for word in ["tills vidare", "tillsvidare", "vanlig anställning"]):
        return "permanent"
    return ""


def _jobtech_location(ad: dict[str, Any]) -> str:
    address = ad.get("workplace_address") or {}
    return ", ".join(
        value
        for value in [address.get("city"), address.get("region"), address.get("country")]
        if value
    )


def _jobtech_company(ad: dict[str, Any]) -> str:
    employer = ad.get("employer") or {}
    return employer.get("workplace") or employer.get("name", "")


def jobtech_jobs(payload: dict[str, Any], spec: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for hit in payload.get("hits", []):
        address = hit.get("workplace_address") or {}
        location = ", ".join(
            value
            for value in [address.get("city"), address.get("region"), address.get("country")]
            if value
        )
        employer = hit.get("employer") or {}
        application = hit.get("application_details") or {}
        out.append(
            dict(
                company=employer.get("workplace") or employer.get("name", ""),
                title=hit.get("headline", ""),
                location=location,
                url=application.get("url") or hit.get("webpage_url", ""),
                apply_url=application.get("url", ""),
                listing_url=hit.get("webpage_url", ""),
                desc=clean_job_description((hit.get("description") or {}).get("text", "")),
                posted=hit.get("publication_date", ""),
                deadline=hit.get("application_deadline", "") or "",
                commitment=_jobtech_employment(
                    (hit.get("employment_type") or {}).get("label", ""),
                    (hit.get("duration") or {}).get("label", ""),
                ),
                workplace="",
                remote_flag=None,
                source="jobtech",
                source_id=str(hit.get("id") or hit.get("job_id") or hit.get("external_id") or ""),
                source_query=spec.get("q", ""),
                source_ref="jobsearch.api.jobtechdev.se",
            )
        )
    return out


def remotive_jobs(payload: dict[str, Any], spec: dict[str, Any]) -> list[dict[str, Any]]:
    """Map Remotive remote-jobs payloads onto the shared discovery record shape.

    Remotive's API leaves employer apply URLs unstructured; when the description
    HTML/text contains a non-board http(s) link, surface it as ``apply_url`` so
    cross-source clustering can match on it. The Remotive job page stays the
    canonical ``url`` / ``listing_url``.
    """
    out = []
    category = str(spec.get("category", "") or "")
    for job in payload.get("jobs", []):
        url = str(job.get("url", "") or "")
        raw_description = job.get("description", "") or ""
        tags = [str(tag).strip() for tag in (job.get("tags") or []) if str(tag).strip()]
        out.append(
            dict(
                company=job.get("company_name", ""),
                title=job.get("title", ""),
                location=job.get("candidate_required_location", "") or "",
                url=url,
                apply_url=first_eligible_url_from_text(raw_description),
                listing_url=url,
                desc=clean_job_description(strip_html(raw_description)),
                posted=job.get("publication_date", "") or "",
                deadline="",
                salary=str(job.get("salary") or "").strip(),
                tags=tags,
                commitment=job.get("job_type", "") or "",
                workplace="remote",
                remote_flag=True,
                source="remotive",
                source_id=str(job.get("id", "")),
                source_query=category,
                source_ref="remotive.com",
            )
        )
    return out


_HN_URL_RE = re.compile(r"https?://[^\s<>\"']+", re.I)
_HN_HIRING_RE = re.compile(
    r"^(.+?)\s+is\s+(?:hiring|looking for)\s+(?:an?\s+)?(.+)$",
    re.I,
)


def _hn_permalink(comment_id: str) -> str:
    return f"https://news.ycombinator.com/item?id={comment_id}"


def _hn_apply_url(text: str) -> str:
    """Prefer a clusterable external apply URL; skip HN permalinks and homepages."""
    for match in _HN_URL_RE.finditer(text):
        url = match.group(0).rstrip(").,;]'\"")
        if normalize_apply_url(url):
            return url
    return ""


def _hn_parse_comment(raw_html: str) -> dict[str, str] | None:
    """Deterministic company+title extraction; None when the comment is unparseable."""
    plain = clean_job_description(strip_html(raw_html))
    if not plain:
        return None
    first_line = plain.split("\n", 1)[0].strip()
    parts = [part.strip() for part in first_line.split("|")]
    parts = [part for part in parts if part]
    if len(parts) >= 2:
        company, title = parts[0], parts[1]
        location = parts[2] if len(parts) >= 3 else ""
        if company and title:
            return {
                "company": company,
                "title": title,
                "location": location,
                "desc": plain,
            }
    match = _HN_HIRING_RE.match(first_line)
    if match:
        company = match.group(1).strip()
        title = match.group(2).strip().rstrip(".,;")
        if company and title:
            return {"company": company, "title": title, "location": "", "desc": plain}
    return None


def hn_jobs(payload: dict[str, Any], thread_id: str) -> tuple[list[dict[str, Any]], int]:
    """Map top-level HN Who's Hiring comments; return (jobs, parse_failures).

    Nested replies are ignored. Comments missing company+title are counted as
    parse failures and never enter the admission path.
    """
    out: list[dict[str, Any]] = []
    failures = 0
    thread_id = str(thread_id)
    for comment in payload.get("children") or []:
        comment_id = str(comment.get("id", "") or "")
        raw_text = comment.get("text") or ""
        parsed = _hn_parse_comment(raw_text)
        if parsed is None:
            failures += 1
            continue
        if not comment_id:
            failures += 1
            continue
        permalink = _hn_permalink(comment_id)
        apply_url = _hn_apply_url(html.unescape(raw_text))
        location = parsed["location"]
        loc_blob = f"{location} {parsed['desc'][:500]}".lower()
        remote_flag = True if "remote" in loc_blob else None
        workplace = "remote" if remote_flag else ""
        out.append(
            dict(
                company=parsed["company"],
                title=parsed["title"],
                location=location,
                url=apply_url or permalink,
                apply_url=apply_url,
                listing_url=permalink,
                desc=parsed["desc"],
                posted=comment.get("created_at", "") or "",
                deadline="",
                commitment="",
                workplace=workplace,
                remote_flag=remote_flag,
                source="hn",
                source_id=comment_id,
                source_query="",
                source_ref="",
                description_source="hn-comment",
                hn_thread_id=thread_id,
            )
        )
    return out, failures


def jobtech_detail(payload: dict[str, Any], ad_id: str) -> dict[str, Any]:
    """Normalize one current JobTech detail payload."""
    ad_id = str(ad_id)
    detail_url = f"https://jobsearch.api.jobtechdev.se/ad/{ad_id}"
    application = payload.get("application_details") or {}
    description = payload.get("description") or {}
    raw_text = description.get("text") or strip_html(description.get("text_formatted", ""))
    record = dict(
        company=_jobtech_company(payload),
        title=payload.get("headline", ""),
        location=_jobtech_location(payload),
        url=application.get("url") or payload.get("webpage_url", "") or detail_url,
        apply_url=application.get("url", ""),
        listing_url=payload.get("webpage_url", ""),
        description=clean_job_description(raw_text),
        posted=payload.get("publication_date", ""),
        deadline=payload.get("application_deadline", "") or "",
        commitment=_jobtech_employment(
            (payload.get("employment_type") or {}).get("label", ""),
            (payload.get("duration") or {}).get("label", ""),
        ),
        workplace="",
        remote_flag=None,
        source="jobtech",
        source_id=ad_id,
        source_ref="jobsearch.api.jobtechdev.se",
        source_query="",
        source_queries=[],
        description_source="detail",
        detail_url=detail_url,
        retrieved_at=datetime.datetime.now(datetime.UTC).isoformat(),
        raw_detail=payload,
    )
    record["job_id"] = f"jobtech:jobsearch.api.jobtechdev.se:{ad_id}"
    if not record["company"] or not record["title"] or not record["description"]:
        raise ValueError(f"JobTech ad {ad_id} did not contain company, title, and description")
    return record


def stable_job_id(job: dict[str, Any]) -> str:
    """Return an identifier that survives repeated searches and report rewrites."""
    source = job.get("source", "unknown")
    source_ref = job.get("source_ref", "")
    source_id = job.get("source_id", "")
    if source == "hn" and source_id:
        return f"hn:{source_id}"
    if source == "ingest":
        # URL identity when present (idempotent re-ingest); else field-hash.
        url = str(job.get("url") or job.get("source_url") or "").strip()
        if url:
            return f"ingest:{hashlib.sha1(url.encode('utf-8')).hexdigest()}"
        basis = "|".join(
            str(job.get(key, "")).strip().lower() for key in ("company", "title", "location")
        )
        return f"ingest:{hashlib.sha1(basis.encode('utf-8')).hexdigest()[:12]}"
    if source_id:
        return f"{source}:{source_ref}:{source_id}"
    basis = "|".join(
        str(job.get(key, "")).strip().lower() for key in ("url", "company", "title", "location")
    )
    digest = hashlib.sha1(basis.encode("utf-8")).hexdigest()[:12]
    return f"{source}:{digest}"


def shell_quote(value: Any) -> str:
    return shlex.quote(str(value))


def detect_employment(job: dict[str, Any]) -> str:
    description = str(job.get("desc", ""))
    source = f"{job.get('commitment', '')} {job.get('title', '')} {description[:600]}".lower()
    contract = any(
        word in source
        for word in [
            "contract",
            "freelance",
            "consultant",
            "interim",
            "b2b",
            "temporary",
            "fixed-term",
            "fixed term",
        ]
    )
    permanent = any(
        word in source
        for word in [
            "permanent",
            "full-time",
            "full time",
            "fulltime",
            "regular full",
            "tillsvidare",
            "fast anställning",
            "vast anstallning",
        ]
    )
    if job.get("commitment"):
        commitment = str(job["commitment"]).lower()
        if any(word in commitment for word in ["contract", "temporary", "freelance"]):
            return "contract"
        if any(word in commitment for word in ["full", "permanent", "regular"]):
            return "permanent"
    if contract and not permanent:
        return "contract"
    if permanent and not contract:
        return "permanent"
    return "unknown"


def detect_arrangement(job: dict[str, Any]) -> tuple[str, int | None]:
    workplace = job.get("workplace")
    if workplace in ("remote", "hybrid", "onsite"):
        mode = workplace
    elif job.get("remote_flag") is True:
        mode = "remote"
    else:
        description = str(job.get("desc", ""))
        if re.search(
            r"fully remote|100% remote|remote-first|remote first|work from anywhere",
            description,
            re.I,
        ):
            mode = "remote"
        elif "hybrid" in description.lower():
            mode = "hybrid"
        elif re.search(r"on-?site|in[- ]office|in the office|on premise", description, re.I):
            mode = "onsite"
        elif "remote" in description.lower():
            mode = "remote"
        else:
            mode = "unknown"
    days = None
    description = str(job.get("desc", ""))
    match = re.search(r"(\d)\s*(?:days?)\s*(?:per|a|/)?\s*week", description.lower())
    if not match:
        match = re.search(r"(\d)\s*days?\s*(?:in|at)?\s*(?:the\s*)?office", description.lower())
    if match:
        days = int(match.group(1))
        if mode in ("unknown", "remote") and days > 0:
            mode = "hybrid"
    return mode, days


def classify_region(job: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    source = f"{job.get('location', '')} {str(job.get('desc', ''))[:800]}".lower()
    hard = policy["hard"]

    def contains_any(terms: list[str]) -> bool:
        return any(term in source for term in terms)

    sweden = contains_any(hard["sweden_terms"])
    eu = sweden or contains_any(hard["eu_terms"])
    us = contains_any(hard["us_terms"])
    deny_timezone = contains_any(hard["deny_timezone_terms"])
    if sweden:
        region = "sweden"
    elif eu:
        region = "eu"
    elif us:
        region = "us"
    else:
        region = "unknown"
    return dict(region=region, sweden=sweden, eu=eu, us=us, deny_tz=deny_timezone)


CUR = r"(?:€|£|\$|eur|gbp|usd|sek|kr)"
PAY_RE = re.compile(
    rf"{CUR}\s?\d[\d ,.]*\s*(?:k)?(?:\s*(?:-|–|to)\s*{CUR}?\s?\d[\d ,.]*\s*k?)?"
    rf"\s*(?:per\s*(?:hour|day|year|annum)|/\s*(?:hr|hour|day|year)|p\.?a\.?|k/year)?",
    re.IGNORECASE,
)


def _pay_period(raw: str) -> str:
    lower = raw.lower()
    if any(word in lower for word in ["hour", "/hr", "hr"]):
        return "hour"
    if "day" in lower:
        return "day"
    if any(word in lower for word in ["year", "annum", "p.a", "pa", "k/year"]):
        return "annual"
    return "unknown"


def detect_pay(job: dict[str, Any]) -> dict[str, Any]:
    # Structured source salary (e.g. Remotive) is stored raw for display.
    structured = str(job.get("salary") or "").strip()
    if structured:
        raw = re.sub(r"\s+", " ", structured).strip()
        return dict(raw=raw, period=_pay_period(raw))
    match = PAY_RE.search(str(job.get("desc", "")))
    if not match:
        return dict(raw=None, period=None)
    raw = re.sub(r"\s+", " ", match.group(0)).strip()
    return dict(raw=raw, period=_pay_period(raw))


def extract(job: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    employment = detect_employment(job)
    arrangement, office_days = detect_arrangement(job)
    region = classify_region(job, policy)
    pay = detect_pay(job)
    return dict(
        employment=employment,
        arrangement=arrangement,
        office_days=office_days,
        pay=pay,
        **region,
    )


def location_verdict(attrs: dict[str, Any]) -> tuple[bool, str]:
    if attrs["arrangement"] == "remote":
        if attrs["deny_tz"] and not attrs["eu"]:
            return False, "remote restricted to non-CET timezone"
        if attrs["us"] and not attrs["eu"]:
            return False, "remote but US-bound"
        return True, ""
    if attrs["arrangement"] in ("hybrid", "onsite"):
        if attrs["eu"] or attrs["sweden"]:
            return True, ""
        if attrs["us"]:
            return False, f"{attrs['arrangement']} in US"
        return True, "location unknown — kept"
    if attrs["us"] and not attrs["eu"]:
        return False, "US-bound, no remote signal"
    return True, ""


def keyword_score(job: dict[str, Any], keywords: list[str], weights: dict[str, int]) -> int:
    """Legacy flat keyword tally — kept for offline self-tests; fetch uses angles."""
    title = str(job.get("title", "")).lower()
    blob = f"{job.get('title', '')} {job.get('desc', '')}".lower()
    score, hits = 0, []
    for keyword in keywords:
        keyword = keyword.lower()
        if keyword in title:
            score += weights["keyword_title"]
            hits.append(keyword)
        elif keyword in blob:
            score += weights["keyword_body"]
            hits.append(keyword)
    job["hits"] = sorted(set(hits))
    return score


CANONICAL_ANGLES = (
    "full_stack_lead",
    "product_engineer",
    "backend_principal",
    "mobile_product",
    "ai_native",
)
RN_CUES = ("react native", "expo")
SENIORITY_CUES = (
    "tech lead",
    "engineering lead",
    "staff",
    "principal",
    "cto",
    "head of",
    "head-of",
    "senior",
)
# Title cues weigh heavier than body when comparing angles for the primary pick.
_TITLE_CUE_WEIGHT = 3
_BODY_CUE_WEIGHT = 1


def _matched_cues(text: str, cues: list[str]) -> list[str]:
    lower = text.lower()
    return [cue for cue in cues if cue.lower() in lower]


def _angle_match_points(title_hits: int, body_hits: int) -> int:
    """Map cue counts onto weak/solid/strong (1/2/3). Zero means below the floor."""
    if title_hits >= 2 or (title_hits >= 1 and body_hits >= 2):
        return 3
    if title_hits >= 1 and body_hits >= 1:
        return 2
    if title_hits >= 1 or body_hits >= 2:
        return 1
    return 0


def _seniority_points(job: dict[str, Any]) -> int:
    blob = f"{job.get('title', '')} {job.get('desc', '')}".lower()
    return 1 if any(cue in blob for cue in SENIORITY_CUES) else 0


def _rn_points(primary: str, title: str, body: str) -> float:
    if primary == "mobile_product":
        return 1.0
    blob = f"{title} {body}".lower()
    if any(cue in blob for cue in RN_CUES):
        return 0.5
    return 0.0


def _pick_primary(qualified: dict[str, dict[str, Any]], title: str) -> str:
    """Highest cue weight wins; ties → full_stack_lead unless RN/Expo title cues win."""
    best_weight = max(item["weight"] for item in qualified.values())
    tied = sorted(key for key, item in qualified.items() if item["weight"] == best_weight)
    if any(cue in title.lower() for cue in RN_CUES) and "mobile_product" in tied:
        return "mobile_product"
    if "full_stack_lead" in tied:
        return "full_stack_lead"
    for key in CANONICAL_ANGLES:
        if key in tied:
            return key
    return tied[0]


def classify_angle(job: dict[str, Any], angles: dict[str, Any]) -> dict[str, Any] | None:
    """Return primary-angle fit fields, or None when no angle clears the weak floor.

    An angle qualifies with ≥1 title cue or ≥2 distinct body cues. ``fit_score``
    is capped at 5: angle match (0–3) + seniority (0–1) + RN preference (0–1,
    half-weight when RN/Expo is only a secondary cue).
    """
    title = str(job.get("title", ""))
    body = str(job.get("desc", ""))
    tags = [str(tag).strip() for tag in (job.get("tags") or []) if str(tag).strip()]
    if tags:
        # Remotive (and similar) tags feed the scoring body only — never the
        # stored description.
        body = f"{body}\n\n{' '.join(tags)}"
    qualified: dict[str, dict[str, Any]] = {}
    for key in CANONICAL_ANGLES:
        spec = angles.get(key) or {}
        title_cues = _matched_cues(title, list(spec.get("title") or []))
        all_body = _matched_cues(body, list(spec.get("body") or []))
        title_hits = len(title_cues)
        body_hits = len(all_body)
        match_points = _angle_match_points(title_hits, body_hits)
        if match_points == 0:
            continue
        weight = title_hits * _TITLE_CUE_WEIGHT + body_hits * _BODY_CUE_WEIGHT
        hits = sorted({*title_cues, *all_body}, key=str.lower)
        qualified[key] = {
            "match_points": match_points,
            "weight": weight,
            "hits": hits,
        }
    if not qualified:
        return None
    primary = _pick_primary(qualified, title)
    chosen = qualified[primary]
    seniority = _seniority_points(job)
    rn = _rn_points(primary, title, body)
    fit_score = min(5.0, chosen["match_points"] + seniority + rn)
    if fit_score == int(fit_score):
        fit_score = int(fit_score)
    hits = list(chosen["hits"])
    # Surface RN/Expo cues that contributed to the RN preference component.
    if rn:
        for cue in RN_CUES:
            if cue in f"{title} {body}".lower() and cue not in {h.lower() for h in hits}:
                hits.append(cue)
        hits = sorted(hits, key=str.lower)
    return {
        "angle": primary,
        "fit_score": fit_score,
        "fit_breakdown": {
            "angle": chosen["match_points"],
            "seniority": seniority,
            "rn": rn if rn != int(rn) else int(rn),
        },
        "hits": hits,
    }


def parse_job_date(value: str | None) -> datetime.datetime | None:
    """Parse a source date string into an aware UTC datetime, or None if unknown."""
    text = str(value or "").strip()
    if not text:
        return None
    if text.isdigit():
        number = int(text)
        # Lever and similar boards emit epoch milliseconds.
        seconds = number / 1000 if number > 10_000_000_000 else number
        return datetime.datetime.fromtimestamp(seconds, tz=datetime.UTC)
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.datetime.fromisoformat(normalized)
    except ValueError:
        try:
            parsed = datetime.datetime.strptime(text[:10], "%Y-%m-%d")
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.UTC)
    return parsed


def prefer_earlier_date(stored: str, incoming: str) -> str:
    """Keep the first non-empty date; when both parse, prefer the earlier one."""
    if not incoming:
        return stored
    if not stored:
        return incoming
    stored_dt = parse_job_date(stored)
    incoming_dt = parse_job_date(incoming)
    if stored_dt and incoming_dt:
        return stored if stored_dt <= incoming_dt else incoming
    return stored


def recency_points(
    posted: str,
    first_seen: str,
    now: str,
    weights: dict[str, int],
) -> int:
    """Capped recency bonus for the attribute score (≤7d / 8–30d buckets)."""
    anchor = parse_job_date(posted) or parse_job_date(first_seen)
    current = parse_job_date(now)
    if anchor is None or current is None:
        return 0
    age = (current - anchor).days
    if age < 0:
        return 0
    if age <= 7:
        return int(weights.get("recency_within_7d", 0))
    if age <= 30:
        return int(weights.get("recency_within_30d", 0))
    return 0


def pay_points(pay: dict[str, Any], config: dict[str, Any], weights: dict[str, int]) -> int:
    if not pay["raw"] or pay["period"] in (None, "unknown"):
        return 0
    numbers = [
        int(re.sub(r"[ ,.\u00a0]", "", number)) for number in re.findall(r"\d[\d ,.]*", pay["raw"])
    ]
    if not numbers:
        return 0
    value = max(numbers)
    if "k" in pay["raw"].lower():
        value *= 1000
    floor = {
        "hour": config.get("min_hourly", 0),
        "day": config.get("min_day", 0),
        "annual": config.get("min_annual", 0),
    }.get(pay["period"], 0)
    if not floor:
        return 0
    return weights["pay_meets_floor"] if value >= floor else weights["pay_below_floor"]


def pref_score(
    attrs: dict[str, Any],
    weights: dict[str, int],
    pay_config: dict[str, Any],
    *,
    posted: str = "",
    first_seen: str = "",
    now: str = "",
) -> int:
    score = {
        "permanent": weights["employment_permanent"],
        "contract": weights["employment_contract"],
    }.get(attrs["employment"], weights["employment_unknown"])
    if attrs["arrangement"] == "remote":
        score += weights["remote_full"]
    elif attrs["arrangement"] == "hybrid":
        score += weights["hybrid_base"] + weights["hybrid_per_office_day"] * (
            attrs["office_days"] or 0
        )
    elif attrs["arrangement"] == "onsite":
        score += weights["onsite"]
    else:
        score += weights["arrangement_unknown"]
    score += {"sweden": weights["region_sweden"], "eu": weights["region_eu"]}.get(
        attrs["region"],
        weights["region_global_remote"] if attrs["arrangement"] == "remote" else 0,
    )
    score += pay_points(attrs["pay"], pay_config, weights)
    if now:
        score += recency_points(posted, first_seen, now, weights)
    return score


def fmt_attrs(attrs: dict[str, Any]) -> str:
    days = f"{attrs['office_days']}d" if attrs["office_days"] is not None else "?"
    pay = attrs["pay"]["raw"] or "?"
    return (
        f"emp:{attrs['employment']} · work:{attrs['arrangement']} · office:{days} "
        f"· region:{attrs['region']} · pay:{pay}"
    )


def missing(attrs: dict[str, Any]) -> list[str]:
    result = []
    if attrs["employment"] == "unknown":
        result.append("employment")
    if attrs["arrangement"] == "unknown":
        result.append("arrangement")
    if attrs["arrangement"] == "hybrid" and attrs["office_days"] is None:
        result.append("office-days")
    if not attrs["pay"]["raw"]:
        result.append("pay")
    return result

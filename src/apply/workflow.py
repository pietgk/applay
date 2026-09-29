"""Bounded draft/check/finalize workflow for application CV artifacts.

The workflow deliberately stops at files and gates.  It does not call an AI
provider and it never edits the master profile or the imported job snapshot.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import applications, ats

ANALYSIS_NAME = "cv-analysis.md"
FEEDBACK_NAME = "cv-feedback.md"
DRAFT_NAME = "cv-draft.md"
DRAFT_PDF_NAME = "cv-draft.pdf"
REVIEW_NAME = "cv-review.md"
FINAL_NAME = "cv.md"
FINAL_PDF_NAME = "cv.pdf"

_PLACEHOLDER_RE = re.compile(
    r"^\s*(?:[-*]\s*)?(?:TODO|TBD|REPLACE|FILL\s+IN|CHOOSE|ADD\s+(?:YOUR|THE)|WRITE\s+YOUR)\b"
    r"|\[[^\]\n]+\]|<[^>\n]+>",
    flags=re.IGNORECASE,
)
_RENDER_PLACEHOLDER_MARKERS = (
    "<headline_variant from master-profile.yaml>",
    "<3-5 line summary assembled from summary_atoms matching this role's angle>",
    "- **Backend:** ...",
    "- **Frontend:** ...",
    "- **Architecture:** ...",
    "- **Quality & Delivery:** ...",
)

ANALYSIS_TEMPLATE = """# CV analysis

<!-- Working notes only. This file is not rendered into the CV. Every claim in the draft must be supported by the profile. -->

## Job context

- Job description: `job.md`
- Profile source: `{profile_reference}`

## Requirements and signals

- [Fill in the 8-12 most important requirements and keywords from job.md]

## Positioning decision

- [Choose an angle from profile/positioning.md and record the evidence]

## Profile evidence

- [List only matching proof points from the master profile]

## Truth and review notes

- [Record claims that need human verification before approval]
"""

DRAFT_TEMPLATE = """# CV DRAFT
%%headline%% [factual headline selected from the profile]
%%contact%% [copy factual contact details from the profile]

## SUMMARY
[Write a concise, truthful summary supported by the profile and job analysis.]

## CORE SKILLS
- **Backend:** [profile-backed skills relevant to this job]
- **Frontend:** [profile-backed skills relevant to this job]
- **Architecture:** [profile-backed skills relevant to this job]
- **Quality & Delivery:** [profile-backed skills relevant to this job]

## EXPERIENCE

### [Relevant role from the profile]
- [Profile-backed accomplishment with measurable context]
- [Profile-backed accomplishment with measurable context]

## EDUCATION
[Copy education from the profile]

## LANGUAGES
[Copy languages from the profile]
"""

FEEDBACK_TEMPLATE = """# Next-draft feedback

<!-- Human review and instructions for the next generated draft. This file is not rendered into the CV. -->

## Corrections and missing evidence

## Draft decisions

## Questions before the next generation
"""


class WorkflowError(Exception):
    """A user-correctable workflow refusal."""


@dataclass(frozen=True)
class WorkflowPaths:
    application: Path
    job: Path
    profile: Path
    analysis: Path
    feedback: Path
    draft: Path
    draft_pdf: Path
    review: Path
    final: Path
    final_pdf: Path

    @classmethod
    def for_application(
        cls, application_dir: str | Path, profile_path: str | Path | None = None
    ) -> WorkflowPaths:
        application = Path(application_dir).expanduser()
        if profile_path is None:
            # Application folders conventionally live at applications/<name>.
            profile = application.parent.parent / "profile" / "master-profile.yaml"
        else:
            profile = Path(profile_path).expanduser()
        return cls(
            application=application,
            job=application / "job.md",
            profile=profile,
            analysis=application / ANALYSIS_NAME,
            feedback=application / FEEDBACK_NAME,
            draft=application / DRAFT_NAME,
            draft_pdf=application / DRAFT_PDF_NAME,
            review=application / REVIEW_NAME,
            final=application / FINAL_NAME,
            final_pdf=application / FINAL_PDF_NAME,
        )


@dataclass(frozen=True)
class Gate:
    name: str
    passed: bool
    detail: str
    findings: tuple[str, ...] = ()


@dataclass(frozen=True)
class CheckResult:
    paths: WorkflowPaths
    gates: tuple[Gate, ...]

    @property
    def passed(self) -> bool:
        return all(gate.passed for gate in self.gates)

    @property
    def findings(self) -> tuple[str, ...]:
        return tuple(finding for gate in self.gates for finding in gate.findings)


def _now() -> str:
    return dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as error:
        raise WorkflowError(f"could not read {path}: {error}") from error


def _metadata_value(path: Path, key: str) -> str:
    if not path.exists():
        return ""
    pattern = re.compile(rf"^{re.escape(key)}:\s*(.*?)(?:\s+#.*)?$")
    for line in _read(path).splitlines():
        match = pattern.match(line)
        if match:
            value = match.group(1).strip()
            if len(value) >= 2 and value[0] == value[-1] == '"':
                try:
                    return str(json.loads(value))
                except json.JSONDecodeError:
                    return value[1:-1]
            return value
    return ""


def _metadata_int(path: Path, key: str, default: int = 0) -> int:
    value = _metadata_value(path, key)
    try:
        return int(value)
    except ValueError:
        return default


def _update_metadata(path: Path, values: dict[str, Any]) -> None:
    """Update only workflow fields while preserving all existing YAML text."""
    applications.update_meta(str(path), values, force=True)


def _without_comments(text: str) -> str:
    return re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)


def scaffold_placeholders(text: str) -> list[str]:
    """Return actionable placeholder lines, excluding explanatory comments."""
    if not text.strip():
        return ["file is empty"]
    found = [marker for marker in _RENDER_PLACEHOLDER_MARKERS if marker in text]
    visible = _without_comments(text)
    for line in visible.splitlines():
        if _PLACEHOLDER_RE.search(line) and line.strip() not in found:
            found.append(line.strip())
    return list(dict.fromkeys(found))


def _profile_reference(paths: WorkflowPaths) -> str:
    try:
        return str(paths.profile.relative_to(paths.application.parent.parent))
    except ValueError:
        return str(paths.profile)


def _ensure_application(paths: WorkflowPaths) -> None:
    if not paths.application.is_dir():
        raise WorkflowError(f"application folder does not exist: {paths.application}")
    if not paths.job.is_file():
        raise WorkflowError(f"application is missing job.md: {paths.application}")


def _write_template(path: Path, content: str, force: bool) -> bool:
    if not path.exists():
        path.write_text(content, encoding="utf-8")
        return True
    existing = _read(path)
    if existing == content:
        return False
    if not scaffold_placeholders(existing):
        if not force:
            raise WorkflowError(
                f"refusing to overwrite non-placeholder {path.name}; use --force explicitly"
            )
        backup = path.with_name(path.name + ".bak")
        shutil.copyfile(path, backup)
        path.write_text(content, encoding="utf-8")
        return True
    return False


def start(
    application_dir: str | Path,
    profile_path: str | Path | None = None,
    force: bool = False,
) -> WorkflowPaths:
    """Initialize draft and analysis files without generating candidate content."""
    paths = WorkflowPaths.for_application(application_dir, profile_path)
    _ensure_application(paths)
    if not paths.profile.is_file() or not _read(paths.profile).strip():
        raise WorkflowError(f"profile source is missing or empty: {paths.profile}")

    draft_changed = _write_template(paths.draft, DRAFT_TEMPLATE, force)
    analysis_changed = _write_template(
        paths.analysis,
        ANALYSIS_TEMPLATE.format(profile_reference=_profile_reference(paths)),
        force,
    )
    feedback_changed = _write_template(paths.feedback, FEEDBACK_TEMPLATE, force)
    metadata = {
        "workflow_state": "drafting",
        "draft_iteration": max(
            1, _metadata_int(paths.application / "meta.yaml", "draft_iteration", 0)
        ),
    }
    if draft_changed or analysis_changed or feedback_changed:
        if _metadata_int(paths.application / "meta.yaml", "draft_iteration", 0) == 0:
            metadata["draft_iteration"] = 1
        if not _metadata_value(paths.application / "meta.yaml", "draft_started_at"):
            metadata["draft_started_at"] = _now()
    _update_metadata(paths.application / "meta.yaml", metadata)
    return paths


def _context_gate(paths: WorkflowPaths) -> Gate:
    findings: list[str] = []
    if not paths.job.is_file():
        findings.append("job.md is missing; import or paste the job description first")
    else:
        job_text = _read(paths.job)
        if applications.is_job_placeholder(
            job_text,
            _metadata_value(paths.application / "meta.yaml", "company"),
            _metadata_value(paths.application / "meta.yaml", "role"),
        ):
            findings.append("job.md still contains the scaffold job placeholder")
        elif not applications.job_body(job_text):
            findings.append("job.md has no usable job description body")
    if not paths.profile.is_file():
        findings.append(f"profile source is missing: {paths.profile}")
    elif not _read(paths.profile).strip():
        findings.append(f"profile source is empty: {paths.profile}")
    passed = not findings
    return Gate(
        "job/profile context",
        passed,
        "job.md and master profile are available" if passed else "context is incomplete",
        tuple(findings),
    )


def _scaffold_gate(paths: WorkflowPaths) -> Gate:
    findings: list[str] = []
    for path in (paths.analysis, paths.draft):
        if not path.is_file():
            findings.append(f"{path.name} is missing; run cv-start first")
            continue
        placeholders = scaffold_placeholders(_read(path))
        findings.extend(f"{path.name}: {placeholder}" for placeholder in placeholders)
    return Gate(
        "scaffold placeholders",
        not findings,
        "analysis and draft contain no scaffold placeholders"
        if not findings
        else "draft inputs still need human/Codex content",
        tuple(findings),
    )


def _ats_gate(
    paths: WorkflowPaths, context: Gate, scaffold: Gate
) -> tuple[Gate, ats.AtsResult | None]:
    if not context.passed or not paths.draft.is_file():
        return Gate("ATS lint", False, "not run because job/profile context is incomplete"), None
    result = ats.evaluate(_read(paths.job), _read(paths.draft))
    passed = result.verdict == "STRONG"
    findings: list[str] = []
    if result.coverage < 75:
        findings.append(f"raise truthful keyword coverage from {result.coverage}% to at least 75%")
    if result.metrics < 6:
        findings.append(
            f"add truthful quantified evidence; found {result.metrics}, need at least 6"
        )
    if not scaffold.passed:
        findings.append("clear scaffold placeholders before relying on ATS results")
    detail = (
        f"{result.verdict}: coverage {result.coverage}%, {result.metrics} quantified hits, "
        f"{result.words} words"
    )
    return Gate("ATS lint", passed, detail, tuple(findings)), result


def _render_gates(paths: WorkflowPaths, scaffold: Gate) -> tuple[Gate, Gate, int | None]:
    from . import rendering

    if not paths.draft.is_file() or not scaffold.passed:
        reason = "not rendered because draft placeholders remain or cv-draft.md is missing"
        return Gate("PDF render", False, reason), Gate("exactly one page", False, reason), None
    try:
        css_path = Path(__file__).resolve().parents[2] / "templates" / "cv.css"
        result = rendering.render_document(_read(paths.draft), css_path.read_text(encoding="utf-8"))
        page_total = rendering.page_count(result.html)
        rendering.write_pdf(result, paths.draft_pdf)
    except (OSError, RuntimeError, ValueError) as error:
        detail = f"render failed: {error}"
        return (
            Gate("PDF render", False, detail, (detail,)),
            Gate("exactly one page", False, "not checked because PDF rendering failed"),
            None,
        )
    render_gate = Gate("PDF render", True, f"wrote {paths.draft_pdf.name}")
    page_gate = Gate(
        "exactly one page",
        page_total == 1,
        f"rendered page count: {page_total}",
        ()
        if page_total == 1
        else ("trim or simplify the draft until it renders to exactly one page",),
    )
    return render_gate, page_gate, page_total


def _review_text(result: CheckResult) -> str:
    status = "PASS" if result.passed else "FAIL"
    lines = [
        "# CV review",
        "",
        f"Overall gate result: **{status}**",
        "",
        "This artifact is generated by `cv-check`. It is a review aid, not human approval.",
        "",
        "## Gates",
        "",
    ]
    for gate in result.gates:
        marker = "PASS" if gate.passed else "FAIL"
        lines.append(f"- **{marker} — {gate.name}:** {gate.detail}")
        lines.extend(f"  - Action: {finding}" for finding in gate.findings)
    if result.passed:
        lines.extend(
            [
                "",
                "All automated gates passed. A human must still verify every claim and explicitly run `cv-finalize --approve`.",
            ]
        )
    else:
        lines.extend(["", "## Next actions", ""])
        lines.extend(f"- {finding}" for finding in result.findings)
    return "\n".join(lines) + "\n"


def check(application_dir: str | Path, profile_path: str | Path | None = None) -> CheckResult:
    """Run every offline gate, render a draft PDF when possible, and write review."""
    paths = WorkflowPaths.for_application(application_dir, profile_path)
    _ensure_application(paths)
    context = _context_gate(paths)
    scaffold = _scaffold_gate(paths)
    ats_gate, ats_result = _ats_gate(paths, context, scaffold)
    render_gate, page_gate, page_total = _render_gates(paths, scaffold)
    result = CheckResult(paths, (scaffold, context, ats_gate, render_gate, page_gate))
    paths.review.write_text(_review_text(result), encoding="utf-8")
    values: dict[str, Any] = {
        "workflow_state": "ready_for_approval" if result.passed else "drafting",
        "last_checked_at": _now(),
    }
    if ats_result is not None:
        values.update(
            {
                "ats_coverage": ats_result.coverage,
                "ats_metrics": ats_result.metrics,
            }
        )
    if page_total is not None:
        values["draft_page_count"] = page_total
    _update_metadata(paths.application / "meta.yaml", values)
    return result


def finalize(
    application_dir: str | Path,
    profile_path: str | Path | None = None,
    approve: bool = False,
) -> CheckResult:
    """Promote a passing draft only after explicit approval."""
    if not approve:
        raise WorkflowError("finalize requires explicit approval: pass --approve")
    result = check(application_dir, profile_path)
    if not result.passed:
        raise WorkflowError(
            f"refusing to finalize: gates failed; review {result.paths.review} for actions"
        )
    shutil.copyfile(result.paths.draft, result.paths.final)
    shutil.copyfile(result.paths.draft_pdf, result.paths.final_pdf)
    _update_metadata(
        result.paths.application / "meta.yaml",
        {"workflow_state": "finalized", "finalized_at": _now()},
    )
    return result

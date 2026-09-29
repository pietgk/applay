# Job application system

Public copy of the toolchain (`applay`). It includes the Python, the docs, and Piet Groot Kormelink's profile. It does not include application folders, the live job catalog, or the agent queue. Those stay in the private working repo.

Documentation: [workflow](docs/workflow.md) · [domain model](docs/domain-model.md) ·
[development](docs/development.md) · [architecture decisions](docs/adr/)

Structured, repeatable pipeline for turning a job description into a tailored,
ATS-safe, 1-page PDF CV — and keeping every application organised for monthly reporting.

## Layout
```
profile/
  master-profile.yaml   Single source of truth: every achievement, tagged. Tailoring
                        SELECTS from here — never invent facts outside it. Add new
                        proof points here first, then they flow into future CVs.
  positioning.md        The 5 angles to lead with + a job-fit quick test (use at search time).
  sources/              Raw source material (LinkedIn export, motivation, recap).
templates/
  cv.css                Locked 1-page, single-column, ATS-safe stylesheet.
tools/
  cv-tailor.md          The workflow prompt for the human-steered draft loop.
  cv_workflow.py        Start, check, and finalize draft artifacts.
  new_application.py     Scaffold a dated application folder.
  render_cv.py           cv.md -> auto-fitted 1-page PDF (WeasyPrint, the one locked engine).
  ats_lint.py            Score a cv.md draft vs its job.md before rendering.
  jobs_fetch.py          Scan public ATS boards -> filtered, ranked shortlist in reports/.
  jobs_ingest.py         Clipboard ingest into the persistent catalog (macOS pbpaste).
  jobs-ingest.md         Agent/human workflow prompt for confirming ingest fields.
  jobs_sources.yaml      Boards to watch + match keywords for jobs_fetch.py.
  preferences.yaml       Filter/rank policy: location hard filter + soft weights + pay floors.
applications/
  YYYY-MM-DD_Company/    job.md · cv-analysis.md · cv-draft.md · cv-draft.pdf
                         cv-feedback.md · cv-review.md · cv.md · cv.pdf
                         cover-letter.md · meta.yaml · source.json
reports/                 Job shortlists (jobs_fetch) + monthly "applied for" summaries.
_legacy/                 Superseded/duplicate files kept for reference, out of the way.
```

## Setup (once)
The toolchain is managed by [mise](https://mise.jdx.dev) + [uv](https://docs.astral.sh/uv/):
```bash
brew install pango        # WeasyPrint native dependency (cairo/pango/gdk-pixbuf)
mise install              # provisions Python 3.12 + uv (pinned in mise.toml)
mise run install          # uv sync -> creates .venv from pyproject.toml / uv.lock
```

## The normal workflow: from jobs to CVs

You drive this flow from an **agent CLI session opened in this repo** — either
**Claude Code** (`claude`) or **Zed's agent panel** — with the **local UI open
in a browser** for looking at jobs and drafts. You don't memorize commands: you
say two things to the agent — **"fetch jobs"** and **"refresh drafts"** — and do
everything a human reviews (triage, read, give feedback, approve) in the UI.

**What the agent does vs. what you do.** The agent runs the `mise` commands and
writes the CV drafts (following `tools/cv-tailor.md`, drawing only on facts in
`profile/master-profile.yaml`). It never approves anything. You look at jobs and
pick them, read the drafts, give feedback, and click **Approve**. The commands
are shown at each step so nothing is hidden — you can always run them yourself.

Then just open the UI in a browser and start talking to the agent:
```bash
mise run ui        # then open http://127.0.0.1:5052/jobs
```
`mise run ui` is idempotent: it asks the port for the UI's health endpoint and
reports "already running" instead of starting a second server, so the
`apply-fetch-jobs` skill starts it for you if it isn't up. You never have to
babysit it. If something *else* owns the port it says so rather than pretending
the UI is up; set `APPLY_UI_PORT` to move it. (The default is 5052 because
macOS AirPlay Receiver holds port 5000.)

### 1. Fetch jobs — say **"fetch jobs"**
The agent ensures the UI is up, runs `mise run jobs` (the `apply-fetch-jobs`
skill), and relays its summary — kept/dropped/scanned counts and the top hits.
This scans the public sources, ranks them, and updates the catalog under
`data/jobs/`. Spotted a role the API can't reach (LinkedIn, email, a PDF)? Copy
its description and say so — the agent uses `mise run ingest -- --url "…"` to
drop it into the *same* catalog (see `tools/jobs-ingest.md`).

### 2. Look at the jobs and pick them — in the UI
Open `http://127.0.0.1:5052/jobs`. It's a two-pane triage board over the active
catalog: filter and sort the feed, browse roles, read the description, and click
**Interested** on the ones worth pursuing. Each click scaffolds
`applications/<date>_Company/` with `job.md`, `source.json`, and `meta.yaml`
filled from the catalog record. Pick your whole set before moving on.

### 3. Draft the CVs — say **"refresh drafts"**
The agent runs `mise run drafts-todo` (the `apply-refresh-drafts` skill) to find
every application that needs a draft — never-drafted ones, plus any where you
left newer feedback — shows you the worklist, and after you confirm, writes a
real `cv-draft.md` for each and runs `mise run cv-check` on it. It reports
pass/fail per application and **never approves**.

### 4. Read the drafts and give feedback — in the UI
Open each application in the UI, read its `cv-draft.pdf`, and for any that need
changes type notes in the **cv-feedback.md** box and click **Check**. Your
feedback is all you need to leave — you don't hand-edit the draft.

### 5. Regenerate from feedback — say **"refresh drafts"** again
`drafts-todo` now lists exactly the applications whose feedback is newer than
their draft, so the agent regenerates just those and re-checks them. Repeat
steps 4–5 until each draft is right.

### 6. Approve — in the UI
When a draft looks right, click **Approve** in the UI. That reruns the gates and,
on your confirmation, promotes `cv-draft.*` to the final `cv.md` / `cv.pdf`. It
refuses while placeholders, missing context, weak ATS evidence, render errors, or
a multi-page PDF remain. The application page also shows an **Apply ↗** link
(from the posting URL) so you can open the employer's form directly.

### 7. Cover letter (optional) — say **"cover letter for <app>"**
Want one? The `apply-cover-letter` skill drafts a truthful `cover-letter.md` from
the job, the approved CV, and the profile — kept consistent with the CV's claims.
It's on demand and per-application (never part of `refresh drafts`). Render a PDF
with `mise run render applications/<date>_Company/cover-letter.md` if you want one.

### 8. Record that you applied
Sending the application is a human action. Afterwards say **"I applied to
<company>"**: the `apply-mark-applied` skill runs the deterministic command that
sets `status: applied` and `date_applied` in the application's `meta.yaml`.
For a historical submission, include the date. A month's applications are the
folders whose metadata has a `date_applied` in that month.

---

**Prefer plain shell, or no agent?** Every step is a `mise` command you can run
yourself: `mise run jobs`, `mise run cv-create …` (scaffold headless),
`mise run cv-start -- <folder>`, then drive the draft loop by asking your
assistant to *"run cv-tailor for <folder>"*, `mise run cv-check -- <folder>`,
`mise run cv-approve -- <folder>`, and `mise run applied -- <folder>`. Each
`mise run <task>` wraps
`uv run python tools/<script>.py`; run `mise tasks` for the full list. The
sections below document the discovery engine, import variants, and reporting in
more depth.

## Development
```bash
mise run fmt     # ruff format  — layout
mise run fmt-check # verify formatting without changing files
mise run lint    # ruff check   — style / unused imports / bug patterns
mise run check   # basedpyright — types + import resolution
mise run test    # offline unittest suite
mise run verify  # fmt-check + lint + check + test
```
These are three different jobs: the formatter fixes layout, the linter catches
style/bug patterns, and the type checker (basedpyright) resolves imports and types —
a clean `lint` does not imply a clean `check`. `mise run check` uses **basedpyright**,
the same engine Zed and other editors now default to, so the CLI and your editor
agree exactly. `[tool.pyright]` in `pyproject.toml` (read by basedpyright too) points
it at `.venv` and pins `typeCheckingMode = "standard"` — the appropriate level for
scripts that parse dynamically-typed JSON, avoiding strict-mode `reportUnknown*` noise.

## Finding jobs (less LinkedIn-email dependence)
Two source types in `tools/jobs_sources.yaml`:

**Discovery (`searches:`) — the primary way, no company names needed.** Cross-company
keyword search against Sweden's public **JobTech / Platsbanken** API (free, no key). One
entry per keyword angle (`typescript developer`, `react native`, …); it returns roles
from every employer in the country with structured fields (employment type, region,
apply URL). This is what replaces manually curating companies.

**Watchlist (`boards:`) — optional.** Specific companies you want to track closely,
straight from their Greenhouse / Lever / Ashby board (token = the slug in
`jobs.lever.co/<token>` etc.). Leave empty to rely purely on discovery.

(LinkedIn has no open API and blocks scraping; JobTech + ATS boards are the legal,
reliable substitute for your alert emails.)

```bash
mise run jobs                  # -> reports/jobs-YYYY-MM-DD.md (+ .jsonl with descriptions)
# Clipboard ingest (LinkedIn / auth-walled pages) — confirm fields first; see tools/jobs-ingest.md
mise run ingest -- --title "…" --company "…" --location "…" --url "…"
```

### How volume becomes a shortlist
For each posting the scanner extracts attributes from the ATS's structured fields first,
then regex over the description as fallback:
**employment** (permanent / contract), **work arrangement** (remote / hybrid / onsite)
and **office days**, **region / timezone**, and **pay**. Filtering is **tri-state** —
each attribute is pass / fail / *unknown*, and a hard filter drops a role only on an
explicit fail, never on unknown (most posts omit pay/office-days; those are kept and
flagged, not rejected).

Policy lives in `tools/preferences.yaml`:
- **Hard filter — location/timezone only.** Onsite/hybrid roles must be in Sweden or the
  EU; remote roles are dropped only if bound to a non-CET zone (e.g. "US only").
- **Soft ranking (everything else).** Permanent ranks above contract; remote above
  hybrid above onsite, and fewer office days rank higher; a stated pay at/above your floor
  boosts, below penalises (never drops). Set your real pay floors in `preferences.yaml`.

Output: a ranked `reports/jobs-<date>.md` where each hit shows its attributes, source,
stable job ID, a `missing-info` note for anything the posting didn't state, and a
ready-to-run report-aware `mise run new` command — plus a **Dropped** section (with
reasons) so you can loosen the filter. The `.jsonl` sibling holds the structured
records, including the fetched job description and provenance.

To import a specific hit manually, use its generated command or select it by company,
title, one-based JSONL line number, or stable ID:

```bash
mise run new --from-report reports/jobs-YYYY-MM-DD.jsonl --match "Navigraph KB"
mise run new --from-report reports/jobs-YYYY-MM-DD.jsonl --job-index 5
mise run new --from-report reports/jobs-YYYY-MM-DD.jsonl --job-id 'jobtech:jobsearch.api.jobtechdev.se:...'
```

For a current JobTech detail fetch, use the stable JobTech ID directly or add
`--refresh` to a report import:

```bash
mise run new --job-id 'jobtech:jobsearch.api.jobtechdev.se:31215727' --refresh
mise run new --from-report reports/jobs-YYYY-MM-DD.jsonl \
  --job-id 'jobtech:jobsearch.api.jobtechdev.se:31215727' --refresh
```

The detail fetch stores the raw response and provenance in `source.json`, while
`job.md` receives the cleaned description. If `job.md` has been edited, the refresh
writes `job.md.new` for review instead of overwriting it. `--force` creates a
`job.md.bak` before replacing it.

Imports are non-destructive: an existing edited `job.md` is preserved. Use `--force`
only when you intentionally want to replace the imported snapshot and `source.json`.

## Monthly reporting
Every application has a `meta.yaml` with `company, role, status, date_applied, source, url`.
A month's applications = the folders dated in that month. A one-line report generator over
those `meta.yaml` files is the remaining next-phase piece (see handover note).

## Worked example
See [docs/examples/parkit-demo.md](docs/examples/parkit-demo.md) for an end-to-end JobTech
import. Application folders themselves are not in this public tree.

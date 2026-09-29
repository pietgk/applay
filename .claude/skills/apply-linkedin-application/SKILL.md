---
name: apply-linkedin-application
description: Create an application from a LinkedIn job URL and pasted description — ingest into the catalog, scaffold the application folder, and draft a truthful CV. Use when the user pastes a linkedin.com/jobs/view link, an auth-walled LinkedIn JD, says add or apply to a LinkedIn role, or asks for a LinkedIn application.
---

# LinkedIn application

End-to-end path for a role LinkedIn (and this repo's fetch) cannot scrape: paste
becomes a catalog record, then an application folder, then a checked CV draft.
Never fetch the LinkedIn URL. Never approve or mark applied.

Field rules for ingest live in `tools/jobs-ingest.md`. The draft procedure
lives in `tools/cv-tailor.md`. Follow those; this skill is the glue.

## Inputs

Need all of:

- **Description body** — the job text, not a bare URL (ingest rejects short /
  URL-only pastes). Chat paste wins over the clipboard; write it to a temp file
  and pass `--text-file`. If the user only sent a URL, ask them to paste the JD
  (or confirm the clipboard holds it and `pbpaste` it into the temp file).
- **Title, company, location** — propose `{title, company, location}` from the
  paste. If the user already named them, or they are unambiguous, ingest in the
  same turn after stating the fields. Pause only when title or company is
  missing or two readings are plausible (ADR-0005).
- **URL** — provenance only. Strip tracking to
  `https://www.linkedin.com/jobs/view/<numeric-id>/`. Blank is allowed.

Default ingest triage: `interested`. Location should keep Sweden/remote words
from the JD so ranking can see them (e.g. `Remote, Sweden`).

## Steps

### 1. Ensure the UI is up

```bash
mise run ui
```

Background, idempotent — same as `apply-fetch-jobs`. Do not wait on it.

### 2. Ingest into the catalog

```bash
mise run ingest -- \
  --title "…" \
  --company "…" \
  --location "…" \
  --url "https://www.linkedin.com/jobs/view/<id>/" \
  --text-file /tmp/<slug>.txt
```

Completion: stdout contains `created ingest:<sha>` (or `unchanged ingest:<sha>`
on a re-run of the same URL). That `job_id` is the handle for the next step.
`--force` only when the user asked to replace a prior ingest of this URL.

### 3. Scaffold the application

This is the Jobs UI **Interested** seam, not `mise run new "Company"` (that
would skip the catalog record).

If the catalog record already has `application:` set, reuse that folder.
Otherwise:

```bash
mise exec -- uv run python -c "from apply.applications import scaffold_from_catalog; print(scaffold_from_catalog('.', 'ingest:<sha>'))"
```

Completion: prints `YYYY-MM-DD_Company`. Catalog triage becomes `applied`
(folder exists). Application `status` stays `draft` until a human submits —
do not treat catalog triage as submitted.

Then initialize draft files:

```bash
mise run cv-start -- applications/<folder>
```

### 4. Draft the CV

Follow `tools/cv-tailor.md` for this one folder (the user named it; do not
batch via `drafts-todo`).

1. Read `job.md`, `profile/master-profile.yaml`, `profile/positioning.md`.
2. Run the job-fit quick test. Record `angle` and `fit_score` with
   `applications.update_meta` (`force=True`) — do not hand-edit `meta.yaml`.
   Catalog `fit_score` is keyword classification; the job-fit test is the one
   that goes on the application. If `fit_score < 3`, flag it, then still draft
   unless they skip.
3. Fill `cv-analysis.md` (evidence map, gaps, truth notes).
4. Replace placeholders in `cv-draft.md`. Facts only from the master profile.
   Mirror top JD terms in at least two sections (summary + skills/experience).
5. Format: look at a recent `applications/*/cv-draft.md` with the same angle.
   Use the `30+ years` framing. Do not list The Future Group as a dated job.

**Placeholder gate:** `cv-check` treats `[…]` and `<…>` on a line as scaffold
placeholders. Do not use markdown links or filled-in bracket tokens in
`cv-analysis.md` or `cv-draft.md`. `%%headline%%` / `%%contact%%` are fine.

### 5. Check

```bash
mise run cv-check -- applications/<folder>
```

Completion: `cv-check: PASS` (or FAIL with named gates). Fix failed gates and
re-check. Do not run `cv-approve` / `cv-finalize`.

### 6. Hand back

Relay folder, `job_id`, angle, fit_score, and gate result. Then:

> Draft written. Review it in the UI — read `cv-draft.pdf` at
> http://127.0.0.1:5052/applications/<folder>. For changes, type notes in
> **cv-feedback.md** and run **Check**. When it looks right, click **Approve**.
> Want a cover letter? Ask. After you submit, say you applied.

## Boundaries

- Do not fetch, scrape, or log into LinkedIn.
- Do not approve the CV or run `mise run applied`.
- Do not draft a cover letter unless asked (`apply-cover-letter`).
- Do not ingest a bare URL. Do not invent title/company.
- Email/PDF pastes that are not LinkedIn stay on `tools/jobs-ingest.md` plus
  the Jobs UI Interested action (or `apply-refresh-drafts` after that).

# Current workflow

The repository turns a job description into a tailored, one-page PDF while
keeping the source material and application status in ordinary files.

```text
public ATS sources or manual JD
              |
       jobs_fetch.py (optional)
              v
     reports/jobs-YYYY-MM-DD.jsonl
              |
       new_application.py
              v
applications/YYYY-MM-DD_Company/
   job.md + source.json + meta.yaml
              |
       cv-start (context + draft)
              v
   cv-analysis.md + cv-feedback.md
              |
       controlled draft generation
              v
         cv-draft.md
              |
       human/AI review loop
              v
   cv-check -> cv-draft.pdf + cv-review.md
              |
       cv-finalize --approve
              v
         cv.md + cv.pdf
```

## 1. Discover or receive a job

`tools/jobs_fetch.py` reads the configured public JobTech, Greenhouse, Lever,
and Ashby sources. It normalizes postings, extracts employment, work
arrangement, region, and pay signals, then writes a dated Markdown shortlist
and JSONL report under `reports/`. The JSONL record contains the description,
stable job ID, source fields, retrieval time, and scoring details needed for a
later import.

Discovery is optional. A manually sourced application can be scaffolded with
`mise run new "Company" --role "Role"`, after which the job description is
pasted into `job.md`.

## 2. Import a selected posting

`tools/new_application.py` creates an application folder and its initial files.
With `--from-report`, it selects one JSONL record by stable ID, one-based index,
or company/title match. The description is copied into `job.md`, the record is
saved as `source.json`, and blank provenance fields are filled in `meta.yaml`.

An existing, edited `job.md` is preserved. A refresh writes `job.md.new` for
review; `--force` is the explicit replacement path and creates `job.md.bak`
when there is edited content. This keeps a previously reviewed job snapshot
from being silently replaced by a later fetch.

## 3. Start and tailor a draft

For a new application, `mise run cv-create` combines application
scaffolding/import and draft initialization. The lower-level
`mise run cv-start -- <folder>` command is useful when the application already
exists or when a UI wants each transition separately.

Run `mise run cv-start -- applications/YYYY-MM-DD_Company/`. It creates
`cv-analysis.md`, `cv-feedback.md`, and `cv-draft.md` without inventing
candidate content. The start operation is idempotent and refuses to overwrite
a non-placeholder draft unless `--force` is supplied.

`tools/cv-tailor.md` is the current human/Codex tailoring procedure. It uses
`profile/master-profile.yaml` as the factual source, chooses a positioning
angle, records evidence and open questions in `cv-analysis.md`, and writes
human corrections and next-draft instructions in `cv-feedback.md`. A
controlled model or other explicitly managed generator uses those inputs to
write `cv-draft.md`; the local UI does not call an AI provider yet.

The loop is deliberately explicit: edit the analysis and feedback, generate a
new draft version, run the checks, then improve the instructions until the
review is useful. The analysis and feedback are never rendered into the CV.

## 4. Check the draft

Run `mise run cv-check -- applications/YYYY-MM-DD_Company/`. It writes
`cv-review.md` and runs five gates: job/profile context, scaffold placeholder
detection, ATS coverage and quantified evidence, PDF rendering, and exactly one
page. The command is offline and returns a nonzero exit code when a gate fails.

The lower-level commands remain useful for focused checks:
`mise run lint-ats ...` and `mise run render ...`.

The workflow renderer uses the locked WeasyPrint engine and `templates/cv.css`
to create the one-page draft PDF. It is a final artifact generator, not a
content editor.

## 5. Finalize with human approval

The convenient `mise run cv-approve -- <folder>` command reruns the checks and
performs the explicit approval/promotion in one user-facing step. The lower-
level `cv-finalize -- --approve <folder>` command remains available for callers
that want to keep those transitions separate.

After reviewing every claim and the PDF, run
`mise run cv-finalize -- --approve applications/YYYY-MM-DD_Company/`.
Finalization reruns all gates, copies `cv-draft.md` and `cv-draft.pdf` to
`cv.md` and `cv.pdf`, leaves the draft/review files intact, and records the
workflow state in `meta.yaml`. Without `--approve`, finalization is refused.

The CLI never calls an AI provider. AI assistance happens in the conversation
or another explicitly controlled client, which writes the analysis and draft
files. A future UI should call the same `src/apply/workflow.py` functions and
display the same artifacts and gates rather than creating a second workflow.

## 6. Apply and record status

Sending the application is a human action. After sending, record it through the
deterministic command:

```bash
mise run applied -- applications/YYYY-MM-DD_Company
```

It performs the guarded `draft` → `applied` transition and records today's date.
Pass `--date YYYY-MM-DD` for a historical submission. Re-running it is safe and
preserves the original date. The `apply-mark-applied` skill resolves natural
requests such as "I applied to Company" to this command; it never infers a
submission from CV approval or catalog triage. Later interview, offer,
rejection, or withdrawal changes are also recorded in `meta.yaml`. The
repository currently has no report generator for these metadata files; monthly
reporting is a later phase.

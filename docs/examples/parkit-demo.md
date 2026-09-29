# Parkit CV demo

This is the end-to-end example for JobTech ad `31215727`. It uses the real
application folder and the real imported job snapshot, while keeping the
current final files unchanged until the approval step.

## 1. Import the job

The report entry is in `reports/jobs-2026-07-10.jsonl` and is also shown as
item 16 in `reports/jobs-2026-07-10.md`.

The original report-aware command is:

```bash
mise run new \
  --from-report reports/jobs-2026-07-10.jsonl \
  --job-id 'jobtech:jobsearch.api.jobtechdev.se:31215727'
```

For a current JobTech detail refresh, the equivalent direct command is:

```bash
mise run new \
  --job-id 'jobtech:jobsearch.api.jobtechdev.se:31215727' \
  --refresh
```

This produced `applications/2026-07-10_ParkitSwedenAb/job.md`,
`source.json`, and provenance fields in `meta.yaml`.

## 2. Create the CV workflow

The convenient user-facing wrapper combines application import and draft
initialization:

```bash
mise run cv-create -- \
  --from-report reports/jobs-2026-07-10.jsonl \
  --job-id 'jobtech:jobsearch.api.jobtechdev.se:31215727'
```

It creates or preserves the application, then creates:

```text
cv-analysis.md
cv-draft.md
```

It does not overwrite an existing approved `cv.md` or `cv.pdf`.

## 3. Human/Codex tailoring pause

Review `job.md`, `profile/master-profile.yaml`, and `profile/positioning.md`.
For this role, the recommended starting angle is `mobile_product`, with
React Native/Expo and end-to-end product delivery in the foreground.

Write the reasoning into `cv-analysis.md`:

- the strongest job requirements and keywords;
- the evidence map from the master profile;
- gaps or claims needing confirmation;
- focused grill-me questions;
- the proposed positioning angle.

Then generate or revise `cv-draft.md` from the complete input bundle: the job,
master profile, positioning, analysis, feedback, and previous draft. The current
repository keeps that model step explicit and controlled; editing analysis or
feedback alone does not rewrite the draft. Every new claim must be profile-backed
or explicitly confirmed by the human before approval.

## 4. Check and iterate

Run the primitive check command after each meaningful draft revision:

```bash
mise run cv-check -- applications/2026-07-10_ParkitSwedenAb
```

This writes `cv-draft.pdf` and `cv-review.md` when possible, and checks:

1. job/profile context;
2. scaffold placeholders;
3. ATS coverage and quantified evidence;
4. PDF rendering;
5. exactly one page.

Improve `cv-analysis.md` and `cv-feedback.md`, generate the next draft version,
then repeat the check.

## 5. Approve the final CV

The convenient wrapper reruns all checks and promotes the draft only when they
pass:

```bash
mise run cv-approve -- applications/2026-07-10_ParkitSwedenAb
```

It copies:

```text
cv-draft.md  -> cv.md
cv-draft.pdf -> cv.pdf
```

The draft, analysis, and review files remain available for inspection. The
primitive `cv-start`, `cv-check`, and `cv-finalize --approve` commands remain
available for a future UI or more controlled workflows.

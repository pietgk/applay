---
name: apply-refresh-drafts
description: Generate or regenerate cv-draft.md for every application that needs one (never drafted, or has newer feedback), then check each. Use when the user says "refresh drafts", "update drafts", "draft the CVs", "regenerate drafts", or after triaging jobs in the UI.
---

# Refresh drafts

Bring every application's `cv-draft.md` up to date: write a first draft for the
ones that were never drafted, and regenerate the ones where the user left newer
feedback. Then run the gates on each so the user can review in the UI. This is
the drafting engine of the normal apply flow.

**This skill never approves.** Approval/finalization is a human click in the UI
(or `mise run cv-approve`). Here we only draft and check.

## Steps

### 1. Get the worklist (deterministic, read-only)
Run:
```bash
mise run drafts-todo
```
This lists exactly the applications that need a draft under **rule A**: the
application status is `draft` (or missing on a legacy record), it is not
finalized, and either `cv-draft.md` still has scaffold placeholders
(*needs first draft*) or `cv-feedback.md` is newer than `cv-draft.md`
(*new feedback since last draft*). It writes nothing.

### 2. Show the plan and confirm
Print the worklist back to the user as a short numbered list with each app's
reason, then ask before doing anything:

> These need drafting:
> 1. 2026-07-20_SellhelpAb — needs first draft
> 2. 2026-06-15_Zymego — new feedback since last draft
>
> I'll draft/redraft these and run the gates on each (I won't approve any).
> Proceed with all, or a subset?

If `drafts-todo` reports "All drafts up to date.", say so and stop.

### 3. For each application in the confirmed set
Do the following, one application at a time:

1. **Draft it** by running the `tools/cv-tailor.md` procedure for that folder:
   read `job.md` and `profile/master-profile.yaml`, run the job-fit test from
   `profile/positioning.md`, record the angle + `fit_score` in `meta.yaml`, fill
   `cv-analysis.md` with the evidence map, then **replace the placeholders in
   `cv-draft.md` with a real, tailored, truthful draft.** On a *regenerate*, also
   read `cv-feedback.md` and the previous `cv-draft.md` and apply that feedback.
   - Every claim must be supported by the master profile — never invent facts.
   - Mirror the top JD terms in at least two sections (summary + skills/experience).
   - If `fit_score < 3`, flag it to the user — it may not be worth pursuing —
     but still produce the draft unless they say to skip.
2. **Check it**:
   ```bash
   mise run cv-check -- applications/<date>_Company
   ```
3. **Report** one line per app: PASS, or FAIL with the failing gates
   (coverage %, quantified hits, page count) and any missing-evidence notes
   from `cv-analysis.md`.

### 4. Summarize and hand back to the UI
After the set, give a compact table: app → gate result → what's needed. Then:

> Drafts written. Review them in the UI — read each `cv-draft.pdf`, and for any
> that need changes, type notes in the **cv-feedback.md** box and run **Check**.
> When one looks right, click **Approve** to promote `cv.md` / `cv.pdf`.
> Left feedback on some? Say **refresh drafts** again and I'll regenerate just those.

## Boundaries
- **Never** run `cv-approve` / `cv-finalize` — approval is the human's call.
- **Never** hand-edit a promoted `cv.md`; only write `cv-draft.md` via the loop.
- Only draft apps that `drafts-todo` lists (plus any the user names explicitly).
  Do not touch finalized applications or ones with an up-to-date draft.

---
name: apply-cover-letter
description: Draft a tailored, truthful cover letter for one application on demand. Use when the user asks for a cover letter for an application, requests a cover-letter draft, or names a company whose cover letter should be written.
---

# Draft a cover letter

Write `cover-letter.md` for a single application, on demand. Cover letters are
deliberate and not always wanted, so this is **never** part of `refresh drafts`
(which only does CVs) — you run it per application when the user asks.

Like the CV draft, this is human+AI content: you write it in the conversation
from the factual sources, drawing only on what the profile and the CV already
support. No `mise` command generates it.

## Inputs (read all before writing)
- `applications/<date>_Company/job.md` — the role, company, and its mission/tone
- `applications/<date>_Company/cv.md` (or `cv-draft.md` if not yet approved) —
  stay consistent with the exact claims already made there
- `applications/<date>_Company/meta.yaml` — `angle` and `fit_score` (match the
  CV's positioning)
- `profile/master-profile.yaml` — factual source; `closers:` offers closing lines
- `profile/positioning.md` — the angle's proof points

## Write `cover-letter.md`
Three to four short paragraphs, ~250–350 words, first person, addressed to the
company. Structure:
1. **Hook** — why this company/mission, specifically (use `job.md`'s own framing;
   for a user-facing product, lead with the user/customer outcome, not tech).
2. **Proof** — 2–3 concrete, truthful achievements from the CV/profile that map
   to the role's top needs. Every claim must already be supported by the profile
   or the approved CV — never introduce a new fact the CV doesn't back.
3. **Fit + close** — the positioning angle in one line, availability/location,
   and a closer (adapt one from `closers:`).

Rules:
- Truthful and defensible — the user must be able to stand behind every line in
  an interview. Respect the same descoping the CV uses (e.g. no "owned the whole
  X" overclaims).
- Match the CV's years-of-experience framing (see the user's CV conventions —
  first-round age framing may apply).
- No invented metrics; reuse the CV's real numbers.
- Plain Markdown, no letterhead/graphics (the shared renderer handles layout).

## After writing
- Show the draft in the conversation and ask for changes.
- Optional PDF when the user wants one:
  ```bash
  mise run render applications/<date>_Company/cover-letter.md
  ```

## Boundaries
- One application at a time; only when asked. Do not batch.
- Do not approve or promote anything. Do not touch `cv.md` / `cv-draft.md`.
- If the CV isn't drafted yet, say so — draft the CV first (`refresh drafts`) so
  the letter stays consistent with it.

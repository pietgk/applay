# cv-tailor — workflow prompt

Paste this (or say "run cv-tailor for <folder>") to tailor a CV from a job description.
It is the repeatable procedure for the structured-profile pipeline and the
human-steered draft loop.

## Inputs
- `profile/master-profile.yaml`  — single source of truth (never invent facts outside it)
- `profile/positioning.md`       — angles + job-fit test
- an application folder `applications/YYYY-MM-DD_Company/` with `job.md` filled in

## Steps
1. **Prepare the application** if needed: `mise run new "Company" --role "Role"`.
   Import the real job description or paste the body (no email headers) into `job.md`.
2. **Start the loop**: `mise run cv-start -- <folder>`. This creates
   `cv-analysis.md`, `cv-feedback.md`, and the initial `cv-draft.md` scaffold;
   it does not generate claims.
3. **Pick the angle**: run the job-fit quick test in `positioning.md`. Record `angle`
   and `fit_score` in `meta.yaml`. If `fit_score < 3`, tell me — it may not be worth it.
4. **Extract JD signal**: list the 8-12 most important requirements/keywords from `job.md`.
   Add the evidence map, recommended focus, gaps, and grill-me questions to `cv-analysis.md`.
5. **Generate or revise `cv-draft.md`** from the complete input bundle:
   `job.md`, `master-profile.yaml`, `positioning.md`, `cv-analysis.md`,
   `cv-feedback.md`, and the previous draft. The current repository leaves the
   model step controlled by the conversation or an explicitly chosen local
   generator; the UI does not call a provider automatically.
   - headline = the angle's `headline_variants` key
   - summary = 3-5 lines from `summary_atoms` whose tags match the angle + JD
   - skills = the skill groups the JD rewards, JD terms first
   - experience = for each relevant role pick the 3-6 bullets whose `tags` match; compress
     older roles to one line. Light rewrite to mirror JD language is OK; **facts stay true**.
   - Mirror the top JD terms in at least TWO sections (summary + skills/experience).
   - Prefer existing quantified bullets (booking 5%→21%, CSAT 3→4.8, release
     velocity) when the angle allows. Do not invent metrics.
   - If the summary uses `30+ years`, the compressed earlier block must include
     undated seniority proof: VP R&D, org ~10→110, or 0-to-1 ERP. Do not add
     dates to Nowark / Mivon / DiMS.
6. **Check the newly generated draft**: run `mise run cv-check -- <folder>`.
   It writes `cv-draft.pdf` and `cv-review.md` when possible. Fix failed gates and
   put human corrections and next-draft instructions in `cv-feedback.md`; do not
   silently edit the generated draft in the UI. Generate the next version, then
   repeat this step for each loop iteration.
7. **Lint** (optional focused view): `mise run lint-ats <folder>/job.md <folder>/cv-draft.md`.
   Aim: coverage >=75%, metrics >=6, words ~430-560. Only add MISSING terms that are
   truthful — do not stuff. Iterate on the generated `cv-draft.md`, re-lint.
8. **Approve and finalize**: after reviewing the Markdown and PDF, run
   `mise run cv-finalize -- --approve <folder>`. This promotes the draft to `cv.md`
   and `cv.pdf` while preserving the draft and review artifacts.
9. **Cover letter** (optional): draft `cover-letter.md`; render with the same tool if a PDF
   is wanted.
10. **Log**: after you send it, record the human-confirmed submission with
    `mise run applied -- applications/<folder>` (the `apply-mark-applied` skill).
11. **Feed back**: if this JD surfaced a strong new proof point, add it to
   `master-profile.yaml` so every future CV benefits.

## Quality bar (2026 ATS/LLM reality)
- Parsing is the gate: text PDF, single column, standard headings — the template handles this.
- LLMs reward meaning, not keyword stuffing; hidden text/stuffing is penalised.
- Context-rich quantified bullets ("5% → 21%", "10→110 people") beat vague ones.

## Recruiter-AI feedback (do not treat as a quality bar)
External resume-AI reports (e.g. Clera) mix real source gaps with generic ATS
theater. Use this file and `master-profile.yaml` as the bar, not the report.

- **Keep `30+ years`.** It is true (career from the early 1980s) and a deliberate
  first-screen convention. "Looks like 15–20 years because early roles have no
  dates" is a known false positive on compressed CVs. Do not soften to "two
  decades" and do not date Nowark / Mivon / DiMS on first-round CVs.
- **Back `30+` with undated seniority proof** in the compressed earlier block
  (VP R&D, ~10→110, or 0-to-1 ERP). One-liners, not 2–3 sentences per company.
- **Do not invent metrics.** Klarna stays qualitative. Core Web Vitals has no
  attested number — never emit that bullet standalone; pair it with a quantified
  sibling (release velocity, conversion) or fold the phrase into that bullet.
- **Pulumi is not a proof point.** Short try-out only. Shipped IaC for the 0-to-1
  products is AWS CDK. Do not list Pulumi in skills or bullets even if the JD
  names it.
- **Ignore ATS theater and generic rewrites** (Languages/Databases/DevOps
  subsection headers, keyword-stuffing the summary, punching up Klarna verbs).
  Canonical bullet wording lives in the profile; do not flatten toward
  resume-AI style.

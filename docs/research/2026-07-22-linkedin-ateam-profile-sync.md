# LinkedIn & A.Team profile sync — can apply be the only SSOT?

- Date: 2026-07-22
- Question: Can this repo maintain a single career profile (experience, education, etc.) and sync it to LinkedIn (and secondarily A.Team), so LinkedIn is not a second source of truth?
- Method: Primary sources only (LinkedIn / Microsoft Learn docs, LinkedIn Help & legal pages, A.Team first-party site/privacy). Secondary material used only where noted as corroboration.
- Repo context: `profile/master-profile.yaml` is already the factual SSOT for CVs ([ADR 0002](../adr/0002-master-profile-is-truth.md)); `profile/sources/linkedin-profile.md` and LinkedIn export PDFs are ingest sources, not authority.

## Executive summary / verdict

**Write-sync LinkedIn from apply: no, not for a personal app.** LinkedIn documents Profile Edit APIs (positions, educations, skills, certifications), but they are restricted to LinkedIn-approved partners and are not among the self-serve “Open Permissions.” The Compliance partner path that historically unlocked deep profile read/write is **closed to new partners** and aimed at FINRA/SEC archiving — not personal career tooling. Marketing / Community Management APIs manage **posts and company pages**, not experience/education sections.

**Read-sync LinkedIn → apply: partially yes, for this member.** Self-serve Sign In with LinkedIn only yields lite identity fields. Full experience/education via classic `r_fullprofile` is **closed**. Practical legal read paths are: (1) Settings → “Get a copy of your data” (Positions, Education, Skills, … — machine-readable, preferred), and (2) for EEA/Switzerland profile location (Sweden qualifies), the **DMA Member Data Portability** Snapshot API domains `POSITIONS`, `EDUCATION`, `SKILLS`, etc. Both are **pull/reconcile into apply**, not a bidirectional sync.

**PDF export: usable fallback ingest, weaker than the data archive.** Sample `profile/sources/Profile-linked-in-22-08-2026.pdf` is a real LinkedIn “Save to PDF” resume (Author=LinkedIn, extractable text, Experience + Education present). Prefer the archive CSV/JSON over PDF for structured reconciliation.

**A.Team: no public builder API to push profile.** They ask for a LinkedIn URL at join; ongoing maintenance is manual (project cards in the UI). Apply can **generate** paste-ready project-card content; it cannot feed A.Team via a documented API.

**Best model:** Keep `master-profile.yaml` as SSOT → **export/checklist/manual update** LinkedIn and A.Team as derived surfaces → optional **occasional read** from LinkedIn archive/DMA to detect drift. Do not automate LinkedIn’s website (ToS-prohibited).

---

## LinkedIn official API capabilities

### Open / self-serve (any developer)

From [Getting Access to LinkedIn APIs](https://learn.microsoft.com/en-us/linkedin/shared/authentication/getting-access) (updated 2025-06-26):

| Product | Permission | What you get |
| --- | --- | --- |
| Sign In with LinkedIn (OIDC) | `openid`, `profile`, `email` | Authenticated member’s name, photo, email — **not** full experience/education history. See [Sign In with LinkedIn using OpenID Connect](https://learn.microsoft.com/en-us/linkedin/consumer/integrations/self-serve/sign-in-with-linkedin-v2). |
| Share on LinkedIn | `w_member_social` | Post, comment, like on behalf of the member — **not** profile section editing. |

**Implication for apply:** Self-serve APIs cannot maintain LinkedIn Experience or Education.

### Profile read (partner / restricted)

- [Profile API](https://learn.microsoft.com/en-us/linkedin/shared/integrations/people/profile-api): “restricted to those developers approved by LinkedIn.” Default returns lite fields; richer field projections require “additional permissions that are only granted to select partners.”
- [Full Profile Fields](https://learn.microsoft.com/en-us/linkedin/shared/references/v2/profile/full-profile): documents `positions`, `educations`, `skills`, etc. under `r_fullprofile` — **“Access to `r_fullprofile` is now closed.”** Marketing FAQ repeats: [`r_full_profile` closed, not accepting requests](https://learn.microsoft.com/en-us/linkedin/marketing/lms-faq?view=li-lms-2026-06).
- [Verified on LinkedIn — `/identityMe`](https://learn.microsoft.com/en-us/linkedin/consumer/integrations/verified-on-linkedin/api-reference/identity-me): Plus tier only adds **most recent education** and **primary current position** — not full career history. Product is for identity verification partners, not personal SSOT sync.

### Profile write (exists in docs; not available to personal apps)

Documented create / partial-update / delete endpoints:

- Positions: [Profile Edit API — Positions](https://learn.microsoft.com/en-us/linkedin/shared/integrations/people/profile-edit-api/positions) — `POST/DELETE …/people/id={id}/positions`
- Educations: [Profile Edit API — Educations](https://learn.microsoft.com/en-us/linkedin/shared/integrations/people/profile-edit-api/educations)
- Skills, certifications, organizations: same Profile Edit API family (e.g. [Certifications](https://learn.microsoft.com/en-us/linkedin/shared/integrations/people/profile-edit-api/certifications) — explicitly “restricted to those developers approved by LinkedIn”)

These endpoints are **not** listed under Open Permissions in [Getting Access](https://learn.microsoft.com/en-us/linkedin/shared/authentication/getting-access). There is no self-serve Developer Portal product that enables “edit my Experience section from my resume tool.”

### DMA Member Data Portability — best legal **read** path for this user

Piet’s LinkedIn location is Sweden (EEA). LinkedIn states Member Portability APIs are for members located in the **EU/EEA or Switzerland** ([Member portability APIs — Help](https://www.linkedin.com/help/linkedin/answer/a6214075)).

- Product: [Member Data Portability (Member)](https://learn.microsoft.com/en-us/linkedin/dma/member-data-portability/member-data-portability-member/) — request via Developer Portal; scope `r_dma_portability_self_serve` (member self-serve path).
- [Member Snapshot API](https://learn.microsoft.com/en-us/linkedin/dma/member-data-portability/shared/member-snapshot-api?view=li-dma-data-portability-2026-05): `GET …/rest/memberSnapshotData?q=criteria&domain=…`
- Domains explicitly include career sections ([Member Snapshot Domains](https://learn.microsoft.com/en-us/linkedin/dma/member-data-portability/shared/snapshot-domain?view=li-dma-data-portability-2026-05)):

  - `POSITIONS` — “Job roles listed on the member's profile, including company names, titles, descriptions, locations, and dates.”
  - `EDUCATION` — schools, dates, degrees, activities
  - Also: `PROFILE`, `SKILLS`, `CERTIFICATIONS`, `PROJECTS`, `LANGUAGES`, `HONORS`, `RECOMMENDATIONS`, …

- Terms: [DMA Portability API Terms](https://www.linkedin.com/legal/l/portability-api-terms) — portability is for obtaining/using your data; **not** a write-back channel. Storage allowed with member consent; no scraping outside Portability APIs.

**Verdict:** DMA Snapshot can **pull** LinkedIn experience/education into apply for drift checks. It cannot push apply → LinkedIn.

---

## Partner / Marketing / Community Management vs member profile editing

### Marketing & Community Management

[Increasing Access](https://learn.microsoft.com/en-us/linkedin/marketing/increasing-access?view=li-lms-2026-06) lists Community Management permissions such as `r_basicprofile`, `w_member_social`, `w_member_social_feed`, org page admin scopes, and analytics (`r_member_profileAnalytics`, `r_member_postAnalytics`). None grant create/update of Experience or Education.

[Community Management Overview](https://learn.microsoft.com/en-us/linkedin/marketing/community-management/community-management-overview?view=li-lms-2026-06) defines **“Profile Management”** as:

> Create and manage **posts, comments, and reactions** while monitoring engagement on behalf of individual profiles.

That is social content, not résumé sections.

### Compliance (historical home of deep profile APIs; closed)

- [Compliance APIs Overview](https://learn.microsoft.com/en-us/linkedin/compliance/compliance-api/overview): `r_compliance` / `w_compliance` for regulated industries; restricted; requires LinkedIn BD agreement.
- [Compliance FAQ](https://learn.microsoft.com/en-us/linkedin/compliance/compliance-api/compliance-faq) (updated 2026-05-15): partner org/customers should be **FINRA/SEC registered**; primary use case is **archiving/monitoring** posts and correspondence; **“Compliance APIs are currently not accepting applications for new Partners.”**
- [Getting Access](https://learn.microsoft.com/en-us/linkedin/shared/authentication/getting-access): Compliance listed as **“(Closed)”** — “Access is closed and may not be requested.”

**Implication:** Even if Profile Edit endpoints still exist in docs for compliance remediation, apply cannot join that program, and the program is closed anyway.

### Talent Solutions

[Getting Access](https://learn.microsoft.com/en-us/linkedin/shared/authentication/getting-access) Talent programs (RSC, Apply Connect, Apply with LinkedIn, Premium Job Posting) are employer/recruiter integrations — not APIs for a member to rewrite their own Experience section from an external SSOT.

---

## Third-party tools that update LinkedIn profiles

### Legal / ToS

LinkedIn [User Agreement §8.2 Don’ts](https://www.linkedin.com/legal/user-agreement) prohibits, among other things:

- Developing/using software, scripts, robots, crawlers, **browser plugins** to **scrape or copy** the Services, including profiles;
- Using **bots or other unauthorized automated methods** to access the Services … or otherwise drive inauthentic engagement;
- Overlaying or modifying the Services’ appearance.

Official Help reinforces this:

- [Prohibited software and extensions](https://www.linkedin.com/help/linkedin/answer/a1341387): third-party software that scrapes, **modifies the appearance of**, or **automates activity** on LinkedIn’s website is not permitted; risk of account restriction/shutdown.
- [Automated activity on LinkedIn](https://www.linkedin.com/help/linkedin/answer/a1340567): same ban; notes third-party automation may violate privacy law in some jurisdictions.

### Technical

Tools that “sync your resume to LinkedIn” typically drive the logged-in web UI (extensions, RPA, unofficial private endpoints). That is exactly what Help forbids. There is **no** LinkedIn-documented consumer product that lets a personal resume app write Experience/Education via OAuth.

**Verdict:** Third-party write-back is neither ToS-clean nor a durable architecture for apply. Do not build or recommend it.

---

## PDF export ingest feasibility

### Official feature

[Save a profile as a PDF](https://www.linkedin.com/help/linkedin/answer/a541960): desktop **More → Save to PDF**; English profile language; limit **200 PDF downloads/month**; not on mobile.

### Sample file inspected

Path: `profile/sources/Profile-linked-in-22-08-2026.pdf`

| Property | Observation |
| --- | --- |
| Metadata | Title=`Resume`, Author=`LinkedIn`, Subject=`Resume generated from profile`, Producer=`Apache FOP Version 2.3` |
| CreationDate | Wed Jul 22 11:50:37 2026 CEST (filename says `22-08-2026` — treat filename as mislabeled; export is Jul 2026) |
| Pages | 11 |
| Text extract | Works via `pdftotext`; two-column layout |
| Sections present | Contact, Summary, Top Skills, Languages, Certifications, Experience (multi-role), Education (Saxion, etc.) |

### Feasibility for apply

- **Yes as fallback ingest:** map Experience/Education text into a draft diff against `master-profile.yaml` / `linkedin-profile.md`.
- **Weaker than archive:** layout/column artifacts; “Present” end dates can lag reality (sample still shows Mindler as Present while master profile records leave date May 2026); less field-normalized than Positions/Education archive files.
- **Prefer machine-readable export:** [Download your account data](https://www.linkedin.com/help/linkedin/answer/a1339364) — categories available within ~10 minutes include **Positions** (company, title, description, location, dates), **Education**, **Skills**, **Certifications**, **Profile**, **Projects**, etc. (category table confirmed via LinkedIn Help HTML for that article).

Resume Builder note: LinkedIn Help states changes in Resume Builder **do not** reflect on the LinkedIn profile (separate artifact) — relevant so apply does not treat LinkedIn resumes as profile sync.

---

## A.Team

### What they extract / require

- Join flow ([a.team/join](https://www.a.team/join)): “Submit your **LinkedIn**, portfolio, or GitHub” → human vetting conversation → missions. LinkedIn URL is an **application input**, not a documented continuous sync.
- Ongoing profile shape is **mission-oriented project cards**, not a 1:1 LinkedIn Experience mirror ([Project cards — first-party article](https://hello.a.team/async/project-cards)): role, company, URL, industry, dates, skills, collaborators, images — curated initiatives, not employer dump.
- Public profile URL pattern `platform.a.team/{username}` requires sign-in when fetched unauthenticated (observed 2026-07-22 for `pietgrootkormelink`).

### APIs / export-import

- **No public developer documentation** for builders to create/update profiles, projects, or expertise via API (searched first-party marketing + platform; none found).
- Platform uses an internal authenticated API (`REACT_APP_API_URL=https://api.a.team` in platform HTML). That is a private product backend, not a partner integration surface for apply.
- [Privacy Policy](https://platform.a.team/privacy-policy): update profile by logging into the account; European users have a right to **transfer** a machine-readable copy of personal information — that is a **user rights** export, not a documented push API for apply to call. Mentions LinkedIn only as a social page / possible third-party data source, not as a sync partner API. Google API limited-use clause present; **no LinkedIn API limited-use partner disclosure**.

### Can apply feed A.Team?

**Not via official API today.** Practical path: generate project-card-ready markdown (or a checklist) from `master-profile.yaml` / application-specific proof points → paste into A.Team UI. Treat A.Team as another **derived surface**, same as LinkedIn.

---

## Recommended architecture: apply as SSOT → LinkedIn / A.Team as derived

```
┌─────────────────────────────────────────┐
│  apply: profile/master-profile.yaml     │  ← only place facts are authored
│  (+ positioning, sources for provenance)│
└──────────────────┬──────────────────────┘
                   │ select / rewrite for CVs (existing)
                   │
     ┌─────────────┼─────────────┐
     ▼             ▼             ▼
  CV PDF/MD    LinkedIn UI    A.Team UI
  (pipeline)   (manual paste  (manual project
                / checklist)    cards)
                   ▲
                   │ optional occasional PULL
                   │ DMA Snapshot or data archive
                   │ (reconcile drift INTO apply)
```

### Concrete practices

1. **Author once in apply** — reinforce ADR 0002; when LinkedIn or A.Team needs a new fact, add it to `master-profile.yaml` first.
2. **LinkedIn publish path (outbound):** generate a “LinkedIn update pack” from master profile (headline variants, About, per-role title/dates/bullets, education) → human pastes into LinkedIn Experience/Education UI. No automation against linkedin.com.
3. **LinkedIn reconcile path (inbound, optional):** periodically request Positions + Education (+ Skills) via Settings data download, **or** (as EEA member) Member Snapshot `POSITIONS`/`EDUCATION`; diff against master; resolve conflicts in YAML, then re-publish to LinkedIn if needed.
4. **Prefer archive/DMA over PDF** for ingest; keep PDF only as emergency snapshot.
5. **A.Team:** map experience bullets → project cards (one initiative per card per their guidance); no expectation of LinkedIn parity.
6. **Do not** pursue Compliance/Profile Edit partner access, browser automation, or unofficial LinkedIn private APIs.

### What “single source of truth” means in practice

LinkedIn will remain a **public presentation layer** that can drift until someone updates it. Apply wins if:

- All application truth flows from `master-profile.yaml`;
- LinkedIn/A.Team updates are **derived rituals** (checklist or generated text), not competing editors;
- Any LinkedIn→apply import is labeled provenance (`profile/sources/…`) and never silently overwrites attested facts without review.

---

## Open questions / blockers

| Blocker | Status |
| --- | --- |
| Self-serve LinkedIn write of Experience/Education | **Blocked** — not in Open Permissions |
| Partner Profile Edit / Compliance access | **Blocked** — Compliance closed; FINRA/SEC use case; not appropriate for personal apply |
| `r_fullprofile` read of full history via classic Profile API | **Blocked** — closed |
| ToS-safe third-party UI automation | **Blocked** — explicitly prohibited |
| A.Team public write API | **None found** (2026-07-22) |
| DMA Snapshot field schemas vs YAML mapping | **Open** — domains confirmed; exact JSON keys per domain need a live token probe when implementing |
| Whether A.Team will accept a CV/PDF upload in lieu of LinkedIn URL for updates | **Open** — ask A.Team support after join; first-party docs emphasize LinkedIn at application time + manual project cards thereafter |
| LinkedIn PDF “Present” vs real end dates | **Known drift risk** — human review required on ingest |

---

## Repo fit (context gathered)

- SSOT already declared: `profile/master-profile.yaml` + ADR 0002.
- Existing LinkedIn-derived source: `profile/sources/linkedin-profile.md`; PDFs under `profile/sources/`.
- Prior research convention: `docs/research/` (this note follows that).
- README already notes LinkedIn has no open jobs API and blocks scraping — consistent with this profile finding.

---

## Sources

### LinkedIn / Microsoft Learn (API)

- https://learn.microsoft.com/en-us/linkedin/shared/authentication/getting-access
- https://learn.microsoft.com/en-us/linkedin/consumer/integrations/self-serve/sign-in-with-linkedin-v2
- https://learn.microsoft.com/en-us/linkedin/shared/integrations/people/profile-api
- https://learn.microsoft.com/en-us/linkedin/shared/references/v2/profile/full-profile
- https://learn.microsoft.com/en-us/linkedin/shared/integrations/people/profile-edit-api/positions
- https://learn.microsoft.com/en-us/linkedin/shared/integrations/people/profile-edit-api/educations
- https://learn.microsoft.com/en-us/linkedin/shared/integrations/people/profile-edit-api/certifications
- https://learn.microsoft.com/en-us/linkedin/marketing/increasing-access?view=li-lms-2026-06
- https://learn.microsoft.com/en-us/linkedin/marketing/community-management/community-management-overview?view=li-lms-2026-06
- https://learn.microsoft.com/en-us/linkedin/marketing/lms-faq?view=li-lms-2026-06
- https://learn.microsoft.com/en-us/linkedin/compliance/compliance-api/overview
- https://learn.microsoft.com/en-us/linkedin/compliance/compliance-api/compliance-faq
- https://learn.microsoft.com/en-us/linkedin/dma/member-data-portability/member-data-portability-member/
- https://learn.microsoft.com/en-us/linkedin/dma/member-data-portability/shared/member-snapshot-api?view=li-dma-data-portability-2026-05
- https://learn.microsoft.com/en-us/linkedin/dma/member-data-portability/shared/snapshot-domain?view=li-dma-data-portability-2026-05
- https://learn.microsoft.com/en-us/linkedin/consumer/integrations/verified-on-linkedin/api-reference/identity-me

### LinkedIn Help / Legal

- https://www.linkedin.com/legal/user-agreement
- https://www.linkedin.com/legal/l/portability-api-terms
- https://www.linkedin.com/help/linkedin/answer/a1341387 (Prohibited software and extensions)
- https://www.linkedin.com/help/linkedin/answer/a1340567 (Automated activity)
- https://www.linkedin.com/help/linkedin/answer/a541960 (Save profile as PDF)
- https://www.linkedin.com/help/linkedin/answer/a1339364 (Download your account data)
- https://www.linkedin.com/help/linkedin/answer/a6214075 (Member portability APIs)
- https://www.linkedin.com/help/linkedin/answer/a1341547 (Data Portability)

### A.Team (first-party)

- https://www.a.team/
- https://www.a.team/join
- https://hello.a.team/async/project-cards
- https://platform.a.team/privacy-policy
- https://onboarding.a.team/builder/

### Local artifacts inspected

- `/Users/grop/apply/profile/master-profile.yaml`
- `/Users/grop/apply/profile/sources/linkedin-profile.md`
- `/Users/grop/apply/profile/sources/Profile-linked-in-22-08-2026.pdf`
- `/Users/grop/apply/docs/adr/0002-master-profile-is-truth.md`

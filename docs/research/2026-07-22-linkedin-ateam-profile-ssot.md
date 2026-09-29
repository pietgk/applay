# Research: LinkedIn / A.Team as derived surfaces from apply SSOT

- Date: 2026-07-22
- Question: Can this repo be the only place to maintain the full professional
  profile (experience, education, projects, expertise), with LinkedIn
  (`linkedin.com/in/pietgrootkormelink`, including Details → Experience /
  Education) and A.Team (`platform.a.team/pietgrootkormelink`) kept in sync
  without becoming second sources of truth?
- Repo context: ADR 0002 already treats `profile/master-profile.yaml` as factual
  SSOT for CVs. Sources already include `profile/sources/linkedin-profile.md`
  and PDF export `profile/sources/Profile-linked-in-22-08-2026.pdf`.

## Executive verdict

**No practical write-sync to LinkedIn.** Official docs describe Profile Edit APIs
that can create/update/delete positions and educations, but those APIs are
partner-restricted and are **not** among the self-serve Open Permissions. Open
consumer access is limited to Sign In (name/headline/photo/email) and Share on
LinkedIn (posts). Full-profile **read** via `r_fullprofile` is closed.

**Read/import from LinkedIn is feasible** for a Sweden/EEA member via DMA Member
Data Portability (Member Snapshot API), or via manual Settings → Get a copy of
your data / Save as PDF. Those paths are **inbound only** — they refresh apply
sources; they do not push changes back to LinkedIn.

**A.Team has no documented public profile API.** First-party builder docs describe
manual project-card editing after LinkedIn-style extraction. Treat A.Team as
another derived surface fed by apply exports, not as a sync target.

**Practical model:** keep editing only in `profile/master-profile.yaml`; generate
LinkedIn- and A.Team-shaped copy packs for human paste; optionally pull LinkedIn
snapshots/PDFs as reconciliation inputs when LinkedIn drifts.

## LinkedIn official API capabilities

### Open permissions (self-serve)

Per [Getting Access to LinkedIn APIs](https://learn.microsoft.com/en-us/linkedin/shared/authentication/getting-access)
(updated 2025-06-26), the only Open Permissions available to all developers
without special approval are:

| Product | Permission | What you get |
| --- | --- | --- |
| Sign in with LinkedIn (OIDC) | `profile` | Authenticated member name, headline, photo |
| Sign in with LinkedIn (OIDC) | `email` | Primary email |
| Share on LinkedIn | `w_member_social` | Post / comment / like on behalf of member |

There is **no** open permission to read full experience/education history or to
edit the member profile.

### Profile read API (restricted; lite only for typical apps)

[Profile API](https://learn.microsoft.com/en-us/linkedin/shared/integrations/people/profile-api)
is explicitly restricted to LinkedIn-approved developers. Documented member
permissions for `/v2/me` are `r_liteprofile`, `r_basicprofile`, and private
`r_compliance`. Default field set is lite/basic (name, headline, vanity name,
photo) — not positions/educations.

[Full Profile Fields](https://learn.microsoft.com/en-us/linkedin/shared/references/v2/profile/full-profile)
(`educations`, `positions`, `skills`, `projects`, …) require `r_fullprofile`.
LinkedIn states: **“Access to `r_fullprofile` is now closed.”**

Verified-on-LinkedIn [Profile Details `/identityMe`](https://learn.microsoft.com/en-us/linkedin/consumer/integrations/verified-on-linkedin/api-reference/identity-me)
can return most-recent education and primary current experience only on Plus
tier with specific scopes — still not a full career history editor.

### Profile Edit API (exists in docs; partner-gated write)

Microsoft Learn documents CRUD for profile sub-resources, including:

- Positions: CREATE / PARTIAL_UPDATE / DELETE at
  `POST|DELETE https://api.linkedin.com/v2/people/id={person ID}/positions[/{id}]`
  ([Positions](https://learn.microsoft.com/en-us/linkedin/shared/integrations/people/profile-edit-api/positions))
- Educations: same pattern under `/educations`
  ([Educations](https://learn.microsoft.com/en-us/linkedin/shared/integrations/people/profile-edit-api/educations))
- Also documented: skills, certifications, organizations, languages, …

The Certifications page states the use of the API is **“restricted to those
developers approved by LinkedIn”**. Profile Edit is **absent** from the Open
Permissions table on Getting Access. Marketing / Sales / Talent partner programs
listed there do not offer a self-serve “edit my own member profile from a
personal tool” product.

**Blocker for apply:** even though write endpoints exist on paper, a personal
job-application repo cannot reasonably obtain partner approval to push experience
and education updates. Plan as if LinkedIn write-back does not exist.

### Member Data Portability — best official **read** path (EEA/CH)

LinkedIn ships DMA regulatory products, including Member Data Portability
([Regulatory catalog](https://developer.linkedin.com/product-catalog/Regulatory),
[DMA overview](https://learn.microsoft.com/en-us/linkedin/dma/)).

[Member Data Portability (Member)](https://learn.microsoft.com/en-us/linkedin/dma/member-data-portability/member-data-portability-member)
lets a member create a developer app (using the designated Default Company Page),
request the **Member Data Portability API (Member)** product, and generate a
token with scope `r_dma_portability_self_serve` via the OAuth Token Generator.

[LinkedIn Help — Member portability APIs](https://www.linkedin.com/help/linkedin/answer/a6214075):
available to members located in the **EU/EEA or Switzerland** (by LinkedIn
profile location). Members elsewhere get errors. **Sweden qualifies.**

[Member Snapshot API](https://learn.microsoft.com/en-us/linkedin/dma/member-data-portability/shared/member-snapshot-api):

```http
GET https://api.linkedin.com/rest/memberSnapshotData?q=criteria
Header: Linkedin-Version: 202312
```

Optional `domain` filter; sample response uses `snapshotDomain: "PROFILE"`.
Docs say a complete domain list is linked from that page; [Recent Changes](https://learn.microsoft.com/en-us/linkedin/dma/member-data-portability/recent-changes?view=li-dma-data-portability-2026-05)
confirm domain additions such as `VOLUNTEERING_EXPERIENCES`. This product is
**read/portability only** — not a write path.

> Note: third-party DMA clients (e.g. Unlinked MCP) enumerate professional
> domains such as `POSITIONS`, `EDUCATION`, `SKILLS`, `PROJECTS`. Treat those
> names as implementation hints; verify against Developer Portal “View
> Endpoints” / current Learn domain docs before building an ingest tool.

### Manual downloads (universal fallback)

[Download your account data](https://www.linkedin.com/help/linkedin/answer/a1339364):
Settings → Data Privacy → Get a copy of your data. Category archives arrive by
email (minutes for selected categories; up to ~24h for larger archives). Available
to all members; not limited to EEA.

## Third-party / automation write tools — not viable

LinkedIn Help [Prohibited software and extensions](https://www.linkedin.com/help/linkedin/answer/a1341387)
forbids third-party software (crawlers, bots, browser plugins/extensions) that
scrape, **modify appearance of**, or **automate activity** on LinkedIn’s website.
User Agreement §8.2 (same prohibitions) bans scrapers and unauthorized bots.

So browser-automation “sync my YAML to LinkedIn Experience” tools are ToS
violations and account-risk — not a recommended architecture for apply.

## PDF export ingest feasibility

Sample file: `profile/sources/Profile-linked-in-22-08-2026.pdf`

| Attribute | Observation |
| --- | --- |
| Generator | LinkedIn “Resume generated from profile” (Apache FOP 2.3) |
| Created | 2026-07-22 11:50 CEST (filename date is misleading) |
| Size / pages | ~103 KB, 11 letter pages |
| Content | Contact, Summary, Top Skills, Languages, Certifications, full Experience narrative, Education |

`pdftotext` recovers structured-enough plain text for reconciliation against
`master-profile.yaml` / `linkedin-profile.md`. Layout is two-column on early
pages (contact vs body), so parsers should use text extraction + section
headers (`Experience`, `Education`), not pixel layout.

**Caveat — LinkedIn can be stale vs apply.** In this PDF, Mindler still shows
roles ending “Present”, while `master-profile.yaml` records leave date 21 May
2026. That drift is exactly why apply should own truth and LinkedIn should be
reconciled outward, not trusted as SSOT.

PDF is a good **fallback ingest** when DMA setup is heavier than needed, and a
good **diff baseline** before a manual LinkedIn update session.

## A.Team

Observed need: platform profile at `platform.a.team/pietgrootkormelink` holds a
copy of profile + projects + expertise + companies (often seeded from LinkedIn).

First-party evidence:

- [Showcase … project cards](https://hello.a.team/async/project-cards) (2022-12-20):
  builders manually add/edit project cards (role, company, URL, industry, dates,
  skills, collaborators, images). Guidance is mission/project-shaped cards, not
  employer dump.
- No public developer API, webhook, or documented import/export format found on
  A.Team marketing/docs surfaces surveyed for this note.
- Sign-in is Google / email to a members-only product; no Product Catalog style
  API listing analogous to LinkedIn’s.

**Implication:** LinkedIn extraction into A.Team is a one-way convenience seed.
Ongoing maintenance is UI paste. apply cannot push programmatically with current
public surface. Best support is generating A.Team-shaped project cards /
expertise lists from `master-profile.yaml` for copy-paste.

Repo already has an A.Team application under `applications/2026-07-21_ATeam/`;
that is CV tailoring, not platform-profile sync.

## Recommended architecture (apply as SSOT)

```text
                    ┌─────────────────────────────┐
                    │ profile/master-profile.yaml │  ← only place humans edit facts
                    └──────────────┬──────────────┘
                                   │
           ┌───────────────────────┼───────────────────────┐
           ▼                       ▼                       ▼
   CV / cover drafts      LinkedIn update pack      A.Team update pack
   (existing tailor)      (markdown sections for    (project cards,
                           About / Experience /      expertise, companies)
                           Education — human paste)
           ▲
           │ optional reconcile
   LinkedIn PDF export  OR  DMA Member Snapshot (EEA)
   → profile/sources/…  →  diff report vs master
```

### Concrete next steps (if implementing later)

1. **Keep ADR 0002.** Never invent facts outside `master-profile.yaml`.
2. **Outbound (high value, low risk):** CLI/skill that renders
   - LinkedIn About + per-role Experience blocks + Education list
   - A.Team project-card stubs (one card per shipped initiative, not per employer)
   from master profile for clipboard/paste.
3. **Inbound (optional):**
   - Parse Save-as-PDF / data archive into `profile/sources/` and emit a drift
     report (e.g. LinkedIn still “Present” at Mindler).
   - Optionally wire DMA Member Snapshot for structured JSON (Sweden-eligible).
4. **Do not build:** LinkedIn browser automation, unofficial scrapers, or
   speculative Profile Edit clients without partner access.

### What “only place to maintain” can mean here

| Surface | Maintain in apply? | Sync method |
| --- | --- | --- |
| apply CVs / letters | Yes (native) | Tailor from master |
| LinkedIn public profile | Facts yes; live page no | Human paste from generated pack |
| A.Team builder profile | Facts yes; live page no | Human paste from generated pack |
| LinkedIn → apply | Occasional import | PDF / data download / DMA read |

True one-click multi-platform push is blocked by LinkedIn partner gates and
A.Team’s closed UI. Single **editorial** SSOT with derived paste packs is the
achievable design.

## Open questions / blockers

1. Will LinkedIn ever open Profile Edit (or a DMA write counterpart) to ordinary
   members? Unlikely soon; Getting Access still lists only Sign In + Share as open.
2. Exact Member Snapshot domain enum for POSITIONS/EDUCATION — confirm in
   Developer Portal when prototyping DMA ingest (Learn “refer here” link not
   resolved in this pass; PROFILE and VOLUNTEERING_EXPERIENCES confirmed officially).
3. Does A.Team expose any undocumented member export or GraphQL from
   `platform.a.team`? Not evidenced in first-party docs; would need product
   support confirmation, not reverse engineering.
4. Should LinkedIn public narrative stay intentionally shorter than master
   (age-camouflage / emphasis), while master stays complete? Positioning choice,
   not an API issue — encode as render profiles in the export pack.

## Sources

### LinkedIn / Microsoft Learn (primary)

- [Getting Access to LinkedIn APIs](https://learn.microsoft.com/en-us/linkedin/shared/authentication/getting-access)
- [Profile API](https://learn.microsoft.com/en-us/linkedin/shared/integrations/people/profile-api)
- [Full Profile Fields (Closed)](https://learn.microsoft.com/en-us/linkedin/shared/references/v2/profile/full-profile)
- [Profile Edit API — Positions](https://learn.microsoft.com/en-us/linkedin/shared/integrations/people/profile-edit-api/positions)
- [Profile Edit API — Educations](https://learn.microsoft.com/en-us/linkedin/shared/integrations/people/profile-edit-api/educations)
- [Profile Details `/identityMe`](https://learn.microsoft.com/en-us/linkedin/consumer/integrations/verified-on-linkedin/api-reference/identity-me)
- [Regulatory Developer Products](https://developer.linkedin.com/product-catalog/Regulatory)
- [LinkedIn DMA overview](https://learn.microsoft.com/en-us/linkedin/dma/)
- [Member Data Portability (Member)](https://learn.microsoft.com/en-us/linkedin/dma/member-data-portability/member-data-portability-member)
- [Member Snapshot API](https://learn.microsoft.com/en-us/linkedin/dma/member-data-portability/shared/member-snapshot-api)
- [Recent Member Data Portability Changes](https://learn.microsoft.com/en-us/linkedin/dma/member-data-portability/recent-changes?view=li-dma-data-portability-2026-05)
- [Member portability APIs (Help)](https://www.linkedin.com/help/linkedin/answer/a6214075)
- [Download your account data (Help)](https://www.linkedin.com/help/linkedin/answer/a1339364)
- [Prohibited software and extensions (Help)](https://www.linkedin.com/help/linkedin/answer/a1341387)
- [User Agreement](https://www.linkedin.com/legal/user-agreement)

### A.Team (primary)

- [Project cards product post](https://hello.a.team/async/project-cards)

### Local

- `docs/adr/0002-master-profile-is-truth.md`
- `profile/master-profile.yaml`
- `profile/sources/linkedin-profile.md`
- `profile/sources/Profile-linked-in-22-08-2026.pdf`

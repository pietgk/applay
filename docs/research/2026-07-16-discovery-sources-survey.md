# Survey: additional discovery sources

- Date: 2026-07-16
- Ticket: [Survey additional discovery sources](https://github.com/pietgk/apply/issues/6)
- Question: JobTech/Platsbanken is the only discovery aggregator today and is weak on
  lead/CTO-level roles and remote-EU React Native product roles. Survey free/API-accessible
  aggregators that might cover those gaps and recommend 1-3 to add.

## Method

Live-queried each source's public endpoint on 2026-07-16 and checked its published API terms.
Numbers below are single-snapshot samples, not long-run averages — treat them as directional.

## Sources surveyed

### Remotive — recommend adding

- **API**: `GET https://remotive.com/api/remote-jobs` — free, JSON, no key. Supports
  `category` and `search` params. ([API docs](https://remotive.com/remote-jobs/api), [ToS](https://support.remotive.com/en/article/terms-of-service-u4kbkf/))
- **Terms**: attribution + link-back required; do not republish to other aggregators
  (Jooble, Google Jobs, LinkedIn Jobs, etc. — not a concern for a personal catalog); jobs are
  delayed 24h; **max ~4 requests/day** advised, excessive requests blocked. Fine for a daily
  fetch cadence.
- **Snapshot** (`category=software-dev`, n=39): 15/39 (38%) had an EU/EMEA/worldwide-ish
  `candidate_required_location`; 15/39 titles matched lead/staff/principal/CTO keywords
  (though in this snapshot most of those were LatAm-restricted, not EU); 20/39 tag-matched
  "react native" (tag co-occurrence, likely overcounts literal RN roles).
- **Verdict**: structured JSON, same shape as JobTech, cheap to integrate into
  `jobs_fetch.py` as a new `source: remotive` adapter. Volume is modest (dozens, not
  hundreds) but the EU share and lead-title share are both meaningfully non-zero.

### RemoteOK — recommend against

- **API**: `GET https://remoteok.com/api` — free, JSON, no key. ([Terms embedded in
  response payload])
- **Terms**: attribution + link-back required, no other restriction found.
- **Snapshot** (n=100, unfiltered): only 5/100 (5%) matched lead/staff/principal/director
  keywords, and those were mostly non-engineering (Product Director, Head of Creative
  Studio, Director of Social Media). 0/100 mentioned React Native. Locations skew heavily
  "Worldwide"/US/LatAm with sparse EU representation.
- **Verdict**: technically free and easy to integrate, but the role mix in this snapshot is
  weak for both target gaps — mostly non-technical/ops remote roles. Lower priority than
  Remotive; **not** recommended as one of the first additions.

### We Work Remotely — recommend against

- **Access**: only a public **RSS feed** (`weworkremotely.com/categories/*.rss`); the JSON
  API is invite-only ("email hello@weworkremotely.com to partner"). ([Terms & Guidelines](https://weworkremotely.com/api-terms-and-guidelines) — returned 403 on direct fetch during
  this survey, corroborating it isn't meant for open automated access; terms captured via
  search-engine cache).
- **Terms**: explicitly **prohibits storing/persisting data beyond what's exposed by the
  API** ("scraping, copying, saving, or storing their data is strictly prohibited"). That
  conflicts directly with this repo's persistent job-catalog design (upsert-by-job-id,
  lifecycle state) — the ToS only contemplates transient display, not a stored catalog.
- **Snapshot** (`remote-programming-jobs.rss`, n=25 — RSS only returns the most recent
  batch, no historical query): 18/25 "Anywhere in the World", 1 lead-ish title, 1 explicit
  React Native mention.
- **Verdict**: small window (RSS, ~25 items, no pagination), and the storage restriction is
  a poor fit for the catalog architecture. Skip.

### Hacker News "Who is Hiring" (via Algolia HN Search API) — recommend adding

- **API**: `https://hn.algolia.com/api/v1/*` — free, public, no auth, no documented rate
  limit, no restrictive ToS (it's a search index over public HN content).
  ([API docs](https://hn.algolia.com/api))
- **Shape**: **not structured job postings** — each "Ask HN: Who is hiring?" thread (posted
  monthly) has one comment per job, as free-text prose. Title/location/remote-status/role
  level all live inside the comment body; extracting them needs a small parser (regex/keyword
  pass, not a clean schema like JobTech/Remotive).
- **Snapshot** (July 2026 thread, [id 48747976](https://news.ycombinator.com/item?id=48747976),
  n=279 posts): 79/279 (28%) mention lead/CTO/VP-eng/staff/principal-level keywords; 15/279
  mention React Native explicitly; 42/279 mention Europe/EU/EMEA/a named EU city.
- **Verdict**: by far the strongest signal for exactly the two gaps named in this ticket —
  more than 1 in 4 posts skew senior/leadership, and EU mentions are dense. The cost is
  integration effort: needs a lightweight extractor (title line + location/remote keywords)
  rather than a JSON-to-JobRecord mapping. Worth the effort given the gap it closes;
  recommend adding as a second source, sized as its own follow-on ticket for the parser design.

### Otta / Welcome to the Jungle — out of scope, same reasoning as LinkedIn

- Otta was acquired by / merged into Welcome to the Jungle (WTTJ) during 2025-2026.
  ([coverage](https://www.whatjobs.com/news/what-reviews-welcome-to-the-jungle-otta-2026/))
- No free public API for job seekers was found. The only programmatic access is **paid**
  third-party data feeds/scrapers (Techmap, Apify, Mantiks) reselling WTTJ listings.
- **Verdict**: same profile the map already ruled out of scope for LinkedIn — paid,
  third-party, ToS-grey scraping. Recommend treating consistently: do not add.

## Recommendation

Add **Remotive** (structured JSON, cheap `jobs_fetch.py` adapter, same shape as the existing
JobTech integration) and **HN "Who is Hiring"** (unstructured but by far the best-targeted
signal for lead/CTO and remote-EU RN roles; needs a small parser — worth scoping as its own
ticket). Skip RemoteOK (weak role-mix fit) and We Work Remotely (ToS forbids the persistent
storage this repo's catalog needs). Treat Otta/WTTJ as out of scope, matching the LinkedIn
decision already on the map.

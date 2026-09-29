---
screen:
  what: Shows the live catalog of discovered job postings for triage.
  why: Keeps discovery decisions in one place before a posting becomes an application workspace.
  how: Builds a server-rendered feed from current non-stale catalog records.
  ref: docs/intent/jobs.md
filters:
  what: Narrows and orders the ranked feed by angle, fit, triage bucket, and sort.
  why: Keeps the skim surface focused on the roles worth deciding now.
  how: Stores every selection in query parameters so reloads and detail navigation preserve it.
  ref: docs/intent/jobs.md
feed:
  what: Presents one flat ranked feed of rich job cards.
  why: Supports quick comparisons without fragmenting jobs into competing groups.
  how: Shows fit, role context, cues, freshness, closing pressure, and triage state on each row.
  ref: docs/intent/jobs.md
detail:
  what: Shows the complete selected posting and its triage actions.
  why: Lets a decision happen beside the feed without losing the current place.
  how: Uses ordinary navigation and anchored redirects to keep the selected row in view.
  ref: docs/research/2026-07-22-jobs-list-refresh-scroll-options.md
---
Jobs is the catalog and triage screen: one flat ranked feed beside a detail pane on the shared 70vw shell (feed ~40% / detail ~60%). There are no triage-group headers; rich cards carry fit, title, company, location, angle, blurb, cues, freshness/closing badges, and a triage chip when the row is interested or skipped.

Filters live in query parameters: angle multi-select, minimum fit, triage buckets (open / closing / interested / skipped), and sort (fit default, deadline, or newest). Defaults show open + closing + interested and hide skipped, but only when no bucket choice was submitted — an all-unchecked filter form yields an empty feed, not a reset. Empty states name the fix: empty or all-stale catalogs ask for a fetch; only a live catalog the filters exclude suggests widening the feed.

Detail opens Interested / Skip beside the feed. Place-keeping uses fragments + PRG (`#job-<id>`), not htmx. Skip keeps the submitted buckets and pins only that job into the feed so one skip never unhides the rest of skipped.

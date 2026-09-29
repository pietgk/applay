# jobs-ingest — clipboard ingest workflow prompt

Paste this (or say "ingest this job") after copying a job description to the
clipboard. The deterministic CLI never calls a provider — no SDK, no API key.
You propose fields in-conversation; the human confirms before anything is
written (ADR-0005).

## Inputs
- Clipboard holding the job description body (not a bare URL)
- Optional posting URL for provenance (never fetched)

## Steps
1. **Read the paste**: run `pbpaste` (or ask the human what they copied) and
   skim enough to propose `{title, company, location}`.
2. **Propose fields** in-conversation. Ask the human to confirm or correct.
   Also ask for the posting URL (blank allowed when the paste has no stable
   link — LinkedIn sometimes).
3. **Write the catalog record** with the confirmed values:
   ```bash
   mise run ingest -- \
     --title "…" \
     --company "…" \
     --location "…" \
     --url "…"          # omit or pass empty for paste-only
   ```
   Defaults: triage `interested`. Use `--triage open` when it should not jump
   the interested queue. Use `--force` only when replacing a prior ingest of
   the same URL (writes a `.bak`).
4. **Scaffold later** via the normal catalog→application path
   (`mise run new --from-report …` or the Jobs UI Interested action). There is
   no `--scaffold` on ingest. A LinkedIn URL plus paste that should become an
   application and CV draft is the `apply-linkedin-application` skill.

## Notes
- Location/TZ and angle weak-floor gates warn but never drop an ingest.
- Re-ingesting the same URL without `--force` is a no-op (idempotent).
- Manual-paste descriptions are authoritative; fetches will not overwrite them.

---
name: apply-fetch-jobs
description: Fetch a fresh ranked job shortlist into the catalog and hand off to the /jobs UI for triage. Use when the user says "fetch jobs", "get jobs", "find jobs", "refresh the shortlist", or starts the apply pipeline.
---

# Fetch jobs

Step 1 of the normal apply flow. This skill is a thin orchestrator: it runs
deterministic commands and relays their output. It does **not** rank, re-describe,
or select jobs — `mise run jobs` already produces the authoritative summary, and
selection is a human action in the `/jobs` UI.

## Steps — run these, don't reason about them

### 1. Ensure the UI is up (idempotent)
Start it **in the background**:
```bash
mise run ui
```
`mise run ui` probes the port first: if the UI is already running it prints
"UI already running" and exits; otherwise it starts. Safe to call every time —
never spawns a duplicate. Do not wait on it (it serves until stopped).

### 2. Fetch
```bash
mise run jobs
```
Offline-safe to re-run; calls no AI provider. It scans the configured sources,
ranks hits, writes `reports/jobs-<date>.md` (+ `.jsonl`), updates the catalog
under `data/jobs/`, and prints the summary + top hits + a `Next:` line.

### 3. Relay
**Relay the `mise run jobs` output to the user verbatim** — the headline counts
(kept / dropped / scanned / errors), the top hits it listed, and its `Next:`
line. Do not re-rank, re-summarize, or re-describe the jobs; the command is the
source of truth. Add at most one sentence of your own if something genuinely
needs flagging (e.g. zero kept, or errors > 0).

## Boundaries
- Do **not** select jobs or create applications — the user triages in the UI.
- Do **not** draft CVs here; that is the `apply-refresh-drafts` skill.
- Spotted a LinkedIn role with a pasted description? That is the
  `apply-linkedin-application` skill (ingest + scaffold + draft). Other
  auth-walled pastes (email, PDF) go into the same catalog with
  `mise run ingest -- --url "…"` (see `tools/jobs-ingest.md`).

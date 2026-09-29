# ADR 0003: Preserve job snapshots and provenance

- Status: accepted
- Date: 2026-07-10

## Decision

An imported job keeps a readable `job.md` snapshot, a `source.json` record, and
provenance comments in the Markdown. `meta.yaml` receives stable IDs, source
URLs, query information, description source, and fetch time when available.
Refreshing an edited snapshot writes `job.md.new`; replacement requires
`--force`, which creates `job.md.bak`.

## Context

Public job postings change or disappear, while an application must remain
auditable against the description used at the time. The current importer
already implements non-destructive refresh behavior.

## Consequences

The application folder is a durable historical snapshot. It may contain
several source artifacts, and users must review `.new`/`.bak` files when they
choose to refresh or replace content.

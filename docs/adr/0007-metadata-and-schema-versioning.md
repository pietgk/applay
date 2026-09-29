# ADR 0007: Evolve metadata additively and version deliberately

- Status: accepted
- Date: 2026-07-10

## Decision

Keep the current informal `meta.yaml`, report JSONL, and `source.json` shapes
backward-compatible and additive. Do not add a version field or migration
solely for this documentation milestone. If a future change makes an existing
field change meaning or representation, introduce an explicit schema version,
document the migration, and retain a reader for older artifacts where
practical.

## Context

The scaffold and importer already share field names, but there is no formal
schema package or version marker. Existing applications contain older and
source-specific combinations of fields, so silently rewriting them would risk
losing provenance or status.

## Milestone 4 amendment

The local UI introduces `cv-feedback.md` as an optional additive artifact and
recognizes an optional `drafts/<version>/` history directory. Older application
folders remain valid when these paths are absent; no migration is required.
Actual draft generation and archival are separate controlled operations and
are not implemented by the local UI yet.

## Job-catalog amendment

The persistent job catalog (`data/jobs/`) is a new artifact family and starts
versioned from day one: every per-job record and the index carry
`schema_version`. Changes to the record's field meanings bump the version
and follow the migration rule above. Report JSONL and `meta.yaml` shapes are
unchanged by the catalog's introduction.

`schema_version: 2` (angle scoring): `score` is the attribute preference
score only (no longer keyword+attrs); `hits` are matched primary-angle cues;
additive `angle`, `fit_score`, and `fit_breakdown` fields carry fit ranking.
Older `schema_version: 1` catalog files are discarded by the next fetch
(gitignored scratch data, no migration).

Clipboard ingest adds optional provenance fields without a version bump:
`source_url`, `raw_paste`, `ingested_at`, `parsed_by`, and `parse_confirmed`.
Absent fields read as empty/false; fetch-admitted records leave them blank.

`acknowledged_at` is similarly additive (no version bump): set when a job is
opened in the `/jobs` UI so derived New labels clear; absent means unacknowledged.

`schema_version: 3` (multi-source clusters): additive `cluster_id` (hash of the
normalized employer/apply URL, or empty for singletons). Recomputed on every
upsert; older catalog files pick it up on the next fetch/ingest write.

## Application events amendment

The application event model (#28, built in #39) extends `meta.yaml` without a
version marker, because the rule above is satisfied by readers rather than a
migration:

- `events:` is a new optional list. Absent means "no timeline yet"; every
  application written before the model existed keeps parsing and sorting. Its
  `kind` values are a closed enum (`status_changed`, `email`, `link`, `note`);
  per-kind required and optional fields live in `applications.EVENT_FIELDS`.
  Bulky `email`/`link` payloads live as sibling files under the application's
  `events/` folder, referenced by the event's `ref`.
- The flat `notes:` field is renamed `summary:` (the standing fit rationale,
  as distinct from dated `note` events). This is a field rename, so the
  compatibility reader is the migration: `applications.summary()` reads
  `summary:` and falls back to `notes:`. Existing folders are not rewritten —
  no batch migration runs over them, and a `notes:`-only application renders
  exactly as before. The scaffold writes `summary:` from now on.
- `last_activity_at` is **derived on read** (`applications.last_activity_at()`)
  from the flat dated fields and the event `when`s, and is deliberately never
  stored, so no field can drift from the facts it summarizes.

Three field-owned entry points therefore share `meta.yaml`. The line-oriented
`update_meta` writes ordinary flat fields but rejects `status` and
`date_applied`. `append_event` writes non-status events and their payloads but
rejects `status_changed`. `set_status` is the scoped overlap: it updates the
`status` head, fills an empty `date_applied` when entering `applied`, and appends
the matching `status_changed` event through one atomic file replacement. All
three entry points serialize their complete mutation against the application
folder, including payload reference allocation and commit. Implicit event
instants and date-only clock components are captured only after entering that
serialized operation. A status transition whose resolved instant precedes the
latest status event is rejected; historical backfill is a separate, currently
unsupported operation. The human-confirmed application flow also decides
eligibility, immutable-date conflicts, and its authoritative result there. A
`date_applied` already on record is the day of the first submission and is never
overwritten — for the folders written before `events:` existed it is the only
record of that day, so a later pick of `applied` adds its event and leaves the
date alone. A canonical UTC event does not preserve the separately supplied
submission calendar day. If prior status history has entered `applied` but the
cache is empty, `set_status` refuses repair rather than deriving or accepting a
new date. A genuinely first transition into `applied` still writes the cache
and event atomically, while legacy repair with no status-transition history
remains available. Status mutations reject malformed history, including equal
transition endpoints and timezone-naive event instants, with a precise indexed
error before applying chronology rules. Date-only inputs require extended
`YYYY-MM-DD` form and a rule-bearing local timezone; basic dates are rejected,
and only implicit current instants may fall back to a fixed current offset.
Picking the status the application already holds is not a transition and writes
no event.
The event writer verifies before every replacement that only the fields owned by
that operation changed.

## Consequences

New optional fields can be added without breaking current folders and reports.
Schema-changing work must include compatibility tests and a documented migration
decision (as the Application events amendment does for the additive `events:`
list and the `notes:` → `summary:` rename). Older folders stay readable without
a batch rewrite.

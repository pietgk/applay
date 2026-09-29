# ADR 0006: Keep CLI scripts, core logic, and UI concerns separate

- Status: accepted
- Date: 2026-07-10

## Decision

The current command-line scripts remain the integration boundary. Their pure
helpers are the testable core seams; file and network access stays at the
script edges. No web UI or package extraction is part of this foundation
milestone.

## Context

`jobs_fetch.py`, `new_application.py`, `ats_lint.py`, and `render_cv.py` are
already usable as command-line tools and expose enough pure functions for
offline tests. Introducing a UI or a new package layout would change the
workflow and broaden this milestone.

## Milestone 4 scope update

The foundation milestone intentionally stopped before a UI. Milestone 4 adds a
private, localhost-only Flask UI as a thin adapter over the existing seams.
This does not replace the CLI, move workflow logic into the UI, or introduce a
second implementation of ATS or PDF behavior.

## Discovery-upgrade scope update

The job-discovery prefactor (issue #15) moves the fetch run — source
dispatch, dedupe, scoring, and report writing — into `src/apply/fetch.py`
behind an injected transport, so fixture payloads can drive a complete run
offline. HTTP requests, TLS trust, and argument parsing stay in
`tools/jobs_fetch.py`; report files are now written by the core seam rather
than the script edge. The persistent job catalog (issue #16) extends the same
carve-out: `src/apply/catalog.py` owns reads and writes under `data/jobs/` so
that every interface (CLI today, UI later) goes through one core module.

## Agent-session scope update

The local UI may host Agent Client Protocol (ACP) agent subprocesses and own
their runtime lifecycle. Process startup, session routing, transcript capture,
stream delivery, permission round-trips, cancellation, and process recovery are
adapter responsibilities. They do not move workflow rules, prompt templates,
provider credentials, or skill implementations into the UI.

The hosted agent runs the project's existing skills from the repository root
and writes durable results through the existing CLI and core seams. The UI
therefore remains a thin adapter even though it is no longer stateless: it
coordinates a process and presents its protocol, while the core continues to
own application and queue behavior.

## Consequences

Tests can exercise normalization, selection, placeholder, lint, and rendering
logic without network access. Some modules still have script-oriented imports
and filesystem constants; a later extraction can be justified when reuse or a
new interface requires it.

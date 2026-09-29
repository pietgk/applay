---
screen:
  what: Shows every application workspace in one flat list.
  why: Keeps the campaign readable as work moves and completed applications naturally settle.
  how: Orders the list by latest derived activity, then by folder name for deterministic ties.
  ref: docs/intent/applications.md
application_list:
  what: Presents one row per durable application workspace.
  why: Keeps active and terminal applications together without hiding recent movement.
  how: Derives recency from dated workflow fields and timeline events rather than a stored cache.
  ref: docs/adr/0007-metadata-and-schema-versioning.md#application-events-amendment
status:
  what: Shows the current application status head.
  why: Makes the campaign state scannable without replacing the status-change history.
  how: Reads the flat status field maintained alongside status transition events.
  ref: docs/adr/0007-metadata-and-schema-versioning.md#application-events-amendment
workflow:
  what: Shows the latest CV workflow state for each application.
  why: Makes the next drafting or review action visible from the list.
  how: Reads the application workspace metadata without running the workflow.
  ref: docs/adr/0006-cli-core-ui-boundary.md
fit:
  what: Shows the recorded fit score for the role.
  why: Preserves the original relevance signal while the campaign evolves.
  how: Reads the application snapshot's fit score and leaves unknown scores explicit.
  ref: docs/adr/0007-metadata-and-schema-versioning.md
---
Applications is the campaign overview: one flat list sorted by derived `last_activity_at` descending, with folder-name ties, and no status grouping or "show closed" toggle. Terminal applications (`rejected`, `withdrawn`, `accepted`) stay visible and sink naturally as activity stops; they may briefly float when they are what just changed. Recency comes from dated flat fields and event `when`s (ADR-0007), never a stored activity cache.

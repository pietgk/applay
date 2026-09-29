---
screen:
  what: Shows one application as a job card above an event timeline.
  why: Keeps role context, current state, history, and working files together.
  how: Reads the file-backed workspace and selects the newest timeline item by default.
  ref: docs/intent/application.md
job_card:
  what: Shows the application-specific role context and standing fit summary.
  why: Keeps the reason for pursuing the role visible while reading its history.
  how: Reads fit, company, role, posting link, and summary from the application snapshot.
  ref: docs/intent/application.md
status:
  what: Shows and changes the live status head for this application.
  why: Makes the current state quick to scan while preserving an honest transition history.
  how: Labels natural next states but permits any state and appends a transition when the head moves.
  ref: docs/adr/0007-metadata-and-schema-versioning.md#application-events-amendment
events:
  what: Lists the complete application story newest first.
  why: Keeps workflow moments and captured communication in one skimmable history.
  how: Merges flat dated moments with stored events and opens one selection in the detail pane.
  ref: docs/intent/application.md
event_status_changed:
  what: Records an honest transition between two application statuses.
  why: Preserves how the campaign moved while the dropdown shows only the live head.
  how: Stores the previous state, next state, and transition instant in the append-only event list.
  ref: docs/adr/0007-metadata-and-schema-versioning.md#application-events-amendment
event_email:
  what: Captures an incoming or outgoing application message.
  why: Keeps correspondence inside the application story instead of scattering it across inbox context.
  how: Stores message metadata on the event and reads the body from its referenced sibling file.
  ref: docs/adr/0007-metadata-and-schema-versioning.md#application-events-amendment
event_link:
  what: Attaches an external resource to this application.
  why: Keeps candidate portals and other relevant links beside the history that needs them.
  how: Stores the URL and label as a dated link event.
  ref: docs/adr/0007-metadata-and-schema-versioning.md#application-events-amendment
event_note:
  what: Records a dated observation about this application.
  why: Keeps time-specific context separate from the standing summary in the job card.
  how: Stores free-form text as an append-only note event.
  ref: docs/adr/0007-metadata-and-schema-versioning.md#application-events-amendment
event_event:
  what: Shows a stored application event.
  why: Keeps unrecognized legacy history visible rather than silently dropping it.
  how: Presents the stored event through the same selected-event detail seam.
  ref: docs/adr/0007-metadata-and-schema-versioning.md
moment_date_fetched:
  what: Marks when the saved posting snapshot was fetched.
  why: Identifies the application-specific source used for tailoring and checks.
  how: Reads the flat date_fetched field and presents job.md as the selected detail.
  ref: docs/adr/0007-metadata-and-schema-versioning.md
moment_date_created:
  what: Marks when the durable application workspace entered the campaign.
  why: Gives every application a visible beginning even before later events exist.
  how: Reads the flat date_created field and presents its role context.
  ref: docs/adr/0007-metadata-and-schema-versioning.md#application-events-amendment
moment_date_applied:
  what: Preserves the calendar day of the first real submission.
  why: Keeps the human-confirmed submission date stable across later status changes.
  how: Reads the immutable flat date_applied field without duplicating it as a workflow event.
  ref: docs/adr/0007-metadata-and-schema-versioning.md#application-events-amendment
moment_draft_started_at:
  what: Shows the live draft workspace and its archived versions.
  why: Keeps iteration history attached to the draft moment instead of creating a separate section or screen.
  how: Reads the saved cv-draft.md, job.md, and profile context alongside analysis, feedback, the live iteration, and any drafts/<version>/ snapshots.
  ref: docs/intent/application.md
moment_last_checked_at:
  what: Shows what the latest saved draft check observed.
  why: Makes review results inspectable without changing the draft.
  how: Reads the persisted gate report and offers the same deterministic check again.
  ref: docs/adr/0006-cli-core-ui-boundary.md
moment_finalized_at:
  what: Shows the explicitly approved final snapshot.
  why: Distinguishes promoted application files from a draft that may later change.
  how: Reads the final Markdown and PDF produced from a passing, human-approved draft.
  ref: docs/intent/application.md
moment_workspace:
  what: Keeps application files and workflow actions reachable at all times.
  why: Ensures legacy or sparse timelines still expose the durable workspace.
  how: Saves only the chosen editable file while checks read the saved draft, posting, and profile context.
  ref: docs/adr/0006-cli-core-ui-boundary.md
---
Application is the single-workspace screen: a compact job-card header (fit, company, role, posting link, standing summary) and status dropdown above the shared 70vw shell (event rail ~40% / selected-event detail ~60%). The rail merges flat dated workflow moments with `events:` kinds (`status_changed` / `email` / `link` / `note`), newest first; default selection is the newest row. An always-present Application workspace row keeps files and workflow actions reachable. Browse in the detail pane rather than accordioning the rail; selection is carried by `?event=` + `#event-<key>` after navigation and writes (PRG). Status changes go through `applications.set_status` (see ADR-0007): natural next states are labelled, every status stays selectable, and a head move appends `status_changed`.

Info carriers on this screen are the job-card chrome, Status, the Events heading, and every selected event — including dynamic draft-archive facts on the draft moment. There are no top-of-page workflow panels and no competing `<details>` Info drawers; draft-version history lives in the draft event's Info (live head + `drafts/<version>/` when present), not a separate page section.

# Domain model

This glossary names the durable concepts in the file-backed application workflow. Detailed screen intent is authored once in `docs/intent/`; binding implementation constraints live in the ADRs linked below.

## Glossary

| Term | Meaning | Authoritative detail |
| --- | --- | --- |
| **Jobs** | The catalog screen for discovered external postings and triage. | [Jobs intent](intent/jobs.md) |
| **Applications** | The activity-ordered list of durable application workspaces. | [Applications intent](intent/applications.md) |
| **Application** | The screen for one application's role context, live status, event timeline, and artifacts. | [Application intent](intent/application.md) |
| **Info** | Contextual `ℹ` popovers beside the element they explain. Copy is authored in `docs/intent/` (what / why / how / ref plus screen narrative). Opens on click; closes on second click, outside click, or Escape. Info is a pattern, not a Help or Docs screen. Agent-dock Info is shared chrome, not a fourth screen. | [Issue #46](https://github.com/pietgk/apply/issues/46), the three screen intent files above, and [ADR-0009](adr/0009-local-ui-hosts-acp-agent-sessions.md) for agent-dock Info placement |
| **Job catalog** | Current-state records under `data/jobs/by-id/`, with `data/jobs/index.json` as an index and `data/jobs/last_fetch_at` as the freshness watermark. | [ADR-0007](adr/0007-metadata-and-schema-versioning.md) |
| **Application workspace** | One independent job-specific folder under `applications/`, normally named with its creation date and company. | [ADR-0001](adr/0001-file-based-artifacts.md) |
| **Job snapshot** | The readable `job.md` saved inside an Application and used for tailoring and checks. | [ADR-0001](adr/0001-file-based-artifacts.md) |
| **Application metadata** | The workspace's `meta.yaml`, containing flat heads, dated workflow fields, and optional append-only events. | [ADR-0007](adr/0007-metadata-and-schema-versioning.md) |
| **Event** | A dated `status_changed`, `email`, `link`, or `note` entry in Application metadata. | [ADR-0007 application events amendment](adr/0007-metadata-and-schema-versioning.md#application-events-amendment) |
| **Workflow moment** | A dated flat metadata field rendered directly in the Application timeline, without duplicating it into `events:`. | [Application intent](intent/application.md) |
| **Status head** | The current application status stored flat in `meta.yaml` and written through with transition history. | [ADR-0007 application events amendment](adr/0007-metadata-and-schema-versioning.md#application-events-amendment) |
| **Standing summary** | The current fit rationale stored as `summary:`; readers fall back to the legacy `notes:` field. | [ADR-0007 application events amendment](adr/0007-metadata-and-schema-versioning.md#application-events-amendment) |
| **Last activity** | A read-time derivation from dated flat fields and event instants, never a stored field. | [ADR-0007 application events amendment](adr/0007-metadata-and-schema-versioning.md#application-events-amendment) |
| **Agent dock** | Persistent, collapsible shared chrome for live conversation and activity on Jobs, Applications, and Application. It is not a fourth screen. | [ADR-0009](adr/0009-local-ui-hosts-acp-agent-sessions.md) |
| **Agent session** | A live ACP conversation scoped by the command target: campaign-wide for target none, per-Application for `app: <folder>`, with `job: <id>` commands served by the campaign session. | [ADR-0009](adr/0009-local-ui-hosts-acp-agent-sessions.md) |
| **Agent status chip** | The always-visible agent-state signal, ordered as `Decision needed`, `Working`, `Queued`, `Error`, or `Idle`. | [ADR-0009](adr/0009-local-ui-hosts-acp-agent-sessions.md) |
| **Run now** | The interactive delivery path that sends a command through the live ACP session for its target. | [ADR-0009](adr/0009-local-ui-hosts-acp-agent-sessions.md) |
| **Command queue** | The app-wide `queue/` used by the **Queue** delivery path for deferred or unattended agent work. It shares one closed command and target vocabulary with **Run now**. | [ADR-0008](adr/0008-chat-ui-command-queue.md) |
| **Permission card** | The in-surface rendering of a blocked ACP permission request, including the proposed action, available decisions, waiting time, and cancellation path. | [ADR-0009](adr/0009-local-ui-hosts-acp-agent-sessions.md) |
| **Draft** | The generated candidate CV in `cv-draft.md` and `cv-draft.pdf`, with optional archived iterations under `drafts/<version>/`. | [ADR-0007](adr/0007-metadata-and-schema-versioning.md) |
| **Final snapshot** | The explicitly approved `cv.md` and `cv.pdf` promoted from a passing draft. | [ADR-0005](adr/0005-ai-human-approval.md) |

## Artifact index

| Artifact | Purpose |
| --- | --- |
| `profile/master-profile.yaml` | Reusable factual source for CV content. |
| `profile/positioning.md` | Positioning angles and the job-fit quick test. |
| `tools/jobs_sources.yaml`, `tools/preferences.yaml` | Discovery sources, admission cues, hard rules, and ranking preferences. |
| `data/jobs/by-id/*.json` | Versioned catalog records. |
| `reports/jobs-YYYY-MM-DD.md`, `.jsonl` | Dated views over the catalog. |
| `applications/<identifier>/source.json` | Raw and normalized source provenance for an imported job. |
| `applications/<identifier>/cv-analysis.md` | Application-specific planning and evidence notes. |
| `applications/<identifier>/cv-feedback.md` | Human instructions for a future generated draft. |
| `applications/<identifier>/cv-review.md` | Latest persisted deterministic check report. |
| `applications/<identifier>/cover-letter.md`, `prep.md`, `interview-notes.md` | Optional supporting artifacts. |
| `queue/*.yaml` | Transient UI→agent command requests (`state: queued` until the drain skill claims them). |

## Binding records

- [ADR-0001: file-based artifacts](adr/0001-file-based-artifacts.md)
- [ADR-0005: AI-assisted, human-approved workflow](adr/0005-ai-human-approval.md)
- [ADR-0006: CLI, core, and UI boundaries](adr/0006-cli-core-ui-boundary.md)
- [ADR-0007: metadata and schema evolution](adr/0007-metadata-and-schema-versioning.md)
- [ADR-0008: chat and UI command queue](adr/0008-chat-ui-command-queue.md)
- [ADR-0009: local UI hosted ACP agent sessions](adr/0009-local-ui-hosts-acp-agent-sessions.md)
- [Jobs refresh and place-keeping research](research/2026-07-22-jobs-list-refresh-scroll-options.md)

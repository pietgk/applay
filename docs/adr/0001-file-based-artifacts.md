# ADR 0001: Keep the pipeline file-based

- Status: accepted
- Date: 2026-07-10

## Decision

Use ordinary Markdown, YAML, JSON, JSONL, and PDF files as the system of
record. Organize job-specific work under dated application folders and keep
discovery reports under `reports/`.

## Context

The current tools already read and write these paths directly. The workflow is
personal, inspectable in a text editor, and needs to preserve drafts and source
material. A database or service would add lifecycle and migration work before
the current scripts require it.

## Consequences

Files are easy to diff, copy, back up, and review. Referential integrity,
reporting, and concurrent edits remain lightweight responsibilities of the
scripts and conventions.

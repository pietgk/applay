# ADR 0004: Separate drafts from final artifacts

- Status: accepted
- Date: 2026-07-10

## Decision

`cv-draft.md` is the current tailored draft and `cv-draft.pdf` is its derived
review artifact. A controlled model or other explicitly managed generator may
write the draft; the normal local UI treats it as read-only. Human planning and
next-draft instructions live in `cv-analysis.md` and `cv-feedback.md`.
After automated gates pass and a human explicitly approves, the workflow
promotes them to `cv.md` and `cv.pdf`. The renderer refuses scaffold
placeholders and uses the locked stylesheet and WeasyPrint path to target one
A4 page.

## Context

The scaffold deliberately makes unfinished content visible, and the renderer
already blocks the known placeholder markers. Keeping both draft and final
Markdown means a PDF can be regenerated rather than hand-edited, while the
approved artifact remains stable during later iterations.

## Consequences

Content review happens against `cv-draft.md` and layout review happens in
`cv-draft.pdf`; human changes intended for a future generated draft go in
`cv-feedback.md`. `cv.md`/`cv.pdf` are approved snapshots, and a generated PDF
is never the canonical editable source.

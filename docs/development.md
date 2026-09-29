# Development

The project uses mise to select Python 3.12 and uv to manage the in-project
`.venv`. It is an application of scripts, not an installable Python package.

## Setup

```bash
brew install pango                 # native dependency used by WeasyPrint
mise install                        # Python 3.12 and uv from mise.toml
mise run install                    # sync pyproject.toml and uv.lock
```

The renderer needs the native Pango/Cairo stack. The `DYLD_FALLBACK_LIBRARY_PATH`
setting in `mise.toml` points the renderer at the Homebrew library directory on
this machine.

## Daily checks

```bash
mise run fmt                        # format Python files
mise run fmt-check                  # verify formatting without changing files
mise run lint                       # Ruff lint
mise run check                      # basedpyright over tools/
mise run test                       # offline unittest suite
mise run verify                     # formatting, lint, type-check, and tests
```

## Local UI

The private browser UI runs against the existing application folders and binds
only to localhost:

```bash
mise run ui                         # reports the local URL when ready
```

It calls the same `src/apply/workflow.py` check and approval functions as the
CLI. `cv-analysis.md` and `cv-feedback.md` are directly editable from the UI;
the generated `cv-draft.md` and `cv-review.md` are read-only there. Job
snapshots, metadata, and generated artifacts are not directly editable.
The check and approval workflow may write its normal review, PDF, final, and
workflow metadata artifacts.

The tests use Python’s standard-library `unittest` runner. They do not call
public APIs or write into `applications/` or `reports/`; temporary directories
are used for import tests, and static inputs live in `tests/fixtures/`.

The offline job-source behavior can also be smoke-tested directly:

```bash
mise run jobs -- --self-test
```

## Test coverage boundary

The foundation suite protects current behavior at the seams that are already
present: JSONL selection and import provenance, placeholder detection, JobTech
normalization, ATS token/section scoring, and one-page HTML rendering. It does
not test network calls, external ATS availability, PDF visual design in every
font environment, or a future domain API.

When adding behavior, prefer a fixture and an offline test first. Keep tests at
the existing script and local-UI seams rather than inventing a broader domain
API surface.

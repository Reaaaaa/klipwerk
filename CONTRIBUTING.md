# Contributing to Klipwerk

Thanks for taking the time. Here's everything you need to get started.

## Setup

```bash
git clone https://github.com/Reaaaaa/klipwerk
cd klipwerk
pip install -e ".[dev]"
```

You'll need `ffmpeg` and `ffprobe` on `$PATH` for manual testing. For running tests headlessly (no display required):

```bash
QT_QPA_PLATFORM=offscreen pytest -q
```

## Workflow

1. **Open an issue first** for anything non-trivial so we can align before you write code.
2. Fork, create a branch (`feat/my-thing` or `fix/my-bug`).
3. Make your changes. Keep commits focused.
4. Ensure the checklist below is green before opening a PR.

## Quality bar

```bash
pytest -q              # all tests must pass
ruff check klipwerk    # zero lint errors
```

`mypy` is not yet blocking (54 unresolved PyQt6 stubs), but try not to make it worse.

## Guidelines

- **No new dependencies** without discussion — the install footprint matters.
- **Pure-function logic belongs in `core/`** — keep Qt out of business logic so it stays testable.
- **New behaviour needs a test** — especially for export logic in `core/export_builder.py`.
- **Keep keyboard shortcuts working** — the K/C toggle and all shortcuts in the README must still fire after your change.
- **No comments that explain what the code does** — only add a comment when the *why* is non-obvious.

## Commit style

```
type: short imperative summary (under 72 chars)

Optional body. Wrap at 72 chars. Explain WHY, not what.
```

Types: `feat`, `fix`, `refactor`, `test`, `docs`, `ci`, `chore`.

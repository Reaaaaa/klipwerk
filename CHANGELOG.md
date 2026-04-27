# Changelog

All notable changes to this project will be documented in this file.

## [0.3.0]

### Added
- **Standalone sequence preview window** (`widgets/seq_preview.py`):
  clicking "Preview Sequence" now opens an independent floating window
  with its own `VideoCapture` and timer — no conflict with the main
  player. Includes the same frameless custom title bar as the main
  window (drag, resize, min/max/close), transport buttons, clip counter,
  and keyboard shortcuts (`Space`, `←`/`→`, `Esc`).
- **Per-mode export suffix fields**: the single generic suffix input is
  replaced by three independent fields — `→ Crop` (default `_crop`),
  `→ Clip` (default `_clip`), `→ Seq` (default `_seq`). All three
  persist across sessions via `QSettings`.
- **Stream-copy fast path for sequence export**: when no clip has a crop
  and all clips have positive duration, sequence export skips
  re-encoding entirely and uses `-c copy`. Cuts snap to the nearest
  keyframe; the status label reads "stream-copy (fast)…" while active.
- **`SequencePlan` planner** (`core/export_builder.py`): the fast-copy
  decision and argv construction are pure functions, fully testable
  without Qt.
- **Settings persistence** (`settings.py`): window geometry, export
  format/CRF/preset/prefix/suffix, and K/C mode survive restarts via
  `QSettings`. Corrupt or missing values fall back to defaults silently.
- **`--version` / `-V` and `--help` CLI flags** — flag parsing happens
  before `QApplication` construction so they work on headless machines.
- **UI smoke-test suite** (`tests/test_app_smoke.py`): 12 tests that
  construct the main window, exercise common paths, and verify clean
  teardown.
- 61 new unit tests total across settings, export builder, sequence
  planner, and waveform modules.

### Fixed
- **Clips not cleared on Close Video** — `_close_video()` now resets
  the clip list, undo history, and active-clip index and re-renders the
  sidebar and timeline immediately.
- **Zombie ffmpeg processes on cancel** — worker now waits up to 2 s
  after `terminate()`, escalates to `kill()` on timeout, then waits
  again.
- **Hardcoded `.mp4` segment extension** in sequence export — segments
  now match the source or target container so the concat demuxer's
  consistency rule is always satisfied.
- **Taskbar minimize broken on frameless window** — added
  `WindowMinimizeButtonHint` alongside `FramelessWindowHint`.

### Changed
- Video info panel redesigned: permanent "Video-Infos" title with a
  subtitle line, hover effect, and inline "click to expand/collapse"
  hint — no longer shows the raw filename in the header.
- Button borders increased to 2 px, `border-radius` reduced to 4 px,
  toolbar height increased to 58 px for better visual clarity.
- "Preview Clips" button renamed to "Preview Sequence" consistently,
  independent of the K/C language toggle.

## [0.2.0] — refactor release

### Added
- Modular package layout (`core/`, `widgets/`, `workers/`, `ui/`)
- Command-pattern undo/redo — O(1) per edit instead of deep-copying the clip list
- `Clip.id` — stable UUID so UI widgets can be diffed instead of rebuilt
- Test suite covering formats, history, ffmpeg-runner, and waveform downsampling
- `pyproject.toml` with `klipwerk` console-script entry point
- Linting configuration: ruff + mypy
- README with install instructions, keyboard shortcuts, project layout

### Fixed
- **`BASE` was undefined** — `find_bin()` would raise `NameError` when ffmpeg
  wasn't on `$PATH`. Binary lookup now works reliably as a fallback.
- **`subprocess.CREATE_NO_WINDOW`** — referenced on Linux/macOS inside a ternary
  that Python eagerly evaluated, causing `AttributeError` at every export.
  Now gated behind `getattr` and exposed as a platform-safe constant.
- **`_update_codec_note` was defined twice** — the second override had only
  three entries, so selecting H.265/AV1/VP9 raised `IndexError`.
- **Timeline drag-to-self** — `_move_clip` now ignores from-index == to-index.
- **Bounds checks** — `_sel_clip`, `_rename_clip`, `_preview_clip`, `_del_clip`
  all validate the index before dereferencing.
- **QImage garbage-collection** — frames in the preview and thumbnails now
  `.copy()` the QImage so the numpy buffer can be freed safely.
- **Waveform worker leak** — re-loading a video now properly cancels the
  previous extraction's ffmpeg subprocess.
- **Bare `except:`** — replaced with specific exception types everywhere.

### Changed
- Waveform downsampling vectorized via `numpy.reshape` + `max(axis=1)`,
  avoiding a Python loop over samples.
- `SequenceFFmpegWorker` pulled out of the monkey-patched closure that used
  to live inside `_run_export`.
- Export format table moved to `core/formats.py` as a proper dataclass list.
- Icon rendering now cached via `functools.lru_cache` — no more re-parsing
  SVGs on every hover.
- `subprocess.run` in `probe_video` catches specific exception types instead
  of bare `except`.

## [0.1.0] — initial release

Monolithic single-file editor. See `klipwerk.py` in the project history.

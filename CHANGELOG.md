# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Added
- **UI smoke-test suite** (`tests/test_app_smoke.py`): 12 tests using
  pytest-qt's `qtbot` fixture that construct the main window, exercise
  common paths (shortcuts, format-combo changes, export guards, K/C
  toggle), and verify clean teardown. Catches regressions like the
  old double-defined `_update_codec_note` that would IndexError on
  H.265+ without anyone noticing until runtime.
- **`--version` / `-V` CLI flag** on the `klipwerk` entry point, plus
  a minimal `--help` output. Flag parsing happens before
  `QApplication` construction so it works on headless boxes.
- **Stream-copy fast path for sequence export**
  (`klipwerk/core/export_builder.py`): when no clip has a crop and all
  clips have positive duration, sequence export skips re-encoding
  entirely and trims segments with `-c copy` instead. Turns minute-long
  H.265 re-encodes into second-long stream copies. The status label
  reads "stream-copy (fast)…" while active. Note: cuts snap to the
  nearest keyframe in this mode because `-ss` is placed before `-i`
  for speed.
- New `SequencePlan` dataclass and `plan_sequence_export()` planner —
  the sequence-export dispatcher in `app.py` is now a thin shim around
  this pure-function planner, which means the fast-copy decision logic
  is fully testable without Qt.
- 38 new unit tests (23 builder + 15 planner) covering fast-copy
  eligibility, argv shape for both modes, segment-container selection,
  and concat-step invariants.
- **Settings persistence** (`klipwerk/settings.py`): window geometry,
  export prefix/suffix, format/CRF/preset, and K/C mode now survive
  restarts via `QSettings`. Corrupt or out-of-range values fall back
  to defaults silently instead of preventing startup.
- 8 unit tests covering roundtrip, defaults, and corruption robustness.

### Fixed
- **Zombie ffmpeg processes on cancel** — `FFmpegWorker._run_one`
  called `proc.terminate()` and returned immediately, leaving the
  subprocess un-reaped. Now waits up to 2s, escalates to `proc.kill()`
  on timeout, and waits again. Especially relevant for sequence export
  where many ffmpeg processes run back-to-back.
- **Hardcoded `.mp4` segment extension** in sequence export — segments
  now use the source extension (fast-copy path) or the target
  container (re-encode path) so the concat demuxer's container-
  consistency rule is always satisfied, even for WebM/MKV exports.

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
- Waveform downsampling vectorized (`numpy.reshape` + `max(axis=1)`), roughly
  10-50× faster than the Python loop.
- `SequenceFFmpegWorker` pulled out of the monkey-patched closure that used
  to live inside `_run_export`.
- Export format table moved to `core/formats.py` as a proper dataclass list.
- Icon rendering now cached via `functools.lru_cache` — no more re-parsing
  SVGs on every hover.
- `subprocess.run` in `probe_video` catches specific exception types instead
  of bare `except`.

## [0.1.0] — initial release

Monolithic single-file editor. See `klipwerk.py` in the project history.

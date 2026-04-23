<div align="center">

# ✂ Klipwerk

**Fast, keyboard-driven video trimming and cropping — powered by ffmpeg.**

[![CI](https://github.com/Reaaaaa/klipwerk/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/Reaaaaa/klipwerk/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12-blue?logo=python&logoColor=white)](https://www.python.org/)
[![PyQt6](https://img.shields.io/badge/UI-PyQt6-41cd52?logo=qt&logoColor=white)](https://pypi.org/project/PyQt6/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-107%20passing-brightgreen)](tests/)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey)](https://github.com/Reaaaaa/klipwerk)

<br/>

*Drop in a video. Mark in and out. Draw a crop. Export. Nothing else.*

<br/>

<!-- Replace with an actual screenshot/GIF once you have one -->
<!-- ![Klipwerk demo](assets/demo.gif) -->

</div>

---

## Why Klipwerk?

Most video editors are built around timelines with hundreds of tracks. Klipwerk does one thing: it lets you cut and crop clips out of a video as fast as possible, then export them — individually or stitched into a sequence. Every action has a keyboard shortcut. The UI never gets in your way.

Under the hood it's a thin, opinionated wrapper around `ffmpeg`. No proprietary formats, no vendor lock-in, no cloud anything.

---

## Features

| | |
|---|---|
| **Live preview** | OpenCV-powered frame display with drag-to-crop, rule-of-thirds overlay, and aspect-ratio presets |
| **Waveform scrubber** | Timeline with waveform visualization (numpy-vectorized, 10–50× faster than naive), hover thumbnails, and I/O markers |
| **Clip list** | Drag-to-reorder, rename, undo/redo (command-pattern, O(1) per edit) |
| **Sequence export** | Concatenate any number of clips into one video in a single click |
| **Stream-copy fast path** | No crop + all positive durations → skips re-encoding entirely. Minute-long H.265 jobs become second-long stream copies |
| **7 output formats** | H.264, H.265, AV1, VP9 across MP4, MKV, WebM |
| **Rich media info** | ffprobe panel: codec, container, bitrate, color space, pixel format, duration |
| **Settings persistence** | Window geometry, export defaults, format/CRF/preset survive restarts via `QSettings` |
| **Frameless chrome** | Custom title bar with proper resize handles on all edges |
| **Zero config** | Drop `ffmpeg`/`ffprobe` next to the script or put them on `$PATH` — done |

---

## Installation

### From source

```bash
git clone https://github.com/Reaaaaa/klipwerk
cd klipwerk
pip install -e .
klipwerk
```

### ffmpeg

Klipwerk calls your existing `ffmpeg` installation — nothing is bundled. It searches in this order: `$PATH` → package directory → `./bin/` → `~/Documents/ffmpeg/` → `C:\ffmpeg\bin\` → `C:\Program Files\ffmpeg\bin\`.

| Platform | How to get ffmpeg |
|---|---|
| **Windows** | [gyan.dev/ffmpeg/builds](https://www.gyan.dev/ffmpeg/builds/) → `ffmpeg-release-essentials.zip` → drop `ffmpeg.exe` + `ffprobe.exe` next to the package or on `%PATH%` |
| **Linux** | `sudo apt install ffmpeg` |
| **macOS** | `brew install ffmpeg` |

---

## Keyboard shortcuts

| Key | Action |
|---|---|
| `Space` | Play / pause |
| `I` | Set **In** marker at current frame |
| `O` | Set **Out** marker at current frame |
| `C` | Add clip from In → Out |
| `←` / `→` | Step one frame |
| `Shift` + `←` / `→` | Step ten frames |
| `Ctrl`+`Z` | Undo |
| `Ctrl`+`Y` / `Ctrl`+`Shift`+`Z` | Redo |
| `Delete` | Delete active clip |

---

## CLI flags

```
klipwerk              # launch the editor
klipwerk --version    # print version and exit
klipwerk --help       # show flag summary
klipwerk --reset-settings  # clear saved preferences
```

---

## Development

```bash
pip install -e ".[dev]"

pytest                       # run all 107 tests
pytest -v                    # verbose output
ruff check klipwerk          # lint
mypy klipwerk                # type-check

# Headless (CI / no display)
QT_QPA_PLATFORM=offscreen pytest -q
```

CI runs the full matrix on every push: **Ubuntu × Windows × macOS** × **Python 3.10, 3.11, 3.12**.

---

## Project layout

```
klipwerk/
├── __main__.py           # entry point, CLI flag parsing
├── app.py                # main window orchestration
├── history.py            # command-pattern undo/redo
├── sidebar.py            # export controls panel builder
├── settings.py           # QSettings facade
│
├── core/
│   ├── models.py         # Clip dataclass + CropRect
│   ├── ffmpeg_runner.py  # binary lookup, platform flags, subprocess
│   ├── probe.py          # ffprobe wrapper
│   ├── formats.py        # 7 FormatSpec entries + codec arg builder
│   └── export_builder.py # pure-function planner, fast-copy decision
│
├── widgets/
│   ├── preview.py        # live video preview + crop drag
│   ├── scrubber.py       # timeline scrubber with waveform
│   ├── clip_item.py      # sidebar list row + timeline tile
│   ├── guarded.py        # scroll-safe QSpinBox / QComboBox
│   └── helpers.py        # styled label / button / separator
│
├── workers/
│   ├── ffmpeg_worker.py  # QThread for export (with cancel + kill escalation)
│   ├── waveform.py       # vectorized peak extraction
│   └── thumbnail.py      # scrubber hover thumbnails
│
└── ui/
    ├── theme.py          # dark palette + Qt stylesheet
    └── icons.py          # SVG → QIcon with lru_cache
```

---

## Architecture highlights

- **Pure-function export planner** (`SequencePlan`) — the fast-copy decision and argv construction are fully testable without Qt, covered by 38 dedicated unit tests.
- **Command-pattern undo/redo** — edits push/pop `Command` objects; no deep-copying the clip list on every action.
- **Vectorized waveform** — `numpy.reshape` + `max(axis=1)` is 10–50× faster than a Python loop over samples.
- **Platform-safe subprocess flags** — `CREATE_NO_WINDOW` is gated behind `getattr` so the same code path works on Linux and macOS without `AttributeError`.
- **Zombie-process cleanup** — `FFmpegWorker` waits 2 s after `terminate()`, escalates to `kill()` on timeout, then waits again. Especially relevant for sequence exports that spawn many back-to-back ffmpeg processes.

---

## License

MIT — see [LICENSE](LICENSE).
=======
# klipwerk
Fast, keyboard-driven video editor for trimming, cropping and converting, built around ffmpeg. PyQt6 · OpenCV · Python 3.10+
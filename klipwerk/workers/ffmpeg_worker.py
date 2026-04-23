"""QThread wrappers around ffmpeg subprocesses.

Two improvements over the original:

* Cross-platform ``CREATION_FLAGS`` — the original ``CREATE_NO_WINDOW``
  reference crashed on Linux/macOS.
* The sequence-concat worker used to be defined as a local class monkey-
  patched inside ``_run_export``. Pulled up to a proper subclass here.
"""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

from ..core.ffmpeg_runner import CREATION_FLAGS

log = logging.getLogger(__name__)

# Keep the last N lines of stderr for error reporting — ffmpeg is
# extremely verbose, so the tail is usually where the actual error is.
_STDERR_TAIL_LINES = 15


class FFmpegWorker(QThread):
    """Run a single ffmpeg invocation with live progress reporting."""

    progress = pyqtSignal(int, str)   # (percent 0-100, status text)
    done     = pyqtSignal(str)        # out_path
    error    = pyqtSignal(str)        # error message

    def __init__(self, cmd: list[str], out_path: str, parent=None):
        super().__init__(parent)
        self.cmd = cmd
        self.out_path = out_path
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    # ── Core subprocess runner ───────────────────────────────────────
    def _run_one(self, cmd: list[str], report_progress: bool = False) -> None:
        """Run *cmd*, optionally parsing stderr for ffmpeg progress info.

        Raises RuntimeError with the tail of stderr on non-zero exit.
        """
        log.debug("ffmpeg: %s", " ".join(cmd))
        proc = subprocess.Popen(
            cmd,
            stderr=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            text=True,
            bufsize=1,
            creationflags=CREATION_FLAGS,
        )
        duration: float | None = None
        tail: list[str] = []

        assert proc.stderr is not None  # we requested a PIPE above
        for line in proc.stderr:
            line = line.rstrip()
            tail.append(line)
            if len(tail) > _STDERR_TAIL_LINES * 4:
                tail = tail[-_STDERR_TAIL_LINES * 2:]

            if self._cancel:
                # Try graceful shutdown first; escalate to SIGKILL if
                # ffmpeg ignores SIGTERM for >2s. Without the wait() the
                # subprocess became a zombie — especially bad in the
                # sequence worker where many ffmpeg calls happen in a row.
                proc.terminate()
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=2)
                return

            # Parse total duration once
            if duration is None and "Duration:" in line:
                duration = _parse_duration(line)

            # Parse current position and emit progress
            if report_progress and duration and "time=" in line:
                cur = _parse_time(line)
                if cur is not None:
                    pct = min(99, int(cur / duration * 100))
                    self.progress.emit(pct, f"{pct}%")

        proc.wait()
        if proc.returncode not in (0, None) and not self._cancel:
            raise RuntimeError("\n".join(tail[-_STDERR_TAIL_LINES:]))

    def run(self) -> None:
        try:
            self._run_one(self.cmd, report_progress=True)
            if not self._cancel:
                self.done.emit(self.out_path)
        except Exception as exc:
            log.exception("ffmpeg export failed")
            self.error.emit(str(exc))


class SequenceFFmpegWorker(FFmpegWorker):
    """Encode N segments individually then concat them with stream-copy.

    The concat step requires a list file on disk; we write it *after*
    all segments are encoded so references are definitely valid. The
    parent caller supplies a ``list_file`` path and a list of
    ``(cmd, label)`` tuples describing how to build each segment.
    """

    def __init__(
        self,
        segment_cmds: list[tuple[list[str], str]],
        concat_cmd: list[str],
        list_file: str,
        out_path: str,
        parent=None,
    ):
        super().__init__(concat_cmd, out_path, parent)
        self._segment_cmds = segment_cmds
        self._list_file = list_file

    def run(self) -> None:
        try:
            total = len(self._segment_cmds)
            seg_paths: list[str] = []

            for i, (cmd, label) in enumerate(self._segment_cmds):
                if self._cancel:
                    return
                self.progress.emit(int(i / total * 85), label)
                self._run_one(cmd)
                seg_paths.append(cmd[-1])   # convention: output is last arg

            # Concat list must be written *after* segments exist.
            # Paths need forward slashes on Windows too for the concat demuxer.
            with open(self._list_file, "w", encoding="utf-8") as fh:
                for path in seg_paths:
                    escaped = Path(path).as_posix().replace("'", r"'\''")
                    fh.write(f"file '{escaped}'\n")

            self.progress.emit(90, "Concatenating…")
            self._run_one(self.cmd, report_progress=True)

            if not self._cancel:
                self.progress.emit(100, "Done")
                self.done.emit(self.out_path)
        except Exception as exc:
            log.exception("sequence export failed")
            self.error.emit(str(exc))


# ── Internal parsers ────────────────────────────────────────────────────
def _parse_duration(line: str) -> float | None:
    """Parse ``Duration: HH:MM:SS.ms`` from an ffmpeg stderr line."""
    try:
        t = line.split("Duration:")[1].split(",")[0].strip()
        h, m, s = t.split(":")
        return float(h) * 3600 + float(m) * 60 + float(s)
    except (IndexError, ValueError):
        return None


def _parse_time(line: str) -> float | None:
    """Parse ``time=HH:MM:SS.ms`` from an ffmpeg stderr progress line."""
    try:
        t = line.split("time=")[1].split(" ")[0].strip()
        h, m, s = t.split(":")
        return float(h) * 3600 + float(m) * 60 + float(s)
    except (IndexError, ValueError):
        return None

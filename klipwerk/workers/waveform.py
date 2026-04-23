"""Extract audio peaks for the scrubber waveform overlay.

Optimizations vs. the original:

* Vectorized peak computation with ``numpy.reshape`` + ``max(axis=1)``
  — the old Python list-comprehension over ``max(abs(...))`` was
  ~10-50× slower on long videos.
* Cancel flag so re-loading a video doesn't leak the old thread.
"""
from __future__ import annotations

import logging
import subprocess

import numpy as np
from PyQt6.QtCore import QThread, pyqtSignal

from ..core.ffmpeg_runner import CREATION_FLAGS, ffmpeg_bin

log = logging.getLogger(__name__)

_SAMPLE_RATE = 8000   # enough for a visual waveform; keeps RAM tiny


class WaveformWorker(QThread):
    """Produce a numpy array of normalized peaks, one per pixel column."""

    done = pyqtSignal(object)   # np.ndarray | None

    def __init__(self, path: str, width: int = 800, parent=None):
        super().__init__(parent)
        self.path = path
        self.width = max(1, int(width))
        self._cancel = False
        self._proc: subprocess.Popen | None = None

    def cancel(self) -> None:
        self._cancel = True
        if self._proc and self._proc.poll() is None:
            try:
                self._proc.terminate()
            except OSError:
                pass

    def run(self) -> None:
        try:
            cmd = [
                ffmpeg_bin(), "-i", self.path,
                "-ac", "1",
                "-ar", str(_SAMPLE_RATE),
                "-f", "f32le",
                "-vn",
                "pipe:1",
            ]
            self._proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                creationflags=CREATION_FLAGS,
            )
            raw, _ = self._proc.communicate()

            if self._cancel or not raw:
                self.done.emit(None)
                return

            samples = np.frombuffer(raw, dtype=np.float32)
            if samples.size == 0:
                self.done.emit(None)
                return

            peaks = self._downsample(samples, self.width)
            self.done.emit(peaks)

        except Exception:
            log.exception("waveform extraction failed")
            self.done.emit(None)
        finally:
            self._proc = None

    @staticmethod
    def _downsample(samples: np.ndarray, width: int) -> np.ndarray:
        """Bucket *samples* into *width* peaks, normalized to [0, 1]."""
        chunk = max(1, samples.size // width)
        n_complete = (samples.size // chunk) * chunk

        if n_complete == 0:
            return np.zeros(width, dtype=np.float32)

        # Reshape into (n_chunks, chunk) and take per-row max of abs.
        reshaped = np.abs(samples[:n_complete]).reshape(-1, chunk)
        peaks = reshaped.max(axis=1)

        # Pad or truncate to exactly *width* entries.
        if peaks.size >= width:
            peaks = peaks[:width]
        else:
            peaks = np.pad(peaks, (0, width - peaks.size))

        mx = peaks.max()
        if mx > 0:
            peaks = peaks / mx
        return peaks

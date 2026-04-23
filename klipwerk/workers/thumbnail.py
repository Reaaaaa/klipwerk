"""Produce a single-frame thumbnail for the scrubber hover tooltip.

Uses OpenCV's seek rather than ffmpeg because it's meaningfully faster
for repeated small seeks into a single open file (ffmpeg has to re-open
and re-probe for every frame, OpenCV keeps the container open).

Bugfix vs. original: the QImage was constructed directly over the
numpy buffer. As soon as ``run()`` returned the buffer was garbage-
collected, occasionally leaving Qt to read torn memory (green flicker
or crash). We call ``.copy()`` to detach the QImage before emitting.
"""
from __future__ import annotations

import logging

import cv2
from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtGui import QImage, QPixmap

log = logging.getLogger(__name__)

_THUMB_WIDTH = 160


class ThumbnailWorker(QThread):
    done = pyqtSignal(float, object)   # (time, QPixmap | None)

    def __init__(self, path: str, t: float, parent=None):
        super().__init__(parent)
        self.path = path
        self.t = t

    def run(self) -> None:
        cap = cv2.VideoCapture(self.path)
        try:
            cap.set(cv2.CAP_PROP_POS_MSEC, self.t * 1000)
            ret, frame = cap.read()
        finally:
            cap.release()

        if not ret or frame is None:
            self.done.emit(self.t, None)
            return

        try:
            h, w = frame.shape[:2]
            tw = _THUMB_WIDTH
            th = max(1, int(h * tw / w))
            frame = cv2.resize(frame, (tw, th))
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

            # .copy() detaches the QImage from the numpy buffer before
            # we return — otherwise the backing memory is freed and Qt
            # reads garbage later.
            qimg = QImage(rgb.data, tw, th, tw * 3,
                          QImage.Format.Format_RGB888).copy()
            self.done.emit(self.t, QPixmap.fromImage(qimg))
        except Exception:
            log.exception("thumbnail render failed")
            self.done.emit(self.t, None)

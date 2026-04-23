"""Data models used throughout Klipwerk."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import TypedDict


class CropRect(TypedDict):
    """Crop rectangle in video (pixel) coordinates.

    ``x`` / ``y`` are offsets from the top-left of the source frame.
    ``w`` / ``h`` are the crop region's size. All values are integer
    pixels; widths/heights are always even (ffmpeg encoders require it).
    """

    x: int
    y: int
    w: int
    h: int


@dataclass
class Clip:
    """A single trim/crop on the loaded video.

    ``id`` is a short UUID so widgets can be diffed across re-renders
    instead of being rebuilt from scratch — important once a project
    grows past a handful of clips.
    """

    name: str
    start: float
    end: float
    crop: CropRect | None = None
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)

"""Export format table and codec argument builder.

Previously this lived as a flat 7-tuple on the main window class with a
``_update_codec_note`` method defined **twice** — the second override
had only 3 entries and would ``IndexError`` on any non-H.264 format.
Now it's a proper dataclass list with one source of truth.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Encoder = Literal["libx264", "libx265", "libaom-av1", "libvpx-vp9"]


@dataclass(frozen=True)
class FormatSpec:
    label: str           # UI label shown in the combo box
    container: str       # 'mp4', 'mkv', 'webm'
    encoder: Encoder
    audio_encoder: str
    crf_default: int
    crf_max: int
    presets: tuple[str, ...]
    note: str            # human-readable codec info shown under the combo


FORMATS: tuple[FormatSpec, ...] = (
    FormatSpec(
        "mp4  —  H.264", "mp4", "libx264", "aac",
        23, 51, ("ultrafast", "fast", "medium", "slow", "veryslow"),
        "H.264 · AAC · MP4  —  universell kompatibel",
    ),
    FormatSpec(
        "mp4  —  H.265 / HEVC", "mp4", "libx265", "aac",
        28, 51, ("ultrafast", "fast", "medium", "slow", "veryslow"),
        "H.265/HEVC · AAC · MP4  —  ~50% kleiner als H.264",
    ),
    FormatSpec(
        "mkv  —  H.264", "mkv", "libx264", "aac",
        23, 51, ("ultrafast", "fast", "medium", "slow", "veryslow"),
        "H.264 · AAC · MKV",
    ),
    FormatSpec(
        "mkv  —  H.265 / HEVC", "mkv", "libx265", "aac",
        28, 51, ("ultrafast", "fast", "medium", "slow", "veryslow"),
        "H.265/HEVC · AAC · MKV  —  ~50% kleiner als H.264",
    ),
    FormatSpec(
        "mkv  —  AV1  (slow!)", "mkv", "libaom-av1", "opus",
        32, 63, ("4", "6", "8", "10"),
        "AV1 · Opus · MKV  —  kleinste Dateigröße, sehr langsam",
    ),
    FormatSpec(
        "webm —  VP9", "webm", "libvpx-vp9", "libopus",
        31, 63, ("good", "best"),
        "VP9 · Opus · WebM  —  ~40% kleiner als H.264",
    ),
    FormatSpec(
        "webm —  AV1  (slow!)", "webm", "libaom-av1", "libopus",
        32, 63, ("4", "6", "8", "10"),
        "AV1 · Opus · WebM  —  kleinste Dateigröße, sehr langsam",
    ),
)


def codec_args(spec: FormatSpec, crf: int, preset: str) -> list[str]:
    """Build the ffmpeg codec arguments for a given format spec."""
    crf_s = str(crf)
    enc = spec.encoder

    if enc == "libx264":
        return [
            "-c:v", "libx264", "-crf", crf_s, "-preset", preset,
            "-c:a", "aac",
            "-movflags", "+faststart",
        ]
    if enc == "libx265":
        return [
            "-c:v", "libx265", "-crf", crf_s, "-preset", preset,
            "-c:a", "aac",
            "-tag:v", "hvc1",          # required for QuickTime/Safari
            "-movflags", "+faststart",
        ]
    if enc == "libaom-av1":
        return [
            "-c:v", "libaom-av1", "-crf", crf_s, "-b:v", "0",
            "-cpu-used", preset,
            "-c:a", spec.audio_encoder, "-row-mt", "1",
        ]
    if enc == "libvpx-vp9":
        return [
            "-c:v", "libvpx-vp9", "-crf", crf_s, "-b:v", "0",
            "-deadline", preset,
            "-c:a", "libopus",
        ]
    raise ValueError(f"unsupported encoder: {enc}")


def pick_default_for(v_codec: str) -> int:
    """Return the index into :data:`FORMATS` that best matches the input codec."""
    v = v_codec.upper()
    if "265" in v or "HEVC" in v:
        return 1  # mp4 H.265
    if "AV1" in v:
        return 4  # mkv AV1
    if "VP9" in v:
        return 5  # webm VP9
    return 0      # mp4 H.264 default

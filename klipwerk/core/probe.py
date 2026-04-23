"""Inspect a video file with ffprobe, with OpenCV as a fallback."""
from __future__ import annotations

import json
import logging
import subprocess
from typing import Any

import cv2

from .ffmpeg_runner import CREATION_FLAGS, ffprobe_bin

log = logging.getLogger(__name__)


def _format_size(size_bytes: int) -> str:
    if size_bytes > 1_000_000_000:
        return f"{size_bytes/1e9:.2f} GB"
    if size_bytes > 1_000_000:
        return f"{size_bytes/1e6:.1f} MB"
    if size_bytes > 0:
        return f"{size_bytes/1e3:.0f} KB"
    return "—"


def _parse_fps(fps_raw: str) -> float:
    try:
        num, den = fps_raw.split("/")
        den_f = float(den)
        if den_f == 0:
            return 30.0
        return float(num) / den_f
    except (ValueError, ZeroDivisionError):
        return 30.0


def probe_video(path: str) -> dict[str, Any]:
    """Return a dict of metadata for *path*.

    Never raises — on any kind of probe failure we fall back to OpenCV
    and fill missing values with ``"—"`` / ``0`` so the caller doesn't
    need to defensively ``.get()`` every field.
    """
    try:
        result = subprocess.run(
            [
                ffprobe_bin(),
                "-v", "quiet",
                "-print_format", "json",
                "-show_streams",
                "-show_format",
                path,
            ],
            capture_output=True,
            text=True,
            timeout=15,
            creationflags=CREATION_FLAGS,
        )
        if result.returncode == 0 and result.stdout.strip():
            info = json.loads(result.stdout)
            streams = info.get("streams", [])
            v = next((s for s in streams if s.get("codec_type") == "video"), {})
            a = next((s for s in streams if s.get("codec_type") == "audio"), {})
            fmt = info.get("format", {})

            fps_raw = v.get("r_frame_rate", "30/1")
            bit_rate = int(fmt.get("bit_rate", 0) or 0)

            return {
                "duration":     float(fmt.get("duration", 0) or 0),
                "width":        int(v.get("width", 0) or 0),
                "height":       int(v.get("height", 0) or 0),
                "fps":          _parse_fps(fps_raw),
                "fps_raw":      fps_raw,
                "v_codec":      (v.get("codec_name") or "—").upper(),
                "v_profile":    v.get("profile", "") or "",
                "pix_fmt":      v.get("pix_fmt", "—") or "—",
                "dar":          v.get("display_aspect_ratio", "—") or "—",
                "color":        v.get("color_space", v.get("colorspace", "")) or "—",
                "a_codec":      (a.get("codec_name") or "—").upper() if a else "—",
                "a_channels":   int(a.get("channels", 0) or 0) if a else 0,
                "a_samplerate": int(a.get("sample_rate", 0) or 0) if a else 0,
                "bitrate":      f"{bit_rate//1000} kbps" if bit_rate else "—",
                "size":         _format_size(int(fmt.get("size", 0) or 0)),
                "nb_streams":   len(streams),
                "container":    fmt.get("format_long_name", fmt.get("format_name", "—")),
            }
    except (subprocess.TimeoutExpired, json.JSONDecodeError, ValueError, OSError) as exc:
        log.warning("ffprobe failed, falling back to OpenCV: %s", exc)

    # OpenCV fallback — always returns something so the UI doesn't crash.
    cap = cv2.VideoCapture(path)
    try:
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
        duration = count / fps if fps else 0.0
    finally:
        cap.release()

    return {
        "duration":     duration,
        "width":        w,
        "height":       h,
        "fps":          fps,
        "fps_raw":      f"{fps}",
        "v_codec":      "—",
        "v_profile":    "",
        "pix_fmt":      "—",
        "dar":          "—",
        "color":        "—",
        "a_codec":      "—",
        "a_channels":   0,
        "a_samplerate": 0,
        "bitrate":      "—",
        "size":         "—",
        "nb_streams":   0,
        "container":    "—",
    }

"""Pure functions for building ffmpeg export command lists.

Separated from :mod:`klipwerk.app` so the command-builder logic can be
unit-tested without constructing a ``QMainWindow`` or actually running
ffmpeg.

The two interesting entries are:

* :func:`can_fast_copy` — decides whether a sequence export can skip
  re-encoding entirely.
* :func:`build_segment_cmd` — produces the ffmpeg argv for a single
  segment, either as a full re-encode or as a stream-copy trim.
* :func:`plan_sequence_export` — high-level planner that combines the
  above into a ready-to-execute :class:`SequencePlan`. This is the
  function the app calls; the dispatcher is a thin shim around it.

The ``fast_copy`` path places ``-ss`` / ``-to`` **before** ``-i``. That's
the fast form of seeking, but it snaps to the nearest upstream keyframe.
Callers that enable fast-copy should surface that trade-off in the UI
(something like "Stream-copy — cuts may snap to keyframes"), because
users who expect frame-accurate trims will otherwise be surprised by a
segment starting a fraction of a second off.
"""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from .models import Clip, CropRect


def crop_vf_args(cr: CropRect | None) -> list[str]:
    """Return ``['-vf', 'crop=w:h:x:y']`` or ``[]`` for no-crop.

    Widths/heights are rounded down to even pixels because ffmpeg's
    mainstream encoders (libx264, libx265) refuse odd dimensions.
    """
    if not cr:
        return []
    w = cr["w"] - cr["w"] % 2
    h = cr["h"] - cr["h"] % 2
    return ["-vf", f"crop={w}:{h}:{cr['x']}:{cr['y']}"]


def can_fast_copy(clips: Sequence[Clip]) -> bool:
    """Return True iff a sequence of *clips* is eligible for stream-copy.

    Eligibility rules (all must hold):

    * At least one clip.
    * No clip has a crop set (crop requires re-encode).
    * All clips have a positive duration — zero-length clips produce
      cryptic ffmpeg errors in stream-copy mode and are better caught
      here.

    The "all clips share a source file" condition is not checked here
    because Klipwerk only ever has one loaded video per session; the
    source is implicit. If that invariant ever changes, extend the
    check to also verify a shared source.
    """
    if not clips:
        return False
    for c in clips:
        if c.crop is not None:
            return False
        if c.duration <= 0:
            return False
    return True


def build_segment_cmd(
    clip: Clip,
    src_path: str,
    out_path: str,
    codec_args: Iterable[str],
    ffmpeg: str,
    fast_copy: bool = False,
) -> list[str]:
    """Build the ffmpeg argv to extract/encode a single segment.

    Two modes:

    * ``fast_copy=False`` — re-encode with the given *codec_args*. Applies
      any crop on the clip. This is the historical behaviour and the
      only path that supports crops, format changes, or audio
      transcoding.

    * ``fast_copy=True`` — stream-copy using ``-ss`` / ``-to`` before
      ``-i``. No re-encode, no crop support. The clip's crop is ignored
      by precondition: callers guard this with :func:`can_fast_copy`.
      ``-avoid_negative_ts make_zero`` keeps the concat demuxer happy
      later when the segments get stitched together; without it you
      occasionally get audio-video drift at segment boundaries.
    """
    if fast_copy:
        # -ss before -i: fast seek, snaps to nearest keyframe.
        # -to is an absolute timestamp in this position (same clock as -ss).
        return [
            ffmpeg, "-y",
            "-ss", str(clip.start),
            "-to", str(clip.end),
            "-i", src_path,
            "-c", "copy",
            "-avoid_negative_ts", "make_zero",
            out_path,
        ]

    # Re-encode path: -ss before -i still seeks fast, but the subsequent
    # decode/encode makes the cut frame-accurate anyway.
    return [
        ffmpeg, "-y",
        "-ss", str(clip.start), "-i", src_path, "-t", str(clip.duration),
        *crop_vf_args(clip.crop),
        *codec_args,
        out_path,
    ]


def build_concat_cmd(list_file: str, out_path: str, ffmpeg: str) -> list[str]:
    """Build the concat-demuxer ffmpeg argv that stitches segments together.

    Always uses ``-c copy``. All segments must share codec, container,
    and pixel format — ensured by generating them from the same source
    in :func:`build_segment_cmd`.
    """
    return [
        ffmpeg, "-y",
        "-f", "concat", "-safe", "0",
        "-i", list_file,
        "-c", "copy",
        out_path,
    ]


# ── High-level plan ────────────────────────────────────────────────────
@dataclass(frozen=True)
class SequencePlan:
    """Everything the worker needs to execute a sequence export.

    ``fast_copy`` is kept around for UI feedback — the commands
    themselves already bake the decision in. ``status_text`` is the
    label the progress bar should start with.
    """

    segment_cmds: list[tuple[list[str], str]]
    concat_cmd: list[str]
    list_file: str
    tmp_dir: Path
    fast_copy: bool
    status_text: str


def plan_sequence_export(
    clips: Sequence[Clip],
    src_path: str,
    out_path: str,
    codec_args: Iterable[str],
    target_container: str,
    ffmpeg: str,
    tmp_dir: Path,
) -> SequencePlan:
    """Build the full plan for a sequence export.

    Chooses between stream-copy and re-encode based on
    :func:`can_fast_copy`, picks an appropriate segment container,
    builds every per-segment ffmpeg command plus the concat step, and
    returns the result as a :class:`SequencePlan`.

    Parameters:
        clips           — ordered list of clips to export.
        src_path        — path to the single source video. All clips
                          come from here.
        out_path        — final output file path.
        codec_args      — codec argument list used when re-encoding is
                          forced. Ignored in fast-copy mode.
        target_container — container short-name (e.g. ``"mp4"``) the
                          user picked in the format dropdown. Used for
                          segment files in the re-encode path.
        ffmpeg          — path to the ffmpeg binary.
        tmp_dir         — pre-created directory for segments + concat
                          list. Caller owns cleanup.
    """
    fast = can_fast_copy(clips)

    # Segment container strategy:
    # * fast-copy: match the source (streams are copied as-is, so the
    #   container has to be able to hold them). Falls back to mp4 if
    #   the source has no extension.
    # * re-encode: use the target container, since that's what the
    #   codec args are producing anyway.
    if fast:
        seg_ext = Path(src_path).suffix.lstrip(".") or "mp4"
    else:
        seg_ext = target_container

    # Snapshot codec_args into a list — it's consumed once per segment
    # below, and the caller might have passed a generator.
    codec_list = list(codec_args)

    segment_cmds: list[tuple[list[str], str]] = []
    for i, c in enumerate(clips):
        seg_path = str(tmp_dir / f"seg{i:03d}.{seg_ext}")
        cmd = build_segment_cmd(
            c, src_path, seg_path, codec_list, ffmpeg, fast_copy=fast,
        )
        label = f"Copying {c.name}…" if fast else f"Encoding {c.name}…"
        segment_cmds.append((cmd, label))

    list_file = str(tmp_dir / "concat.txt")
    concat_cmd = build_concat_cmd(list_file, out_path, ffmpeg)
    status_text = "stream-copy (fast)…" if fast else "exporting…"

    return SequencePlan(
        segment_cmds=segment_cmds,
        concat_cmd=concat_cmd,
        list_file=list_file,
        tmp_dir=tmp_dir,
        fast_copy=fast,
        status_text=status_text,
    )

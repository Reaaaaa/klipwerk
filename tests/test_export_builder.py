"""Tests for the pure ffmpeg command-builder functions.

Deliberately ffmpeg-free: we construct ``Clip`` objects, call the
builders, and assert on the returned argv lists. No subprocesses, no
Qt, no disk I/O.
"""
from __future__ import annotations

import pytest

from klipwerk.core.export_builder import (
    build_concat_cmd,
    build_segment_cmd,
    can_fast_copy,
    crop_vf_args,
)
from klipwerk.core.models import Clip, CropRect

FFMPEG = "/usr/bin/ffmpeg"
SRC = "/tmp/input.mp4"
OUT = "/tmp/out.mp4"
DUMMY_CODEC = ["-c:v", "libx264", "-crf", "23", "-preset", "medium", "-c:a", "aac"]


# ── can_fast_copy ──────────────────────────────────────────────────────
class TestCanFastCopy:
    def test_empty_list_rejected(self) -> None:
        assert can_fast_copy([]) is False

    def test_simple_trim_accepted(self) -> None:
        clips = [Clip("a", 0.0, 5.0), Clip("b", 10.0, 20.0)]
        assert can_fast_copy(clips) is True

    def test_any_crop_rejects(self) -> None:
        cr: CropRect = {"x": 0, "y": 0, "w": 100, "h": 100}
        clips = [Clip("a", 0.0, 5.0), Clip("b", 10.0, 20.0, crop=cr)]
        assert can_fast_copy(clips) is False

    def test_all_crop_rejects(self) -> None:
        cr: CropRect = {"x": 0, "y": 0, "w": 100, "h": 100}
        clips = [Clip("a", 0.0, 5.0, crop=cr)]
        assert can_fast_copy(clips) is False

    def test_zero_length_clip_rejects(self) -> None:
        # end == start → duration 0 → reject (ffmpeg chokes on these)
        clips = [Clip("a", 0.0, 5.0), Clip("b", 10.0, 10.0)]
        assert can_fast_copy(clips) is False

    def test_negative_duration_rejects(self) -> None:
        # Shouldn't happen in practice, but Clip.duration clamps at 0,
        # so end < start is effectively zero-length.
        clips = [Clip("weird", 10.0, 5.0)]
        assert can_fast_copy(clips) is False

    def test_single_clip_accepted(self) -> None:
        # Fast-copy is still faster even for a single trim; no reason
        # to exclude based on count.
        clips = [Clip("a", 1.0, 2.0)]
        assert can_fast_copy(clips) is True


# ── build_segment_cmd: re-encode path ──────────────────────────────────
class TestBuildSegmentReencode:
    def test_no_crop_reencode(self) -> None:
        c = Clip("a", 1.0, 4.0)
        cmd = build_segment_cmd(
            c, SRC, OUT, DUMMY_CODEC, FFMPEG, fast_copy=False,
        )
        assert cmd[0] == FFMPEG
        assert "-ss" in cmd and "1.0" in cmd
        assert "-t" in cmd and "3.0" in cmd
        assert "-i" in cmd
        assert cmd[-1] == OUT
        # Codec args must be present
        assert "libx264" in cmd
        # No -vf (no crop)
        assert "-vf" not in cmd
        # And crucially: NOT a stream-copy command
        # The "-c copy" pair (adjacent) must not appear.
        assert not any(
            cmd[i] == "-c" and cmd[i + 1] == "copy"
            for i in range(len(cmd) - 1)
        )

    def test_with_crop_reencode(self) -> None:
        cr: CropRect = {"x": 10, "y": 20, "w": 640, "h": 480}
        c = Clip("a", 0.5, 2.5, crop=cr)
        cmd = build_segment_cmd(
            c, SRC, OUT, DUMMY_CODEC, FFMPEG, fast_copy=False,
        )
        assert "-vf" in cmd
        vf_idx = cmd.index("-vf")
        assert cmd[vf_idx + 1] == "crop=640:480:10:20"

    def test_odd_crop_dims_are_evened(self) -> None:
        cr: CropRect = {"x": 0, "y": 0, "w": 641, "h": 481}
        c = Clip("a", 0.0, 1.0, crop=cr)
        cmd = build_segment_cmd(
            c, SRC, OUT, DUMMY_CODEC, FFMPEG, fast_copy=False,
        )
        vf_idx = cmd.index("-vf")
        # 641→640, 481→480
        assert cmd[vf_idx + 1] == "crop=640:480:0:0"


# ── build_segment_cmd: fast-copy path ──────────────────────────────────
class TestBuildSegmentFastCopy:
    def test_fast_copy_uses_stream_copy(self) -> None:
        c = Clip("a", 1.0, 4.0)
        cmd = build_segment_cmd(
            c, SRC, OUT, DUMMY_CODEC, FFMPEG, fast_copy=True,
        )
        # Must contain the adjacent "-c copy" pair
        assert any(
            cmd[i] == "-c" and cmd[i + 1] == "copy"
            for i in range(len(cmd) - 1)
        ), f"expected '-c copy' in {cmd}"

    def test_fast_copy_has_no_encoder(self) -> None:
        c = Clip("a", 1.0, 4.0)
        cmd = build_segment_cmd(
            c, SRC, OUT, DUMMY_CODEC, FFMPEG, fast_copy=True,
        )
        # No encoder tokens
        for enc in ("libx264", "libx265", "libaom-av1", "libvpx-vp9"):
            assert enc not in cmd, f"fast-copy must not re-encode, saw {enc}"
        # No -vf
        assert "-vf" not in cmd
        # No -crf
        assert "-crf" not in cmd

    def test_fast_copy_uses_ss_before_i(self) -> None:
        """Speed-critical: -ss must come before -i for keyframe seek."""
        c = Clip("a", 5.0, 10.0)
        cmd = build_segment_cmd(
            c, SRC, OUT, DUMMY_CODEC, FFMPEG, fast_copy=True,
        )
        ss_idx = cmd.index("-ss")
        i_idx = cmd.index("-i")
        assert ss_idx < i_idx

    def test_fast_copy_uses_to_not_t(self) -> None:
        """Fast path uses -to (absolute), re-encode path uses -t (duration)."""
        c = Clip("a", 5.0, 10.0)
        cmd = build_segment_cmd(
            c, SRC, OUT, DUMMY_CODEC, FFMPEG, fast_copy=True,
        )
        assert "-to" in cmd
        assert "-t" not in cmd
        to_idx = cmd.index("-to")
        assert cmd[to_idx + 1] == "10.0"

    def test_fast_copy_ignores_crop(self) -> None:
        """Caller must guard with can_fast_copy; if they don't, the crop
        simply gets dropped rather than silently corrupting output."""
        cr: CropRect = {"x": 0, "y": 0, "w": 100, "h": 100}
        c = Clip("oops", 0.0, 1.0, crop=cr)
        cmd = build_segment_cmd(
            c, SRC, OUT, DUMMY_CODEC, FFMPEG, fast_copy=True,
        )
        assert "-vf" not in cmd

    def test_fast_copy_has_avoid_negative_ts(self) -> None:
        c = Clip("a", 0.0, 1.0)
        cmd = build_segment_cmd(
            c, SRC, OUT, DUMMY_CODEC, FFMPEG, fast_copy=True,
        )
        assert "-avoid_negative_ts" in cmd
        idx = cmd.index("-avoid_negative_ts")
        assert cmd[idx + 1] == "make_zero"


# ── build_concat_cmd ───────────────────────────────────────────────────
class TestBuildConcat:
    def test_concat_uses_copy(self) -> None:
        cmd = build_concat_cmd("/tmp/list.txt", OUT, FFMPEG)
        # Always stream-copy at concat stage, regardless of segment method
        assert any(
            cmd[i] == "-c" and cmd[i + 1] == "copy"
            for i in range(len(cmd) - 1)
        )

    def test_concat_uses_demuxer(self) -> None:
        cmd = build_concat_cmd("/tmp/list.txt", OUT, FFMPEG)
        assert "-f" in cmd
        f_idx = cmd.index("-f")
        assert cmd[f_idx + 1] == "concat"
        assert "-safe" in cmd
        safe_idx = cmd.index("-safe")
        assert cmd[safe_idx + 1] == "0"


# ── crop_vf_args (small but worth pinning) ─────────────────────────────
class TestCropVfArgs:
    def test_none_returns_empty(self) -> None:
        assert crop_vf_args(None) == []

    def test_even_dims_untouched(self) -> None:
        cr: CropRect = {"x": 0, "y": 0, "w": 640, "h": 360}
        assert crop_vf_args(cr) == ["-vf", "crop=640:360:0:0"]

    @pytest.mark.parametrize(
        ("w", "h", "expected_w", "expected_h"),
        [
            (641, 360, 640, 360),
            (640, 361, 640, 360),
            (3, 3, 2, 2),
        ],
    )
    def test_odd_dims_rounded_down(
        self, w: int, h: int, expected_w: int, expected_h: int,
    ) -> None:
        cr: CropRect = {"x": 5, "y": 7, "w": w, "h": h}
        args = crop_vf_args(cr)
        assert args == ["-vf", f"crop={expected_w}:{expected_h}:5:7"]

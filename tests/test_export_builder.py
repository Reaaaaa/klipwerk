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
    gif_vf,
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


# ── gif_vf ─────────────────────────────────────────────────────────────
class TestGifVf:
    def test_no_crop_no_scale(self) -> None:
        vf = gif_vf(12, None)
        assert vf.startswith("fps=12,split")
        assert "crop" not in vf
        assert "flags=lanczos" not in vf   # "scale" alone would match bayer_scale=5

    def test_no_crop_with_scale(self) -> None:
        vf = gif_vf(15, 480)
        assert "fps=15" in vf
        assert "scale=480:-1:flags=lanczos" in vf
        assert "crop" not in vf

    def test_with_crop_no_scale(self) -> None:
        cr: CropRect = {"x": 10, "y": 20, "w": 640, "h": 360}
        vf = gif_vf(12, None, cr)
        # crop must come first, then fps
        assert vf.startswith("crop=640:360:10:20,fps=12,split")
        assert "flags=lanczos" not in vf   # "scale" alone would match bayer_scale=5

    def test_with_crop_and_scale(self) -> None:
        cr: CropRect = {"x": 0, "y": 0, "w": 1280, "h": 720}
        vf = gif_vf(8, 320, cr)
        assert "crop=1280:720:0:0" in vf
        assert "fps=8" in vf
        assert "scale=320:-1:flags=lanczos" in vf

    def test_palette_chain_always_present(self) -> None:
        for vf in (gif_vf(12, None), gif_vf(12, 480), gif_vf(8, 320, {"x": 0, "y": 0, "w": 100, "h": 100})):
            assert "split[s0][s1]" in vf
            assert "palettegen=" in vf
            assert "paletteuse=" in vf

    def test_crop_precedes_fps_precedes_scale(self) -> None:
        cr: CropRect = {"x": 5, "y": 5, "w": 200, "h": 100}
        vf = gif_vf(12, 320, cr)
        crop_pos  = vf.index("crop=")
        fps_pos   = vf.index("fps=")
        scale_pos = vf.index("scale=")
        assert crop_pos < fps_pos < scale_pos

    @pytest.mark.parametrize("fps", [8, 12, 15, 24])
    def test_fps_token_correct(self, fps: int) -> None:
        vf = gif_vf(fps, None)
        assert f"fps={fps}" in vf

    @pytest.mark.parametrize("width", [320, 480, 640])
    def test_width_token_correct(self, width: int) -> None:
        vf = gif_vf(12, width)
        assert f"scale={width}:-1:flags=lanczos" in vf

    def test_palette_uses_bayer_dither(self) -> None:
        vf = gif_vf(12, 480)
        assert "dither=bayer" in vf
        assert "bayer_scale=5" in vf

    def test_palettegen_stats_mode_diff(self) -> None:
        vf = gif_vf(12, None)
        assert "stats_mode=diff" in vf

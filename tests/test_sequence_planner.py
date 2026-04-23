"""Tests for ``plan_sequence_export`` — the high-level dispatcher.

Pure-function tests: no ``QMainWindow``, no subprocess. We give the
planner a clip list and assert on the returned ``SequencePlan``.

These replaced an earlier set of Qt-window-based dispatcher tests that
passed but segfaulted on teardown. The lesson learned was to push the
decision logic down into the pure-function layer and test it there,
keeping the app method a thin wiring shim.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from klipwerk.core.export_builder import SequencePlan, plan_sequence_export
from klipwerk.core.models import Clip, CropRect

FFMPEG = "/usr/bin/ffmpeg"
CODEC = ["-c:v", "libx264", "-crf", "23", "-preset", "medium", "-c:a", "aac"]


@pytest.fixture
def tmp_export_dir(tmp_path: Path) -> Path:
    # Planner expects the dir to exist; caller's responsibility.
    d = tmp_path / "segments"
    d.mkdir()
    return d


def _plan(
    clips: list[Clip],
    tmp_dir: Path,
    *,
    src: str = "/tmp/src.mp4",
    out: str = "/tmp/out.mp4",
    container: str = "mp4",
) -> SequencePlan:
    return plan_sequence_export(
        clips=clips,
        src_path=src,
        out_path=out,
        codec_args=CODEC,
        target_container=container,
        ffmpeg=FFMPEG,
        tmp_dir=tmp_dir,
    )


def _has_c_copy(cmd: list[str]) -> bool:
    """Adjacent ``-c copy`` pair somewhere in argv."""
    return any(
        cmd[i] == "-c" and cmd[i + 1] == "copy"
        for i in range(len(cmd) - 1)
    )


class TestFastCopyDecision:
    def test_no_crops_picks_fast(self, tmp_export_dir: Path) -> None:
        plan = _plan(
            [Clip("intro", 0.0, 5.0), Clip("outro", 10.0, 15.0)],
            tmp_export_dir,
        )
        assert plan.fast_copy is True
        assert "stream-copy" in plan.status_text

    def test_any_crop_forces_reencode(self, tmp_export_dir: Path) -> None:
        cr: CropRect = {"x": 0, "y": 0, "w": 640, "h": 480}
        plan = _plan(
            [Clip("a", 0.0, 5.0), Clip("b", 10.0, 15.0, crop=cr)],
            tmp_export_dir,
        )
        assert plan.fast_copy is False
        assert "stream-copy" not in plan.status_text

    def test_zero_length_clip_forces_reencode(self, tmp_export_dir: Path) -> None:
        plan = _plan(
            [Clip("a", 0.0, 5.0), Clip("dud", 10.0, 10.0)],
            tmp_export_dir,
        )
        assert plan.fast_copy is False


class TestSegmentCommands:
    def test_fast_path_produces_copy_commands(self, tmp_export_dir: Path) -> None:
        plan = _plan(
            [Clip("a", 0.0, 5.0), Clip("b", 10.0, 15.0), Clip("c", 20.0, 25.0)],
            tmp_export_dir,
        )
        assert len(plan.segment_cmds) == 3
        for cmd, _ in plan.segment_cmds:
            assert _has_c_copy(cmd), f"expected stream-copy: {cmd}"
            assert "libx264" not in cmd
            assert "-vf" not in cmd

    def test_reencode_path_produces_codec_commands(self, tmp_export_dir: Path) -> None:
        cr: CropRect = {"x": 0, "y": 0, "w": 320, "h": 240}
        plan = _plan(
            [Clip("a", 0.0, 5.0), Clip("b", 10.0, 15.0, crop=cr)],
            tmp_export_dir,
        )
        # Both segments go through re-encode because the *sequence* can't
        # fast-copy when any one clip needs it.
        for cmd, _ in plan.segment_cmds:
            assert "libx264" in cmd
        # Only the cropped clip has a -vf filter
        uncropped_cmd, _ = plan.segment_cmds[0]
        cropped_cmd, _ = plan.segment_cmds[1]
        assert "-vf" not in uncropped_cmd
        assert "-vf" in cropped_cmd


class TestSegmentExtensions:
    def test_fast_copy_uses_source_extension(self, tmp_export_dir: Path) -> None:
        plan = _plan(
            [Clip("a", 0.0, 5.0)],
            tmp_export_dir,
            src="/videos/whatever.mkv",
            container="mp4",   # target container
        )
        # Segment path is the last argv of the first segment cmd
        seg_path = plan.segment_cmds[0][0][-1]
        assert seg_path.endswith(".mkv"), f"expected .mkv, got {seg_path}"

    def test_reencode_uses_target_container(self, tmp_export_dir: Path) -> None:
        cr: CropRect = {"x": 0, "y": 0, "w": 320, "h": 240}
        plan = _plan(
            [Clip("a", 0.0, 5.0, crop=cr)],
            tmp_export_dir,
            src="/videos/source.mkv",
            container="webm",
        )
        seg_path = plan.segment_cmds[0][0][-1]
        assert seg_path.endswith(".webm"), f"expected .webm, got {seg_path}"

    def test_extensionless_source_falls_back_to_mp4(
        self, tmp_export_dir: Path,
    ) -> None:
        plan = _plan(
            [Clip("a", 0.0, 5.0)],
            tmp_export_dir,
            src="/videos/no_extension_file",
            container="mp4",
        )
        seg_path = plan.segment_cmds[0][0][-1]
        assert seg_path.endswith(".mp4")


class TestLabels:
    def test_fast_mode_says_copying(self, tmp_export_dir: Path) -> None:
        plan = _plan(
            [Clip("intro", 0.0, 5.0), Clip("outro", 10.0, 15.0)],
            tmp_export_dir,
        )
        for _cmd, label in plan.segment_cmds:
            assert "Copying" in label
            assert "Encoding" not in label

    def test_reencode_says_encoding(self, tmp_export_dir: Path) -> None:
        cr: CropRect = {"x": 0, "y": 0, "w": 320, "h": 240}
        plan = _plan(
            [Clip("crop_me", 0.0, 5.0, crop=cr)],
            tmp_export_dir,
        )
        for _cmd, label in plan.segment_cmds:
            assert "Encoding" in label


class TestConcatCmd:
    def test_concat_always_stream_copies(self, tmp_export_dir: Path) -> None:
        """Regardless of segment mode, concat step is stream-copy."""
        # Fast mode
        fast_plan = _plan([Clip("a", 0.0, 5.0)], tmp_export_dir)
        assert _has_c_copy(fast_plan.concat_cmd)

        # Re-encode mode
        cr: CropRect = {"x": 0, "y": 0, "w": 320, "h": 240}
        reenc_plan = _plan([Clip("a", 0.0, 5.0, crop=cr)], tmp_export_dir)
        assert _has_c_copy(reenc_plan.concat_cmd)

    def test_concat_uses_demuxer(self, tmp_export_dir: Path) -> None:
        plan = _plan([Clip("a", 0.0, 5.0)], tmp_export_dir)
        cmd = plan.concat_cmd
        assert "-f" in cmd and cmd[cmd.index("-f") + 1] == "concat"
        assert "-safe" in cmd and cmd[cmd.index("-safe") + 1] == "0"


class TestPlanShape:
    def test_list_file_in_tmp_dir(self, tmp_export_dir: Path) -> None:
        plan = _plan([Clip("a", 0.0, 5.0)], tmp_export_dir)
        assert plan.list_file.startswith(str(tmp_export_dir))
        assert plan.list_file.endswith("concat.txt")

    def test_tmp_dir_preserved_on_plan(self, tmp_export_dir: Path) -> None:
        plan = _plan([Clip("a", 0.0, 5.0)], tmp_export_dir)
        assert plan.tmp_dir == tmp_export_dir

    def test_codec_args_generator_is_safe(self, tmp_export_dir: Path) -> None:
        """Passing a generator for codec_args must not break on internal re-use."""
        plan = plan_sequence_export(
            clips=[Clip("a", 0.0, 5.0, crop={"x": 0, "y": 0, "w": 320, "h": 240})],
            src_path="/tmp/src.mp4",
            out_path="/tmp/out.mp4",
            codec_args=(x for x in CODEC),   # generator!
            target_container="mp4",
            ffmpeg=FFMPEG,
            tmp_dir=tmp_export_dir,
        )
        cmd = plan.segment_cmds[0][0]
        # All codec tokens must still be present despite the generator
        assert "libx264" in cmd
        assert "-crf" in cmd
        assert "23" in cmd

"""Tests for the format table and codec argument builder."""
from __future__ import annotations

import pytest

from klipwerk.core import formats


def test_formats_nonempty():
    assert len(formats.FORMATS) > 0


def test_all_formats_have_labels_and_containers():
    for spec in formats.FORMATS:
        assert spec.label
        assert spec.container in {"mp4", "mkv", "webm"}


def test_all_formats_have_at_least_one_preset():
    for spec in formats.FORMATS:
        assert len(spec.presets) >= 1


def test_all_formats_have_sane_crf_defaults():
    for spec in formats.FORMATS:
        assert 0 <= spec.crf_default <= spec.crf_max


def test_codec_args_contains_video_encoder():
    for spec in formats.FORMATS:
        args = formats.codec_args(spec, spec.crf_default, spec.presets[0])
        assert "-c:v" in args
        idx = args.index("-c:v")
        assert args[idx + 1] == spec.encoder


def test_h264_produces_faststart():
    spec = next(s for s in formats.FORMATS if s.encoder == "libx264")
    args = formats.codec_args(spec, 23, "medium")
    assert "-movflags" in args
    assert "+faststart" in args


def test_h265_tags_hvc1_for_apple_compat():
    spec = next(s for s in formats.FORMATS if s.encoder == "libx265")
    args = formats.codec_args(spec, 28, "medium")
    idx = args.index("-tag:v")
    assert args[idx + 1] == "hvc1"


def test_av1_gets_row_mt():
    spec = next(s for s in formats.FORMATS if s.encoder == "libaom-av1")
    args = formats.codec_args(spec, 32, "6")
    assert "-row-mt" in args


def test_pick_default_maps_input_codec_to_sensible_output():
    # Just verify the indices are valid and produce the documented choices.
    assert formats.pick_default_for("H264") == 0
    assert formats.pick_default_for("HEVC") == 1
    assert formats.pick_default_for("H265") == 1
    assert formats.pick_default_for("AV1") == 4
    assert formats.pick_default_for("VP9") == 5
    # Unknown codec falls back to H.264 default
    assert formats.pick_default_for("WEIRD_CODEC") == 0


@pytest.mark.parametrize("spec", formats.FORMATS)
def test_codec_args_handles_every_format(spec):
    """Regression guard: every format must produce valid args without raising."""
    args = formats.codec_args(spec, spec.crf_default, spec.presets[0])
    # Minimally we need both a video and an audio codec specified
    assert args.count("-c:v") == 1
    assert args.count("-c:a") == 1

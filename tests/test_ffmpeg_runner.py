"""Tests for the ffmpeg binary lookup and platform-safe subprocess flags."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from klipwerk.core import ffmpeg_runner


def test_creation_flags_is_int():
    """Must be an int on every platform so we can pass it to Popen unconditionally."""
    assert isinstance(ffmpeg_runner.CREATION_FLAGS, int)


def test_creation_flags_zero_on_non_windows():
    if sys.platform != "win32":
        assert ffmpeg_runner.CREATION_FLAGS == 0


def test_creation_flags_matches_windows_constant():
    if sys.platform == "win32":
        assert ffmpeg_runner.CREATION_FLAGS == subprocess.CREATE_NO_WINDOW


def test_base_is_defined():
    """The original bug: BASE was referenced but never defined."""
    assert isinstance(ffmpeg_runner.BASE, Path)
    assert ffmpeg_runner.BASE.exists()


def test_find_bin_uses_path_first(monkeypatch, tmp_path):
    fake = tmp_path / "ffmpeg"
    fake.write_text("")
    fake.chmod(0o755)

    monkeypatch.setattr("shutil.which", lambda name: str(fake) if name == "ffmpeg" else None)
    assert ffmpeg_runner.find_bin("ffmpeg") == str(fake)


def test_find_bin_raises_helpful_error_when_missing(monkeypatch):
    """When nothing matches, we want a clear message — not a NameError."""
    monkeypatch.setattr("shutil.which", lambda _name: None)
    monkeypatch.setattr(ffmpeg_runner, "_candidates", lambda _name: [])
    with pytest.raises(FileNotFoundError) as exc:
        ffmpeg_runner.find_bin("ffmpeg")
    assert "ffmpeg" in str(exc.value)


def test_resolve_binaries_caches(monkeypatch, tmp_path):
    f_ffmpeg = tmp_path / "ffmpeg";  f_ffmpeg.write_text(""); f_ffmpeg.chmod(0o755)
    f_probe  = tmp_path / "ffprobe"; f_probe.write_text("");  f_probe.chmod(0o755)

    def fake_which(name):
        return {"ffmpeg": str(f_ffmpeg), "ffprobe": str(f_probe)}.get(name)

    monkeypatch.setattr("shutil.which", fake_which)

    ff, fp = ffmpeg_runner.resolve_binaries()
    assert ff == str(f_ffmpeg)
    assert fp == str(f_probe)
    assert ffmpeg_runner.ffmpeg_bin() == ff
    assert ffmpeg_runner.ffprobe_bin() == fp

"""Tests for the settings persistence layer."""
from __future__ import annotations

import os

import pytest
from PyQt6.QtCore import QByteArray, QCoreApplication

from klipwerk.settings import Settings


@pytest.fixture(autouse=True, scope="module")
def _qapp():
    """QSettings needs a live QCoreApplication for path resolution."""
    app = QCoreApplication.instance() or QCoreApplication([])
    yield app


@pytest.fixture
def tmp_settings(tmp_path):
    """Fresh ini-file-backed Settings for each test."""
    return Settings(str(tmp_path / "kw.ini"))


class TestRoundtrip:
    def test_prefix_and_suffix(self, tmp_settings: Settings) -> None:
        tmp_settings.set_prefix("foo_")
        tmp_settings.set_suffix("_bar")
        tmp_settings.sync()

        fresh = Settings(tmp_settings.path)
        assert fresh.prefix() == "foo_"
        assert fresh.suffix() == "_bar"

    def test_fmt_crf_preset(self, tmp_settings: Settings) -> None:
        tmp_settings.set_fmt_index(3)
        tmp_settings.set_crf(21)
        tmp_settings.set_preset("slow")
        tmp_settings.sync()

        fresh = Settings(tmp_settings.path)
        assert fresh.fmt_index() == 3
        assert fresh.crf(default=28) == 21
        assert fresh.preset() == "slow"

    def test_k_mode_toggle(self, tmp_settings: Settings) -> None:
        tmp_settings.set_use_k_mode(False)
        tmp_settings.sync()

        fresh = Settings(tmp_settings.path)
        assert fresh.use_k_mode() is False

        tmp_settings.set_use_k_mode(True)
        tmp_settings.sync()
        fresh2 = Settings(tmp_settings.path)
        assert fresh2.use_k_mode() is True

    def test_geometry_blob(self, tmp_settings: Settings) -> None:
        blob = QByteArray(b"\x01\x00\xff\xfe" * 8)
        tmp_settings.set_geometry(blob)
        tmp_settings.sync()

        fresh = Settings(tmp_settings.path)
        got = fresh.geometry()
        assert got is not None
        assert bytes(got) == bytes(blob)

    def test_sidebar_splitter_blob(self, tmp_settings: Settings) -> None:
        blob = QByteArray(b"\xde\xad\xbe\xef" * 4)
        tmp_settings.set_sidebar_splitter(blob)
        tmp_settings.sync()

        fresh = Settings(tmp_settings.path)
        got = fresh.sidebar_splitter()
        assert got is not None
        assert bytes(got) == bytes(blob)


class TestDefaults:
    def test_missing_keys_return_defaults(self, tmp_settings: Settings) -> None:
        # Empty ini file → every getter must return its declared default.
        assert tmp_settings.prefix(default="x") == "x"
        assert tmp_settings.suffix(default="_y") == "_y"
        assert tmp_settings.fmt_index(default=4) == 4
        assert tmp_settings.crf(default=23) == 23
        assert tmp_settings.preset(default="medium") == "medium"
        assert tmp_settings.use_k_mode(default=True) is True
        assert tmp_settings.use_k_mode(default=False) is False
        assert tmp_settings.geometry() is None
        assert tmp_settings.sidebar_splitter() is None

    def test_empty_string_prefix_is_valid(self, tmp_settings: Settings) -> None:
        """User can deliberately clear the prefix back to empty."""
        tmp_settings.set_prefix("")
        tmp_settings.sync()
        fresh = Settings(tmp_settings.path)
        assert fresh.prefix(default="should-not-be-used") == ""

    def test_per_mode_suffixes_roundtrip(self, tmp_settings: Settings) -> None:
        tmp_settings.set_suffix_crop("_cropped")
        tmp_settings.set_suffix_clip("_myclip")
        tmp_settings.set_suffix_seq("_sequence_final")
        tmp_settings.sync()

        fresh = Settings(tmp_settings.path)
        assert fresh.suffix_crop() == "_cropped"
        assert fresh.suffix_clip() == "_myclip"
        assert fresh.suffix_seq() == "_sequence_final"

    def test_per_mode_suffixes_defaults(self, tmp_settings: Settings) -> None:
        assert tmp_settings.suffix_crop() == "_crop"
        assert tmp_settings.suffix_clip() == "_clip"
        assert tmp_settings.suffix_seq() == "_seq"


class TestRobustness:
    def test_corrupted_value_falls_back_to_default(
        self, tmp_path, tmp_settings: Settings
    ) -> None:
        """A hand-edited int key with garbage should not crash."""
        # Write a string where an int is expected
        with open(tmp_settings.path, "w") as fh:
            fh.write("[export]\ncrf=not_a_number\n")

        fresh = Settings(tmp_settings.path)
        # Should gracefully return default, not raise
        assert fresh.crf(default=23) == 23

    def test_missing_file_ok(self, tmp_path) -> None:
        """Pointing at a non-existent file is equivalent to 'fresh user'."""
        ghost = str(tmp_path / "does-not-exist.ini")
        assert not os.path.exists(ghost)
        s = Settings(ghost)
        assert s.prefix(default="hi") == "hi"
        # And writing then works:
        s.set_prefix("hello")
        s.sync()
        assert os.path.exists(ghost)

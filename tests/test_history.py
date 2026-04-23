"""Tests for the Clip dataclass and the History / command stack."""
from __future__ import annotations

import pytest

from klipwerk.core.models import Clip
from klipwerk.history import History


def make_clip(name: str = "Klip 1", start: float = 0.0, end: float = 5.0) -> Clip:
    return Clip(name=name, start=start, end=end)


# ── Clip ────────────────────────────────────────────────────────────
def test_clip_duration():
    assert make_clip(start=2.5, end=7.0).duration == pytest.approx(4.5)


def test_clip_duration_never_negative():
    # Defensive: if someone inverts start/end we return 0 rather than a negative.
    assert make_clip(start=10, end=5).duration == 0.0


def test_clip_id_is_unique():
    ids = {Clip(name=f"c{i}", start=0, end=1).id for i in range(100)}
    assert len(ids) == 100


# ── History: add ────────────────────────────────────────────────────
def test_history_add_appends():
    clips: list[Clip] = []
    h = History(clips)
    c = make_clip()
    h.add(c)
    assert clips == [c]
    assert h.undo_depth == 1


def test_history_add_then_undo_removes():
    clips: list[Clip] = []
    h = History(clips)
    c = make_clip()
    h.add(c)
    assert h.undo()
    assert clips == []


def test_history_add_undo_redo_roundtrip():
    clips: list[Clip] = []
    h = History(clips)
    c = make_clip()
    h.add(c)
    h.undo()
    assert h.redo()
    assert clips == [c]


# ── History: delete ─────────────────────────────────────────────────
def test_history_delete_removes_and_undo_restores():
    c1, c2 = make_clip("a"), make_clip("b")
    clips = [c1, c2]
    h = History(clips)
    h.delete(0)
    assert clips == [c2]
    h.undo()
    assert clips == [c1, c2]


def test_history_delete_out_of_bounds_is_noop():
    clips = [make_clip()]
    h = History(clips)
    assert h.delete(5) is None
    assert h.delete(-1) is None
    assert clips == [clips[0]]
    assert h.undo_depth == 0   # nothing recorded


# ── History: move ───────────────────────────────────────────────────
def test_history_move_reorders():
    a, b, c = make_clip("a"), make_clip("b"), make_clip("c")
    clips = [a, b, c]
    h = History(clips)
    assert h.move(0, 2)
    assert [x.name for x in clips] == ["b", "c", "a"]


def test_history_move_same_index_is_noop():
    clips = [make_clip("a")]
    h = History(clips)
    assert h.move(0, 0) is False
    assert h.undo_depth == 0


def test_history_move_invalid_index_is_noop():
    clips = [make_clip("a"), make_clip("b")]
    h = History(clips)
    assert h.move(0, 99) is False
    assert h.move(-1, 0) is False
    assert h.undo_depth == 0


def test_history_move_undo_redo():
    a, b, c = make_clip("a"), make_clip("b"), make_clip("c")
    clips = [a, b, c]
    h = History(clips)
    h.move(0, 2)
    h.undo()
    assert [x.name for x in clips] == ["a", "b", "c"]
    h.redo()
    assert [x.name for x in clips] == ["b", "c", "a"]


# ── History: rename ─────────────────────────────────────────────────
def test_history_rename_updates_name():
    clips = [make_clip("old")]
    h = History(clips)
    assert h.rename(0, "new")
    assert clips[0].name == "new"
    h.undo()
    assert clips[0].name == "old"


def test_history_rename_same_name_is_noop():
    clips = [make_clip("same")]
    h = History(clips)
    assert h.rename(0, "same") is False
    assert h.undo_depth == 0


# ── History: bounds on stack ────────────────────────────────────────
def test_history_stack_has_max_depth():
    clips: list[Clip] = []
    h = History(clips, max_depth=3)
    for i in range(10):
        h.add(make_clip(f"c{i}"))
    assert h.undo_depth == 3


def test_history_new_edit_clears_redo():
    clips: list[Clip] = []
    h = History(clips)
    c1, c2 = make_clip("a"), make_clip("b")
    h.add(c1)
    h.undo()
    assert h.redo_depth == 1
    h.add(c2)
    assert h.redo_depth == 0

"""Undo/redo history as a command stack.

The original script deep-copied the entire clip list on every edit.
That's O(n) memory per action and slow on big projects. Command pattern
stores just the minimum info to undo/redo a single operation.

Each command knows how to `do()` (apply) and `undo()` (revert) against
the shared clip list. The executor keeps two stacks.
"""
from __future__ import annotations

from dataclasses import dataclass

from .core.models import Clip


# ── Individual commands ─────────────────────────────────────────────
@dataclass
class _AddClip:
    clip: Clip

    def do(self, clips: list[Clip]) -> None:
        clips.append(self.clip)

    def undo(self, clips: list[Clip]) -> None:
        # Remove by identity — safer than by index if list changed
        clips.remove(self.clip)


@dataclass
class _DeleteClip:
    index: int
    clip: Clip

    def do(self, clips: list[Clip]) -> None:
        clips.pop(self.index)

    def undo(self, clips: list[Clip]) -> None:
        clips.insert(self.index, self.clip)


@dataclass
class _MoveClip:
    from_idx: int
    to_idx: int

    def do(self, clips: list[Clip]) -> None:
        clip = clips.pop(self.from_idx)
        clips.insert(self.to_idx, clip)

    def undo(self, clips: list[Clip]) -> None:
        clip = clips.pop(self.to_idx)
        clips.insert(self.from_idx, clip)


@dataclass
class _RenameClip:
    index: int
    old_name: str
    new_name: str

    def do(self, clips: list[Clip]) -> None:
        clips[self.index].name = self.new_name

    def undo(self, clips: list[Clip]) -> None:
        clips[self.index].name = self.old_name


Command = _AddClip | _DeleteClip | _MoveClip | _RenameClip


# ── Executor ────────────────────────────────────────────────────────
class History:
    """Keep two bounded stacks of commands for undo/redo."""

    def __init__(self, clips: list[Clip], max_depth: int = 100):
        self._clips = clips
        self._undo: list[Command] = []
        self._redo: list[Command] = []
        self._max = max_depth

    # Factories that apply-and-record in one step
    def add(self, clip: Clip) -> None:
        self._exec(_AddClip(clip))

    def delete(self, index: int) -> Clip | None:
        if not (0 <= index < len(self._clips)):
            return None
        clip = self._clips[index]
        self._exec(_DeleteClip(index, clip))
        return clip

    def move(self, from_idx: int, to_idx: int) -> bool:
        if from_idx == to_idx:
            return False
        if not (0 <= from_idx < len(self._clips)):
            return False
        if not (0 <= to_idx < len(self._clips)):
            return False
        self._exec(_MoveClip(from_idx, to_idx))
        return True

    def rename(self, index: int, new_name: str) -> bool:
        if not (0 <= index < len(self._clips)):
            return False
        old = self._clips[index].name
        if old == new_name:
            return False
        self._exec(_RenameClip(index, old, new_name))
        return True

    # ── Stack ops ───────────────────────────────────────────────
    def _exec(self, cmd: Command) -> None:
        cmd.do(self._clips)
        self._undo.append(cmd)
        self._redo.clear()
        if len(self._undo) > self._max:
            self._undo.pop(0)

    def undo(self) -> bool:
        if not self._undo:
            return False
        cmd = self._undo.pop()
        cmd.undo(self._clips)
        self._redo.append(cmd)
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        cmd = self._redo.pop()
        cmd.do(self._clips)
        self._undo.append(cmd)
        return True

    def clear(self) -> None:
        self._undo.clear()
        self._redo.clear()

    @property
    def undo_depth(self) -> int:
        return len(self._undo)

    @property
    def redo_depth(self) -> int:
        return len(self._redo)

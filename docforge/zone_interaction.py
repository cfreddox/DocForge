"""Pure drag-and-drop lifecycle logic shared by Qt zone and regression tests.

A transient DragLeave during a native X11/Wayland resize should not restart the
flower animation or prematurely destroy the file-to-format selection.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class DropSession:
    inside: bool = False
    generation: int = 0
    leave_deadline: float | None = None

    def enter(self) -> None:
        self.inside = True
        self.generation += 1
        self.leave_deadline = None

    def leave(self, now: float, grace: float = 0.32) -> int:
        self.inside = False
        self.generation += 1
        self.leave_deadline = now + grace
        return self.generation

    def drop(self) -> None:
        self.inside = False
        self.generation += 1
        self.leave_deadline = None

    def should_collapse(self, generation: int, now: float, pointer_in_window: bool) -> bool:
        if self.inside or generation != self.generation or self.leave_deadline is None:
            return False
        # Resizing a native window can fire DragLeave with the pointer still
        # over its visible petals. Never fold while the cursor remains there;
        # wait for an actual exit from the window (or an explicit drop).
        if now < self.leave_deadline or pointer_in_window:
            return False
        self.leave_deadline = None
        return True

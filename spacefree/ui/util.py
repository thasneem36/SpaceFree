from __future__ import annotations

import os
import subprocess

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QTableWidgetItem


class NumItem(QTableWidgetItem):
    """Table item that sorts by a number instead of by its text."""

    def __init__(self, text: str, value: float) -> None:
        super().__init__(text)
        self.value = value
        self.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

    def __lt__(self, other: QTableWidgetItem) -> bool:
        return self.value < getattr(other, "value", 0)


def open_in_explorer(path: str) -> bool:
    """Show a file or folder in Windows Explorer (selected). Falls back to its parent folder."""
    path = os.path.normpath(path)
    if os.name != "nt":
        return False
    if os.path.exists(path):
        subprocess.Popen(f'explorer /select,"{path}"')
        return True
    parent = os.path.dirname(path)
    while parent and not os.path.isdir(parent):
        nxt = os.path.dirname(parent)
        if nxt == parent:
            return False
        parent = nxt
    if parent:
        os.startfile(parent)  # type: ignore[attr-defined]
        return True
    return False


def open_file(path: str) -> None:
    if os.name == "nt" and os.path.exists(path):
        os.startfile(os.path.normpath(path))  # type: ignore[attr-defined]

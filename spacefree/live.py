"""Incremental classifier that runs while the scan is still in progress."""
from __future__ import annotations

import os
import threading

from . import safety
from .models import DirNode, FileRec, Finding
from .rules import MIN_FINDING, classify_dir, classify_file


class LiveAnalyzer:
    """Receives scanner callbacks (from many threads) and queues UI updates."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.findings: dict[str, Finding] = {}
        self.flagged_dirs: set[str] = set()
        self._added: list[Finding] = []
        self._removed: list[str] = []

    # --- scanner hooks -------------------------------------------------
    def on_big_file(self, rec: FileRec) -> None:
        f = classify_file(rec)
        if f is None:
            return
        with self._lock:
            self.findings[f.path] = f
            self._added.append(f)

    def on_dir_done(self, node: DirNode) -> None:
        if node.parent is None:
            return
        if node.name.lower() != "windows.old" and not safety.worth_descending(node.path):
            return
        f = classify_dir(node.path, node)
        if f is None or f.size < MIN_FINDING:
            return
        prefix = node.path + os.sep
        with self._lock:
            # the whole folder is junk: drop findings for things inside it
            for p in [p for p in self.findings if p.startswith(prefix)]:
                del self.findings[p]
            self._removed.append(node.path)
            self.findings[f.path] = f
            self.flagged_dirs.add(f.path)
            self._added.append(f)

    # --- UI side ---------------------------------------------------------
    def drain(self) -> tuple[list[Finding], list[str]]:
        with self._lock:
            added, removed = self._added, self._removed
            self._added, self._removed = [], []
        return added, removed

    def totals(self, label: str) -> int:
        with self._lock:
            return sum(f.size for f in self.findings.values() if f.label == label)

    def snapshot(self) -> list[Finding]:
        with self._lock:
            return list(self.findings.values())

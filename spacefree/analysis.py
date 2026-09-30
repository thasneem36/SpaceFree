"""Turns a raw ScanResult into labelled findings and summary numbers."""
from __future__ import annotations

import os
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Callable

from . import safety
from .duplicates import find_duplicates
from .models import BAD, REVIEW, FileRec, Finding, ScanResult
from .rules import classify_dir, classify_file, age_days, MIN_FINDING

# folders where duplicate files are expected and meaningless
DUP_SKIP_PARTS = (r"\appdata" + os.sep, r"\node_modules" + os.sep, r"\.git" + os.sep,
                  r"\site-packages" + os.sep, r"\programdata" + os.sep)


@dataclass
class Analysis:
    scan: ScanResult
    findings: list[Finding] = field(default_factory=list)
    flagged_dirs: set[str] = field(default_factory=set)
    important_bytes: int = 0
    top_dirs: list[tuple[str, int]] = field(default_factory=list)

    def total(self, label: str) -> int:
        return sum(f.size for f in self.findings if f.label == label)

    @property
    def good_bytes(self) -> int:
        used = self.total(BAD) + self.total(REVIEW) + self.important_bytes
        return max(0, self.scan.total_size - used)

    def by_category(self) -> list[tuple[str, str, int, int]]:
        agg: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0])
        for f in self.findings:
            a = agg[(f.category, f.label)]
            a[0] += 1
            a[1] += f.size
        rows = [(c, l, n, s) for (c, l), (n, s) in agg.items()]
        return sorted(rows, key=lambda r: r[3], reverse=True)


def _in_flagged(path: str, flagged: set[str]) -> bool:
    p = os.path.dirname(path)
    while p and p not in flagged:
        parent = os.path.dirname(p)
        if parent == p:
            return False
        p = parent
    return bool(p)


def analyze(scan: ScanResult, cancel: threading.Event | None = None,
            status: Callable[[str], None] | None = None, find_dupes: bool = True) -> Analysis:
    out = Analysis(scan)
    nodes = scan.nodes
    if status:
        status("Classifying folders...")

    # 1) folders: walk top-down, flag junk folders, never descend into flagged/protected ones
    stack = list(scan.roots)
    while stack:
        path = stack.pop()
        node = nodes.get(path)
        if node is None:
            continue
        if node.parent is not None:
            if node.name.lower() == "windows.old":  # protected, but reported (manual removal)
                out.findings.append(classify_dir(path, node))
                continue
            if not safety.worth_descending(path):
                out.important_bytes += node.size
                continue
            f = classify_dir(path, node)
            if f is not None and f.size >= MIN_FINDING:
                out.findings.append(f)
                out.flagged_dirs.add(path)
                continue
            if f is not None:
                continue
            if safety.is_personal(path) and not safety.is_personal(node.parent):
                out.important_bytes += node.size
        stack.extend(node.children)

    # 2) individual big files
    if status:
        status("Classifying large files...")
    candidates: list[FileRec] = []
    for rec in scan.big_files:
        if cancel is not None and cancel.is_set():
            break
        if _in_flagged(rec.path, out.flagged_dirs):
            continue
        f = classify_file(rec)
        if f is not None:
            out.findings.append(f)
            continue
        low = safety.norm(rec.path)
        if not safety.is_protected(rec.path) and not any(s in low for s in DUP_SKIP_PARTS):
            candidates.append(rec)

    # 3) duplicates
    if find_dupes and candidates and not (cancel is not None and cancel.is_set()):
        for group in find_duplicates(candidates, cancel, status):
            keep = min(group, key=lambda r: (r.path.count(os.sep), len(r.path), r.mtime))
            for r in group:
                if r is keep:
                    continue
                label = REVIEW if safety.is_personal(r.path) else BAD
                out.findings.append(Finding(
                    r.path, r.size, False, label, "Duplicate",
                    f"Identical copy of {keep.path}", age_days(r.mtime, r.atime), True, keep.path))

    out.findings.sort(key=lambda f: f.size, reverse=True)

    # 4) biggest folders (answers "why is my disk full?")
    def depth(p: str) -> int:
        return p.rstrip(os.sep).count(os.sep)
    root_depth = {r: depth(r) for r in scan.roots}
    cands = []
    for p, n in nodes.items():
        if n.parent is None:
            continue
        root = next((r for r in scan.roots if p.startswith(r)), None)
        if root and depth(p) - root_depth[root] <= 3:
            cands.append((p, n.size))
    out.top_dirs = sorted(cands, key=lambda x: x[1], reverse=True)[:25]
    return out

"""Duplicate finder: size -> partial hash -> full hash."""
from __future__ import annotations

import hashlib
import os
import threading
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Iterable

from .models import FileRec, MB

PARTIAL = 64 * 1024
MAX_FILE = 4 * 1024 * MB


def _partial_hash(rec: FileRec) -> tuple[FileRec, bytes | None]:
    try:
        h = hashlib.blake2b(str(rec.size).encode())
        with open(rec.path, "rb") as f:
            h.update(f.read(PARTIAL))
            if rec.size > PARTIAL * 2:
                f.seek(rec.size - PARTIAL)
                h.update(f.read(PARTIAL))
        return rec, h.digest()
    except OSError:
        return rec, None


def _full_hash(rec: FileRec) -> tuple[FileRec, bytes | None]:
    try:
        h = hashlib.blake2b()
        with open(rec.path, "rb") as f:
            while chunk := f.read(4 * MB):
                h.update(chunk)
        return rec, h.digest()
    except OSError:
        return rec, None


def _regroup(groups: Iterable[list[FileRec]], fn, pool, cancel) -> list[list[FileRec]]:
    todo = [r for g in groups for r in g]
    buckets: dict[tuple, list[FileRec]] = defaultdict(list)
    for rec, digest in pool.map(fn, todo):
        if cancel is not None and cancel.is_set():
            return []
        if digest is not None:
            buckets[(rec.size, digest)].append(rec)
    return [g for g in buckets.values() if len(g) > 1]


def find_duplicates(recs: Iterable[FileRec], cancel: threading.Event | None = None,
                    status: Callable[[str], None] | None = None) -> list[list[FileRec]]:
    by_size: dict[int, list[FileRec]] = defaultdict(list)
    for r in recs:
        if 0 < r.size <= MAX_FILE:
            by_size[r.size].append(r)
    groups = [g for g in by_size.values() if len(g) > 1]
    if not groups:
        return []
    with ThreadPoolExecutor(max_workers=8) as pool:
        if status:
            status(f"Comparing {sum(len(g) for g in groups)} same-size files...")
        groups = _regroup(groups, _partial_hash, pool, cancel)
        if status:
            status(f"Verifying {sum(len(g) for g in groups)} possible duplicates...")
        groups = _regroup(groups, _full_hash, pool, cancel)

    # drop hard links: same underlying file is not a real duplicate
    result = []
    for g in groups:
        unique: list[FileRec] = []
        for r in g:
            if not any(_same_file(r.path, u.path) for u in unique):
                unique.append(r)
        if len(unique) > 1:
            result.append(unique)
    return result


def _same_file(a: str, b: str) -> bool:
    try:
        return os.path.samefile(a, b)
    except OSError:
        return False

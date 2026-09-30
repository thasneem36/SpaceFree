"""Fast multi-threaded disk walker that builds a folder-size tree."""
from __future__ import annotations

import ctypes
import os
import queue
import shutil
import threading
import time
from dataclasses import dataclass
from typing import Callable

from .models import DirNode, FileRec, ScanResult, MB

REPARSE = 0x400
CLOUD_ONLY = 0x1000 | 0x40000 | 0x400000  # OFFLINE | RECALL_ON_OPEN | RECALL_ON_DATA_ACCESS
MIN_TRACK = 1 * MB
SKIP_DIRS = {"$recycle.bin", "system volume information"}

ProgressCb = Callable[[int, int, int, str], None]


@dataclass
class Drive:
    path: str
    total: int
    used: int
    free: int
    fixed: bool


def list_drives() -> list[Drive]:
    if os.name != "nt":
        u = shutil.disk_usage("/")
        return [Drive("/", u.total, u.used, u.free, True)]
    drives: list[Drive] = []
    mask = ctypes.windll.kernel32.GetLogicalDrives()
    for i in range(26):
        if not mask & (1 << i):
            continue
        root = f"{chr(65 + i)}:\\"
        kind = ctypes.windll.kernel32.GetDriveTypeW(root)
        if kind not in (2, 3):  # removable, fixed
            continue
        try:
            u = shutil.disk_usage(root)
        except OSError:
            continue
        drives.append(Drive(root, u.total, u.used, u.free, kind == 3))
    return drives


def scan(roots: list[str], progress: ProgressCb | None = None,
         cancel: threading.Event | None = None, workers: int = 16) -> ScanResult:
    nodes: dict[str, DirNode] = {}
    big: list[FileRec] = []
    lock = threading.Lock()
    stats = {"files": 0, "dirs": 0, "bytes": 0, "errors": 0, "last": 0.0}
    q: queue.Queue[str | None] = queue.Queue()

    for r in roots:
        nodes[r] = DirNode(path=r, name=r, parent=None)
        q.put(r)

    def report(path: str, force: bool = False) -> None:
        now = time.monotonic()
        if progress and (force or now - stats["last"] > 0.1):
            stats["last"] = now
            progress(stats["files"], stats["dirs"], stats["bytes"], path)

    def scan_dir(path: str) -> None:
        node = nodes[path]
        own = nfiles = 0
        kids: list[str] = []
        local_big: list[FileRec] = []
        try:
            with os.scandir(path) as it:
                for e in it:
                    try:
                        st = e.stat(follow_symlinks=False)
                        attrs = getattr(st, "st_file_attributes", 0)
                        if e.is_dir(follow_symlinks=False):
                            if attrs & REPARSE or e.name.lower() in SKIP_DIRS:
                                continue
                            cp = os.path.join(path, e.name)
                            nodes[cp] = DirNode(cp, e.name, path, st.st_mtime)
                            kids.append(cp)
                            q.put(cp)
                        elif e.is_symlink():
                            continue
                        else:
                            nfiles += 1
                            if attrs & CLOUD_ONLY:
                                continue  # online-only file, takes no disk space
                            size = st.st_size
                            own += size
                            if size >= MIN_TRACK:
                                local_big.append(FileRec(os.path.join(path, e.name), size,
                                                         st.st_mtime, st.st_atime))
                    except OSError:
                        stats["errors"] += 1
        except OSError:
            stats["errors"] += 1
        node.own_size, node.files, node.children = own, nfiles, kids
        with lock:
            big.extend(local_big)
            stats["files"] += nfiles
            stats["dirs"] += 1
            stats["bytes"] += own
        report(path)

    def worker() -> None:
        while True:
            path = q.get()
            try:
                if path is None:
                    return
                if cancel is None or not cancel.is_set():
                    scan_dir(path)
            finally:
                q.task_done()

    threads = [threading.Thread(target=worker, daemon=True) for _ in range(workers)]
    for t in threads:
        t.start()
    q.join()
    for _ in threads:
        q.put(None)
    for t in threads:
        t.join()
    report("", force=True)

    for n in nodes.values():
        n.size = n.own_size
    for n in sorted(nodes.values(), key=lambda x: len(x.path), reverse=True):
        if n.parent and n.parent in nodes:
            nodes[n.parent].size += n.size
            nodes[n.parent].files += n.files

    return ScanResult(nodes, list(roots), big, stats["files"], stats["errors"],
                      bool(cancel and cancel.is_set()))

"""Fast multi-threaded disk walker that builds a folder-size tree, with live state."""
from __future__ import annotations

import ctypes
import os
import queue
import shutil
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Protocol

from . import safety
from .filetypes import MEDIA_TYPES, OTHER, type_of
from .models import DirNode, FileRec, ScanResult, MB

REPARSE = 0x400
CLOUD_ONLY = 0x1000 | 0x40000 | 0x400000  # OFFLINE | RECALL_ON_OPEN | RECALL_ON_DATA_ACCESS
MIN_TRACK = 1 * MB
MIN_MEDIA = 20 * 1024  # ignore tiny icons / sound effects
SKIP_DIRS = {"$recycle.bin", "system volume information"}
MEDIA_SKIP_PARTS = ("\\appdata\\", "\\node_modules\\", "\\.git\\", "\\site-packages\\", "\\programdata\\")
SHALLOW_DEPTH = 3

ProgressCb = Callable[[int, int, int, str], None]


class Hooks(Protocol):
    def on_big_file(self, rec: FileRec) -> None: ...
    def on_dir_done(self, node: DirNode) -> None: ...


@dataclass
class ScanState:
    """Shared, live-readable state. The UI reads it while the scan threads write it."""
    nodes: dict[str, DirNode] = field(default_factory=dict)
    big_files: list[FileRec] = field(default_factory=list)
    media: list[FileRec] = field(default_factory=list)
    shallow: list[str] = field(default_factory=list)  # folders near the root, for "biggest folders"
    type_stats: dict[str, list[int]] = field(default_factory=dict)  # type -> [count, bytes]
    files: int = 0
    dirs: int = 0
    bytes: int = 0
    errors: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock)

    def type_snapshot(self) -> dict[str, tuple[int, int]]:
        with self.lock:
            return {k: (v[0], v[1]) for k, v in self.type_stats.items()}


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
         cancel: threading.Event | None = None, workers: int = 16,
         state: ScanState | None = None, hooks: Hooks | None = None) -> ScanResult:
    st_ = state or ScanState()
    nodes, lock = st_.nodes, st_.lock
    pending: dict[str, int] = {}
    last = [0.0]
    q: queue.Queue[str | None] = queue.Queue()
    root_depth = {r: r.rstrip(os.sep).count(os.sep) for r in roots}

    for r in roots:
        nodes[r] = DirNode(path=r, name=r, parent=None)
        pending[r] = 1
        st_.shallow.append(r)
        q.put(r)

    def report(path: str, force: bool = False) -> None:
        now = time.monotonic()
        if progress and (force or now - last[0] > 0.1):
            last[0] = now
            progress(st_.files, st_.dirs, st_.bytes, path)

    def finish_chain(path: str) -> None:
        """Mark `path` complete, and any ancestors whose subtree is now complete."""
        done: list[DirNode] = []
        with lock:
            cur: str | None = path
            while cur is not None:
                pending[cur] -= 1
                if pending[cur] > 0:
                    break
                done.append(nodes[cur])
                del pending[cur]
                cur = nodes[cur].parent
        if hooks:
            for n in done:
                hooks.on_dir_done(n)

    def scan_dir(path: str, root: str) -> None:
        node = nodes[path]
        own = nfiles = 0
        kids: list[str] = []
        local_big: list[FileRec] = []
        local_media: list[FileRec] = []
        local_types: dict[str, list[int]] = {}
        media_ok = not safety.is_protected(path) and not any(
            p in (path.lower() + os.sep) for p in MEDIA_SKIP_PARTS)
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
                        elif e.is_symlink():
                            continue
                        else:
                            nfiles += 1
                            if attrs & CLOUD_ONLY:
                                continue  # online-only file, takes no disk space
                            size = st.st_size
                            own += size
                            ext = os.path.splitext(e.name)[1].lower()
                            ftype = type_of(ext)
                            t = local_types.setdefault(ftype, [0, 0])
                            t[0] += 1
                            t[1] += size
                            if size >= MIN_TRACK:
                                local_big.append(FileRec(os.path.join(path, e.name), size,
                                                         st.st_mtime, st.st_atime))
                            if media_ok and ftype in MEDIA_TYPES and size >= MIN_MEDIA:
                                local_media.append(FileRec(os.path.join(path, e.name), size,
                                                           st.st_mtime, st.st_atime))
                    except OSError:
                        st_.errors += 1
        except OSError:
            st_.errors += 1

        node.own_size, node.files, node.children = own, nfiles, kids
        with lock:
            p: str | None = path
            while p is not None:  # live-propagate size to every ancestor
                n = nodes[p]
                n.size += own
                n.files += nfiles
                p = n.parent
            st_.big_files.extend(local_big)
            st_.media.extend(local_media)
            st_.files += nfiles
            st_.dirs += 1
            st_.bytes += own
            for k, (c, b) in local_types.items():
                t = st_.type_stats.setdefault(k, [0, 0])
                t[0] += c
                t[1] += b
            for cp in kids:
                pending[cp] = 1
                if cp.count(os.sep) - root_depth[root] <= SHALLOW_DEPTH:
                    st_.shallow.append(cp)
            pending[path] += len(kids)  # before any kid can finish
        if hooks:
            for rec in local_big:
                hooks.on_big_file(rec)
        for cp in kids:
            q.put(cp)
        finish_chain(path)
        report(path)

    def root_of(path: str) -> str:
        for r in roots:
            if path.startswith(r):
                return r
        return roots[0]

    def worker() -> None:
        while True:
            path = q.get()
            try:
                if path is None:
                    return
                if cancel is None or not cancel.is_set():
                    scan_dir(path, root_of(path))
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

    return ScanResult(nodes, list(roots), st_.big_files, st_.files, st_.errors,
                      bool(cancel and cancel.is_set()), st_.media, st_.type_snapshot())

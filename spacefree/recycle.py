"""Windows Recycle Bin size / emptying via the shell API."""
from __future__ import annotations

import ctypes
import os


class _RBInfo(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_ulong), ("size", ctypes.c_int64), ("items", ctypes.c_int64)]


def recycle_bin_size() -> tuple[int, int]:
    """Return (bytes, item_count) across all drives; (0, 0) if unavailable."""
    if os.name != "nt":
        return 0, 0
    info = _RBInfo()
    info.cbSize = ctypes.sizeof(_RBInfo)
    try:
        if ctypes.windll.shell32.SHQueryRecycleBinW(None, ctypes.byref(info)) == 0:
            return int(info.size), int(info.items)
    except OSError:
        pass
    return 0, 0


def empty_recycle_bin() -> bool:
    """Permanently empty the Recycle Bin (no shell prompt). Caller must confirm first."""
    if os.name != "nt":
        return False
    flags = 0x1 | 0x2 | 0x4  # NOCONFIRMATION | NOPROGRESSUI | NOSOUND
    return ctypes.windll.shell32.SHEmptyRecycleBinW(None, None, flags) in (0, -2147418113)

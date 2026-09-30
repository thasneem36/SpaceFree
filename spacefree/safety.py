"""Hard safety rules. Anything protected here can never be deleted by the app."""
from __future__ import annotations

import os
import re

SEP = os.sep


def norm(path: str) -> str:
    return os.path.normcase(os.path.normpath(path))


_WIN = os.environ.get("SystemRoot", r"C:\Windows")
_PF = os.environ.get("ProgramFiles", r"C:\Program Files")
_PF86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
_PD = os.environ.get("ProgramData", r"C:\ProgramData")

PROTECTED_ROOTS = [norm(p) for p in (_WIN, _PF, _PF86, _PD)]

# Folders that stay deletable even though they live inside a protected root.
ALLOW_INSIDE = [
    norm(os.path.join(_WIN, "Temp")),
    norm(os.path.join(_WIN, "SoftwareDistribution", "Download")),
]

# Names directly under a drive root that are never touched (any drive).
ROOT_SYSTEM = {
    "windows", "program files", "program files (x86)", "programdata",
    "system volume information", "$recycle.bin", "recovery", "boot", "efi",
    "$windows.~bt", "$windows.~ws", "config.msi", "documents and settings",
    "hiberfil.sys", "pagefile.sys", "swapfile.sys", "bootmgr", "bootnxt",
    "windows.old",
}

PERSONAL_RE = re.compile(
    r"[\\/]users[\\/][^\\/]+[\\/](documents|pictures|desktop|videos|music|onedrive[^\\/]*)([\\/]|$)"
)
PROFILE_CRITICAL_RE = re.compile(
    r"[\\/]users([\\/][^\\/]+([\\/](appdata([\\/](local|roaming|locallow))?|documents|pictures|"
    r"desktop|videos|music|downloads|onedrive[^\\/]*))?)?$"
)


def _under(p: str, root: str) -> bool:
    return p == root or p.startswith(root + SEP)


def is_protected(path: str) -> bool:
    p = norm(path)
    for allowed in ALLOW_INSIDE:
        if _under(p, allowed):
            return False
    for root in PROTECTED_ROOTS:
        if _under(p, root):
            return True
    _, rest = os.path.splitdrive(p)
    parts = [x for x in rest.split(SEP) if x]
    if not parts:
        return True  # a drive root
    return parts[0] in ROOT_SYSTEM


def worth_descending(path: str) -> bool:
    """True if a protected folder still contains an allowed junk location."""
    p = norm(path)
    if not is_protected(p):
        return True
    return any(a.startswith(p + SEP) for a in ALLOW_INSIDE)


def is_personal(path: str) -> bool:
    return bool(PERSONAL_RE.search(norm(path)))


def is_critical_dir(path: str) -> bool:
    return bool(PROFILE_CRITICAL_RE.search(norm(path)))


def can_delete(path: str) -> tuple[bool, str]:
    if not os.path.lexists(path):
        return False, "Item no longer exists"
    if is_protected(path):
        return False, "Protected system location"
    if is_critical_dir(path):
        return False, "Core user folder"
    return True, ""

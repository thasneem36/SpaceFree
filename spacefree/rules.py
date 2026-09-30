"""Rule-based classifier: decides what is Bad (safe to delete), Review, Good or Important."""
from __future__ import annotations

import os
import time

from . import safety
from .models import BAD, GOOD, IMPORTANT, REVIEW, DirNode, FileRec, Finding, MB, GB

MIN_FINDING = 1 * MB
OLD_INSTALLER_DAYS = 30
OLD_DOWNLOAD_DAYS = 180
STALE_NODE_MODULES_DAYS = 180
LARGE_FILE = 500 * MB
LARGE_STALE_DAYS = 365

SEP = os.sep

# (normalized path suffix, label, category, reason, deletable)
PATH_RULES = [
    (r"\appdata\local\temp", BAD, "Temp files", "Temporary files left behind by apps. Safe to remove.", True),
    (r"\windows\temp", BAD, "Temp files", "Windows temporary files. Safe to remove.", True),
    (r"\windows\softwaredistribution\download", BAD, "Windows Update cache",
     "Already-installed Windows Update downloads.", True),
    (r"\appdata\local\crashdumps", BAD, "Crash dumps", "Memory dumps from crashed programs.", True),
    (r"\appdata\local\microsoft\windows\inetcache", BAD, "Browser cache",
     "Internet Explorer/Edge legacy cache.", True),
    (r"\appdata\local\microsoft\windows\wer", BAD, "Error reports", "Windows error report files.", True),
    (r"\appdata\local\pip\cache", BAD, "Package cache", "pip download cache; re-downloaded when needed.", True),
    (r"\appdata\local\npm-cache", BAD, "Package cache", "npm download cache; re-downloaded when needed.", True),
    (r"\.gradle\caches", BAD, "Package cache", "Gradle build cache; rebuilt when needed.", True),
    (r"\appdata\local\d3dscache", BAD, "Shader cache", "GPU shader cache; rebuilt automatically.", True),
    (r"\appdata\local\nvidia\dxcache", BAD, "Shader cache", "GPU shader cache; rebuilt automatically.", True),
    (r"\windows.old", BAD, "Old Windows install",
     "Previous Windows version. Remove via Settings > System > Storage > Temporary files.", False),
]

DEV_CACHE_NAMES = {
    "__pycache__": "Python bytecode cache; regenerated automatically.",
    ".pytest_cache": "Pytest cache; regenerated automatically.",
    ".mypy_cache": "Mypy cache; regenerated automatically.",
    ".ruff_cache": "Ruff cache; regenerated automatically.",
    ".tox": "Tox environments; recreated on demand.",
}
APP_CACHE_NAMES = {"cache", "code cache", "gpucache", "cache_data", "shadercache",
                   "dxcache", "glcache", "cacheddata", "media cache"}

TEMP_EXT = {".tmp", ".temp", ".dmp", ".mdmp", ".chk", ".etl", ".gid", ".old"}
INSTALLER_EXT = {".exe", ".msi", ".msix", ".iso", ".img", ".dmg", ".zip", ".rar", ".7z"}
VM_EXT = {".vhd", ".vhdx", ".vmdk", ".vdi", ".ova", ".qcow2"}
SYSTEM_FILES = {
    "hiberfil.sys": "Hibernation file. Reclaim with 'powercfg /h off' (admin) if you don't use hibernate.",
    "pagefile.sys": "Windows virtual-memory file. Manage in System > Advanced > Performance settings.",
    "swapfile.sys": "Windows app swap file. Managed by Windows.",
}


def age_days(mtime: float, atime: float = 0.0, now: float | None = None) -> int:
    now = now or time.time()
    return max(0, int((now - max(mtime, atime)) / 86400))


def classify_dir(path: str, node: DirNode, now: float | None = None) -> Finding | None:
    """Return a Finding if this whole folder is junk, else None."""
    p = safety.norm(path)
    name = node.name.lower()
    age = age_days(node.mtime, 0.0, now)

    for suffix, label, cat, reason, deletable in PATH_RULES:
        if p.endswith(suffix):
            return Finding(path, node.size, True, label, cat, reason, age, deletable)

    if name in DEV_CACHE_NAMES:
        return Finding(path, node.size, True, BAD, "Dev cache", DEV_CACHE_NAMES[name], age)
    if name == "node_modules":
        if age > STALE_NODE_MODULES_DAYS:
            return Finding(path, node.size, True, BAD, "node_modules",
                           f"Node.js dependencies of a project untouched for {age} days. Restore with 'npm install'.",
                           age)
        return Finding(path, node.size, True, REVIEW, "node_modules",
                       "Node.js dependencies. Restore with 'npm install' if you no longer need this project.", age)
    if name in APP_CACHE_NAMES:
        in_app_data = r"\appdata" + SEP in p or r"\programdata" + SEP in p
        if in_app_data:
            return Finding(path, node.size, True, BAD, "App cache",
                           "Cache of an application; rebuilt automatically.", age)
        return Finding(path, node.size, True, REVIEW, "App cache", "Looks like a cache folder.", age)
    return None


def classify_file(rec: FileRec, now: float | None = None) -> Finding | None:
    name = os.path.basename(rec.path)
    lname = name.lower()
    ext = os.path.splitext(lname)[1]
    p = safety.norm(rec.path)
    age = age_days(rec.mtime, rec.atime, now)
    size = rec.size

    if lname in SYSTEM_FILES:
        _, rest = os.path.splitdrive(p)
        if rest.count(SEP) == 1:  # directly on the drive root
            return Finding(rec.path, size, False, REVIEW, "System file", SYSTEM_FILES[lname], age, False)
    if safety.is_protected(rec.path) or size < MIN_FINDING:
        return None

    in_downloads = SEP + "downloads" + SEP in p
    f: Finding | None = None
    if ext in TEMP_EXT:
        f = Finding(rec.path, size, False, BAD, "Temp / dump file",
                    "Temporary or crash-dump file.", age)
    elif in_downloads and ext in INSTALLER_EXT and age > OLD_INSTALLER_DAYS:
        f = Finding(rec.path, size, False, BAD, "Old installer / archive",
                    f"Installer or archive in Downloads, untouched for {age} days.", age)
    elif in_downloads and age > OLD_DOWNLOAD_DAYS and size >= 50 * MB:
        f = Finding(rec.path, size, False, REVIEW, "Old download",
                    f"Large download not touched for {age} days.", age)
    elif ext in VM_EXT and size >= 500 * MB:
        f = Finding(rec.path, size, False, REVIEW, "Virtual disk",
                    "Virtual machine disk image. Delete only if the VM is no longer used.", age)
    elif size >= LARGE_FILE and age > LARGE_STALE_DAYS:
        f = Finding(rec.path, size, False, REVIEW, "Large unused file",
                    f"Large file not opened or changed for {age} days.", age)
    elif ext in (".log", ".bak") and size >= 50 * MB:
        f = Finding(rec.path, size, False, REVIEW, "Large log / backup",
                    "Large log or backup file.", age)

    if f and f.label == BAD and safety.is_personal(rec.path):
        f.label = REVIEW  # never call personal files "safe" automatically
    return f


def label_for_dir(path: str, flagged: set[str]) -> str:
    """Label used by the folder-tree view."""
    if path in flagged:
        return BAD
    if safety.is_protected(path) or safety.is_personal(path):
        return IMPORTANT
    return GOOD

from __future__ import annotations

from dataclasses import dataclass, field

IMPORTANT = "Important"
GOOD = "Good"
BAD = "Bad"
REVIEW = "Review"

MB = 1024 * 1024
GB = 1024 * MB


@dataclass(slots=True)
class DirNode:
    path: str
    name: str
    parent: str | None
    mtime: float = 0.0
    own_size: int = 0
    size: int = 0
    files: int = 0
    children: list[str] = field(default_factory=list)


@dataclass(slots=True)
class FileRec:
    path: str
    size: int
    mtime: float
    atime: float


@dataclass(slots=True)
class Finding:
    path: str
    size: int
    is_dir: bool
    label: str
    category: str
    reason: str
    age_days: int = 0
    deletable: bool = True
    group: str = ""


@dataclass
class ScanResult:
    nodes: dict[str, DirNode]
    roots: list[str]
    big_files: list[FileRec]
    files_seen: int = 0
    errors: int = 0
    cancelled: bool = False
    media: list[FileRec] = field(default_factory=list)
    type_stats: dict[str, tuple[int, int]] = field(default_factory=dict)

    @property
    def total_size(self) -> int:
        return sum(self.nodes[r].size for r in self.roots if r in self.nodes)


def fmt_size(n: float) -> str:
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"

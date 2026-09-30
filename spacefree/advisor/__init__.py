"""Advisor: a small System One style model that turns scan output into simple decisions."""
from .decide import DELETE, EDUCATIONAL, KEEP, REVIEW, VERDICTS, Advice, advise_all, advise_one
from .features import Item

__all__ = ["DELETE", "EDUCATIONAL", "KEEP", "REVIEW", "VERDICTS", "Advice", "Item",
           "advise_all", "advise_one", "from_finding", "from_media"]


def from_finding(f) -> Item:
    return Item(f.path, f.size, f.is_dir, f.category, f.label, f.age_days, f.deletable, f.reason, f.group)


def from_media(rec, now: float | None = None) -> Item:
    import time
    now = now or time.time()
    age = max(0, int((now - max(rec.mtime, rec.atime)) / 86400))
    return Item(rec.path, rec.size, False, "Media", "Good", age)

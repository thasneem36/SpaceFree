"""Composes the typed answers into one simple verdict. All policy lives here, in code."""
from __future__ import annotations

from dataclasses import dataclass

from .features import Features, Item, extract
from .model import is_educational, is_irreplaceable, is_recreatable, kind_of, staleness
from .questions import Choice, Noul, Score

DELETE = "Delete"
REVIEW = "Review"
KEEP = "Keep"
EDUCATIONAL = "Educational"
VERDICTS = (DELETE, REVIEW, KEEP, EDUCATIONAL)

EDU_MIN = 0.6
DELETE_RECREATABLE_MIN = 0.8
DELETE_IRREPLACEABLE_MAX = 0.3
KEEP_IRREPLACEABLE_MIN = 0.6


@dataclass(frozen=True)
class Advice:
    path: str
    size: int
    verdict: str
    reason: str
    confidence: float
    kind: Choice
    educational: Noul
    recreatable: Noul
    irreplaceable: Noul
    staleness: Score


def _short(text: str) -> str:
    return text.strip().rstrip(".")


def advise_one(item: Item) -> Advice:
    f: Features = extract(item)
    edu, rec, irr = is_educational(f), is_recreatable(f), is_irreplaceable(f)
    kind, stale = kind_of(f), staleness(f)

    if not item.deletable:
        verdict, reason, conf = REVIEW, _short(item.reason) or "Manual action needed", 0.5
    elif f.protected:
        verdict, reason, conf = KEEP, "System or program file", 0.99
    elif edu.p >= EDU_MIN and f.duplicate:
        verdict, conf = REVIEW, 0.5
        reason = f"Identical copy inside learning material ({', '.join(f.edu_hits[:2])}) - keep one"
    elif edu.p >= EDU_MIN:
        verdict, conf = EDUCATIONAL, edu.p
        reason = f"Learning material ({', '.join(f.edu_hits[:2])}) - keep"
    elif rec.p >= DELETE_RECREATABLE_MIN and irr.p <= DELETE_IRREPLACEABLE_MAX:
        verdict, conf = DELETE, min(rec.p, 1 - irr.p)
        reason = _short(item.reason) or "Can be recreated"
    elif irr.p >= KEEP_IRREPLACEABLE_MIN and rec.p < 0.6:
        verdict, conf = KEEP, irr.p
        what = {"personal_media": "personal media", "documents": "document"}.get(kind.choice, "personal file")
        reason = f"Looks like a {what} you likely want - no need to delete"
    else:
        verdict, conf = REVIEW, 0.5
        reason = _short(item.reason) or "Not sure - check it yourself"
        if stale.score >= 3 and item.size > 0:
            reason += " (untouched for a long time)"

    return Advice(item.path, item.size, verdict, reason, conf, kind, edu, rec, irr, stale)


def advise_all(items: list[Item]) -> dict[str, Advice]:
    return {i.path: advise_one(i) for i in items}

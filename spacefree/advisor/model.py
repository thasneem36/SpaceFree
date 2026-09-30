"""The five questions. Each is a small, local scorer returning a typed answer."""
from __future__ import annotations

import math

from ..filetypes import CODE, DOCS, IMAGE, AUDIO, VIDEO
from ..models import BAD
from .features import MEDIA, Features
from .questions import Choice, Noul, Score, concentration, sigmoid, softmax

KINDS = ("educational", "project", "personal_media", "documents",
         "installer_archive", "cache_temp", "system_app", "other")

# staleness levels and their representative age in days
STALE_LEVELS = (7, 90, 270, 540, 1100)
STALE_NAMES = ("this week", "this season", "this year", "1-2 years", "2+ years")


def is_educational(f: Features) -> Noul:
    """Is this learning material (course, lecture, book, research)?"""
    z = -2.2
    if f.edu_hits:
        z += 2.8 + 1.2 * (min(len(f.edu_hits), 3) - 1)
    if f.ext in (".pdf", ".epub", ".srt", ".vtt", ".pptx", ".ppt"):
        z += 0.5
    if f.cache_like or f.protected or f.recreatable_cat:
        z -= 4.0
    return Noul(sigmoid(z))


def is_recreatable(f: Features) -> Noul:
    """Can it be regenerated or re-downloaded without losing anything?"""
    z = -2.5
    if f.recreatable_cat:
        z += 5.0 if f.item.label == BAD else 3.0
    if f.duplicate:
        z += 5.2 if f.item.label == BAD else 3.5  # an identical copy exists elsewhere
    if f.cache_like:
        z += 1.5
    if f.in_downloads and f.ext in (".exe", ".msi", ".msix", ".iso"):
        z += 2.0
    if f.personal and not f.duplicate:
        z -= 3.0
    return Noul(sigmoid(z))


def is_irreplaceable(f: Features) -> Noul:
    """Would losing this hurt (personal files, documents, your own work)?"""
    z = -1.0
    if f.personal:
        z += 2.5
    if f.ftype in MEDIA and not f.recreatable_cat:
        z += 1.8
    if f.ftype == DOCS:
        z += 2.0
    if f.ftype == CODE and not f.recreatable_cat:
        z += 1.0
    if f.in_desktop:
        z += 0.8
    if f.item.age_days < 30:
        z += 1.2
    if f.edu_hits:
        z += 1.0
    if f.duplicate:
        z -= 1.5
    if f.recreatable_cat:
        z -= 4.0
    if f.cache_like:
        z -= 2.0
    return Noul(sigmoid(z))


def staleness(f: Features) -> Score:
    """How long untouched: soft-assigned to the five levels by log-age distance."""
    la = math.log(f.item.age_days + 1)
    weights = [math.exp(-((la - math.log(c + 1)) ** 2) / (2 * 0.6 ** 2)) for c in STALE_LEVELS]
    total = sum(weights) or 1.0
    probs = [w / total for w in weights]
    return Score(sum(i * p for i, p in enumerate(probs)), probs, max(probs))


def kind_of(f: Features) -> Choice:
    """What sort of thing is this?"""
    z = {k: 0.0 for k in KINDS}
    z["other"] = 0.8
    if f.edu_hits:
        z["educational"] = 3.0 * len(f.edu_hits) ** 0.5
    if f.recreatable_cat and f.item.category != "Old installer / archive" or f.cache_like:
        z["cache_temp"] = 4.0
    if f.item.category == "Old installer / archive" or (f.in_downloads and f.ext in (".exe", ".msi", ".iso")):
        z["installer_archive"] = 3.0
    if f.ftype in MEDIA:
        z["personal_media"] = 2.5
    if f.ftype == DOCS:
        z["documents"] = 2.5
    if f.ftype == CODE or f.item.category in ("node_modules", "Dev cache"):
        z["project"] = 2.0
    if f.protected or f.item.category in ("System file", "Old Windows install"):
        z["system_app"] = 3.0
    probs = softmax(z)
    best = max(probs, key=probs.get)
    return Choice(best, probs, concentration(list(probs.values())))

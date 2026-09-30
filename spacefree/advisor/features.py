"""Turns a path plus its scan facts into the evidence the questions look at."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

from .. import safety
from ..filetypes import CODE, DOCS, IMAGE, AUDIO, VIDEO, type_of

TOKEN_RE = re.compile(r"[a-z0-9]+")

EDU_STEMS = (
    "cours", "tutori", "lectur", "lesson", "udemy", "coursera", "skillshare", "pluralsight",
    "masterclass", "bootcamp", "curricul", "syllab", "textbook", "ebook", "thesis", "semester",
    "universit", "college", "academy", "training", "learn", "exercis", "assignm", "homework",
    "study", "studies", "research", "lynda", "edx", "certif",
)
EDU_EXT = {".pdf", ".epub", ".srt", ".vtt", ".pptx", ".ppt"}
CACHE_TOKENS = {"cache", "cached", "temp", "tmp", "temporary", "crashdumps", "logs"}
RECREATABLE = {
    "Temp files", "Windows Update cache", "Crash dumps", "Browser cache", "Error reports",
    "Package cache", "Shader cache", "Dev cache", "App cache", "Temp / dump file",
    "node_modules", "Old installer / archive",
}
MEDIA = {IMAGE, AUDIO, VIDEO}


@dataclass
class Item:
    """What the advisor needs to know about one file or folder."""
    path: str
    size: int
    is_dir: bool = False
    category: str = ""
    label: str = ""
    age_days: int = 0
    deletable: bool = True
    reason: str = ""
    group: str = ""


@dataclass
class Features:
    item: Item
    name: str
    ext: str
    ftype: str
    edu_hits: list[str] = field(default_factory=list)
    cache_like: bool = False
    personal: bool = False
    in_desktop: bool = False
    in_downloads: bool = False
    protected: bool = False
    recreatable_cat: bool = False
    duplicate: bool = False


def extract(item: Item) -> Features:
    p = safety.norm(item.path)
    name = os.path.basename(item.path)
    ext = "" if item.is_dir else os.path.splitext(name)[1].lower()
    tokens = TOKEN_RE.findall(p)
    hits: list[str] = []  # the actual words found (e.g. 'course'), one per matching stem
    for stem in EDU_STEMS:
        word = next((t for t in tokens if t.startswith(stem)), None)
        if word and word not in hits:
            hits.append(word)
    sep = os.sep
    return Features(
        item=item, name=name, ext=ext, ftype=type_of(ext),
        edu_hits=hits,
        cache_like=any(t in CACHE_TOKENS for t in tokens),
        personal=safety.is_personal(item.path),
        in_desktop=f"{sep}desktop{sep}" in p + sep,
        in_downloads=f"{sep}downloads{sep}" in p + sep,
        protected=safety.is_protected(item.path) and item.category != "Old Windows install",
        recreatable_cat=item.category in RECREATABLE,
        duplicate=item.category == "Duplicate",
    )

"""Deletion: only ever moves items to the Recycle Bin, after re-checking safety."""
from __future__ import annotations

import os
from typing import Callable

from send2trash import send2trash

from . import safety


def move_to_trash(paths: list[str],
                  progress: Callable[[int, int, str], None] | None = None
                  ) -> tuple[list[str], list[tuple[str, str]]]:
    ok: list[str] = []
    failed: list[tuple[str, str]] = []
    for i, path in enumerate(paths, 1):
        if progress:
            progress(i, len(paths), path)
        allowed, why = safety.can_delete(path)
        if not allowed:
            failed.append((path, why))
            continue
        try:
            send2trash(os.path.normpath(path))
            ok.append(path)
        except Exception as e:  # noqa: BLE001 - report any failure to the user
            failed.append((path, str(e)))
    return ok, failed

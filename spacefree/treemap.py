"""Squarified treemap layout (pure function, UI independent)."""
from __future__ import annotations

Rect = tuple[float, float, float, float]


def _worst(row: list[float], side: float) -> float:
    s = sum(row)
    if s == 0 or side == 0:
        return float("inf")
    return max(max(side * side * r / (s * s), s * s / (side * side * r)) for r in row)


def squarify(values: list[float], x: float, y: float, w: float, h: float) -> list[Rect]:
    """Lay out `values` (any order; returned rects follow the input order) inside the box."""
    n = len(values)
    if n == 0 or w <= 0 or h <= 0:
        return [(x, y, 0.0, 0.0)] * n
    total = float(sum(values))
    if total <= 0:
        return [(x, y, 0.0, 0.0)] * n
    order = sorted(range(n), key=lambda i: values[i], reverse=True)
    areas = [values[i] * w * h / total for i in order]
    rects: list[Rect] = [(x, y, 0.0, 0.0)] * n
    idx = 0
    cx, cy, cw, ch = x, y, w, h
    while idx < n:
        side = min(cw, ch)
        row = [areas[idx]]
        j = idx + 1
        while j < n and _worst(row + [areas[j]], side) <= _worst(row, side):
            row.append(areas[j])
            j += 1
        s = sum(row)
        if cw >= ch:  # lay the row as a column on the left
            col_w = s / ch if ch else 0
            ry = cy
            for k, a in enumerate(row):
                rh = a / col_w if col_w else 0
                rects[order[idx + k]] = (cx, ry, col_w, rh)
                ry += rh
            cx += col_w
            cw -= col_w
        else:  # lay the row along the top
            row_h = s / cw if cw else 0
            rx = cx
            for k, a in enumerate(row):
                rw = a / row_h if row_h else 0
                rects[order[idx + k]] = (rx, cy, rw, row_h)
                rx += rw
            cy += row_h
            ch -= row_h
        idx = j
    return rects

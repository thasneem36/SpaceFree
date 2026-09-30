from __future__ import annotations

from PyQt6.QtCore import QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import QToolTip, QWidget

from ..analysis import Analysis
from ..models import fmt_size
from ..rules import label_for_dir
from ..treemap import squarify
from .theme import LABEL_COLORS

MAX_TILES = 60


class TreemapWidget(QWidget):
    """Size treemap of the current folder. Double-click drills in, right-click goes up."""

    pathChanged = pyqtSignal(str)

    def __init__(self) -> None:
        super().__init__()
        self.analysis: Analysis | None = None
        self.current: str | None = None
        self._tiles: list[tuple[QRectF, str, int]] = []
        self.setMouseTracking(True)
        self.setMinimumHeight(300)

    def set_analysis(self, analysis: Analysis) -> None:
        self.analysis = analysis
        roots = analysis.scan.roots
        self.current = None if len(roots) != 1 else roots[0]
        self.pathChanged.emit(self.current or "All drives")
        self.update()

    def _children(self) -> list[tuple[str, int]]:
        if not self.analysis:
            return []
        nodes = self.analysis.scan.nodes
        if self.current is None:
            items = [(r, nodes[r].size) for r in self.analysis.scan.roots if r in nodes]
        else:
            node = nodes[self.current]
            items = [(c, nodes[c].size) for c in node.children if c in nodes]
            if node.own_size:
                items.append((self.current + "\0files", node.own_size))
        items = [i for i in items if i[1] > 0]
        items.sort(key=lambda i: i[1], reverse=True)
        return items[:MAX_TILES]

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#0d1117"))
        self._tiles = []
        items = self._children()
        if not items:
            p.setPen(QColor("#8b949e"))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Run a scan to see the size map")
            return
        rects = squarify([s for _, s in items], 0, 0, self.width(), self.height())
        flagged = self.analysis.flagged_dirs if self.analysis else set()
        nodes = self.analysis.scan.nodes
        font = QFont(self.font())
        for (path, size), (x, y, w, h) in zip(items, rects):
            r = QRectF(x, y, w, h).adjusted(1, 1, -1, -1)
            is_files = path.endswith("\0files")
            real = path[:-6] if is_files else path
            color = QColor("#30363d") if is_files else QColor(LABEL_COLORS[label_for_dir(real, flagged)])
            color.setAlpha(150)
            p.fillRect(r, color)
            p.setPen(QPen(QColor("#0d1117"), 1))
            p.drawRect(r)
            if r.width() > 60 and r.height() > 32:
                name = "(files here)" if is_files else nodes[real].name
                p.setPen(QColor("#ffffff"))
                font.setBold(True)
                p.setFont(font)
                p.drawText(r.adjusted(6, 4, -4, -4), Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap,
                           f"{name}\n{fmt_size(size)}")
            self._tiles.append((r, path, size))

    def _tile_at(self, pos) -> tuple[QRectF, str, int] | None:
        for t in self._tiles:
            if t[0].contains(pos.x(), pos.y()):
                return t
        return None

    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        t = self._tile_at(e.position())
        if t:
            QToolTip.showText(e.globalPosition().toPoint(), f"{t[1].replace(chr(0), ' ')}\n{fmt_size(t[2])}", self)

    def mouseDoubleClickEvent(self, e) -> None:  # noqa: N802
        t = self._tile_at(e.position())
        if not t or t[1].endswith("\0files") or not self.analysis:
            return
        if self.analysis.scan.nodes[t[1]].children:
            self.current = t[1]
            self.pathChanged.emit(self.current)
            self.update()

    def mousePressEvent(self, e) -> None:  # noqa: N802
        if e.button() == Qt.MouseButton.RightButton:
            self.go_up()

    def go_up(self) -> None:
        if not self.analysis or self.current is None:
            return
        parent = self.analysis.scan.nodes[self.current].parent
        if parent is None and len(self.analysis.scan.roots) > 1:
            self.current = None
        elif parent is not None:
            self.current = parent
        self.pathChanged.emit(self.current or "All drives")
        self.update()

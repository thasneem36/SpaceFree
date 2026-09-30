"""Advisor tab: the whole scan boiled down to Delete / Review / Keep / Educational."""
from __future__ import annotations

import os
from typing import Callable

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QBrush
from PyQt6.QtWidgets import (
    QGroupBox, QHBoxLayout, QLabel, QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from ..advisor import DELETE, EDUCATIONAL, KEEP, REVIEW, VERDICTS, Advice
from ..models import fmt_size
from .theme import VERDICT_COLORS
from .util import open_in_explorer

PER_GROUP = 150

TITLES = {
    DELETE: "Delete these - safe, can be recreated",
    REVIEW: "Review these - not sure, you decide",
    KEEP: "Keep - good, no need to delete",
    EDUCATIONAL: "Keep - educational material",
}


class AdvisorTab(QWidget):
    def __init__(self, trash_cb: Callable[[list[tuple[str, int, str]]], None]) -> None:
        super().__init__()
        self._trash_cb = trash_cb
        self.advice: dict[str, Advice] = {}
        v = QVBoxLayout(self)

        intro = QLabel("The Advisor reads every finding and media file and gives one simple answer. "
                       "Nothing is deleted until you confirm.")
        intro.setObjectName("muted")
        v.addWidget(intro)

        row = QHBoxLayout()
        self.cards: dict[str, QLabel] = {}
        for verdict in VERDICTS:
            box = QGroupBox(verdict)
            lay = QVBoxLayout(box)
            big = QLabel("-")
            big.setObjectName("big")
            big.setStyleSheet(f"color: {VERDICT_COLORS[verdict].name()};")
            small = QLabel("")
            small.setObjectName("muted")
            lay.addWidget(big)
            lay.addWidget(small)
            self.cards[verdict] = big
            self.cards[verdict + "_n"] = small
            row.addWidget(box)
        v.addLayout(row)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(4)
        self.tree.setHeaderLabels(["Item", "Size", "Why", "Sure"])
        self.tree.setColumnWidth(0, 480)
        self.tree.setColumnWidth(1, 90)
        self.tree.setColumnWidth(2, 420)
        self.tree.itemDoubleClicked.connect(lambda it, _c: self.open_selected())
        v.addWidget(self.tree, 1)

        foot = QHBoxLayout()
        b = QPushButton("Open folder")
        b.clicked.connect(self.open_selected)
        foot.addWidget(b)
        foot.addStretch(1)
        self.delete_btn = QPushButton("Move everything marked Delete to Recycle Bin")
        self.delete_btn.setObjectName("danger")
        self.delete_btn.clicked.connect(self.delete_all_safe)
        self.delete_btn.setEnabled(False)
        foot.addWidget(self.delete_btn)
        v.addLayout(foot)

    def set_advice(self, advice: dict[str, Advice]) -> None:
        self.advice = advice
        groups: dict[str, list[Advice]] = {vd: [] for vd in VERDICTS}
        for a in advice.values():
            groups[a.verdict].append(a)
        self.tree.clear()
        for verdict in VERDICTS:
            items = sorted(groups[verdict], key=lambda a: a.size, reverse=True)
            total = sum(a.size for a in items)
            self.cards[verdict].setText(fmt_size(total))
            self.cards[verdict + "_n"].setText(f"{len(items):,} items")
            top = QTreeWidgetItem([f"{TITLES[verdict]}  ({len(items):,} items, {fmt_size(total)})"])
            top.setForeground(0, QBrush(VERDICT_COLORS[verdict]))
            font = top.font(0)
            font.setBold(True)
            top.setFont(0, font)
            self.tree.addTopLevelItem(top)
            for a in items[:PER_GROUP]:
                child = QTreeWidgetItem([a.path, fmt_size(a.size), a.reason, f"{a.confidence:.0%}"])
                child.setData(0, Qt.ItemDataRole.UserRole, a.path)
                child.setToolTip(0, a.path)
                top.addChild(child)
            if len(items) > PER_GROUP:
                top.addChild(QTreeWidgetItem([f"... and {len(items) - PER_GROUP:,} more smaller items "
                                              "(see the Cleanup and Media tabs)"]))
            top.setExpanded(verdict in (DELETE, REVIEW))
        self.delete_btn.setEnabled(bool(groups[DELETE]))
        self.delete_btn.setText(
            f"Move everything marked Delete to Recycle Bin ({fmt_size(sum(a.size for a in groups[DELETE]))})")

    def open_selected(self) -> None:
        it = self.tree.currentItem()
        if it and it.data(0, Qt.ItemDataRole.UserRole):
            open_in_explorer(it.data(0, Qt.ItemDataRole.UserRole))

    def delete_all_safe(self) -> None:
        items = [(a.path, a.size, DELETE) for a in self.advice.values()
                 if a.verdict == DELETE and os.path.lexists(a.path)]
        if items:
            self._trash_cb(items)

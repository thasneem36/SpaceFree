from __future__ import annotations

import csv
import heapq
import os
import threading

from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QBrush, QGuiApplication
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QGroupBox, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QMainWindow, QMenu, QMessageBox, QProgressBar, QProgressDialog,
    QPushButton, QTableWidget, QTableWidgetItem, QTabWidget, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget,
)

from .. import cleaner, recycle, scanner
from ..advisor import DELETE, EDUCATIONAL, KEEP, Advice, advise_one, from_finding
from ..advisor import REVIEW as V_REVIEW
from ..analysis import Analysis, analyze
from ..filetypes import ALL_TYPES
from ..live import LiveAnalyzer
from ..models import BAD, GOOD, IMPORTANT, REVIEW, Finding, ScanResult, fmt_size
from ..rules import label_for_dir
from .advisor_tab import AdvisorTab
from .media_tab import MediaTab
from .theme import LABEL_COLORS, VERDICT_COLORS
from .treemap_widget import TreemapWidget
from .util import NumItem, open_in_explorer

MAX_ROWS = 20000
TICK_MS = 700
LIVE_BATCH = 300


class Worker(QThread):
    status = pyqtSignal(str)
    finished_ok = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, roots: list[str]) -> None:
        super().__init__()
        self.roots = roots
        self.cancel = threading.Event()
        self.state = scanner.ScanState()
        self.live = LiveAnalyzer()

    def run(self) -> None:
        try:
            def prog(files: int, dirs: int, nbytes: int, path: str) -> None:
                self.status.emit(f"Scanning... {files:,} files, {dirs:,} folders, {fmt_size(nbytes)}\n{path}")

            result = scanner.scan(self.roots, prog, self.cancel, state=self.state, hooks=self.live)
            if result.cancelled:
                self.finished_ok.emit(None)
                return
            analysis = analyze(result, self.cancel, self.status.emit)
            self.finished_ok.emit(None if self.cancel.is_set() else analysis)
        except Exception as e:  # noqa: BLE001
            self.failed.emit(str(e))


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("SpaceFree - find out why your disk is full")
        self.resize(1360, 820)
        self.analysis: Analysis | None = None
        self.worker: Worker | None = None
        self.scanning = False
        self.drive_boxes: list[tuple[QCheckBox, scanner.Drive]] = []
        self.row_of: dict[str, int] = {}
        self.media_cursor = 0
        self.advice: dict[str, Advice] = {}

        root = QWidget()
        self.setCentralWidget(root)
        layout = QHBoxLayout(root)
        layout.addWidget(self._build_sidebar())
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_summary(), "Summary")
        self.advisor_tab = AdvisorTab(self.confirm_and_trash)
        self.tabs.addTab(self.advisor_tab, "Advisor")
        self.tabs.addTab(self._build_cleanup(), "Cleanup")
        self.media_tab = MediaTab(self.confirm_and_trash)
        self.tabs.addTab(self.media_tab, "Media")
        self.tabs.addTab(self._build_folders(), "Folders")
        self.tabs.addTab(self._build_treemap(), "Size map")
        layout.addWidget(self.tabs, 1)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.refresh_recycle()

    # ---------- sidebar ----------
    def _build_sidebar(self) -> QWidget:
        box = QGroupBox("Drives to scan")
        box.setFixedWidth(270)
        v = QVBoxLayout(box)
        for d in scanner.list_drives():
            cb = QCheckBox(f"{d.path}  {'(removable)' if not d.fixed else ''}")
            cb.setChecked(d.fixed)
            bar = QProgressBar()
            bar.setRange(0, 1000)
            bar.setValue(int(1000 * d.used / d.total) if d.total else 0)
            bar.setFormat(f"{fmt_size(d.used)} / {fmt_size(d.total)}")
            v.addWidget(cb)
            v.addWidget(bar)
            self.drive_boxes.append((cb, d))
        v.addStretch(1)
        self.scan_btn = QPushButton("Scan selected drives")
        self.scan_btn.setObjectName("primary")
        self.scan_btn.clicked.connect(self.start_scan)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self.cancel_scan)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.hide()
        self.status = QLabel("Ready. Nothing is deleted without your confirmation.")
        self.status.setWordWrap(True)
        self.status.setObjectName("muted")
        for w in (self.scan_btn, self.cancel_btn, self.progress, self.status):
            v.addWidget(w)
        return box

    # ---------- summary ----------
    def _table(self, headers: list[str], stretch: int = 0) -> QTableWidget:
        t = QTableWidget(0, len(headers))
        t.setHorizontalHeaderLabels(headers)
        t.horizontalHeader().setSectionResizeMode(stretch, QHeaderView.ResizeMode.Stretch)
        t.verticalHeader().hide()
        t.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        return t

    def _build_summary(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        row = QHBoxLayout()
        self.card_bad = self._card("Safe to delete", BAD)
        self.card_review = self._card("Worth reviewing", REVIEW)
        self.card_important = self._card("Important (protected)", IMPORTANT)
        self.card_good = self._card("Good / normal", GOOD)
        for c in (self.card_bad, self.card_review, self.card_important, self.card_good):
            row.addWidget(c[0])
        v.addLayout(row)
        self.recycle_btn = QPushButton("Empty Recycle Bin")
        self.recycle_btn.clicked.connect(self.empty_bin)
        v.addWidget(self.recycle_btn, 0, Qt.AlignmentFlag.AlignLeft)

        mid = QHBoxLayout()
        left = QVBoxLayout()
        left.addWidget(QLabel("Why is my disk full? Biggest folders (double-click to open)"))
        self.top_table = self._table(["Folder", "Size", "Label"])
        self.top_table.cellDoubleClicked.connect(
            lambda r, _c: open_in_explorer(self.top_table.item(r, 0).text()))
        left.addWidget(self.top_table, 1)
        mid.addLayout(left, 3)
        right = QVBoxLayout()
        right.addWidget(QLabel("Space by file type (all files)"))
        self.type_table = self._table(["Type", "Files", "Size", "Share"])
        right.addWidget(self.type_table, 1)
        mid.addLayout(right, 2)
        v.addLayout(mid, 3)

        v.addWidget(QLabel("What can be cleaned, by category"))
        self.cat_table = self._table(["Category", "Label", "Items", "Size"])
        v.addWidget(self.cat_table, 2)
        return w

    def _card(self, title: str, label: str):
        box = QGroupBox(title)
        lay = QVBoxLayout(box)
        big = QLabel("-")
        big.setObjectName("big")
        big.setStyleSheet(f"color: {LABEL_COLORS[label].name()};")
        lay.addWidget(big)
        return box, big

    def refresh_recycle(self) -> None:
        size, items = recycle.recycle_bin_size()
        self.recycle_btn.setText(f"Empty Recycle Bin ({fmt_size(size)}, {items} items)")
        self.recycle_btn.setEnabled(items > 0)

    def empty_bin(self) -> None:
        size, items = recycle.recycle_bin_size()
        if QMessageBox.question(
                self, "Empty Recycle Bin",
                f"Permanently delete {items} items ({fmt_size(size)}) from the Recycle Bin?\n"
                "This cannot be undone.") == QMessageBox.StandardButton.Yes:
            recycle.empty_recycle_bin()
            self.refresh_recycle()

    def _colored(self, text: str, label: str) -> QTableWidgetItem:
        it = QTableWidgetItem(text)
        it.setForeground(QBrush(LABEL_COLORS[label]))
        return it

    def fill_top_dirs(self, rows: list[tuple[str, int]], flagged: set[str]) -> None:
        self.top_table.setRowCount(len(rows))
        for r, (p, size) in enumerate(rows):
            self.top_table.setItem(r, 0, QTableWidgetItem(p))
            self.top_table.setItem(r, 1, QTableWidgetItem(fmt_size(size)))
            self.top_table.setItem(r, 2, self._colored(label_for_dir(p, flagged), label_for_dir(p, flagged)))

    def fill_types(self, stats: dict[str, tuple[int, int]]) -> None:
        total = sum(b for _, b in stats.values()) or 1
        order = sorted(ALL_TYPES, key=lambda t: stats.get(t, (0, 0))[1], reverse=True)
        self.type_table.setRowCount(len(order))
        for r, t in enumerate(order):
            n, b = stats.get(t, (0, 0))
            self.type_table.setItem(r, 0, QTableWidgetItem(t))
            self.type_table.setItem(r, 1, QTableWidgetItem(f"{n:,}"))
            self.type_table.setItem(r, 2, QTableWidgetItem(fmt_size(b)))
            self.type_table.setItem(r, 3, QTableWidgetItem(f"{100 * b / total:.1f}%"))

    def fill_categories(self, findings: list[Finding]) -> None:
        agg: dict[tuple[str, str], list[int]] = {}
        for f in findings:
            a = agg.setdefault((f.category, f.label), [0, 0])
            a[0] += 1
            a[1] += f.size
        rows = sorted(((c, l, n, s) for (c, l), (n, s) in agg.items()), key=lambda r: r[3], reverse=True)
        self.cat_table.setRowCount(len(rows))
        for r, (cat, label, n, size) in enumerate(rows):
            self.cat_table.setItem(r, 0, QTableWidgetItem(cat))
            self.cat_table.setItem(r, 1, self._colored(label, label))
            self.cat_table.setItem(r, 2, QTableWidgetItem(str(n)))
            self.cat_table.setItem(r, 3, QTableWidgetItem(fmt_size(size)))

    # ---------- cleanup ----------
    def _build_cleanup(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        bar = QHBoxLayout()
        self.filter_label = QComboBox()
        self.filter_label.addItems(["All", DELETE, V_REVIEW, KEEP, EDUCATIONAL])
        self.filter_cat = QComboBox()
        self.filter_cat.addItem("All categories")
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search path...")
        for c in (self.filter_label, self.filter_cat):
            c.currentIndexChanged.connect(self.apply_filters)
        self.search.textChanged.connect(self.apply_filters)
        bar.addWidget(QLabel("Show:"))
        bar.addWidget(self.filter_label)
        bar.addWidget(self.filter_cat)
        bar.addWidget(self.search, 1)
        v.addLayout(bar)

        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(
            ["", "Verdict", "Label", "Category", "Size", "Age (days)", "Path", "Reason"])
        h = self.table.horizontalHeader()
        h.setSectionResizeMode(6, QHeaderView.ResizeMode.Interactive)
        h.setSectionResizeMode(7, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(0, 34)
        self.table.setColumnWidth(6, 380)
        self.table.verticalHeader().hide()
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.itemChanged.connect(self.update_selection_total)
        self.table.cellDoubleClicked.connect(lambda r, _c: self.open_row_folder(r))
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.row_menu)
        v.addWidget(self.table, 1)

        foot = QHBoxLayout()
        for text, fn in (("Open folder", lambda: self.open_row_folder(self.table.currentRow())),
                         ("Select all Delete", lambda: self.select_verdict(DELETE)),
                         ("Select none", lambda: self.select_verdict(None)),
                         ("Export CSV", self.export_csv)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            foot.addWidget(b)
        foot.addStretch(1)
        self.sel_label = QLabel("Selected: 0 items, 0 B")
        foot.addWidget(self.sel_label)
        self.trash_btn = QPushButton("Move selected to Recycle Bin")
        self.trash_btn.setObjectName("danger")
        self.trash_btn.clicked.connect(self.trash_selected)
        foot.addWidget(self.trash_btn)
        v.addLayout(foot)
        return w

    def _make_row(self, r: int, f: Finding) -> None:
        adv = self.advice.get(f.path)
        if adv is None:
            adv = self.advice[f.path] = advise_one(from_finding(f))
        chk = QTableWidgetItem()
        can_tick = f.deletable and adv.verdict != EDUCATIONAL  # learning material is protected
        chk.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
                     if can_tick else Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        chk.setCheckState(Qt.CheckState.Checked if f.path in self._keep_checked else Qt.CheckState.Unchecked)
        chk.setData(Qt.ItemDataRole.UserRole, f)
        reason = adv.reason if f.deletable else f"{adv.reason}  (manual action - not deletable here)"
        path = QTableWidgetItem(f.path)
        path.setToolTip(f.path)
        verdict = QTableWidgetItem(adv.verdict)
        verdict.setForeground(QBrush(VERDICT_COLORS[adv.verdict]))
        items = [chk, verdict, self._colored(f.label, f.label), QTableWidgetItem(f.category),
                 NumItem(fmt_size(f.size), f.size), NumItem(str(f.age_days), f.age_days), path,
                 QTableWidgetItem(reason)]
        for c, it in enumerate(items):
            self.table.setItem(r, c, it)
        self.row_of[f.path] = r

    _keep_checked: set[str] = set()

    def append_findings(self, findings: list[Finding]) -> None:
        self.table.blockSignals(True)
        new = [f for f in findings if f.path not in self.row_of]
        start = self.table.rowCount()
        self.table.setRowCount(start + len(new))
        for i, f in enumerate(new):
            self._make_row(start + i, f)
        self.table.blockSignals(False)

    def remove_inside(self, prefixes: list[str]) -> None:
        for p in prefixes:
            pre = p + os.sep
            for path in [x for x in self.row_of if x.startswith(pre)]:
                self.table.setRowHidden(self.row_of.pop(path), True)

    def populate_table(self, findings: list[Finding]) -> None:
        self._keep_checked = {self.finding_at(r).path for r in self.checked_rows()}
        self.table.blockSignals(True)
        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        self.row_of.clear()
        findings = findings[:MAX_ROWS]
        self.table.setRowCount(len(findings))
        for r, f in enumerate(findings):
            self._make_row(r, f)
        self._keep_checked = set()
        self.table.setSortingEnabled(True)
        self.table.sortItems(4, Qt.SortOrder.DescendingOrder)
        self.table.blockSignals(False)
        self.row_of.clear()
        cats = sorted({f.category for f in findings})
        self.filter_cat.blockSignals(True)
        self.filter_cat.clear()
        self.filter_cat.addItem("All categories")
        self.filter_cat.addItems(cats)
        self.filter_cat.blockSignals(False)
        self.apply_filters()
        self.update_selection_total()

    def finding_at(self, row: int) -> Finding:
        return self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)

    def apply_filters(self) -> None:
        if self.scanning:
            return
        lab = self.filter_label.currentText()
        cat = self.filter_cat.currentText()
        text = self.search.text().lower()
        for r in range(self.table.rowCount()):
            f = self.finding_at(r)
            show = ((lab == "All" or self.advice[f.path].verdict == lab) and
                    (cat == "All categories" or f.category == cat) and
                    (not text or text in f.path.lower()))
            self.table.setRowHidden(r, not show)

    def select_verdict(self, verdict: str | None) -> None:
        self.table.blockSignals(True)
        for r in range(self.table.rowCount()):
            it = self.table.item(r, 0)
            if it.flags() & Qt.ItemFlag.ItemIsUserCheckable:
                on = (verdict is not None and self.advice[self.finding_at(r).path].verdict == verdict
                      and not self.table.isRowHidden(r))
                it.setCheckState(Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)
        self.table.blockSignals(False)
        self.update_selection_total()

    def checked_rows(self) -> list[int]:
        return [r for r in range(self.table.rowCount())
                if self.table.item(r, 0).checkState() == Qt.CheckState.Checked
                and not self.table.isRowHidden(r)]

    def update_selection_total(self, *_: object) -> None:
        rows = self.checked_rows()
        total = sum(self.finding_at(r).size for r in rows)
        self.sel_label.setText(f"Selected: {len(rows)} items, {fmt_size(total)}")

    def open_row_folder(self, row: int) -> None:
        if row >= 0:
            open_in_explorer(self.finding_at(row).path)

    def row_menu(self, pos) -> None:
        row = self.table.rowAt(pos.y())
        if row < 0:
            return
        f = self.finding_at(row)
        m = QMenu(self)
        m.addAction("Open folder", lambda: open_in_explorer(f.path))
        if f.group:
            m.addAction("Open the original (kept copy)", lambda: open_in_explorer(f.group))
        m.addAction("Copy path", lambda: QGuiApplication.clipboard().setText(f.path))
        m.exec(self.table.viewport().mapToGlobal(pos))

    def export_csv(self) -> None:
        if not self.analysis:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export report", "spacefree_report.csv", "CSV (*.csv)")
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["label", "category", "size_bytes", "age_days", "path", "reason"])
            for f in self.analysis.findings:
                w.writerow([f.label, f.category, f.size, f.age_days, f.path, f.reason])

    # ---------- deleting ----------
    def trash_selected(self) -> None:
        rows = self.checked_rows()
        if not rows:
            QMessageBox.information(self, "Nothing selected", "Tick the items you want to remove first.")
            return
        items = [self.finding_at(r) for r in rows]
        self.confirm_and_trash([(f.path, f.size, self.advice[f.path].verdict) for f in items])

    def confirm_and_trash(self, items: list[tuple[str, int, str]]) -> None:
        if self.scanning:
            QMessageBox.information(self, "Scan running", "Wait for the scan to finish before deleting.")
            return
        total = sum(s for _, s, _ in items)
        review = sum(1 for _, _, v in items if v != DELETE)
        msg = (f"Move {len(items)} items ({fmt_size(total)}) to the Recycle Bin?\n\n"
               "You can restore them from the Recycle Bin. Items larger than the Recycle Bin's "
               "size limit may be deleted permanently by Windows.")
        if review:
            msg += (f"\n\n{review} of these are NOT marked 'Delete' by the Advisor "
                    "(Review/Keep/Educational) - check that you don't need them.")
        if QMessageBox.question(self, "Confirm", msg) != QMessageBox.StandardButton.Yes:
            return
        dlg = QProgressDialog("Moving to Recycle Bin...", "", 0, len(items), self)
        dlg.setCancelButton(None)
        dlg.setWindowModality(Qt.WindowModality.WindowModal)
        dlg.show()

        def prog(i: int, n: int, path: str) -> None:
            dlg.setValue(i - 1)
            dlg.setLabelText(path)
            QApplication.processEvents()

        ok, failed = cleaner.move_to_trash([p for p, _, _ in items], prog)
        dlg.close()
        done = set(ok)
        freed = sum(s for p, s, _ in items if p in done)
        if self.analysis:
            self.analysis.findings = [f for f in self.analysis.findings
                                      if f.path not in done and not any(f.path.startswith(d + os.sep) for d in done)]
            self.populate_table(self.analysis.findings)
            self.fill_categories(self.analysis.findings)
            self.card_bad[1].setText(fmt_size(self.analysis.total(BAD)))
            self.card_review[1].setText(fmt_size(self.analysis.total(REVIEW)))
            for d in done:
                self.analysis.advice.pop(d, None)
            self.advice = self.analysis.advice
            self.advisor_tab.set_advice(self.advice)
        self.media_tab.remove_paths(done)
        self.refresh_recycle()
        text = (f"Moved {len(ok)} items to the Recycle Bin ({fmt_size(freed)}).\n"
                "Empty the Recycle Bin to reclaim the space.")
        if failed:
            text += f"\n\n{len(failed)} could not be removed:\n" + "\n".join(f"{p}: {why}" for p, why in failed[:8])
        QMessageBox.information(self, "Done", text)

    # ---------- folders ----------
    def _build_folders(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        self.tree = QTreeWidget()
        self.tree.setColumnCount(4)
        self.tree.setHeaderLabels(["Folder", "Size", "% of parent", "Label"])
        self.tree.setColumnWidth(0, 520)
        self.tree.itemExpanded.connect(self.expand_item)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.tree_menu)
        v.addWidget(self.tree, 1)
        foot = QHBoxLayout()
        b = QPushButton("Open folder")
        b.clicked.connect(self.open_tree_folder)
        foot.addWidget(b)
        foot.addStretch(1)
        v.addLayout(foot)
        return w

    def _nodes(self):
        if self.analysis:
            return self.analysis.scan.nodes
        return self.worker.state.nodes if self.worker else {}

    def _flagged(self) -> set[str]:
        if self.analysis:
            return self.analysis.flagged_dirs
        return self.worker.live.flagged_dirs if self.worker else set()

    def _style_tree_item(self, it: QTreeWidgetItem, path: str, parent_size: int) -> None:
        nodes = self._nodes()
        n = nodes[path]
        label = label_for_dir(path, self._flagged())
        it.setText(1, fmt_size(n.size))
        it.setText(2, f"{100 * n.size / parent_size:.0f}%" if parent_size else "")
        it.setText(3, label)
        it.setForeground(3, QBrush(LABEL_COLORS[label]))
        if n.children and it.childCount() == 0:
            it.addChild(QTreeWidgetItem(["..."]))

    def _add_children(self, parent_item: QTreeWidgetItem, path: str) -> None:
        nodes = self._nodes()
        node = nodes[path]
        kids = sorted((nodes[c] for c in list(node.children) if c in nodes), key=lambda n: n.size, reverse=True)
        for k in kids[:300]:
            it = QTreeWidgetItem([k.name, "", "", ""])
            it.setData(0, Qt.ItemDataRole.UserRole, k.path)
            it.setToolTip(0, k.path)
            self._style_tree_item(it, k.path, node.size)
            parent_item.addChild(it)

    def expand_item(self, item: QTreeWidgetItem) -> None:
        if item.childCount() == 1 and item.child(0).text(0) == "...":
            item.takeChild(0)
            self._add_children(item, item.data(0, Qt.ItemDataRole.UserRole))

    def ensure_tree_roots(self) -> None:
        if self.tree.topLevelItemCount() or not self.worker:
            return
        nodes = self._nodes()
        for r in self.worker.roots:
            if r not in nodes:
                return
        for r in self.worker.roots:
            it = QTreeWidgetItem([r, "", "", ""])
            it.setData(0, Qt.ItemDataRole.UserRole, r)
            self._style_tree_item(it, r, 0)
            self.tree.addTopLevelItem(it)

    def refresh_tree(self) -> None:
        """Update sizes and labels of every folder already shown, without rebuilding."""
        nodes = self._nodes()

        def walk(it: QTreeWidgetItem, parent_size: int) -> None:
            path = it.data(0, Qt.ItemDataRole.UserRole)
            if path and path in nodes:
                self._style_tree_item(it, path, parent_size)
                size = nodes[path].size
                for i in range(it.childCount()):
                    walk(it.child(i), size)

        for i in range(self.tree.topLevelItemCount()):
            walk(self.tree.topLevelItem(i), 0)

    def open_tree_folder(self) -> None:
        it = self.tree.currentItem()
        if it and it.data(0, Qt.ItemDataRole.UserRole):
            open_in_explorer(it.data(0, Qt.ItemDataRole.UserRole))

    def tree_menu(self, pos) -> None:
        it = self.tree.itemAt(pos)
        if not it or not it.data(0, Qt.ItemDataRole.UserRole):
            return
        path = it.data(0, Qt.ItemDataRole.UserRole)
        m = QMenu(self)
        m.addAction("Open folder", lambda: open_in_explorer(path))
        m.addAction("Copy path", lambda: QGuiApplication.clipboard().setText(path))
        m.exec(self.tree.viewport().mapToGlobal(pos))

    # ---------- treemap ----------
    def _build_treemap(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        top = QHBoxLayout()
        up = QPushButton("Up")
        self.crumb = QLabel("Double-click a block to open it, right-click to go up.")
        self.crumb.setObjectName("muted")
        top.addWidget(up)
        top.addWidget(self.crumb, 1)
        v.addLayout(top)
        self.treemap = TreemapWidget()
        self.treemap.pathChanged.connect(self.crumb.setText)
        up.clicked.connect(self.treemap.go_up)
        v.addWidget(self.treemap, 1)
        return w

    # ---------- scan control ----------
    def start_scan(self) -> None:
        roots = [d.path for cb, d in self.drive_boxes if cb.isChecked()]
        if not roots:
            QMessageBox.warning(self, "No drive", "Tick at least one drive to scan.")
            return
        self.analysis = None
        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        self.row_of.clear()
        self.media_tab.clear()
        self.media_cursor = 0
        self.advice = {}
        self.advisor_tab.set_advice({})
        self.tree.clear()
        for c in (self.card_bad, self.card_review, self.card_important, self.card_good):
            c[1].setText("-")
        self.worker = Worker(roots)
        prov = Analysis(ScanResult(self.worker.state.nodes, roots, []))
        prov.flagged_dirs = self.worker.live.flagged_dirs
        self.treemap.set_analysis(prov)
        self.worker.status.connect(self.status.setText)
        self.worker.finished_ok.connect(self.scan_done)
        self.worker.failed.connect(self.scan_failed)
        self.scanning = True
        self.scan_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.progress.show()
        self.timer.start(TICK_MS)
        self.worker.start()
        self.tabs.setCurrentIndex(0)

    def cancel_scan(self) -> None:
        if self.worker:
            self.worker.cancel.set()
            self.status.setText("Cancelling...")

    def tick(self) -> None:
        """Runs every ~0.7s during a scan: pull new results into every tab."""
        if not self.worker or not self.scanning:
            return
        st, live = self.worker.state, self.worker.live
        added, removed = live.drain()
        if added:
            self.append_findings(added)
        if removed:
            self.remove_inside(removed)
        if added or removed:
            self.update_selection_total()
        media = st.media
        if self.media_cursor < len(media):
            self.media_tab.enqueue(media[self.media_cursor:])
            self.media_cursor = len(media)
        self.card_bad[1].setText(fmt_size(live.totals(BAD)))
        self.card_review[1].setText(fmt_size(live.totals(REVIEW)))
        nodes = st.nodes
        top = heapq.nlargest(25, ((nodes[p].size, p) for p in list(st.shallow) if p in nodes and nodes[p].parent))
        self.fill_top_dirs([(p, s) for s, p in top], live.flagged_dirs)
        self.fill_types(st.type_snapshot())
        self.fill_categories(live.snapshot())
        self.ensure_tree_roots()
        self.refresh_tree()
        self.treemap.update()

    def _finish_ui(self) -> None:
        self.scanning = False
        self.timer.stop()
        self.scan_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.progress.hide()

    def scan_failed(self, msg: str) -> None:
        self._finish_ui()
        self.status.setText(f"Scan failed: {msg}")

    def scan_done(self, analysis: Analysis | None) -> None:
        self._finish_ui()
        if analysis is None:
            self.status.setText("Scan cancelled. Results so far are kept on screen.")
            return
        self.analysis = analysis
        s = analysis.scan
        self.status.setText(f"Done: {s.files_seen:,} files, {fmt_size(s.total_size)} scanned"
                            f"{f', {s.errors:,} unreadable items skipped' if s.errors else ''}.")
        self.card_bad[1].setText(fmt_size(analysis.total(BAD)))
        self.card_review[1].setText(fmt_size(analysis.total(REVIEW)))
        self.card_important[1].setText(fmt_size(analysis.important_bytes))
        self.card_good[1].setText(fmt_size(analysis.good_bytes))
        self.fill_top_dirs(analysis.top_dirs, analysis.flagged_dirs)
        self.fill_types(s.type_stats)
        self.fill_categories(analysis.findings)
        self.advice = analysis.advice
        self.populate_table(analysis.findings)
        self.advisor_tab.set_advice(analysis.advice)
        self.media_tab.finalize(s.media, analysis.advice)
        self.ensure_tree_roots()
        self.refresh_tree()
        self.treemap.set_analysis(analysis)
        self.refresh_recycle()

    def closeEvent(self, e) -> None:  # noqa: N802
        if self.worker and self.worker.isRunning():
            self.worker.cancel.set()
            self.worker.wait(5000)
        e.accept()

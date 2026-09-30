from __future__ import annotations

import csv
import os
import subprocess
import threading

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QBrush
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QGroupBox, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QMainWindow, QMessageBox, QProgressBar, QProgressDialog, QPushButton,
    QTableWidget, QTableWidgetItem, QTabWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from .. import cleaner, recycle, scanner
from ..analysis import Analysis, analyze
from ..models import BAD, REVIEW, Finding, fmt_size
from ..rules import label_for_dir
from .theme import LABEL_COLORS
from .treemap_widget import TreemapWidget

MAX_ROWS = 20000


class NumItem(QTableWidgetItem):
    """Table item that sorts by a number instead of by its text."""

    def __init__(self, text: str, value: float) -> None:
        super().__init__(text)
        self.value = value
        self.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

    def __lt__(self, other: QTableWidgetItem) -> bool:
        return self.value < getattr(other, "value", 0)


class Worker(QThread):
    status = pyqtSignal(str)
    finished_ok = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, roots: list[str]) -> None:
        super().__init__()
        self.roots = roots
        self.cancel = threading.Event()

    def run(self) -> None:
        try:
            def prog(files: int, dirs: int, nbytes: int, path: str) -> None:
                self.status.emit(f"Scanning... {files:,} files, {dirs:,} folders, {fmt_size(nbytes)}\n{path}")

            result = scanner.scan(self.roots, prog, self.cancel)
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
        self.resize(1280, 780)
        self.analysis: Analysis | None = None
        self.worker: Worker | None = None
        self.drive_boxes: list[tuple[QCheckBox, scanner.Drive]] = []

        root = QWidget()
        self.setCentralWidget(root)
        layout = QHBoxLayout(root)
        layout.addWidget(self._build_sidebar())
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_summary(), "Summary")
        self.tabs.addTab(self._build_cleanup(), "Cleanup")
        self.tabs.addTab(self._build_folders(), "Folders")
        self.tabs.addTab(self._build_treemap(), "Size map")
        layout.addWidget(self.tabs, 1)
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
    def _build_summary(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        row = QHBoxLayout()
        self.card_bad = self._card("Safe to delete", BAD)
        self.card_review = self._card("Worth reviewing", REVIEW)
        self.card_important = self._card("Important (protected)", "Important")
        self.card_good = self._card("Good / normal", "Good")
        for c in (self.card_bad, self.card_review, self.card_important, self.card_good):
            row.addWidget(c[0])
        v.addLayout(row)
        self.recycle_btn = QPushButton("Empty Recycle Bin")
        self.recycle_btn.clicked.connect(self.empty_bin)
        v.addWidget(self.recycle_btn, 0, Qt.AlignmentFlag.AlignLeft)
        v.addWidget(QLabel("Why is my disk full? Biggest folders"))
        self.top_table = QTableWidget(0, 3)
        self.top_table.setHorizontalHeaderLabels(["Folder", "Size", "Label"])
        self.top_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.top_table.verticalHeader().hide()
        self.top_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        v.addWidget(self.top_table, 1)
        v.addWidget(QLabel("What can be cleaned, by category"))
        self.cat_table = QTableWidget(0, 4)
        self.cat_table.setHorizontalHeaderLabels(["Category", "Label", "Items", "Size"])
        self.cat_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.cat_table.verticalHeader().hide()
        self.cat_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        v.addWidget(self.cat_table, 1)
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

    # ---------- cleanup ----------
    def _build_cleanup(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        bar = QHBoxLayout()
        self.filter_label = QComboBox()
        self.filter_label.addItems(["All", BAD, REVIEW])
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

        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(["", "Label", "Category", "Size", "Age (days)", "Path", "Reason"])
        h = self.table.horizontalHeader()
        h.setSectionResizeMode(5, QHeaderView.ResizeMode.Interactive)
        h.setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(0, 34)
        self.table.setColumnWidth(5, 420)
        self.table.verticalHeader().hide()
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.itemChanged.connect(self.update_selection_total)
        v.addWidget(self.table, 1)

        foot = QHBoxLayout()
        for text, fn in (("Select all Bad", lambda: self.select_label(BAD)),
                         ("Select none", lambda: self.select_label(None)),
                         ("Show in Explorer", self.show_in_explorer),
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

    def populate_table(self) -> None:
        self.table.blockSignals(True)
        self.table.setSortingEnabled(False)
        findings = self.analysis.findings[:MAX_ROWS] if self.analysis else []
        self.table.setRowCount(len(findings))
        for r, f in enumerate(findings):
            chk = QTableWidgetItem()
            chk.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled
                         if f.deletable else Qt.ItemFlag.NoItemFlags)
            chk.setCheckState(Qt.CheckState.Unchecked)
            chk.setData(Qt.ItemDataRole.UserRole, f)
            lab = QTableWidgetItem(f.label)
            lab.setForeground(QBrush(LABEL_COLORS[f.label]))
            reason = f.reason if f.deletable else f"{f.reason}  (manual action - not deletable here)"
            path = QTableWidgetItem(f.path)
            path.setToolTip(f.path)
            items = [chk, lab, QTableWidgetItem(f.category), NumItem(fmt_size(f.size), f.size),
                     NumItem(str(f.age_days), f.age_days), path, QTableWidgetItem(reason)]
            for c, it in enumerate(items):
                self.table.setItem(r, c, it)
        self.table.setSortingEnabled(True)
        self.table.sortItems(3, Qt.SortOrder.DescendingOrder)
        self.table.blockSignals(False)
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
        lab = self.filter_label.currentText()
        cat = self.filter_cat.currentText()
        text = self.search.text().lower()
        for r in range(self.table.rowCount()):
            f = self.finding_at(r)
            show = ((lab == "All" or f.label == lab) and
                    (cat == "All categories" or f.category == cat) and
                    (not text or text in f.path.lower()))
            self.table.setRowHidden(r, not show)

    def select_label(self, label: str | None) -> None:
        self.table.blockSignals(True)
        for r in range(self.table.rowCount()):
            f = self.finding_at(r)
            it = self.table.item(r, 0)
            on = label is not None and f.label == label and f.deletable and not self.table.isRowHidden(r)
            if f.deletable:
                it.setCheckState(Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)
        self.table.blockSignals(False)
        self.update_selection_total()

    def checked_rows(self) -> list[int]:
        return [r for r in range(self.table.rowCount())
                if self.table.item(r, 0).checkState() == Qt.CheckState.Checked]

    def update_selection_total(self, *_: object) -> None:
        rows = self.checked_rows()
        total = sum(self.finding_at(r).size for r in rows)
        self.sel_label.setText(f"Selected: {len(rows)} items, {fmt_size(total)}")

    def show_in_explorer(self) -> None:
        row = self.table.currentRow()
        if row >= 0 and os.name == "nt":
            subprocess.Popen(["explorer", "/select,", os.path.normpath(self.finding_at(row).path)])

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

    def trash_selected(self) -> None:
        rows = self.checked_rows()
        if not rows:
            QMessageBox.information(self, "Nothing selected", "Tick the items you want to remove first.")
            return
        items = [self.finding_at(r) for r in rows]
        total = sum(f.size for f in items)
        review = sum(1 for f in items if f.label == REVIEW)
        msg = (f"Move {len(items)} items ({fmt_size(total)}) to the Recycle Bin?\n\n"
               "You can restore them from the Recycle Bin. Items larger than the Recycle Bin's "
               "size limit may be deleted permanently by Windows.")
        if review:
            msg += f"\n\n{review} of these are 'Review' items - check that you don't need them."
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

        ok, failed = cleaner.move_to_trash([f.path for f in items], prog)
        dlg.close()
        done = set(ok)
        freed = sum(f.size for f in items if f.path in done)
        if self.analysis:
            self.analysis.findings = [f for f in self.analysis.findings if f.path not in done]
        self.populate_table()
        self.fill_summary()
        self.refresh_recycle()
        text = f"Moved {len(ok)} items to the Recycle Bin ({fmt_size(freed)}).\nEmpty the Recycle Bin to reclaim the space."
        if failed:
            text += f"\n\n{len(failed)} could not be removed:\n" + "\n".join(
                f"{p}: {why}" for p, why in failed[:8])
        QMessageBox.information(self, "Done", text)

    # ---------- folders ----------
    def _build_folders(self) -> QWidget:
        self.tree = QTreeWidget()
        self.tree.setColumnCount(4)
        self.tree.setHeaderLabels(["Folder", "Size", "% of parent", "Label"])
        self.tree.setColumnWidth(0, 520)
        self.tree.itemExpanded.connect(self.expand_item)
        return self.tree

    def _add_children(self, parent_item: QTreeWidgetItem, path: str) -> None:
        nodes = self.analysis.scan.nodes
        node = nodes[path]
        kids = sorted((nodes[c] for c in node.children if c in nodes), key=lambda n: n.size, reverse=True)
        for k in kids[:300]:
            pct = 100 * k.size / node.size if node.size else 0
            it = QTreeWidgetItem([k.name, fmt_size(k.size), f"{pct:.0f}%", ""])
            label = label_for_dir(k.path, self.analysis.flagged_dirs)
            it.setText(3, label)
            it.setForeground(3, QBrush(LABEL_COLORS[label]))
            it.setData(0, Qt.ItemDataRole.UserRole, k.path)
            it.setToolTip(0, k.path)
            if k.children:
                it.addChild(QTreeWidgetItem(["..."]))
            parent_item.addChild(it)

    def expand_item(self, item: QTreeWidgetItem) -> None:
        if item.childCount() == 1 and item.child(0).text(0) == "...":
            item.takeChild(0)
            self._add_children(item, item.data(0, Qt.ItemDataRole.UserRole))

    def populate_tree(self) -> None:
        self.tree.clear()
        nodes = self.analysis.scan.nodes
        for r in self.analysis.scan.roots:
            node = nodes[r]
            it = QTreeWidgetItem([r, fmt_size(node.size), "", ""])
            it.setData(0, Qt.ItemDataRole.UserRole, r)
            it.addChild(QTreeWidgetItem(["..."]))
            self.tree.addTopLevelItem(it)
            it.setExpanded(True)

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
        self.worker = Worker(roots)
        self.worker.status.connect(self.status.setText)
        self.worker.finished_ok.connect(self.scan_done)
        self.worker.failed.connect(self.scan_failed)
        self.scan_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.progress.show()
        self.worker.start()

    def cancel_scan(self) -> None:
        if self.worker:
            self.worker.cancel.set()
            self.status.setText("Cancelling...")

    def _finish_ui(self) -> None:
        self.scan_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.progress.hide()

    def scan_failed(self, msg: str) -> None:
        self._finish_ui()
        self.status.setText(f"Scan failed: {msg}")

    def scan_done(self, analysis: Analysis | None) -> None:
        self._finish_ui()
        if analysis is None:
            self.status.setText("Scan cancelled.")
            return
        self.analysis = analysis
        s = analysis.scan
        self.status.setText(f"Done: {s.files_seen:,} files, {fmt_size(s.total_size)} scanned"
                            f"{f', {s.errors:,} unreadable items skipped' if s.errors else ''}.")
        self.fill_summary()
        self.populate_table()
        self.populate_tree()
        self.treemap.set_analysis(analysis)
        self.refresh_recycle()

    def fill_summary(self) -> None:
        a = self.analysis
        if not a:
            return
        self.card_bad[1].setText(fmt_size(a.total(BAD)))
        self.card_review[1].setText(fmt_size(a.total(REVIEW)))
        self.card_important[1].setText(fmt_size(a.important_bytes))
        self.card_good[1].setText(fmt_size(a.good_bytes))
        self.top_table.setRowCount(len(a.top_dirs))
        for r, (p, size) in enumerate(a.top_dirs):
            label = label_for_dir(p, a.flagged_dirs)
            lab = QTableWidgetItem(label)
            lab.setForeground(QBrush(LABEL_COLORS[label]))
            self.top_table.setItem(r, 0, QTableWidgetItem(p))
            self.top_table.setItem(r, 1, QTableWidgetItem(fmt_size(size)))
            self.top_table.setItem(r, 2, lab)
        rows = a.by_category()
        self.cat_table.setRowCount(len(rows))
        for r, (cat, label, n, size) in enumerate(rows):
            lab = QTableWidgetItem(label)
            lab.setForeground(QBrush(LABEL_COLORS[label]))
            self.cat_table.setItem(r, 0, QTableWidgetItem(cat))
            self.cat_table.setItem(r, 1, lab)
            self.cat_table.setItem(r, 2, QTableWidgetItem(str(n)))
            self.cat_table.setItem(r, 3, QTableWidgetItem(fmt_size(size)))

    def closeEvent(self, e) -> None:  # noqa: N802
        if self.worker and self.worker.isRunning():
            self.worker.cancel.set()
            self.worker.wait(5000)
        e.accept()

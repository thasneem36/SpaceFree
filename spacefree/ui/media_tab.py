"""Media tab: browse every image, video and audio file found, with a real preview."""
from __future__ import annotations

import os
import time
from typing import Callable

from PyQt6.QtCore import QSize, Qt, QTimer, QUrl
from PyQt6.QtGui import QBrush, QImageReader, QPixmap
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
from PyQt6.QtMultimediaWidgets import QVideoWidget
from PyQt6.QtWidgets import (
    QComboBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPushButton, QSlider,
    QSplitter, QStackedWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..advisor import DELETE, EDUCATIONAL, KEEP, Advice
from ..advisor import REVIEW as V_REVIEW
from ..filetypes import AUDIO, IMAGE, MEDIA_TYPES, VIDEO, type_of
from ..models import FileRec, fmt_size
from .theme import VERDICT_COLORS
from .util import NumItem, open_file, open_in_explorer

LIVE_CAP = 20000
FINAL_CAP = 50000
BATCH = 400
PREVIEW_MAX = 1600


def _fmt_time(ms: int) -> str:
    s = max(0, ms // 1000)
    return f"{s // 60}:{s % 60:02d}"


class MediaTab(QWidget):
    def __init__(self, trash_cb: Callable[[list[tuple[str, int, str]]], None]) -> None:
        super().__init__()
        self._trash_cb = trash_cb
        self._backlog: list[FileRec] = []
        self._rows = 0
        self._final = False
        self._checked_restore: set[str] = set()
        self.advice: dict[str, Advice] = {}

        v = QVBoxLayout(self)
        bar = QHBoxLayout()
        self.type_box = QComboBox()
        self.type_box.addItems(["All media", IMAGE, VIDEO, AUDIO])
        self.verdict_box = QComboBox()
        self.verdict_box.addItems(["Any verdict", DELETE, V_REVIEW, KEEP, EDUCATIONAL])
        self.verdict_box.currentIndexChanged.connect(self.apply_filters)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search name or folder...")
        self.count = QLabel("")
        self.count.setObjectName("muted")
        self.type_box.currentIndexChanged.connect(self.apply_filters)
        self.search.textChanged.connect(self.apply_filters)
        bar.addWidget(QLabel("Show:"))
        bar.addWidget(self.type_box)
        bar.addWidget(self.verdict_box)
        bar.addWidget(self.search, 1)
        bar.addWidget(self.count)
        v.addLayout(bar)

        split = QSplitter(Qt.Orientation.Horizontal)
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(["", "Type", "Name", "Size", "Modified", "Folder", "Verdict"])
        h = self.table.horizontalHeader()
        h.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        h.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(0, 34)
        self.table.setColumnWidth(2, 240)
        self.table.setColumnWidth(6, 90)
        self.table.verticalHeader().hide()
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.itemSelectionChanged.connect(self.show_preview)
        self.table.itemChanged.connect(self.update_selected_label)
        self.table.cellDoubleClicked.connect(lambda r, _c: self.open_folder())
        split.addWidget(self.table)
        split.addWidget(self._build_preview())
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        v.addWidget(split, 1)

        foot = QHBoxLayout()
        self.folder_btn = QPushButton("Open folder")
        self.folder_btn.clicked.connect(self.open_folder)
        self.file_btn = QPushButton("Open file")
        self.file_btn.clicked.connect(self.open_selected_file)
        foot.addWidget(self.folder_btn)
        foot.addWidget(self.file_btn)
        foot.addStretch(1)
        self.sel_label = QLabel("Selected: 0 files, 0 B")
        foot.addWidget(self.sel_label)
        self.trash_btn = QPushButton("Move selected to Recycle Bin")
        self.trash_btn.setObjectName("danger")
        self.trash_btn.clicked.connect(self.trash_checked)
        foot.addWidget(self.trash_btn)
        v.addLayout(foot)

        self.flush_timer = QTimer(self)
        self.flush_timer.timeout.connect(self._flush)

    # ---------- preview ----------
    def _build_preview(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        self.stack = QStackedWidget()
        self.placeholder = QLabel("Select a file to preview it")
        self.placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.placeholder.setObjectName("muted")
        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.video = QVideoWidget()
        self.audio_label = QLabel("Audio")
        self.audio_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.audio_label.setStyleSheet("font-size: 56px;")
        for widget in (self.placeholder, self.image_label, self.video, self.audio_label):
            self.stack.addWidget(widget)
        v.addWidget(self.stack, 1)

        self.info = QLabel("")
        self.info.setWordWrap(True)
        self.info.setObjectName("muted")
        v.addWidget(self.info)

        ctl = QHBoxLayout()
        self.play_btn = QPushButton("Play")
        self.play_btn.clicked.connect(self.toggle_play)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.sliderMoved.connect(lambda ms: self.player.setPosition(ms))
        self.time_label = QLabel("0:00 / 0:00")
        ctl.addWidget(self.play_btn)
        ctl.addWidget(self.slider, 1)
        ctl.addWidget(self.time_label)
        self.controls = QWidget()
        self.controls.setLayout(ctl)
        ctl.setContentsMargins(0, 0, 0, 0)
        v.addWidget(self.controls)
        self.controls.hide()

        self.player = QMediaPlayer(self)
        self.audio_out = QAudioOutput(self)
        self.player.setAudioOutput(self.audio_out)
        self.player.setVideoOutput(self.video)
        self.player.positionChanged.connect(self._on_pos)
        self.player.durationChanged.connect(lambda d: self.slider.setRange(0, d))
        self.player.playbackStateChanged.connect(
            lambda s: self.play_btn.setText("Pause" if s == QMediaPlayer.PlaybackState.PlayingState else "Play"))
        self.player.errorOccurred.connect(lambda _e, msg: self.info.setText(f"Cannot play this file: {msg}"))
        return w

    def _on_pos(self, pos: int) -> None:
        if not self.slider.isSliderDown():
            self.slider.setValue(pos)
        self.time_label.setText(f"{_fmt_time(pos)} / {_fmt_time(self.player.duration())}")

    def toggle_play(self) -> None:
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def current_rec(self) -> FileRec | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        return self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)

    def show_preview(self) -> None:
        try:
            self._show_preview()
        except Exception as e:  # noqa: BLE001 - a bad file must not crash the app
            self.info.setText(f"Cannot preview: {e}")

    def _show_preview(self) -> None:
        rec = self.current_rec()
        self.player.stop()
        if rec is None:
            return
        kind = type_of(os.path.splitext(rec.path)[1].lower())
        self.info.setText(f"{rec.path}\n{fmt_size(rec.size)}")
        if kind == IMAGE:
            self.controls.hide()
            reader = QImageReader(rec.path)
            reader.setAutoTransform(True)
            size = reader.size()
            if size.isValid() and max(size.width(), size.height()) > PREVIEW_MAX:
                size.scale(PREVIEW_MAX, PREVIEW_MAX, Qt.AspectRatioMode.KeepAspectRatio)
                reader.setScaledSize(size)
            img = reader.read()
            if img.isNull():
                self.image_label.setText("Preview not available for this image format")
                self.image_label.setPixmap(QPixmap())
            else:
                pix = QPixmap.fromImage(img).scaled(
                    self.stack.size() - QSize(10, 10), Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation)
                self.image_label.setPixmap(pix)
            self.stack.setCurrentWidget(self.image_label)
            return
        self.controls.show()
        self.stack.setCurrentWidget(self.video if kind == VIDEO else self.audio_label)
        self.player.setSource(QUrl.fromLocalFile(rec.path))
        self.player.pause()  # shows the first frame for video without starting playback

    # ---------- table ----------
    def clear(self) -> None:
        self.player.stop()
        self.player.setSource(QUrl())
        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        self._backlog.clear()
        self._rows = 0
        self._final = False
        self.stack.setCurrentWidget(self.placeholder)
        self.controls.hide()
        self.info.setText("")
        self.update_count()

    def enqueue(self, recs: list[FileRec]) -> None:
        self._backlog.extend(recs)
        if not self.flush_timer.isActive():
            self.flush_timer.start(30)

    def _add_rows(self, recs: list[FileRec]) -> None:
        self.table.blockSignals(True)
        start = self.table.rowCount()
        self.table.setRowCount(start + len(recs))
        for i, rec in enumerate(recs):
            name = os.path.basename(rec.path)
            kind = type_of(os.path.splitext(name)[1].lower())
            chk = QTableWidgetItem()
            chk.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled
                         | Qt.ItemFlag.ItemIsSelectable)
            chk.setCheckState(Qt.CheckState.Checked if rec.path in self._checked_restore
                              else Qt.CheckState.Unchecked)
            chk.setData(Qt.ItemDataRole.UserRole, rec)
            folder = QTableWidgetItem(os.path.dirname(rec.path))
            folder.setToolTip(rec.path)
            items = [chk, QTableWidgetItem(kind), QTableWidgetItem(name), NumItem(fmt_size(rec.size), rec.size),
                     NumItem(time.strftime("%Y-%m-%d", time.localtime(rec.mtime)), rec.mtime), folder,
                     self._verdict_item(rec.path)]
            for c, it in enumerate(items):
                self.table.setItem(start + i, c, it)
        self.table.blockSignals(False)
        self._rows += len(recs)

    def _verdict_item(self, path: str) -> QTableWidgetItem:
        adv = self.advice.get(path)
        it = QTableWidgetItem(adv.verdict if adv else "...")
        if adv:
            it.setForeground(QBrush(VERDICT_COLORS[adv.verdict]))
            it.setToolTip(adv.reason)
        return it

    def _flush(self) -> None:
        cap = FINAL_CAP if self._final else LIVE_CAP
        room = max(0, cap - self._rows)
        if not self._backlog or room == 0:
            self._backlog.clear()
            self.flush_timer.stop()
            if self._final:
                self.table.setSortingEnabled(True)
                self.table.sortItems(3, Qt.SortOrder.DescendingOrder)
                self.apply_filters()
            return
        chunk, self._backlog = self._backlog[:min(BATCH, room)], self._backlog[min(BATCH, room):]
        self._add_rows(chunk)
        self.update_count()

    def finalize(self, all_media: list[FileRec], advice: dict[str, Advice] | None = None) -> None:
        """Scan finished: rebuild with the biggest files first, then enable sorting."""
        checked = {r.path for r in self.checked_recs()}
        self.advice = advice or {}
        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        self._rows = 0
        self._final = True
        self._backlog = sorted(all_media, key=lambda r: r.size, reverse=True)
        self._checked_restore = checked
        self.flush_timer.start(10)
        QTimer.singleShot(0, self.update_count)

    def update_count(self) -> None:
        total = self._rows + len(self._backlog)
        self.count.setText(f"{total:,} media files")

    def apply_filters(self) -> None:
        kind = self.type_box.currentText()
        verdict = self.verdict_box.currentText()
        text = self.search.text().lower()
        shown = 0
        for r in range(self.table.rowCount()):
            rec: FileRec = self.table.item(r, 0).data(Qt.ItemDataRole.UserRole)
            ok = ((kind == "All media" or self.table.item(r, 1).text() == kind) and
                  (verdict == "Any verdict" or self.table.item(r, 6).text() == verdict) and
                  (not text or text in rec.path.lower()))
            self.table.setRowHidden(r, not ok)
            shown += ok
        self.count.setText(f"{shown:,} shown of {self._rows + len(self._backlog):,}")

    def checked_recs(self) -> list[FileRec]:
        out = []
        for r in range(self.table.rowCount()):
            it = self.table.item(r, 0)
            if it.checkState() == Qt.CheckState.Checked:
                out.append(it.data(Qt.ItemDataRole.UserRole))
        return out

    def update_selected_label(self, *_: object) -> None:
        recs = self.checked_recs()
        self.sel_label.setText(f"Selected: {len(recs)} files, {fmt_size(sum(r.size for r in recs))}")

    def open_folder(self) -> None:
        rec = self.current_rec()
        if rec:
            open_in_explorer(rec.path)

    def open_selected_file(self) -> None:
        rec = self.current_rec()
        if rec:
            open_file(rec.path)

    def trash_checked(self) -> None:
        recs = self.checked_recs()
        if not recs:
            return
        self.player.stop()
        self.player.setSource(QUrl())  # release the file handle before deleting
        self._trash_cb([(r.path, r.size, self.advice[r.path].verdict if r.path in self.advice else KEEP)
                        for r in recs])

    def remove_paths(self, paths: set[str]) -> None:
        self.table.blockSignals(True)
        for r in range(self.table.rowCount() - 1, -1, -1):
            if self.table.item(r, 0).data(Qt.ItemDataRole.UserRole).path in paths:
                self.table.removeRow(r)
                self._rows -= 1
        self.table.blockSignals(False)
        self.update_selected_label()
        self.apply_filters()

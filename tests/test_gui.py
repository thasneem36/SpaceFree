import os
import sys
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
PyQt6 = pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication, QCheckBox  # noqa: E402

from spacefree.scanner import Drive  # noqa: E402
from spacefree.ui.main_window import MainWindow  # noqa: E402


def _png(path, size=30000):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + os.urandom(size))


def test_live_scan_fills_every_tab(tmp_path, monkeypatch):
    monkeypatch.setattr("spacefree.analysis.DUP_SKIP_PARTS", ())
    monkeypatch.setattr("spacefree.scanner.MEDIA_SKIP_PARTS", ())
    monkeypatch.setattr("spacefree.scanner.safety.is_protected", lambda p: False)
    for i in range(5):
        _png(str(tmp_path / "pics" / f"{i}.png"))
    os.makedirs(tmp_path / "proj" / "__pycache__")
    (tmp_path / "proj" / "__pycache__" / "m.pyc").write_bytes(os.urandom(2 * 1024 * 1024))

    app = QApplication.instance() or QApplication(sys.argv)
    w = MainWindow()
    cb = QCheckBox()
    cb.setChecked(True)
    w.drive_boxes = [(cb, Drive(str(tmp_path), 1, 1, 0, True))]
    w.start_scan()
    deadline = time.time() + 30
    while w.scanning and time.time() < deadline:
        app.processEvents()
        time.sleep(0.02)
    for _ in range(200):  # let the media tab finish its batched fill
        app.processEvents()
        time.sleep(0.01)

    assert not w.scanning and w.analysis is not None
    assert w.table.rowCount() >= 1
    assert any(w.finding_at(r).category == "Dev cache" for r in range(w.table.rowCount()))
    assert w.media_tab.table.rowCount() == 5
    assert w.type_table.rowCount() > 0
    assert w.tree.topLevelItemCount() == 1
    # advisor: the __pycache__ is Delete, and the tab + verdict columns are filled in
    assert w.advice and w.advisor_tab.tree.topLevelItemCount() == 4
    assert w.advisor_tab.delete_btn.isEnabled()
    assert any(w.table.item(r, 1).text() == "Delete" for r in range(w.table.rowCount()))
    assert w.media_tab.table.item(0, 6).text() in ("Keep", "Review", "Delete", "Educational")
    w.media_tab.table.selectRow(0)
    app.processEvents()
    assert w.media_tab.image_label.pixmap() is not None

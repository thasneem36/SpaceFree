import os
import time

import pytest

from spacefree import cleaner, safety
from spacefree.analysis import analyze
from spacefree.duplicates import find_duplicates
from spacefree.models import BAD, MB, REVIEW, FileRec
from spacefree.rules import classify_dir, classify_file
from spacefree.scanner import scan
from spacefree.treemap import squarify


def make(path, size):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(os.urandom(min(size, 1024)) + b"\0" * max(0, size - 1024))


def old(path, days):
    t = time.time() - days * 86400
    os.utime(path, (t, t))


def test_scan_sizes(tmp_path):
    make(str(tmp_path / "a" / "x.bin"), 3 * MB)
    make(str(tmp_path / "a" / "b" / "y.bin"), 2 * MB)
    make(str(tmp_path / "z.bin"), 1000)
    r = scan([str(tmp_path)], workers=4)
    assert r.nodes[str(tmp_path)].size == 5 * MB + 1000
    assert r.nodes[str(tmp_path / "a")].size == 5 * MB
    assert len(r.big_files) == 2


def test_protected_paths():
    assert safety.is_protected(r"C:\Windows\System32")
    assert safety.is_protected(r"D:\Program Files\App")
    assert safety.is_protected("C:\\")
    assert not safety.is_protected(r"C:\Windows\Temp\junk")
    assert not safety.is_protected(r"C:\Users\me\Downloads\a.exe")
    assert safety.is_critical_dir(r"C:\Users\me\Documents")
    assert safety.is_critical_dir(r"C:\Users\me\AppData\Local")
    assert not safety.is_critical_dir(r"C:\Users\me\AppData\Local\Temp")
    assert safety.is_personal(r"C:\Users\me\Pictures\trip\a.jpg")


def test_dir_rules(tmp_path):
    from spacefree.models import DirNode
    n = DirNode(r"C:\proj\__pycache__", "__pycache__", r"C:\proj", time.time(), size=5 * MB)
    assert classify_dir(n.path, n).label == BAD
    n = DirNode(r"C:\Users\me\AppData\Local\Temp", "Temp", "x", time.time(), size=5 * MB)
    assert classify_dir(n.path, n).label == BAD
    n = DirNode(r"C:\proj\node_modules", "node_modules", "x", time.time(), size=5 * MB)
    assert classify_dir(n.path, n).label == REVIEW  # recently used project
    n.mtime = time.time() - 400 * 86400
    assert classify_dir(n.path, n).label == BAD


def test_file_rules():
    now = time.time()
    f = classify_file(FileRec(r"C:\Users\me\Downloads\setup.exe", 50 * MB, now - 90 * 86400, now - 90 * 86400))
    assert f.label == BAD
    f = classify_file(FileRec(r"C:\Users\me\Downloads\setup.exe", 50 * MB, now, now))
    assert f is None
    f = classify_file(FileRec(r"C:\Users\me\Documents\big.tmp", 50 * MB, now, now))
    assert f.label == REVIEW  # personal files are never "safe"
    f = classify_file(FileRec(r"C:\Windows\x\big.tmp", 50 * MB, now, now))
    assert f is None  # protected
    f = classify_file(FileRec("C:\\hiberfil.sys", 4000 * MB, now, now))
    assert f and not f.deletable


def test_duplicates(tmp_path):
    a, b, c = (str(tmp_path / n) for n in ("a.bin", "b.bin", "c.bin"))
    for p in (a, b):
        with open(p, "wb") as f:
            f.write(b"same" * (MB // 4))
    with open(c, "wb") as f:
        f.write(b"diff" * (MB // 4))
    recs = [FileRec(p, os.path.getsize(p), 0, 0) for p in (a, b, c)]
    groups = find_duplicates(recs)
    assert len(groups) == 1 and {r.path for r in groups[0]} == {a, b}


def test_analyze_end_to_end(tmp_path, monkeypatch):
    monkeypatch.setattr("spacefree.analysis.DUP_SKIP_PARTS", ())  # pytest tmp lives in AppData
    make(str(tmp_path / "proj" / "__pycache__" / "m.pyc"), 3 * MB)
    make(str(tmp_path / "keep" / "one.dat"), 2 * MB)
    with open(tmp_path / "keep" / "two.dat", "wb") as f:
        f.write((tmp_path / "keep" / "one.dat").read_bytes())
    result = scan([str(tmp_path)], workers=4)
    a = analyze(result)
    cats = {f.category for f in a.findings}
    assert "Dev cache" in cats and "Duplicate" in cats
    assert a.total(BAD) == 5 * MB


def test_cleaner_refuses_protected(tmp_path):
    ok, failed = cleaner.move_to_trash([r"C:\Windows\System32\kernel32.dll"])
    assert not ok and failed


def test_cleaner_trashes(tmp_path, monkeypatch):
    p = tmp_path / "f.bin"
    p.write_bytes(b"x")
    trashed = []
    monkeypatch.setattr(cleaner, "send2trash", trashed.append)
    ok, failed = cleaner.move_to_trash([str(p)])
    assert ok == [str(p)] and trashed == [str(p)] and not failed


@pytest.mark.parametrize("values", [[6, 6, 4, 3, 2, 2, 1], [1], [5, 5]])
def test_treemap_covers_area(values):
    rects = squarify(values, 0, 0, 100, 60)
    assert len(rects) == len(values)
    assert sum(w * h for _, _, w, h in rects) == pytest.approx(100 * 60)
    for x, y, w, h in rects:
        assert x >= -1e-6 and y >= -1e-6 and x + w <= 100 + 1e-6 and y + h <= 60 + 1e-6

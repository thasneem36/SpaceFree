from spacefree.advisor import DELETE, EDUCATIONAL, KEEP, REVIEW, Item, advise_one
from spacefree.models import BAD, MB, REVIEW as R_LABEL

U = r"C:\Users\me"


def v(path, **kw):
    kw.setdefault("size", 50 * MB)
    return advise_one(Item(path, **kw))


def test_course_video_is_educational():
    a = v(rf"{U}\OneDrive\Desktop\course\Adobe Premiere Pro Audio\lesson 01.mp4", category="Media", label="Good")
    assert a.verdict == EDUCATIONAL and a.educational.p >= 0.6


def test_duplicate_inside_course_needs_review_not_delete():
    a = v(rf"{U}\OneDrive\Desktop\course\Premiere\clip copy.mp4", category="Duplicate", label=R_LABEL,
          reason="Identical copy of x")
    assert a.verdict == REVIEW and "learning" in a.reason.lower()


def test_cache_is_delete():
    a = v(rf"{U}\AppData\Local\Temp", is_dir=True, category="Temp files", label=BAD,
          reason="Temporary files left behind by apps. Safe to remove.")
    assert a.verdict == DELETE and a.recreatable.p >= 0.8 and a.irreplaceable.p <= 0.3


def test_stale_node_modules_delete_recent_review():
    old = v(rf"C:\proj\node_modules", is_dir=True, category="node_modules", label=BAD, reason="Reinstall with npm install")
    new = v(rf"C:\proj2\node_modules", is_dir=True, category="node_modules", label=R_LABEL)
    assert old.verdict == DELETE and new.verdict == REVIEW


def test_personal_photo_is_keep():
    a = v(rf"{U}\Pictures\trip\IMG_1.jpg", category="Media", label="Good", age_days=400)
    assert a.verdict == KEEP


def test_tax_pdf_is_keep():
    a = v(rf"{U}\Documents\tax_return_2025.pdf", label="Good", age_days=10)
    assert a.verdict == KEEP


def test_old_installer_delete():
    a = v(rf"{U}\Downloads\setup.exe", category="Old installer / archive", label=BAD,
          reason="Installer in Downloads, untouched for 90 days.", age_days=90)
    assert a.verdict == DELETE


def test_duplicate_non_personal_delete_personal_review():
    d = v(r"D:\stuff\a copy.bin", category="Duplicate", label=BAD, reason="Identical copy of D:\\stuff\\a.bin")
    p = v(rf"{U}\Pictures\a copy.jpg", category="Duplicate", label=R_LABEL, reason="Identical copy of x")
    assert d.verdict == DELETE and p.verdict == REVIEW


def test_virtual_disk_and_manual_items_review():
    assert v(r"D:\vm\disk.vhdx", category="Virtual disk", label=R_LABEL, reason="VM disk").verdict == REVIEW
    a = v("C:\\hiberfil.sys", category="System file", label=R_LABEL, deletable=False, reason="Hibernation file.")
    assert a.verdict == REVIEW


def test_answers_are_typed_and_bounded():
    a = v(rf"{U}\Downloads\x.zip", category="Old installer / archive", label=BAD)
    for p in (a.educational.p, a.recreatable.p, a.irreplaceable.p, a.kind.confidence):
        assert 0.0 <= p <= 1.0
    assert abs(sum(a.kind.probs.values()) - 1) < 1e-9 and abs(sum(a.staleness.probs) - 1) < 1e-9


def test_reason_names_the_real_word():
    a = v(r"C:\Users\me\Desktop\course\x\lesson 01.mp4", category="Media", label="Good")
    assert "course" in a.reason and "cours)" not in a.reason

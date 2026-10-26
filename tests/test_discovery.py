from __future__ import annotations

from pathlib import Path

import pytest

from hr_screening.discovery import discover_candidates, load_candidate
from hr_screening.models import ContentKind


def test_subfolder_layout(subfolder_layout: Path):
    result = discover_candidates(subfolder_layout)

    assert result.layout == "subfolders"
    # Natural sort: "Candidate 2" before "Candidate 10"; empty folder skipped.
    assert [c.display_name for c in result.candidates] == [
        "Candidate 2", "Candidate 10", "Jane Doe", "John Smith",
    ]
    assert [c.candidate_id for c in result.candidates] == ["C001", "C002", "C003", "C004"]

    messages = {p.name: m for p, m in ((i.path, i.message) for i in result.issues)}
    assert "no PDF" in messages["Empty Folder"]
    assert ".doc" in messages["old_letter.doc"]


def test_subfolder_candidate_loads_all_files_except_temp_files(subfolder_layout: Path):
    jane = next(c for c in discover_candidates(subfolder_layout).candidates if c.display_name == "Jane Doe")
    load_candidate(jane)
    assert sorted(d.name for d in jane.documents) == ["Cover Letter.docx", "Jane_Doe_CV.pdf"]
    assert jane.has_content and not jane.issues


def test_scanned_and_image_candidates(subfolder_layout: Path):
    candidates = {c.display_name: c for c in discover_candidates(subfolder_layout).candidates}
    assert load_candidate(candidates["John Smith"]).documents[0].kind is ContentKind.PDF
    assert load_candidate(candidates["Candidate 10"]).documents[0].kind is ContentKind.IMAGE


def test_file_layout(file_layout: Path):
    result = discover_candidates(file_layout)
    assert result.layout == "files"
    assert [c.display_name for c in result.candidates] == ["alice", "bob", "carol"]
    assert [i.path.name for i in result.issues] == ["notes.xlsx"]  # Thumbs.db silently ignored
    for c in result.candidates:
        assert load_candidate(c).has_content


def test_mixed_layout(subfolder_layout: Path, file_layout: Path):
    (file_layout / "dave").mkdir()
    (file_layout / "bob_resume.docx").rename(file_layout / "dave" / "cv.docx")
    result = discover_candidates(file_layout)
    assert result.layout == "mixed"
    assert {c.display_name for c in result.candidates} == {"alice", "carol", "dave"}


def test_unreadable_file_is_reported_not_fatal(tmp_path: Path):
    folder = tmp_path / "apps" / "Eve"
    folder.mkdir(parents=True)
    (folder / "cv.pdf").write_bytes(b"garbage")
    (eve,) = discover_candidates(tmp_path / "apps").candidates
    load_candidate(eve)
    assert not eve.has_content
    assert "damaged" in eve.issues[0].message


def test_missing_folder():
    with pytest.raises(NotADirectoryError):
        discover_candidates(Path("C:/definitely/not/here"))

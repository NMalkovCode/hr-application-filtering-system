from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from hr_screening.models import Candidate, Tier
from hr_screening.organizer import create_run_folder, output_name, place_all, pseudonym, safe_filename
from hr_screening.scoring import assign_tiers, needs_review, score_evaluation
from hr_screening.settings import TierThresholds

from .conftest import make_docx, make_text_pdf
from .helpers import OPEN_ROLES, M, N, P, X, evaluation, filter_set


def real_candidate(root: Path, name: str, cid: str, folder: bool = True) -> Candidate:
    if folder:
        (root / name).mkdir(parents=True)
        make_text_pdf(root / name / f"{name} CV.pdf")
        make_docx(root / name / "Cover letter.docx")
        (root / name / "~$Cover letter.docx").write_bytes(b"lock")
        return Candidate(cid, name, root / name)
    root.mkdir(parents=True, exist_ok=True)
    return Candidate(cid, name, make_text_pdf(root / f"{name}.pdf"))


def test_names():
    assert pseudonym("C007") == "Candidate 007"
    assert safe_filename('Jane: "The" Doe?/\\ ') == "Jane The Doe"
    assert safe_filename("CON") == "_CON" and safe_filename("...") == "Unnamed"
    assert len(safe_filename("x" * 200)) == 60


def test_output_name_prefers_folder_name_then_extracted_name(tmp_path: Path):
    folder_c = real_candidate(tmp_path / "a", "Jane Doe", "C001")
    file_c = real_candidate(tmp_path / "b", "cv", "C002", folder=False)
    fr = score_evaluation(folder_c, evaluation([M] * 4, candidate_name="J. Doe"), filter_set())
    rr = score_evaluation(file_c, evaluation([M] * 4, candidate_name="  Bob   Smith "), filter_set())
    assert output_name(fr, False) == "Jane Doe"
    assert output_name(rr, False) == "Bob Smith"
    assert output_name(rr, True) == "Candidate 002"


def test_run_folder_is_unique(tmp_path: Path):
    when = datetime(2026, 10, 26, 9, 30)
    a = create_run_folder(tmp_path, "Senior Data Analyst / BI", when)
    b = create_run_folder(tmp_path, "Senior Data Analyst / BI", when)
    assert a.name == "Senior_Data_Analyst_BI_2026-10-26_0930" and b.name.endswith("_2")


def _tiered(tmp_path: Path):
    apps = tmp_path / "apps"
    specs = [
        ("Amy Top", [M, M, M, M], {}),
        ("Ben Top", [M, M, M, P], dict(alt_id="R01", alt_fit="strong", alt_better=True)),
        ("Cat Backup", [M, P, P, X], {}),
        ("Dan Out", [N, M, M, M], dict(alt_id="R02", alt_fit="strong")),
    ]
    results = []
    for i, (name, res, kw) in enumerate(specs, 1):
        c = real_candidate(apps, name, f"C{i:03d}")
        results.append(score_evaluation(c, evaluation(res, **kw), filter_set(), OPEN_ROLES))
    results.append(needs_review(real_candidate(apps, "Eve Broken", "C005"), "Unreadable"))
    return assign_tiers(results, TierThresholds(80, 65, 50))


def test_place_all_creates_folders_reports_and_copies(tmp_path: Path):
    ordered = _tiered(tmp_path)
    run = tmp_path / "run"
    run.mkdir()
    placements = place_all(ordered, filter_set(), run, other_roles_enabled=True)

    top = run / "Top Match"
    assert sorted(p.name for p in top.iterdir()) == [
        "01_Amy_Top", "01_Amy_Top_Report.docx", "02_Ben_Top", "02_Ben_Top_Report.docx"]
    assert sorted(p.name for p in (top / "01_Amy_Top").iterdir()) == ["Amy Top CV.pdf", "Cover letter.docx"]
    assert (run / "Backup" / "01_Cat_Backup_Report.docx").exists()
    # Not Suitable / Needs Review: copies only, no reports.
    assert [p.name for p in (run / "Not Suitable").iterdir()] == ["01_Dan_Out"]
    assert [p.name for p in (run / "Needs Review").iterdir()] == ["01_Eve_Broken"]
    # Other Role: the eliminated candidate, and the Top Match who suits R01 better (duplicated).
    assert sorted(p.name for p in (run / "Other Role").iterdir()) == [
        "Ben_Top", "Ben_Top_Other_Role_Report.docx", "Dan_Out", "Dan_Out_Other_Role_Report.docx"]
    assert (run / "Close Match").is_dir()
    assert all(not p.errors for p in placements)
    # The original applications are untouched.
    assert (tmp_path / "apps" / "Amy Top" / "Amy Top CV.pdf").exists()


def test_anonymised_mode_renames_everything(tmp_path: Path):
    ordered = _tiered(tmp_path)
    run = tmp_path / "run"
    run.mkdir()
    placements = place_all(ordered, filter_set(), run, anonymised=True, other_roles_enabled=True)
    names = [p.name for p in placements]
    assert names == ["Candidate 001", "Candidate 002", "Candidate 003", "Candidate 004", "Candidate 005"]
    copied = sorted(p.name for p in (run / "Top Match" / "01_Candidate_001").iterdir())
    assert copied == ["Candidate 001 - Document 1.pdf", "Candidate 001 - Document 2.docx"]
    all_names = " ".join(str(p) for p in run.rglob("*"))
    assert "Amy" not in all_names and "Dan" not in all_names


def test_duplicate_names_are_disambiguated(tmp_path: Path):
    a = real_candidate(tmp_path / "x", "John Smith", "C001", folder=False)
    b = real_candidate(tmp_path / "y", "John Smith", "C002", folder=False)
    results = assign_tiers([score_evaluation(c, evaluation([M] * 4, candidate_name="John Smith"), filter_set())
                            for c in (a, b)], TierThresholds())
    run = tmp_path / "run"
    run.mkdir()
    placements = place_all(results, filter_set(), run)
    assert {p.name for p in placements} == {"John Smith (C001)", "John Smith (C002)"}


def test_copy_failure_is_recorded_not_fatal(tmp_path: Path):
    (r,) = assign_tiers([score_evaluation(Candidate("C001", "Ghost", tmp_path / "missing.pdf"),
                                          evaluation([M] * 4), filter_set())], TierThresholds())
    run = tmp_path / "run"
    run.mkdir()
    (p,) = place_all([r], filter_set(), run)
    assert p.errors and p.report is not None

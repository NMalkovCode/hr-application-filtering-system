"""Output-side hardening: long paths, many candidates, folder placement, key store failures."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from hr_screening.models import Candidate
from hr_screening.organizer import place_all
from hr_screening.pipeline import RunRequest, ScreeningPipeline
from hr_screening.llm import ClaudeClient
from hr_screening.scoring import assign_tiers, score_evaluation
from hr_screening.settings import TierThresholds
from hr_screening.system import keep_awake, long_path

from .conftest import make_text_pdf
from .helpers import M, N, evaluation, filter_set


@pytest.mark.skipif(sys.platform != "win32", reason="Windows path rules")
def test_long_path():
    assert long_path(Path("C:/a/b")) == "\\\\?\\C:\\a\\b"
    assert long_path("\\\\?\\C:\\x") == "\\\\?\\C:\\x"
    assert long_path("\\\\server\\share\\x") == "\\\\?\\UNC\\server\\share\\x"


def test_rank_prefix_widens_for_large_tiers(tmp_path: Path):
    apps = tmp_path / "apps"
    apps.mkdir()
    results = []
    for i in range(1, 106):
        c = Candidate(f"C{i:03d}", f"Person {i}", make_text_pdf(apps / f"p{i}.pdf", "x"))
        results.append(score_evaluation(c, evaluation([N, M, M, M], candidate_name=f"Person {i}"), filter_set()))
    run = tmp_path / "run"
    run.mkdir()
    place_all(assign_tiers(results, TierThresholds()), filter_set(), run)
    names = sorted(p.name for p in (run / "Not Suitable").iterdir())
    assert names[0].startswith("001_") and names[-1].startswith("105_") and len(names) == 105


@pytest.mark.skipif(sys.platform != "win32", reason="Windows path rules")
def test_copy_and_report_beyond_260_characters(tmp_path: Path):
    deep_src = tmp_path / ("s" * 60) / ("t" * 60)
    deep_src.mkdir(parents=True)
    pdf = make_text_pdf(tmp_path / "cv.pdf", "x")
    folder = deep_src / ("Candidate " + "n" * 40)
    Path(long_path(folder / ("sub" * 15))).mkdir(parents=True)
    import shutil
    shutil.copy2(pdf, long_path(folder / ("sub" * 15) / ("long_file_name_" * 4 + ".pdf")))

    c = Candidate("C001", "Deep Person", folder)
    (r,) = assign_tiers([score_evaluation(c, evaluation([M] * 4), filter_set())], TierThresholds())
    run = tmp_path / ("r" * 80) / ("u" * 60)
    Path(long_path(run)).mkdir(parents=True)
    (p,) = place_all([r], filter_set(), run)
    assert not p.errors, p.errors
    copied = [x for x in Path(long_path(p.application_dir)).rglob("*.pdf")]
    assert copied and len(str(copied[0])) > 260


def test_results_folder_inside_applications_is_rejected(tmp_path: Path):
    apps = tmp_path / "apps"
    apps.mkdir()
    pipeline = ScreeningPipeline(ClaudeClient("sk-test"))
    for out in (apps, apps / "results"):
        with pytest.raises(ValueError, match="outside the applications folder"):
            pipeline.prepare(RunRequest(applications_dir=apps, output_dir=out, filter_set=filter_set()))


def test_keep_awake_is_safe():
    with keep_awake():
        pass


def test_settings_dialog_survives_key_store_failure(qtbot, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    from hr_screening.ui.context import MemoryKeyStore
    from hr_screening.ui.settings_dialog import SettingsDialog
    from .ui_fakes import make_context

    class BrokenStore(MemoryKeyStore):
        def set(self, key):
            raise RuntimeError("Credential Manager is disabled by policy")

    ctx = make_context(tmp_path, key=None)
    ctx.keys = BrokenStore()
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda _p, _t, text, *a, **k: warnings.append(text))
    dialog = SettingsDialog(ctx)
    qtbot.addWidget(dialog)
    dialog.key_edit.setText("sk-ant-abc-123456789")
    dialog._save()
    assert warnings and "disabled by policy" in warnings[0]
    assert dialog.result() != SettingsDialog.DialogCode.Accepted

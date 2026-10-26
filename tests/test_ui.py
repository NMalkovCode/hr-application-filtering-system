"""Drive the real window through the whole workflow with a fake Claude."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox

from hr_screening import filter_cache
from hr_screening.models import Tier
from hr_screening.settings import Settings
from hr_screening.ui import main_window as mw
from hr_screening.ui.filters_page import COL_CRITERION, COL_TYPE, COL_WEIGHT
from hr_screening.ui.main_window import MainWindow
from hr_screening.ui.settings_dialog import SettingsDialog

from .ui_fakes import make_context, make_inputs

JD_TEXT = "We are hiring a Data Analyst. 5+ years SQL essential. Degree required. Python nice to have."


@pytest.fixture(autouse=True)
def isolated_appdata(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))


@pytest.fixture
def window(qtbot, tmp_path):
    w = MainWindow(make_context(tmp_path))
    qtbot.addWidget(w)
    w.show()
    return w


def answer(monkeypatch, button=QMessageBox.StandardButton.Yes):
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: button)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: QMessageBox.StandardButton.Ok)
    errors = []
    monkeypatch.setattr(QMessageBox, "critical", lambda _parent, _title, text, *a, **k: errors.append(text))
    return errors


def analyse(qtbot, w):
    w.jd_page.text.setPlainText(JD_TEXT)
    qtbot.mouseClick(w.jd_page.analyse_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: w.stack.currentIndex() == mw.STEP_FILTERS, timeout=10_000)


def test_full_workflow(qtbot, window, tmp_path, monkeypatch):
    answer(monkeypatch)
    w = window
    analyse(qtbot, w)

    # Step 2: proposed filters and warnings are shown; HR edits and adds a filter.
    fp = w.filters_page
    assert fp.table.rowCount() == 4
    assert fp.job_title.text() == "Data Analyst"
    assert "Native English speaker" in fp.warnings.label.text()
    fp.table.cellWidget(2, COL_WEIGHT).setValue(4)
    fp.add_filter()
    fp.verify_button.click()
    assert "Filter 5 has no criterion text." in fp.errors.label.text()
    assert w.stack.currentIndex() == mw.STEP_FILTERS
    fp.table.item(4, COL_CRITERION).setText("Power BI dashboards")
    fp.verify_button.click()
    assert w.stack.currentIndex() == mw.STEP_SETUP
    assert len(filter_cache.list_filter_sets(w.ctx.cache_base)) == 1     # saved on Verify

    # Step 3: folders, other roles from a folder, anonymised off.
    apps, roles = make_inputs(tmp_path)
    sp = w.setup_page
    sp.apps.set_path(str(apps))
    assert "Found 4 applications (one subfolder per candidate)" in sp.apps_info.text()
    sp.output.set_path(str(tmp_path / "results"))
    sp.radio_folder.setChecked(True)
    sp.careers_folder.set_path(str(roles))
    sp.start_button.click()

    qtbot.waitUntil(lambda: w.stack.currentIndex() == mw.STEP_RESULTS, timeout=30_000)
    rp = w.results_page
    outcome = rp.outcome
    assert outcome.count(Tier.TOP) == 1 and outcome.count(Tier.CLOSE) == 1
    assert outcome.count(Tier.NOT_SUITABLE) == 1 and outcome.count(Tier.NEEDS_REVIEW) == 1
    assert rp.card_values["Other Role"].text() == "1"
    assert rp.table.rowCount() == 4
    assert (outcome.run_dir / "Top Match" / "01_Alice_Shah_Report.docx").exists()
    assert (outcome.run_dir / "Other Role" / "Carol_White_Other_Role_Report.docx").exists()
    assert outcome.placements[0].result.scored[4].filter.criterion == "Power BI dashboards"

    # Choices are remembered for next time.
    saved = Settings.load(w.ctx.settings_path)
    assert saved.careers_folder == str(roles) and saved.output_dir == str(tmp_path / "results")

    # "Screen more applications for this role" returns to step 3 with the same filters.
    rp.same_role.emit()
    assert w.stack.currentIndex() == mw.STEP_SETUP and sp.filter_set.filters[4].criterion == "Power BI dashboards"


def test_saved_filters_are_offered_for_the_same_job_description(qtbot, window, monkeypatch):
    answer(monkeypatch)
    w = window
    analyse(qtbot, w)
    w.filters_page.verify_button.click()
    w.new_screening()

    calls_before = []
    monkeypatch.setattr(w.ctx, "make_client", lambda: calls_before.append(1))   # must not be needed
    w.jd_page.text.setPlainText("  " + JD_TEXT.upper() + "  ")
    w.jd_page.analyse_button.click()
    assert w.stack.currentIndex() == mw.STEP_FILTERS and not calls_before


def test_validation_on_setup_page(qtbot, window, monkeypatch):
    answer(monkeypatch)
    w = window
    analyse(qtbot, w)
    w.filters_page.verify_button.click()
    sp = w.setup_page
    sp.radio_url.setChecked(True)
    sp.top.setValue(40)
    sp.start_button.click()
    text = sp.errors.label.text()
    assert "applications" in text and "careers page URL" in text and "Thresholds" in text
    assert w.stack.currentIndex() == mw.STEP_SETUP


def test_type_change_updates_counts(qtbot, window, monkeypatch):
    answer(monkeypatch)
    analyse(qtbot, window)
    fp = window.filters_page
    assert fp.counts.text().startswith("2 must-have · 2 preferred")
    fp.table.cellWidget(3, COL_TYPE).setCurrentIndex(0)
    assert fp.counts.text().startswith("3 must-have · 1 preferred")


def test_analysis_error_is_shown(qtbot, window, monkeypatch):
    w = window
    w.jd_page.analyse_button.click()
    assert "Paste a job description" in w.jd_page.error.label.text()


def test_missing_key_opens_settings(qtbot, tmp_path, monkeypatch):
    w = MainWindow(make_context(tmp_path, key=None))
    qtbot.addWidget(w)
    opened = []
    answer(monkeypatch)
    monkeypatch.setattr(w, "open_settings", lambda first_run=False: opened.append(1) or False)
    w.jd_page.text.setPlainText("Some brand new job description text")
    w.jd_page.analyse_button.click()
    assert opened and w.stack.currentIndex() == mw.STEP_JD


def test_spending_limit_warning(qtbot, window, tmp_path, monkeypatch):
    answer(monkeypatch)
    w = window
    w.ctx.settings.spending_limit_usd = 0.0001
    shown = []
    monkeypatch.setattr(QMessageBox, "exec", lambda self: shown.append(self.text()) or 0)
    analyse(qtbot, w)
    w.filters_page.verify_button.click()
    apps, _ = make_inputs(tmp_path)
    w.setup_page.apps.set_path(str(apps))
    w.setup_page.output.set_path(str(tmp_path / "results"))
    w.setup_page.radio_none.setChecked(True)
    w.setup_page.start_button.click()
    qtbot.waitUntil(lambda: w.stack.currentIndex() == mw.STEP_RESULTS, timeout=30_000)
    assert shown and "spending limit of $0.00" in shown[0]


def test_settings_dialog_saves_and_clears_cache(qtbot, tmp_path, monkeypatch):
    ctx = make_context(tmp_path, key=None)
    filter_cache.save_filter_set([], __import__("tests.helpers", fromlist=["filter_set"]).filter_set(),
                                 ctx.cache_base, fp="abc", excerpt="")
    answer(monkeypatch)
    dialog = SettingsDialog(ctx)
    qtbot.addWidget(dialog)
    dialog.key_edit.setText("sk-ant-new-key-abcdef")
    dialog.model.setCurrentIndex(dialog.model.findData("claude-sonnet-5-5"))
    dialog.limit.setValue(25)
    dialog._clear_cache()
    assert filter_cache.list_filter_sets(ctx.cache_base) == []
    dialog._save()
    assert ctx.keys.get() == "sk-ant-new-key-abcdef"
    saved = Settings.load(ctx.settings_path)
    assert saved.model == "claude-sonnet-5-5" and saved.spending_limit_usd == 25


def test_settings_key_test(qtbot, tmp_path, monkeypatch):
    ctx = make_context(tmp_path)
    dialog = SettingsDialog(ctx)
    qtbot.addWidget(dialog)
    monkeypatch.setattr("hr_screening.llm.ClaudeClient.check_access", lambda self: None)
    dialog._test_key()
    qtbot.waitUntil(lambda: "key works" in dialog.key_status.text(), timeout=5_000)

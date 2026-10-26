from __future__ import annotations

from pathlib import Path

from hr_screening.selftest import run_self_test


def test_self_test_passes(qtbot, tmp_path: Path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))   # restored after the test
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    report = tmp_path / "report.txt"
    assert run_self_test(report) == 0
    text = report.read_text(encoding="utf-8")
    assert "RESULT: OK" in text and text.count("[PASS]") == 5

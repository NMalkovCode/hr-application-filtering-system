from __future__ import annotations

import json
from pathlib import Path

import pytest

from hr_screening import config, settings as settings_mod
from hr_screening.settings import Settings, TierThresholds


def test_round_trip(tmp_path: Path):
    path = tmp_path / "settings.json"
    s = Settings(model="claude-sonnet-5-5", thresholds=TierThresholds(85, 70, 55),
                 spending_limit_usd=25.0, anonymised_mode=True, careers_url="https://x.test/jobs")
    s.save(path)
    assert Settings.load(path) == s


def test_missing_or_corrupt_file_gives_defaults(tmp_path: Path):
    assert Settings.load(tmp_path / "nope.json") == Settings()
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert Settings.load(bad) == Settings()


def test_invalid_values_are_repaired(tmp_path: Path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({
        "model": "gpt-9", "thresholds": {"top": 40, "close": 60, "backup": 50},
        "concurrency": 999, "unknown_key": 1,
    }), encoding="utf-8")
    s = Settings.load(path)
    assert s.model == config.DEFAULT_MODEL
    assert s.thresholds == TierThresholds()
    assert s.concurrency == 16


def test_invalid_thresholds_cannot_be_saved(tmp_path: Path):
    with pytest.raises(ValueError):
        Settings(thresholds=TierThresholds(top=60, close=70, backup=50)).save(tmp_path / "s.json")


def test_api_key_round_trip(monkeypatch):
    monkeypatch.setattr(config, "KEYRING_SERVICE", "HRScreeningTool.TEST-ONLY")
    try:
        settings_mod.set_api_key("  sk-ant-test-1234567890abcd  ")
        assert settings_mod.get_api_key() == "sk-ant-test-1234567890abcd"
        assert settings_mod.mask_api_key(settings_mod.get_api_key()) == "sk-ant-…abcd"
    finally:
        settings_mod.delete_api_key()
    assert settings_mod.get_api_key() is None

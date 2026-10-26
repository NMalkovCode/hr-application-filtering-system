"""User settings (JSON in %APPDATA%) and the per-user API key (Windows Credential Manager)."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

import keyring
from keyring.errors import KeyringError, PasswordDeleteError

from . import config

log = logging.getLogger(__name__)


@dataclass
class TierThresholds:
    """Minimum score (0-100) for each tier; anything below `backup` is Not Suitable."""

    top: int = 80
    close: int = 65
    backup: int = 50

    def validate(self) -> None:
        if not (0 <= self.backup < self.close < self.top <= 100):
            raise ValueError(
                "Thresholds must satisfy 0 <= Backup < Close Match < Top Match <= 100 "
                f"(got Backup={self.backup}, Close={self.close}, Top={self.top})."
            )


@dataclass
class Settings:
    model: str = config.DEFAULT_MODEL
    thresholds: TierThresholds = field(default_factory=TierThresholds)
    # Per-run budget in USD; a warning is shown if the estimated cost could exceed it.
    spending_limit_usd: float = 10.0
    output_dir: str = ""
    careers_url: str = ""
    careers_folder: str = ""
    anonymised_mode: bool = False
    concurrency: int = 4

    # --- persistence -------------------------------------------------------------

    @classmethod
    def load(cls, path: Path | None = None) -> "Settings":
        path = path or config.settings_path()
        if not path.exists():
            return cls()
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("Could not read settings (%s); using defaults.", exc)
            return cls()
        return cls.from_dict(raw)

    @classmethod
    def from_dict(cls, raw: dict) -> "Settings":
        known = {f.name for f in fields(cls)}
        values = {k: v for k, v in raw.items() if k in known}
        thresholds = values.pop("thresholds", None) or {}
        settings = cls(**values)
        settings.thresholds = TierThresholds(
            **{k: int(v) for k, v in thresholds.items() if k in {"top", "close", "backup"}}
        )
        if settings.model not in config.MODELS:
            settings.model = config.DEFAULT_MODEL
        try:
            settings.thresholds.validate()
        except ValueError:
            settings.thresholds = TierThresholds()
        settings.concurrency = max(1, min(int(settings.concurrency), 16))
        return settings

    def save(self, path: Path | None = None) -> None:
        self.thresholds.validate()
        path = path or config.settings_path()
        path.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")


# --- API key -----------------------------------------------------------------------

def get_api_key() -> str | None:
    try:
        return keyring.get_password(config.KEYRING_SERVICE, config.KEYRING_USERNAME)
    except KeyringError as exc:
        log.error("Could not read API key from the credential store: %s", exc)
        return None


def set_api_key(api_key: str) -> None:
    api_key = api_key.strip()
    if not api_key:
        raise ValueError("API key is empty.")
    keyring.set_password(config.KEYRING_SERVICE, config.KEYRING_USERNAME, api_key)


def delete_api_key() -> None:
    try:
        keyring.delete_password(config.KEYRING_SERVICE, config.KEYRING_USERNAME)
    except PasswordDeleteError:
        pass  # nothing stored


def mask_api_key(api_key: str | None) -> str:
    if not api_key:
        return "(not set)"
    return f"{api_key[:7]}…{api_key[-4:]}" if len(api_key) > 12 else "…"

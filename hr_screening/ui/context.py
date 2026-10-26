"""Everything the UI needs from the outside world, injectable for tests."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .. import settings as settings_mod
from ..llm import ClaudeClient
from ..settings import Settings


class KeyStore:
    """API key in Windows Credential Manager."""

    def get(self) -> str | None:
        return settings_mod.get_api_key()

    def set(self, key: str) -> None:
        settings_mod.set_api_key(key)

    def delete(self) -> None:
        settings_mod.delete_api_key()


class MemoryKeyStore(KeyStore):
    def __init__(self, key: str | None = None):
        self._key = key

    def get(self) -> str | None:
        return self._key

    def set(self, key: str) -> None:
        self._key = key.strip()

    def delete(self) -> None:
        self._key = None


@dataclass
class AppContext:
    settings: Settings = field(default_factory=Settings.load)
    settings_path: Path | None = None              # None = %APPDATA%\HRScreeningTool\settings.json
    cache_base: Path | None = None                 # None = %APPDATA%\HRScreeningTool\cache
    keys: KeyStore = field(default_factory=KeyStore)
    client_factory: Callable[[str, str], ClaudeClient] = ClaudeClient

    def save_settings(self) -> None:
        self.settings.save(self.settings_path)

    def has_api_key(self) -> bool:
        return bool(self.keys.get())

    def make_client(self) -> ClaudeClient:
        return self.client_factory(self.keys.get() or "", self.settings.model)

"""Application-wide constants and paths."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

APP_NAME = "HRScreeningTool"
APP_DISPLAY_NAME = "HR Candidate Screening"

# Credential Manager service name for the per-user API key.
KEYRING_SERVICE = "HRScreeningTool.AnthropicAPIKey"
KEYRING_USERNAME = "default"


def app_data_dir() -> Path:
    """Per-user writable directory (%APPDATA%\\HRScreeningTool on Windows)."""
    base = os.environ.get("APPDATA") or str(Path.home() / ".config")
    path = Path(base) / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def settings_path() -> Path:
    return app_data_dir() / "settings.json"


def cache_dir() -> Path:
    path = app_data_dir() / "cache"
    path.mkdir(parents=True, exist_ok=True)
    return path


# --- Supported application files -------------------------------------------------

PDF_EXTENSIONS = {".pdf"}
DOCX_EXTENSIONS = {".docx"}
TEXT_EXTENSIONS = {".txt"}
# Formats Claude accepts natively.
NATIVE_IMAGE_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}
# Formats converted to PNG before sending.
CONVERTED_IMAGE_EXTENSIONS = {".tif", ".tiff", ".bmp"}
IMAGE_EXTENSIONS = set(NATIVE_IMAGE_TYPES) | CONVERTED_IMAGE_EXTENSIONS

SUPPORTED_EXTENSIONS = PDF_EXTENSIONS | DOCX_EXTENSIONS | TEXT_EXTENSIONS | IMAGE_EXTENSIONS

# Files that are never part of an application (OS / Office artefacts).
IGNORED_FILE_PREFIXES = ("~$", ".")
IGNORED_FILE_NAMES = {"thumbs.db", "desktop.ini"}

# A PDF page with fewer extracted characters than this is treated as a scan.
MIN_TEXT_CHARS_PER_PAGE = 40

# Images are downscaled so the long edge is at most this many pixels.
MAX_IMAGE_EDGE_PX = 1568
# Claude's per-image size limit is 5 MB (base64 adds ~33%), so keep the raw bytes well below.
MAX_IMAGE_BYTES = 3_500_000
# Claude's PDF limit is 32 MB per request; keep a margin for the rest of the request.
MAX_PDF_BYTES = 24_000_000


# --- Models ------------------------------------------------------------------------

@dataclass(frozen=True)
class ModelInfo:
    model_id: str
    label: str
    input_per_mtok: float
    output_per_mtok: float
    cache_read_per_mtok: float


MODELS: dict[str, ModelInfo] = {
    m.model_id: m
    for m in (
        ModelInfo("claude-opus-5-5", "Claude Opus 5.5 (best quality)", 4.00, 20.00, 0.20),
        ModelInfo("claude-sonnet-5-5", "Claude Sonnet 5.5 (balanced)", 2.00, 10.00, 0.20),
        ModelInfo("claude-haiku-5-5", "Claude Haiku 5.5 (lowest cost)", 0.10, 0.50, 0.01),
    )
}
DEFAULT_MODEL = "claude-opus-5-5"

# --- Output ------------------------------------------------------------------------

# Tier folder names are the values of models.Tier.
FOLDER_OTHER_ROLE = "Other Role"

# Applications larger than this (estimated input tokens) are sent to Needs Review instead
# of being truncated.
MAX_APPLICATION_TOKENS = 150_000

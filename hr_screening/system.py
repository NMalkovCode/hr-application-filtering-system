"""Windows-specific helpers: long paths and keeping the PC awake during long runs."""

from __future__ import annotations

import contextlib
import logging
import os
import sys
from pathlib import Path

log = logging.getLogger(__name__)

_ES_CONTINUOUS = 0x80000000
_ES_SYSTEM_REQUIRED = 0x00000001


def long_path(path: Path | str) -> str:
    """Path string that works beyond Windows' 260-character limit (\\\\?\\ prefix)."""
    text = str(Path(path).absolute())
    if sys.platform != "win32" or text.startswith("\\\\?\\"):
        return text
    if text.startswith("\\\\"):                       # UNC share: \\server\share -> \\?\UNC\server\share
        return "\\\\?\\UNC\\" + text[2:]
    return "\\\\?\\" + text


@contextlib.contextmanager
def keep_awake():
    """Stop Windows from going to sleep while a screening runs (the screen may still turn off)."""
    kernel32 = None
    if sys.platform == "win32" and not os.environ.get("HR_SCREENING_NO_KEEP_AWAKE"):
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            kernel32.SetThreadExecutionState(_ES_CONTINUOUS | _ES_SYSTEM_REQUIRED)
        except Exception as exc:  # pragma: no cover - never fatal
            log.info("Could not prevent sleep: %s", exc)
            kernel32 = None
    try:
        yield
    finally:
        if kernel32 is not None:
            kernel32.SetThreadExecutionState(_ES_CONTINUOUS)

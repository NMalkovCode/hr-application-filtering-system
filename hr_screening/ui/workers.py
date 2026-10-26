"""Run slow work (AI calls, file reading) off the UI thread."""

from __future__ import annotations

import logging
from typing import Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from ..extraction import ExtractionError
from ..llm import LLMError
from ..web import CareersError

log = logging.getLogger(__name__)

# Errors whose message is written for HR and can be shown as-is.
FRIENDLY_ERRORS = (LLMError, ExtractionError, CareersError, FileNotFoundError, NotADirectoryError,
                   PermissionError, ValueError)


class TaskSignals(QObject):
    done = Signal(object)
    failed = Signal(str)
    progress = Signal(object)          # free-form progress payload
    status = Signal(str, int, int)     # message, done, total


class Task(QRunnable):
    """Runs `fn(signals)` in the thread pool; emits done(result) or failed(message)."""

    def __init__(self, fn: Callable[[TaskSignals], object]):
        super().__init__()
        self.fn = fn
        self.signals = TaskSignals()
        self.setAutoDelete(False)

    def run(self) -> None:
        try:
            result = self.fn(self.signals)
        except FRIENDLY_ERRORS as exc:
            log.warning("Task failed: %s", exc)
            self.signals.failed.emit(str(exc))
        except Exception as exc:
            log.exception("Unexpected error in background task")
            self.signals.failed.emit(f"Unexpected error: {type(exc).__name__}: {exc}. Details are in the log file.")
        else:
            self.signals.done.emit(result)


class TaskRunner(QObject):
    """Keeps tasks alive until they finish and tracks whether anything is running."""

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(2)
        self._active: set[Task] = set()

    @property
    def busy(self) -> bool:
        return bool(self._active)

    def start(self, fn: Callable[[TaskSignals], object], *, on_done=None, on_failed=None,
              on_progress=None, on_status=None) -> Task:
        task = Task(fn)
        if on_progress:
            task.signals.progress.connect(on_progress)
        if on_status:
            task.signals.status.connect(on_status)
        task.signals.done.connect(lambda result: self._finish(task, on_done, result))
        task.signals.failed.connect(lambda message: self._finish(task, on_failed, message))
        self._active.add(task)
        self._pool.start(task)
        return task

    def _finish(self, task: Task, callback, value) -> None:
        self._active.discard(task)
        if callback:
            callback(value)

    def wait(self, msecs: int = -1) -> bool:
        return self._pool.waitForDone(msecs)

"""Application entry point."""

from __future__ import annotations

import logging
import sys
import traceback
from logging.handlers import RotatingFileHandler
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from .. import __version__, config
from .context import AppContext
from .main_window import MainWindow
from .widgets import apply_theme


def setup_logging() -> str:
    log_dir = config.app_data_dir() / "logs"
    log_dir.mkdir(exist_ok=True)
    path = log_dir / "hr_screening.log"
    handler = RotatingFileHandler(path, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    # Never log request bodies (they contain application content).
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("anthropic").setLevel(logging.WARNING)
    return str(path)


RESOURCES = Path(__file__).resolve().parents[1] / "resources"


def main() -> int:
    if "--self-test" in sys.argv:
        from ..selftest import run_self_test
        args = sys.argv[sys.argv.index("--self-test") + 1:]
        return run_self_test(Path(args[0]) if args else None)

    log_path = setup_logging()
    logging.getLogger(__name__).info("Starting %s %s", config.APP_DISPLAY_NAME, __version__)

    app = QApplication(sys.argv)
    app.setApplicationName(config.APP_DISPLAY_NAME)
    app.setWindowIcon(QIcon(str(RESOURCES / "app.png")))
    apply_theme(app)

    def excepthook(exc_type, exc, tb):
        logging.getLogger(__name__).error("Uncaught error:\n%s", "".join(traceback.format_exception(exc_type, exc, tb)))
        QMessageBox.critical(None, "Unexpected error",
                             f"{exc_type.__name__}: {exc}\n\nDetails were written to:\n{log_path}")

    sys.excepthook = excepthook

    window = MainWindow(AppContext())
    window.show()
    if not window.ctx.has_api_key():
        QTimer.singleShot(200, lambda: window.open_settings(first_run=True))
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())

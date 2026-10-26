"""Step 1: the job description (pasted text and/or a file)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit,
    QVBoxLayout, QWidget,
)

from .. import filter_cache
from ..extraction import ExtractionError
from ..jd_analyzer import load_job_description
from ..models import ContentKind, SourceDocument
from .widgets import Banner, button, card, muted, section, title

JD_FILE_FILTER = "Job descriptions (*.pdf *.docx *.txt *.png *.jpg *.jpeg *.tif *.tiff *.bmp *.webp)"


class JobDescriptionPage(QWidget):
    analyse_requested = Signal()
    saved_requested = Signal()

    def __init__(self):
        super().__init__()
        self._file_docs: list[SourceDocument] = []
        self._file_path: Path | None = None

        layout = QVBoxLayout(self)
        layout.addWidget(title("Job description",
                               "Paste the job description or load it from a file. The tool proposes screening "
                               "filters from it, which you can check and edit in the next step."))

        box, box_layout = card()
        box_layout.addWidget(section("Paste the job description"))
        self.text = QPlainTextEdit()
        self.text.setPlaceholderText("Paste the full job description here…")
        box_layout.addWidget(self.text, 1)

        file_row = QHBoxLayout()
        file_row.addWidget(QLabel("…or load a file:"))
        self.file_label = muted("No file loaded")
        file_row.addWidget(self.file_label, 1)
        self.clear_file_button = button("Remove file", on_click=self.clear_file)
        self.clear_file_button.hide()
        file_row.addWidget(self.clear_file_button)
        file_row.addWidget(button("Load file…", on_click=self._choose_file))
        box_layout.addLayout(file_row)
        layout.addWidget(box, 1)

        self.error = Banner(error=True)
        layout.addWidget(self.error)

        actions = QHBoxLayout()
        actions.addWidget(button("Use saved filters…", on_click=self.saved_requested.emit))
        actions.addStretch(1)
        self.busy_label = muted()
        actions.addWidget(self.busy_label)
        self.analyse_button = button("Analyse job description  →", "Primary", on_click=self._analyse)
        actions.addWidget(self.analyse_button)
        layout.addLayout(actions)

    # --- public ------------------------------------------------------------------

    def documents(self) -> list[SourceDocument]:
        docs = list(self._file_docs)
        text = self.text.toPlainText().strip()
        if text:
            docs.insert(0, SourceDocument(path=Path("pasted text"), kind=ContentKind.TEXT, text=text))
        return docs

    def set_busy(self, busy: bool, message: str = "") -> None:
        self.analyse_button.setEnabled(not busy)
        self.text.setReadOnly(busy)
        self.busy_label.setText(message if busy else "")

    def show_error(self, message: str) -> None:
        self.error.show_messages([message] if message else [])

    def load_file(self, path: Path) -> None:
        try:
            self._file_docs = load_job_description(path)
        except ExtractionError as exc:
            self.show_error(f"Could not read {path.name}: {exc}")
            return
        self._file_path = path
        scanned = any(d.needs_vision for d in self._file_docs)
        self.file_label.setText(f"{path.name}" + ("  (scanned — the AI will read it directly)" if scanned else ""))
        self.clear_file_button.show()
        self.show_error("")

    def clear_file(self) -> None:
        self._file_docs, self._file_path = [], None
        self.file_label.setText("No file loaded")
        self.clear_file_button.hide()

    # --- private -----------------------------------------------------------------

    def _choose_file(self) -> None:
        from PySide6.QtWidgets import QFileDialog
        chosen, _ = QFileDialog.getOpenFileName(self, "Load job description", str(Path.home()), JD_FILE_FILTER)
        if chosen:
            self.load_file(Path(chosen))

    def _analyse(self) -> None:
        if not self.documents():
            self.show_error("Paste a job description or load a file first.")
            return
        self.show_error("")
        self.analyse_requested.emit()


class SavedFiltersDialog(QDialog):
    """Pick (or delete) a previously verified filter set."""

    def __init__(self, cache_base: Path | None, parent: QWidget | None = None):
        super().__init__(parent)
        self.cache_base = cache_base
        self.selected: filter_cache.SavedFilterSet | None = None
        self.setWindowTitle("Saved filters")
        self.resize(640, 420)
        layout = QVBoxLayout(self)
        layout.addWidget(muted("Filters you verified earlier. Choose one to screen more applications for that role."))
        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(lambda _: self._use())
        layout.addWidget(self.list, 1)
        row = QHBoxLayout()
        self.delete_button = button("Delete", "Danger", on_click=self._delete)
        row.addWidget(self.delete_button)
        row.addStretch(1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.use_button = button("Use these filters", "Primary", on_click=self._use)
        buttons.addButton(self.use_button, QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.rejected.connect(self.reject)
        row.addWidget(buttons)
        layout.addLayout(row)
        self._reload()

    def _reload(self) -> None:
        self.list.clear()
        for entry in filter_cache.list_filter_sets(self.cache_base):
            item = QListWidgetItem(f"{entry.label}\n{entry.excerpt[:140]}…")
            item.setData(Qt.ItemDataRole.UserRole, entry)
            self.list.addItem(item)
        if self.list.count():
            self.list.setCurrentRow(0)
        else:
            self.list.addItem("No saved filters yet.")
            self.list.item(0).setFlags(Qt.ItemFlag.NoItemFlags)
        has = self._current() is not None
        self.use_button.setEnabled(has)
        self.delete_button.setEnabled(has)

    def _current(self) -> filter_cache.SavedFilterSet | None:
        item = self.list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _use(self) -> None:
        self.selected = self._current()
        if self.selected:
            self.accept()

    def _delete(self) -> None:
        entry = self._current()
        if entry and QMessageBox.question(self, "Delete", f"Delete saved filters for '{entry.filter_set.job_title}'?") \
                == QMessageBox.StandardButton.Yes:
            filter_cache.delete_filter_set(entry.fingerprint, self.cache_base)
            self._reload()

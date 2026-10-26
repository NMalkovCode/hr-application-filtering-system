"""Settings: API key, model, spending limit, parallel requests, output folder, Clear Cache."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QHBoxLayout, QLineEdit, QMessageBox,
    QSpinBox, QVBoxLayout, QWidget,
)

from .. import config, filter_cache
from ..settings import mask_api_key
from .context import AppContext
from .widgets import PathPicker, button, card, muted, section, title
from .workers import TaskRunner


class SettingsDialog(QDialog):
    def __init__(self, ctx: AppContext, parent: QWidget | None = None, *, first_run: bool = False):
        super().__init__(parent)
        self.ctx = ctx
        self.runner = TaskRunner(self)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(620)
        s = ctx.settings

        layout = QVBoxLayout(self)
        layout.addWidget(title("Settings", "Welcome! Add your Anthropic API key to get started." if first_run
                               else "These settings are saved for your Windows user account."))

        # --- API key ---
        key_card, key_layout = card()
        key_layout.addWidget(section("Anthropic API key"))
        key_layout.addWidget(muted("Each HR user uses their own key. It is stored securely in Windows Credential "
                                   "Manager and is never written to disk in plain text or shared."))
        self.key_status = muted()
        key_layout.addWidget(self.key_status)
        row = QHBoxLayout()
        self.key_edit = QLineEdit()
        self.key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_edit.setPlaceholderText("Paste a new key (sk-ant-…) to replace the saved one")
        row.addWidget(self.key_edit, 1)
        self.test_button = button("Test key", on_click=self._test_key)
        self.remove_button = button("Remove key", "Danger", on_click=self._remove_key)
        row.addWidget(self.test_button)
        row.addWidget(self.remove_button)
        key_layout.addLayout(row)
        layout.addWidget(key_card)

        # --- options ---
        opt_card, opt_layout = card()
        opt_layout.addWidget(section("Screening"))
        form = QFormLayout()
        self.model = QComboBox()
        for info in config.MODELS.values():
            self.model.addItem(f"{info.label} — ${info.input_per_mtok:g} / ${info.output_per_mtok:g} per million tokens",
                               info.model_id)
        self.model.setCurrentIndex(max(0, self.model.findData(s.model)))
        form.addRow("AI model", self.model)

        self.limit = QDoubleSpinBox()
        self.limit.setRange(0, 10_000)
        self.limit.setDecimals(2)
        self.limit.setPrefix("$ ")
        self.limit.setSpecialValueText("No limit")
        self.limit.setValue(s.spending_limit_usd)
        self.limit.setToolTip("Before a run, you are warned if its estimated cost could exceed this. 0 = no limit.")
        form.addRow("Spending limit per run", self.limit)

        self.concurrency = QSpinBox()
        self.concurrency.setRange(1, 16)
        self.concurrency.setValue(s.concurrency)
        self.concurrency.setToolTip("How many applications are assessed at the same time. Lower this if you see "
                                    "rate-limit errors.")
        form.addRow("Parallel requests", self.concurrency)

        self.output = PathPicker("Default folder for screening results")
        self.output.edit.setText(s.output_dir)
        form.addRow("Default output folder", self.output)
        opt_layout.addLayout(form)
        layout.addWidget(opt_card)

        # --- cache ---
        cache_card, cache_layout = card()
        cache_layout.addWidget(section("Saved data"))
        cache_row = QHBoxLayout()
        cache_row.addWidget(muted("Verified filters and other open roles are saved so that a role can be screened "
                                  "again without re-analysis."), 1)
        cache_row.addWidget(button("Clear Cache", "Danger", on_click=self._clear_cache))
        cache_layout.addLayout(cache_row)
        layout.addWidget(cache_card)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._refresh_key_status()

    # --- actions -----------------------------------------------------------------

    def _refresh_key_status(self, extra: str = "") -> None:
        key = self.ctx.keys.get()
        text = f"Saved key: {mask_api_key(key)}" if key else "No API key saved yet."
        self.key_status.setText(text + (f"  —  {extra}" if extra else ""))
        self.remove_button.setEnabled(bool(key))

    def _store_typed_key(self) -> bool:
        typed = self.key_edit.text().strip()
        if not typed:
            return True
        if not typed.startswith("sk-"):
            QMessageBox.warning(self, "API key", "That does not look like an Anthropic API key (it should start with 'sk-').")
            return False
        try:
            self.ctx.keys.set(typed)
        except Exception as exc:   # e.g. Credential Manager unavailable or blocked by policy
            QMessageBox.warning(self, "API key", f"The key could not be saved in Windows Credential Manager:\n{exc}")
            return False
        self.key_edit.clear()
        return True

    def _test_key(self) -> None:
        if not self._store_typed_key():
            return
        if not self.ctx.has_api_key():
            QMessageBox.information(self, "API key", "Paste your API key first.")
            return
        client = self.ctx.client_factory(self.ctx.keys.get() or "", self.model.currentData())
        self.test_button.setEnabled(False)
        self._refresh_key_status("testing…")

        def done(_):
            self.test_button.setEnabled(True)
            self._refresh_key_status("✓ key works")

        def failed(message):
            self.test_button.setEnabled(True)
            self._refresh_key_status("✗ " + message)

        self.runner.start(lambda signals: client.check_access(), on_done=done, on_failed=failed)

    def _remove_key(self) -> None:
        if QMessageBox.question(self, "Remove API key", "Remove the saved API key from this computer?") \
                == QMessageBox.StandardButton.Yes:
            try:
                self.ctx.keys.delete()
            except Exception as exc:
                QMessageBox.warning(self, "API key", f"The key could not be removed:\n{exc}")
            self._refresh_key_status()

    def _clear_cache(self) -> None:
        if QMessageBox.question(
            self, "Clear Cache",
            "Delete all saved filters and cached open roles? Screening results are not affected.",
        ) != QMessageBox.StandardButton.Yes:
            return
        removed = filter_cache.clear_cache(self.ctx.cache_base)
        QMessageBox.information(self, "Clear Cache", f"Cache cleared ({removed} saved item{'s' if removed != 1 else ''} removed).")

    def _save(self) -> None:
        if not self._store_typed_key():
            return
        s = self.ctx.settings
        s.model = self.model.currentData()
        s.spending_limit_usd = float(self.limit.value())
        s.concurrency = int(self.concurrency.value())
        s.output_dir = self.output.path
        self.ctx.save_settings()
        self.accept()

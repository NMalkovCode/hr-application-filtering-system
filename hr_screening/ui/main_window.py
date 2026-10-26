"""Main window: drives the five-step workflow."""

from __future__ import annotations

import logging
import threading

from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QHBoxLayout, QLabel, QMainWindow, QMessageBox, QStackedWidget, QVBoxLayout, QWidget

from .. import config, filter_cache
from ..filters import FilterSet
from ..jd_analyzer import analyze_job_description
from ..models import SourceDocument
from ..pipeline import Preparation, RunOutcome, RunRequest, ScreeningPipeline
from .context import AppContext
from .filters_page import FiltersPage
from .jd_page import JobDescriptionPage, SavedFiltersDialog
from .run_pages import ProgressPage, ResultsPage
from .settings_dialog import SettingsDialog
from .setup_page import SetupPage
from .widgets import StepIndicator, button
from .workers import TaskRunner

log = logging.getLogger(__name__)

STEP_JD, STEP_FILTERS, STEP_SETUP, STEP_PROGRESS, STEP_RESULTS = range(5)


class MainWindow(QMainWindow):
    def __init__(self, ctx: AppContext):
        super().__init__()
        self.ctx = ctx
        self.runner = TaskRunner(self)
        self._jd_docs: list[SourceDocument] = []
        self._saved_fingerprint: str | None = None      # set when filters came from the cache
        self._saved_excerpt = ""
        self._cancel = threading.Event()
        self._pipeline: ScreeningPipeline | None = None
        self._estimate_text = ""

        self.setWindowTitle(config.APP_DISPLAY_NAME)
        self.resize(1180, 820)

        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(20, 14, 20, 16)
        header = QHBoxLayout()
        app_name = QLabel(config.APP_DISPLAY_NAME)
        app_name.setStyleSheet("font-size: 12pt; font-weight: 700;")
        header.addWidget(app_name)
        header.addSpacing(24)
        self.steps = StepIndicator()
        header.addWidget(self.steps, 1)
        self.settings_button = button("⚙  Settings", on_click=lambda: self.open_settings())
        header.addWidget(self.settings_button)
        root.addLayout(header)

        self.stack = QStackedWidget()
        self.jd_page = JobDescriptionPage()
        self.filters_page = FiltersPage()
        self.setup_page = SetupPage(ctx.settings)
        self.progress_page = ProgressPage()
        self.results_page = ResultsPage()
        for page in (self.jd_page, self.filters_page, self.setup_page, self.progress_page, self.results_page):
            self.stack.addWidget(page)
        root.addWidget(self.stack, 1)
        self.setCentralWidget(central)

        self.jd_page.analyse_requested.connect(self.analyse_job_description)
        self.jd_page.saved_requested.connect(self.choose_saved_filters)
        self.filters_page.back_requested.connect(lambda: self.go(STEP_JD))
        self.filters_page.verified.connect(self.on_filters_verified)
        self.setup_page.back_requested.connect(lambda: self.go(STEP_FILTERS))
        self.setup_page.start_requested.connect(self.start_screening)
        self.progress_page.cancel_requested.connect(self._cancel.set)
        self.results_page.new_screening.connect(self.new_screening)
        self.results_page.same_role.connect(lambda: self.go(STEP_SETUP))

    # --- navigation --------------------------------------------------------------

    def go(self, step: int) -> None:
        self.stack.setCurrentIndex(step)
        self.steps.set_current(step)
        self.settings_button.setEnabled(step != STEP_PROGRESS)

    def new_screening(self) -> None:
        self.jd_page.text.clear()
        self.jd_page.clear_file()
        self._jd_docs, self._saved_fingerprint = [], None
        self.go(STEP_JD)

    def open_settings(self, first_run: bool = False) -> bool:
        return SettingsDialog(self.ctx, self, first_run=first_run).exec() == SettingsDialog.DialogCode.Accepted

    def ensure_api_key(self) -> bool:
        if self.ctx.has_api_key():
            return True
        QMessageBox.information(self, "API key needed", "Add your Anthropic API key in Settings first.")
        return self.open_settings() and self.ctx.has_api_key()

    # --- step 1 -> 2 -------------------------------------------------------------

    def analyse_job_description(self) -> None:
        docs = self.jd_page.documents()
        saved = filter_cache.find_filter_set(docs, self.ctx.cache_base)
        if saved:
            answer = QMessageBox.question(
                self, "Saved filters found",
                f"You verified filters for this job description on {saved.saved_at:%d %b %Y at %H:%M}.\n\n"
                "Use the saved filters? Choose No to analyse the job description again.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel,
            )
            if answer == QMessageBox.StandardButton.Cancel:
                return
            if answer == QMessageBox.StandardButton.Yes:
                self._jd_docs, self._saved_fingerprint = docs, None
                self.filters_page.load(saved.filter_set)
                self.go(STEP_FILTERS)
                return
        if not self.ensure_api_key():
            return
        client = self.ctx.make_client()
        self.jd_page.set_busy(True, "Analysing the job description — this usually takes under a minute…")

        def done(filter_set: FilterSet) -> None:
            self.jd_page.set_busy(False)
            self._jd_docs, self._saved_fingerprint = docs, None
            self.filters_page.load(filter_set)
            self.go(STEP_FILTERS)

        def failed(message: str) -> None:
            self.jd_page.set_busy(False)
            self.jd_page.show_error(message)

        self.runner.start(lambda s: analyze_job_description(client, documents=docs), on_done=done, on_failed=failed)

    def choose_saved_filters(self) -> None:
        dialog = SavedFiltersDialog(self.ctx.cache_base, self)
        if dialog.exec() and dialog.selected:
            entry = dialog.selected
            self._jd_docs, self._saved_fingerprint, self._saved_excerpt = [], entry.fingerprint, entry.excerpt
            self.filters_page.load(entry.filter_set)
            self.go(STEP_FILTERS)

    # --- step 2 -> 3 -------------------------------------------------------------

    def on_filters_verified(self, filter_set: FilterSet) -> None:
        filter_set = filter_set.renumbered()
        try:
            if self._saved_fingerprint:
                filter_cache.save_filter_set([], filter_set, self.ctx.cache_base,
                                             fp=self._saved_fingerprint, excerpt=self._saved_excerpt)
            elif self._jd_docs:
                filter_cache.save_filter_set(self._jd_docs, filter_set, self.ctx.cache_base)
        except OSError as exc:
            log.warning("Could not save filters: %s", exc)
        self.setup_page.set_filter_set(filter_set)
        self.go(STEP_SETUP)

    # --- step 3 -> 4 -> 5 --------------------------------------------------------

    def start_screening(self, request: RunRequest) -> None:
        if not self.ensure_api_key():
            return
        self.setup_page.store_in(self.ctx.settings)
        try:
            self.ctx.save_settings()
        except (OSError, ValueError) as exc:
            log.warning("Could not save settings: %s", exc)
        request.concurrency = self.ctx.settings.concurrency
        self._cancel.clear()
        self._estimate_text = ""
        self._pipeline = ScreeningPipeline(self.ctx.make_client())
        self.progress_page.reset()
        self.go(STEP_PROGRESS)

        pipeline = self._pipeline
        self.runner.start(
            lambda s: pipeline.prepare(request, on_status=s.status.emit),
            on_status=self.progress_page.set_status,
            on_done=self._on_prepared,
            on_failed=self._on_run_failed,
        )

    def _on_prepared(self, prep: Preparation) -> None:
        if self._cancel.is_set():
            self.go(STEP_SETUP)
            return
        self.progress_page.set_notes(prep.roles.notes)
        if prep.roles_error:
            answer = QMessageBox.question(
                self, "Other roles not available",
                f"The other open roles could not be read:\n\n{prep.roles_error}\n\n"
                "Continue without the Other Role check?")
            if answer != QMessageBox.StandardButton.Yes:
                self.go(STEP_SETUP)
                return

        estimate = prep.estimate
        self._estimate_text = f"estimate ${estimate.low_usd:.2f}–${estimate.high_usd:.2f}"
        limit = self.ctx.settings.spending_limit_usd
        if estimate.exceeds(limit):
            box = QMessageBox(QMessageBox.Icon.Warning, "Spending limit",
                              f"{estimate.describe()}\n\nThis could exceed your spending limit of ${limit:.2f} per run. "
                              "Continue anyway?", parent=self)
            box.addButton("Continue", QMessageBox.ButtonRole.AcceptRole)
            cancel = box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
            box.exec()
            if box.clickedButton() is cancel:
                self.go(STEP_SETUP)
                return

        self.progress_page.add_log(f"Found {len(prep.candidates)} applications. {estimate.describe()}")
        if prep.discovery_issues:
            self.progress_page.add_log(f"{len(prep.discovery_issues)} file(s)/folder(s) skipped — listed in Summary.xlsx.")
        pipeline = self._pipeline
        cancel = self._cancel
        self.runner.start(
            lambda s: pipeline.run(prep, on_progress=s.progress.emit, cancel=cancel, on_status=s.status.emit),
            on_progress=lambda p: self.progress_page.show_progress(p, self._estimate_text),
            on_status=self.progress_page.set_status,
            on_done=lambda outcome: self._on_run_done(outcome, prep),
            on_failed=self._on_run_failed,
        )

    def _on_run_done(self, outcome: RunOutcome, prep: Preparation) -> None:
        notes = []
        if prep.roles_error:
            notes.append(f"Other Role check skipped: {prep.roles_error}")
        failed_outputs = [p for p in outcome.placements if p.errors]
        if failed_outputs:
            notes.append(f"{len(failed_outputs)} candidate(s) had problems writing their output — see Summary.xlsx.")
        self.results_page.show_outcome(outcome, notes)
        self.go(STEP_RESULTS)

    def _on_run_failed(self, message: str) -> None:
        QMessageBox.critical(self, "Screening stopped", message)
        self.go(STEP_SETUP)
        if "API key" in message:
            self.open_settings()

    # --- window ------------------------------------------------------------------

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.runner.busy:
            answer = QMessageBox.question(
                self, "Screening in progress",
                "A task is still running. Stop it and close? Applications already assessed will be saved.")
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self._cancel.set()
            self.setEnabled(False)
            self.runner.wait(180_000)
        event.accept()

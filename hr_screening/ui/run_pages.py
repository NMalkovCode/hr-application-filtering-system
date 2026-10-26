"""Steps 4 and 5: screening progress and results."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QListWidget, QProgressBar, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from .. import config
from ..evaluator import Progress
from ..models import Tier
from ..pipeline import RunOutcome
from .widgets import Banner, button, card, muted, section, title

TIER_COLOURS = {
    Tier.TOP: "#1E7B34", Tier.CLOSE: "#1F5FA8", Tier.BACKUP: "#A66100",
    Tier.NOT_SUITABLE: "#57606a", Tier.NEEDS_REVIEW: "#B01E1E",
}


class ProgressPage(QWidget):
    cancel_requested = Signal()

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.addWidget(title("Screening in progress", "You can keep working in other programs. "
                                                        "Do not close this window until it finishes."))
        box, b = card()
        self.status = QLabel("Preparing…")
        self.status.setObjectName("SectionTitle")
        b.addWidget(self.status)
        self.bar = QProgressBar()
        self.bar.setRange(0, 0)
        b.addWidget(self.bar)
        self.detail = muted()
        b.addWidget(self.detail)
        layout.addWidget(box)

        self.notes = Banner()
        layout.addWidget(self.notes)

        layout.addWidget(section("Activity"))
        self.log = QListWidget()
        layout.addWidget(self.log, 1)

        nav = QHBoxLayout()
        nav.addStretch(1)
        self.cancel_button = button("Cancel", "Danger", on_click=self._cancel)
        nav.addWidget(self.cancel_button)
        layout.addLayout(nav)

    def reset(self) -> None:
        self.status.setText("Preparing…")
        self.bar.setRange(0, 0)
        self.detail.setText("")
        self.notes.show_messages([])
        self.log.clear()
        self.cancel_button.setEnabled(True)
        self.cancel_button.setText("Cancel")

    def set_status(self, message: str, done: int = 0, total: int = 0) -> None:
        self.status.setText(message)
        if total:
            self.bar.setRange(0, total)
            self.bar.setValue(done)
        else:
            self.bar.setRange(0, 0)

    def set_notes(self, notes: list[str]) -> None:
        self.notes.show_messages(notes)

    def add_log(self, text: str) -> None:
        self.log.addItem(text)
        self.log.scrollToBottom()

    def show_progress(self, p: Progress, estimate_text: str = "") -> None:
        self.status.setText(f"Assessing applications — {p.done} of {p.total}")
        self.bar.setRange(0, p.total)
        self.bar.setValue(p.done)
        self.detail.setText(f"Cost so far: ${p.cost_usd:.2f}" + (f"   ·   {estimate_text}" if estimate_text else ""))
        r = p.last
        if r is not None:
            if r.error:
                self.add_log(f"⚠  {r.name}: needs manual review — {r.error}")
            elif r.eliminated:
                self.add_log(f"✗  {r.name}: does not meet a must-have")
            else:
                self.add_log(f"✓  {r.name}: score {r.score}")

    def _cancel(self) -> None:
        self.cancel_button.setEnabled(False)
        self.cancel_button.setText("Cancelling…")
        self.status.setText("Cancelling — finishing the applications already in progress…")
        self.cancel_requested.emit()


class ResultsPage(QWidget):
    new_screening = Signal()
    same_role = Signal()

    def __init__(self):
        super().__init__()
        self.outcome: RunOutcome | None = None
        layout = QVBoxLayout(self)
        self.heading = title("Screening complete")
        layout.addWidget(self.heading)
        self.subtitle = muted()
        layout.addWidget(self.subtitle)

        self.cards = QGridLayout()
        self.card_values: dict[str, QLabel] = {}
        names = [t.value for t in (Tier.TOP, Tier.CLOSE, Tier.BACKUP)] + \
                [config.FOLDER_OTHER_ROLE, Tier.NOT_SUITABLE.value, Tier.NEEDS_REVIEW.value]
        for i, name in enumerate(names):
            frame, f = card()
            value = QLabel("0")
            value.setStyleSheet("font-size: 20pt; font-weight: 600;")
            f.addWidget(value)
            f.addWidget(muted(name))
            self.card_values[name] = value
            self.cards.addWidget(frame, 0, i)
        layout.addLayout(self.cards)

        self.notes = Banner()
        layout.addWidget(self.notes)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Tier", "Rank", "Candidate", "Score", "Other role", "Summary"])
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        for col, width in ((0, 110), (1, 50), (2, 180), (3, 60), (4, 170)):
            self.table.setColumnWidth(col, width)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.verticalHeader().hide()
        self.table.setWordWrap(True)
        self.table.cellDoubleClicked.connect(self._open_row)
        layout.addWidget(self.table, 1)
        layout.addWidget(muted("Double-click a candidate to open their report (or their folder)."))

        nav = QHBoxLayout()
        nav.addWidget(button("New screening", on_click=self.new_screening.emit))
        nav.addWidget(button("Screen more applications for this role", on_click=self.same_role.emit))
        nav.addStretch(1)
        nav.addWidget(button("Open Summary.xlsx", on_click=self._open_summary))
        nav.addWidget(button("Open results folder", "Primary", on_click=self._open_folder))
        layout.addLayout(nav)

    def show_outcome(self, outcome: RunOutcome, notes: list[str]) -> None:
        self.outcome = outcome
        self.heading.findChild(QLabel, "PageTitle").setText(
            "Screening cancelled — partial results" if outcome.cancelled else "Screening complete")
        self.subtitle.setText(f"{len(outcome.placements)} applications · actual cost ${outcome.cost_usd:.2f} · "
                              f"saved to {outcome.run_dir}")
        for tier in Tier:
            self.card_values[tier.value].setText(str(outcome.count(tier)))
        self.card_values[config.FOLDER_OTHER_ROLE].setText(str(outcome.other_role_count))
        self.notes.show_messages(notes)

        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        for p in outcome.placements:
            r = p.result
            row = self.table.rowCount()
            self.table.insertRow(row)
            tier_item = QTableWidgetItem(r.tier.value)
            tier_item.setForeground(QColor(TIER_COLOURS[r.tier]))
            tier_item.setData(Qt.ItemDataRole.UserRole, p)
            cells = [tier_item, _num(r.rank), QTableWidgetItem(p.name),
                     _num(r.score) if r.evaluation else QTableWidgetItem("—"),
                     QTableWidgetItem((r.other_role or r.alternative_role).title if (r.other_role or r.alternative_role) else ""),
                     QTableWidgetItem(r.one_line_reason)]
            for col, item in enumerate(cells):
                self.table.setItem(row, col, item)
        # Size rows once the stretched Summary column has its final width.
        QTimer.singleShot(0, self.table.resizeRowsToContents)

    def _open_row(self, row: int, _col: int) -> None:
        p = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        target = p.report or p.other_role_report or p.application_dir
        if target:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))

    def _open_summary(self) -> None:
        if self.outcome:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.outcome.summary_path)))

    def _open_folder(self) -> None:
        if self.outcome:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.outcome.run_dir)))


def _num(value: int) -> QTableWidgetItem:
    item = QTableWidgetItem()
    item.setData(Qt.ItemDataRole.DisplayRole, value)   # numeric, so the column sorts correctly
    item.setForeground(QColor("#1f2328"))
    return item

"""Step 2: HR reviews, edits and verifies the proposed filters."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QSpinBox, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..filters import MAX_FILTERS, FilterCategory, FilterSet, FilterType, ScreeningFilter
from .widgets import Banner, button, muted, title

COL_CRITERION, COL_CATEGORY, COL_TYPE, COL_WEIGHT, COL_REASON = range(5)


class FiltersPage(QWidget):
    verified = Signal(object)        # FilterSet
    back_requested = Signal()

    def __init__(self):
        super().__init__()
        self._summary = ""
        layout = QVBoxLayout(self)
        layout.addWidget(title(
            "Check the screening filters",
            "Every application will be checked against these filters. A candidate who does not meet a "
            "Must-have is eliminated; all filters count towards the score, weighted 1 (minor) to 5 (central). "
            "Edit anything that is wrong, then press Verify."))

        title_row = QHBoxLayout()
        title_row.addWidget(QLabel("Job title:"))
        self.job_title = QLineEdit()
        title_row.addWidget(self.job_title, 1)
        layout.addLayout(title_row)

        self.warnings = Banner()
        layout.addWidget(self.warnings)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Requirement", "Category", "Type", "Weight", "Why (from the job description)"])
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(COL_CRITERION, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(COL_REASON, QHeaderView.ResizeMode.Stretch)
        for col, width in ((COL_CATEGORY, 120), (COL_TYPE, 115), (COL_WEIGHT, 70)):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.Fixed)
            self.table.setColumnWidth(col, width)
        self.table.setWordWrap(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.itemChanged.connect(lambda _: self._update_counts())
        layout.addWidget(self.table, 1)

        edit_row = QHBoxLayout()
        edit_row.addWidget(button("+ Add filter", on_click=self.add_filter))
        edit_row.addWidget(button("Remove selected", on_click=self.remove_selected))
        edit_row.addWidget(button("Move up", on_click=lambda: self._move(-1)))
        edit_row.addWidget(button("Move down", on_click=lambda: self._move(1)))
        edit_row.addStretch(1)
        self.counts = muted()
        self.counts.setWordWrap(False)
        edit_row.addWidget(self.counts)
        layout.addLayout(edit_row)

        self.errors = Banner(error=True)
        layout.addWidget(self.errors)

        nav = QHBoxLayout()
        nav.addWidget(button("←  Back", on_click=self.back_requested.emit))
        nav.addStretch(1)
        self.verify_button = button("Verify filters  →", "Primary", on_click=self._verify)
        nav.addWidget(self.verify_button)
        layout.addLayout(nav)

    # --- public ------------------------------------------------------------------

    def load(self, filter_set: FilterSet) -> None:
        self._summary = filter_set.job_summary
        self.job_title.setText(filter_set.job_title)
        self.warnings.show_messages(filter_set.warnings, "Notes from the analysis:")
        self.errors.show_messages([])
        self._render(filter_set.filters)

    def current_filter_set(self) -> FilterSet:
        filters = []
        for row in range(self.table.rowCount()):
            item = self.table.item(row, COL_CRITERION)
            reason = self.table.item(row, COL_REASON)
            filters.append(ScreeningFilter.model_construct(
                id=f"F{row + 1:02d}",
                criterion=" ".join((item.text() if item else "").split()),
                # Combo data comes back as plain strings; convert to the enums.
                category=FilterCategory(self.table.cellWidget(row, COL_CATEGORY).currentData()),
                type=FilterType(self.table.cellWidget(row, COL_TYPE).currentData()),
                weight=int(self.table.cellWidget(row, COL_WEIGHT).value()),
                rationale=reason.text() if reason else "",
            ))
        return FilterSet(job_title=" ".join(self.job_title.text().split()), job_summary=self._summary,
                         filters=filters, warnings=[])

    def add_filter(self) -> None:
        filters = self.current_filter_set().filters
        if len(filters) >= MAX_FILTERS:
            self.errors.show_messages([f"The maximum is {MAX_FILTERS} filters."])
            return
        filters.append(ScreeningFilter(id="", criterion="", rationale="Added by HR"))
        self._render(filters)
        row = len(filters) - 1
        self.table.setCurrentCell(row, COL_CRITERION)
        self.table.editItem(self.table.item(row, COL_CRITERION))

    def remove_selected(self) -> None:
        rows = {i.row() for i in self.table.selectedIndexes()}
        if not rows and self.table.currentRow() >= 0:
            rows = {self.table.currentRow()}
        filters = [f for i, f in enumerate(self.current_filter_set().filters) if i not in rows]
        self._render(filters)

    # --- private -----------------------------------------------------------------

    def _move(self, delta: int) -> None:
        row = self.table.currentRow()
        filters = self.current_filter_set().filters
        target = row + delta
        if row < 0 or not 0 <= target < len(filters):
            return
        filters[row], filters[target] = filters[target], filters[row]
        self._render(filters)
        self.table.selectRow(target)

    def _render(self, filters: list[ScreeningFilter]) -> None:
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        for f in filters:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, COL_CRITERION, QTableWidgetItem(f.criterion))

            category = QComboBox()
            for c in FilterCategory:
                category.addItem(c.label, c.value)
            category.setCurrentIndex(category.findData(FilterCategory(f.category).value))
            self.table.setCellWidget(row, COL_CATEGORY, category)

            ftype = QComboBox()
            for t in FilterType:
                ftype.addItem(t.label, t.value)
            ftype.setCurrentIndex(ftype.findData(FilterType(f.type).value))
            ftype.currentIndexChanged.connect(self._update_counts)
            self.table.setCellWidget(row, COL_TYPE, ftype)

            weight = QSpinBox()
            weight.setRange(1, 5)
            weight.setValue(min(5, max(1, f.weight)))
            self.table.setCellWidget(row, COL_WEIGHT, weight)

            reason = QTableWidgetItem(f.rationale)
            reason.setFlags(reason.flags() & ~Qt.ItemFlag.ItemIsEditable)
            reason.setForeground(Qt.GlobalColor.darkGray)
            reason.setToolTip(f.rationale)
            self.table.setItem(row, COL_REASON, reason)
        self.table.blockSignals(False)
        self.table.resizeRowsToContents()
        self._update_counts()

    def _update_counts(self) -> None:
        fs = self.current_filter_set()
        self.counts.setText(f"{len(fs.must_haves)} must-have · {len(fs.preferred)} preferred · "
                            f"{len(fs.filters)}/{MAX_FILTERS} filters")

    def _verify(self) -> None:
        fs = self.current_filter_set()
        problems = fs.validation_errors()
        self.errors.show_messages(problems, "Please fix the following before verifying:")
        if not problems:
            self.verified.emit(fs)

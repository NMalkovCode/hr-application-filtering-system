"""Step 3: applications folder, output folder, other-roles source, anonymised mode, thresholds."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QFormLayout, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QRadioButton, QSpinBox,
    QVBoxLayout, QWidget,
)

from ..discovery import discover_candidates
from ..filters import FilterSet
from ..pipeline import RunRequest
from ..settings import Settings, TierThresholds
from .widgets import Banner, PathPicker, button, card, muted, section, title

LAYOUT_TEXT = {
    "subfolders": "one subfolder per candidate",
    "files": "one file per candidate",
    "mixed": "a mix of subfolders and single files",
}


class SetupPage(QWidget):
    start_requested = Signal(object)    # RunRequest
    back_requested = Signal()

    def __init__(self, settings: Settings):
        super().__init__()
        self.filter_set: FilterSet | None = None
        self._application_count = 0

        layout = QVBoxLayout(self)
        layout.addWidget(title("Applications and options", "Choose the applications to screen and where to save the results."))

        self.role_summary = muted()
        role_row = QHBoxLayout()
        role_row.addWidget(self.role_summary, 1)
        role_row.addWidget(button("Change filters", on_click=self.back_requested.emit))
        layout.addLayout(role_row)

        # --- folders ---
        folders, f_layout = card()
        f_layout.addWidget(section("Folders"))
        form = QFormLayout()
        self.apps = PathPicker("Folder containing the applications")
        self.apps.changed.connect(self._scan_applications)
        form.addRow("Applications", self.apps)
        self.apps_info = muted("Each candidate can be a subfolder (CV, cover letter, …) or a single file. "
                               "PDF, Word and scanned images are accepted. Originals are never changed.")
        form.addRow("", self.apps_info)
        self.output = PathPicker("Where to create the results folder")
        self.output.edit.setText(settings.output_dir)
        form.addRow("Save results in", self.output)
        f_layout.addLayout(form)
        layout.addWidget(folders)

        # --- other roles ---
        roles, r_layout = card()
        r_layout.addWidget(section("Other open roles (optional)"))
        r_layout.addWidget(muted("Compare candidates with the company's other published vacancies. Anyone better "
                                 "suited to another role is also placed in the Other Role folder."))
        self.role_group = QButtonGroup(self)
        grid = QGridLayout()
        self.radio_url = QRadioButton("Careers page URL")
        self.radio_folder = QRadioButton("Folder of job descriptions")
        self.radio_none = QRadioButton("Don't check other roles")
        self.careers_url = QLineEdit(settings.careers_url)
        self.careers_url.setPlaceholderText("https://www.company.com/careers")
        self.careers_folder = PathPicker("Folder with one job description file per role")
        self.careers_folder.edit.setText(settings.careers_folder)
        for i, (radio, field) in enumerate(((self.radio_url, self.careers_url),
                                            (self.radio_folder, self.careers_folder),
                                            (self.radio_none, None))):
            self.role_group.addButton(radio, i)
            grid.addWidget(radio, i, 0)
            if field is not None:
                grid.addWidget(field, i, 1)
        grid.setColumnStretch(1, 1)
        r_layout.addLayout(grid)
        (self.radio_url if settings.careers_url else self.radio_folder if settings.careers_folder
         else self.radio_none).setChecked(True)
        self.role_group.idToggled.connect(lambda *_: self._sync_role_fields())
        layout.addWidget(roles)

        # --- options ---
        opts, o_layout = card()
        o_layout.addWidget(section("Options"))
        self.anonymised = QCheckBox("Anonymised mode — replace names with Candidate 001, 002… in folders, "
                                    "reports and the spreadsheet")
        self.anonymised.setChecked(settings.anonymised_mode)
        o_layout.addWidget(self.anonymised)
        o_layout.addWidget(muted("A separate Candidate_Key.xlsx links the IDs to the original applications. "
                                 "The contents of the copied files are not altered."))

        thresholds = QHBoxLayout()
        thresholds.addWidget(QLabel("Minimum score for:"))
        self.top, self.close, self.backup = QSpinBox(), QSpinBox(), QSpinBox()
        for label, spin, value in (("Top Match", self.top, settings.thresholds.top),
                                   ("Close Match", self.close, settings.thresholds.close),
                                   ("Backup", self.backup, settings.thresholds.backup)):
            spin.setRange(0, 100)
            spin.setValue(value)
            spin.valueChanged.connect(self._update_thresholds)
            thresholds.addSpacing(10)
            thresholds.addWidget(QLabel(label))
            thresholds.addWidget(spin)
        thresholds.addStretch(1)
        o_layout.addLayout(thresholds)
        self.threshold_info = muted()
        o_layout.addWidget(self.threshold_info)
        layout.addWidget(opts)

        layout.addStretch(1)
        self.errors = Banner(error=True)
        layout.addWidget(self.errors)

        nav = QHBoxLayout()
        nav.addWidget(button("←  Back", on_click=self.back_requested.emit))
        nav.addStretch(1)
        self.start_button = button("Start screening  →", "Primary", on_click=self._start)
        nav.addWidget(self.start_button)
        layout.addLayout(nav)

        self._sync_role_fields()
        self._update_thresholds()

    # --- public ------------------------------------------------------------------

    def set_filter_set(self, filter_set: FilterSet) -> None:
        self.filter_set = filter_set
        self.role_summary.setText(
            f"Role: <b>{filter_set.job_title}</b> — {len(filter_set.filters)} verified filters "
            f"({len(filter_set.must_haves)} must-have)")

    def thresholds(self) -> TierThresholds:
        return TierThresholds(top=self.top.value(), close=self.close.value(), backup=self.backup.value())

    def store_in(self, settings: Settings) -> None:
        """Remember the choices for next time."""
        settings.output_dir = self.output.path
        settings.careers_url = self.careers_url.text().strip()
        settings.careers_folder = self.careers_folder.path
        settings.anonymised_mode = self.anonymised.isChecked()
        try:
            t = self.thresholds()
            t.validate()
            settings.thresholds = t
        except ValueError:
            pass

    # --- private -----------------------------------------------------------------

    def _sync_role_fields(self) -> None:
        self.careers_url.setEnabled(self.radio_url.isChecked())
        self.careers_folder.setEnabled(self.radio_folder.isChecked())

    def _update_thresholds(self) -> None:
        t = self.thresholds()
        try:
            t.validate()
        except ValueError:
            self.threshold_info.setText("⚠ Scores must be ordered: Backup < Close Match < Top Match.")
            self.threshold_info.setObjectName("Error")
        else:
            self.threshold_info.setText(
                f"Top Match ≥ {t.top}  ·  Close Match {t.close}–{t.top - 1}  ·  Backup {t.backup}–{t.close - 1}  ·  "
                f"below {t.backup} (or a missed must-have) → Not Suitable")
            self.threshold_info.setObjectName("Muted")
        self.threshold_info.style().unpolish(self.threshold_info)
        self.threshold_info.style().polish(self.threshold_info)

    def _scan_applications(self, path: str) -> None:
        self._application_count = 0
        if not path:
            return
        try:
            found = discover_candidates(Path(path))
        except (OSError, NotADirectoryError) as exc:
            self.apps_info.setText(f"⚠ {exc}")
            return
        self._application_count = len(found.candidates)
        if not found.candidates:
            self.apps_info.setText("⚠ No applications found in this folder.")
            return
        text = f"Found {len(found.candidates)} application{'s' if len(found.candidates) != 1 else ''} " \
               f"({LAYOUT_TEXT[found.layout]})."
        if found.issues:
            text += f" {len(found.issues)} item(s) will be skipped — hover for details."
        self.apps_info.setText(text)
        self.apps_info.setToolTip("\n".join(f"{i.path.name}: {i.message}" for i in found.issues[:30]))

    def _start(self) -> None:
        problems = []
        apps = self.apps.path
        if not apps or not Path(apps).is_dir():
            problems.append("Choose the folder that contains the applications.")
        output = self.output.path or (str(Path(apps).parent) if apps else "")
        if not output:
            problems.append("Choose where to save the results.")
        elif apps and Path(output).resolve().is_relative_to(Path(apps).resolve()):
            problems.append("Save the results outside the applications folder.")
        url = self.careers_url.text().strip() if self.radio_url.isChecked() else ""
        folder = self.careers_folder.path if self.radio_folder.isChecked() else ""
        if self.radio_url.isChecked() and not url:
            problems.append("Enter the careers page URL, or choose another option for other roles.")
        if self.radio_folder.isChecked() and not folder:
            problems.append("Choose the job descriptions folder, or choose another option for other roles.")
        try:
            self.thresholds().validate()
        except ValueError as exc:
            problems.append(str(exc))
        if self.filter_set is None:
            problems.append("Verify the filters first.")
        self.errors.show_messages(problems, "Please fix the following:")
        if problems:
            return
        if not self.output.path:
            self.output.edit.setText(output)
        self.start_requested.emit(RunRequest(
            applications_dir=Path(apps),
            output_dir=Path(output),
            filter_set=self.filter_set,
            thresholds=self.thresholds(),
            anonymised=self.anonymised.isChecked(),
            careers_url=url,
            careers_folder=folder,
        ))

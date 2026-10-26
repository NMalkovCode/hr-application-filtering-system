"""Small reusable widgets and the application stylesheet."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

ACCENT = "#1F5FA8"

STYLESHEET = f"""
QWidget {{ font-family: "Segoe UI"; font-size: 10pt; color: #1f2328; }}
QMainWindow, QDialog {{ background: #f6f8fa; }}
QLabel#PageTitle {{ font-size: 16pt; font-weight: 600; }}
QLabel#PageSubtitle {{ color: #57606a; }}
QLabel#SectionTitle {{ font-size: 11pt; font-weight: 600; margin-top: 6px; }}
QLabel#Muted {{ color: #57606a; }}
QLabel#Error {{ color: #b01e1e; }}
QFrame#Card {{ background: white; border: 1px solid #d0d7de; border-radius: 8px; }}
QFrame#Banner {{ background: #fff8e1; border: 1px solid #e3c770; border-radius: 6px; }}
QFrame#ErrorBanner {{ background: #fdecec; border: 1px solid #e0a3a3; border-radius: 6px; }}
QPushButton {{ padding: 6px 14px; border: 1px solid #d0d7de; border-radius: 6px; background: white; }}
QPushButton:hover {{ background: #f3f4f6; }}
QPushButton:disabled {{ color: #8c959f; background: #f6f8fa; }}
QPushButton#Primary {{ background: {ACCENT}; color: white; border: 1px solid {ACCENT}; font-weight: 600; }}
QPushButton#Primary:hover {{ background: #184d8a; }}
QPushButton#Primary:disabled {{ background: #9bb5d6; border-color: #9bb5d6; }}
QPushButton#Danger {{ color: #b01e1e; }}
QLineEdit, QPlainTextEdit, QComboBox {{
    padding: 4px 6px; border: 1px solid #d0d7de; border-radius: 5px; background: white; }}
QListWidget {{ background: white; border: 1px solid #d0d7de; border-radius: 5px; }}
QTableWidget {{ background: white; border: 1px solid #d0d7de; gridline-color: #e5e7eb; }}
QHeaderView {{ background: #eef2f6; }}
QHeaderView::section {{ background: #eef2f6; padding: 5px; border: none; border-right: 1px solid #d0d7de;
    font-weight: 600; color: #1f2328; }}
QTableCornerButton::section {{ background: #eef2f6; border: none; }}
QProgressBar {{ border: 1px solid #d0d7de; border-radius: 5px; text-align: center; background: white; height: 18px; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 4px; }}
"""


def apply_theme(app) -> None:
    """Light theme regardless of the Windows dark/light setting, so every screen is consistent."""
    from PySide6.QtGui import QColor, QPalette

    app.setStyle("Fusion")
    try:
        app.styleHints().setColorScheme(Qt.ColorScheme.Light)   # Qt 6.8+
    except AttributeError:
        pass
    p = QPalette()
    colours = {
        QPalette.ColorRole.Window: "#f6f8fa", QPalette.ColorRole.WindowText: "#1f2328",
        QPalette.ColorRole.Base: "#ffffff", QPalette.ColorRole.AlternateBase: "#f6f8fa",
        QPalette.ColorRole.Text: "#1f2328", QPalette.ColorRole.Button: "#ffffff",
        QPalette.ColorRole.ButtonText: "#1f2328", QPalette.ColorRole.Highlight: "#dbe7f5",
        QPalette.ColorRole.HighlightedText: "#1f2328", QPalette.ColorRole.ToolTipBase: "#ffffff",
        QPalette.ColorRole.ToolTipText: "#1f2328", QPalette.ColorRole.PlaceholderText: "#8c959f",
        QPalette.ColorRole.Light: "#ffffff", QPalette.ColorRole.Midlight: "#eef2f6",
        QPalette.ColorRole.Mid: "#d0d7de", QPalette.ColorRole.Dark: "#8c959f", QPalette.ColorRole.Shadow: "#57606a",
        QPalette.ColorRole.Link: ACCENT,
    }
    for role, colour in colours.items():
        p.setColor(role, QColor(colour))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.WindowText, QPalette.ColorRole.ButtonText):
        p.setColor(QPalette.ColorGroup.Disabled, role, QColor("#8c959f"))
    app.setPalette(p)
    app.setStyleSheet(STYLESHEET)


def title(text: str, subtitle: str = "") -> QWidget:
    box = QWidget()
    layout = QVBoxLayout(box)
    layout.setContentsMargins(0, 0, 0, 6)
    layout.setSpacing(2)
    t = QLabel(text)
    t.setObjectName("PageTitle")
    layout.addWidget(t)
    if subtitle:
        s = QLabel(subtitle)
        s.setObjectName("PageSubtitle")
        s.setWordWrap(True)
        layout.addWidget(s)
    return box


def section(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("SectionTitle")
    return label


def muted(text: str = "") -> QLabel:
    label = QLabel(text)
    label.setObjectName("Muted")
    label.setWordWrap(True)
    return label


def button(text: str, kind: str = "", on_click=None) -> QPushButton:
    b = QPushButton(text)
    if kind:
        b.setObjectName(kind)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    if on_click:
        b.clicked.connect(on_click)
    return b


def card() -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    frame.setObjectName("Card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(16, 14, 16, 14)
    return frame, layout


class Banner(QFrame):
    """Yellow (warning) or red (error) message box; hidden when empty."""

    def __init__(self, error: bool = False):
        super().__init__()
        self.setObjectName("ErrorBanner" if error else "Banner")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        self.label = QLabel()
        self.label.setWordWrap(True)
        self.label.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.label)
        self.hide()

    def show_messages(self, messages: list[str], heading: str = "") -> None:
        lines = ([heading] if heading else []) + [f"•  {m}" for m in messages]
        self.label.setText("\n".join(lines))
        self.setVisible(bool(messages))


class PathPicker(QWidget):
    """Line edit + Browse button for a folder or file."""

    changed = Signal(str)

    def __init__(self, placeholder: str, *, folder: bool = True, file_filter: str = ""):
        super().__init__()
        self._folder, self._filter = folder, file_filter
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.edit = QLineEdit()
        self.edit.setPlaceholderText(placeholder)
        self.edit.editingFinished.connect(lambda: self.changed.emit(self.path))
        self.browse = button("Browse…", on_click=self._browse)
        layout.addWidget(self.edit, 1)
        layout.addWidget(self.browse)

    @property
    def path(self) -> str:
        return self.edit.text().strip().strip('"')

    def set_path(self, path: str) -> None:
        self.edit.setText(path)
        self.changed.emit(self.path)

    def _browse(self) -> None:
        start = self.path or str(Path.home())
        if self._folder:
            chosen = QFileDialog.getExistingDirectory(self, "Choose a folder", start)
        else:
            chosen, _ = QFileDialog.getOpenFileName(self, "Choose a file", start, self._filter)
        if chosen:
            self.set_path(str(Path(chosen)))


class StepIndicator(QWidget):
    STEPS = ["Job description", "Filters", "Applications", "Screening", "Results"]

    def __init__(self):
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.labels: list[QLabel] = []
        for i, name in enumerate(self.STEPS, 1):
            label = QLabel(f"{i}  {name}")
            label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
            self.labels.append(label)
            layout.addWidget(label)
            if i < len(self.STEPS):
                arrow = QLabel("›")
                arrow.setObjectName("Muted")
                layout.addWidget(arrow)
        layout.addStretch(1)
        self.set_current(0)

    def set_current(self, index: int) -> None:
        for i, label in enumerate(self.labels):
            if i == index:
                style = f"color: white; background: {ACCENT}; border-radius: 10px; padding: 3px 10px; font-weight: 600;"
            elif i < index:
                style = f"color: {ACCENT}; padding: 3px 10px;"
            else:
                style = "color: #8c959f; padding: 3px 10px;"
            label.setStyleSheet(style)

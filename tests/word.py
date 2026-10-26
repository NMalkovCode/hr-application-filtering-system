"""Optional Microsoft Word automation for checking real page counts."""

from __future__ import annotations

from pathlib import Path


class WordPageCounter:
    def __init__(self):
        import pythoncom
        import win32com.client

        pythoncom.CoInitialize()
        self._word = win32com.client.DispatchEx("Word.Application")
        self._word.Visible = False
        self._word.DisplayAlerts = 0

    def pages(self, path: Path) -> int:
        doc = self._word.Documents.Open(str(Path(path).resolve()), ReadOnly=True, AddToRecentFiles=False)
        try:
            doc.Repaginate()
            return int(doc.ComputeStatistics(2))  # wdStatisticPages
        finally:
            doc.Close(False)

    def close(self):
        try:
            self._word.Quit()
        except Exception:
            pass


def word_page_counter() -> WordPageCounter | None:
    try:
        return WordPageCounter()
    except Exception:
        return None

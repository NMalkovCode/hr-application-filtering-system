"""Find candidates in an applications folder.

Supported layouts (and any mix of them):
  * one subfolder per candidate, holding their CV, cover letter, etc. (searched recursively)
  * one file per candidate directly inside the folder
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from . import config
from .extraction import ExtractionError, extract_document
from .models import Candidate, ExtractionIssue

# Guards against selecting the wrong folder (e.g. a whole drive) as one candidate.
MAX_FILES_PER_CANDIDATE = 15

_UNSUPPORTED_HINTS = {
    ".doc": "Old Word format (.doc) is not supported - save it as .docx or PDF.",
    ".rtf": "RTF is not supported - save it as .docx or PDF.",
    ".odt": "OpenDocument (.odt) is not supported - save it as .docx or PDF.",
    ".pages": "Apple Pages is not supported - export it as .docx or PDF.",
    ".heic": "HEIC photos are not supported - convert to JPG or PNG.",
    ".zip": "Archives are not supported - extract the files first.",
}


@dataclass
class DiscoveryResult:
    candidates: list[Candidate] = field(default_factory=list)
    issues: list[ExtractionIssue] = field(default_factory=list)

    @property
    def layout(self) -> str:
        folders = sum(c.is_folder for c in self.candidates)
        if folders == len(self.candidates):
            return "subfolders"
        if folders == 0:
            return "files"
        return "mixed"


def discover_candidates(folder: Path) -> DiscoveryResult:
    """List candidates without reading their files (fast; used to show counts immediately)."""
    folder = Path(folder)
    if not folder.is_dir():
        raise NotADirectoryError(f"Applications folder not found: {folder}")

    result = DiscoveryResult()
    entries: list[tuple[str, Path]] = []

    for entry in sorted(folder.iterdir(), key=_natural_key):
        if _is_ignored(entry):
            continue
        if entry.is_dir():
            files = _supported_files(entry, result.issues)
            if not files:
                result.issues.append(
                    ExtractionIssue(entry, "Folder contains no PDF, Word or image files - skipped.")
                )
                continue
            if len(files) > MAX_FILES_PER_CANDIDATE:
                result.issues.append(ExtractionIssue(
                    entry,
                    f"Folder has {len(files)} files (limit {MAX_FILES_PER_CANDIDATE}) - skipped. "
                    "Is this really one candidate's application?",
                ))
                continue
            entries.append((entry.name, entry))
        elif entry.suffix.lower() in config.SUPPORTED_EXTENSIONS:
            entries.append((entry.stem, entry))
        else:
            result.issues.append(ExtractionIssue(entry, _unsupported_message(entry)))

    for index, (name, path) in enumerate(entries, start=1):
        result.candidates.append(
            Candidate(candidate_id=f"C{index:03d}", display_name=_tidy_name(name), source_path=path)
        )
    return result


def load_candidate(candidate: Candidate) -> Candidate:
    """Read all files of a candidate into `candidate.documents` (errors go to `issues`)."""
    candidate.documents.clear()
    candidate.issues.clear()
    if candidate.is_folder:
        files = _supported_files(candidate.source_path, candidate.issues)
    else:
        files = [candidate.source_path]
    for path in files:
        try:
            candidate.documents.extend(extract_document(path))
        except ExtractionError as exc:
            candidate.issues.append(ExtractionIssue(path, str(exc)))
    return candidate


# --- helpers -----------------------------------------------------------------------

def _supported_files(folder: Path, issues: list[ExtractionIssue]) -> list[Path]:
    files = []
    for path in sorted(folder.rglob("*"), key=_natural_key):
        # Skip hidden/temp files and anything inside hidden folders.
        if not path.is_file() or any(_is_ignored_name(part) for part in path.relative_to(folder).parts):
            continue
        if path.suffix.lower() in config.SUPPORTED_EXTENSIONS:
            files.append(path)
        else:
            issues.append(ExtractionIssue(path, _unsupported_message(path)))
    return files


def _is_ignored(path: Path) -> bool:
    return _is_ignored_name(path.name)


def _is_ignored_name(name: str) -> bool:
    return name.lower() in config.IGNORED_FILE_NAMES or name.startswith(config.IGNORED_FILE_PREFIXES)


def _unsupported_message(path: Path) -> str:
    return _UNSUPPORTED_HINTS.get(
        path.suffix.lower(), f"Unsupported file type '{path.suffix or '(none)'}' - ignored."
    )


def _natural_key(path: Path):
    """Sort 'Candidate 2' before 'Candidate 10'."""
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", path.name)]


_SEPARATORS = re.compile(r"[_\-\.]+")
_CV_WORDS = re.compile(r"\b(cv|resume|résumé|curriculum vitae|application)\b", re.IGNORECASE)


def _tidy_name(name: str) -> str:
    """'jane_doe-CV' -> 'jane doe'. Falls back to the original if nothing is left."""
    tidy = _CV_WORDS.sub(" ", _SEPARATORS.sub(" ", name))
    tidy = " ".join(tidy.split())
    return tidy or name

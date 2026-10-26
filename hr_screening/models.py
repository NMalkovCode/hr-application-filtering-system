"""Core data structures shared across the pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class ContentKind(str, Enum):
    TEXT = "text"      # text extracted locally
    PDF = "pdf"        # image-only PDF, sent to Claude as a document
    IMAGE = "image"    # scanned image, sent to Claude's vision input


@dataclass
class SourceDocument:
    """One file belonging to an application, in a form ready to send to Claude."""

    path: Path
    kind: ContentKind
    text: str = ""
    # For PDF / IMAGE kinds: raw bytes and their media type.
    data: bytes = b""
    media_type: str = ""
    page_count: int = 0

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def needs_vision(self) -> bool:
        return self.kind is not ContentKind.TEXT

    def estimated_tokens(self) -> int:
        """Rough input-token estimate, used for cost estimates before a run."""
        if self.kind is ContentKind.TEXT:
            return max(1, len(self.text) // 4)
        if self.kind is ContentKind.PDF:
            # Each PDF page is sent as text + page image (~1,500-3,000 tokens per page).
            return max(1, self.page_count) * 2_500
        return 1_600  # one image at <=1568px long edge


@dataclass
class ExtractionIssue:
    path: Path
    message: str


@dataclass
class Candidate:
    """One application: a subfolder of files, or a single file."""

    candidate_id: str            # stable ID, e.g. "C001"
    display_name: str            # folder name or file stem
    source_path: Path            # the subfolder or the single file (copied to the output)
    documents: list[SourceDocument] = field(default_factory=list)
    issues: list[ExtractionIssue] = field(default_factory=list)
    # Remembered when the documents are released (see release()).
    _tokens: int | None = field(default=None, repr=False)
    _has_content: bool | None = field(default=None, repr=False)

    @property
    def is_folder(self) -> bool:
        return self.source_path.is_dir()

    @property
    def has_content(self) -> bool:
        if not self.documents and self._has_content is not None:
            return self._has_content
        return any(d.text.strip() or d.data for d in self.documents)

    def estimated_tokens(self) -> int:
        if not self.documents and self._tokens is not None:
            return self._tokens
        return sum(d.estimated_tokens() for d in self.documents)

    def release(self) -> None:
        """Drop the file contents (scans can be many MB) but keep the size estimate, so a
        batch of 200 applications never has to sit in memory at once. Documents are reloaded
        from disk when the candidate is evaluated."""
        if self.documents:
            self._tokens = self.estimated_tokens()
            self._has_content = self.has_content
            self.documents = []


class Tier(str, Enum):
    """Where a candidate lands for the role being screened. Values are the folder names."""

    TOP = "Top Match"
    CLOSE = "Close Match"
    BACKUP = "Backup"
    NOT_SUITABLE = "Not Suitable"
    NEEDS_REVIEW = "Needs Review"   # unreadable / not an application / AI error

    @property
    def is_shortlisted(self) -> bool:
        return self in (Tier.TOP, Tier.CLOSE, Tier.BACKUP)


@dataclass(frozen=True)
class OpenRole:
    """Another currently advertised role, condensed for comparison."""

    role_id: str        # "R01", ...
    title: str
    summary: str        # key requirements, a few sentences
    source: str = ""    # URL or file path

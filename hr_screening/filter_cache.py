"""Verified filter sets saved per job description, so a role can be re-screened later.

Entries are keyed by a fingerprint of the job description, so loading the same description
again offers the previously verified filters. "Clear Cache" in the UI calls `clear_cache()`.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from pydantic import ValidationError

from . import config
from .filters import FilterSet
from .models import ContentKind, SourceDocument

log = logging.getLogger(__name__)

_EXCERPT_CHARS = 300


@dataclass
class SavedFilterSet:
    fingerprint: str
    saved_at: datetime
    excerpt: str
    filter_set: FilterSet

    @property
    def label(self) -> str:
        return f"{self.filter_set.job_title} — saved {self.saved_at:%d %b %Y %H:%M}"


def fingerprint(documents: list[SourceDocument]) -> str:
    """Stable ID for a job description, insensitive to whitespace and letter case."""
    h = hashlib.sha256()
    for doc in documents:
        if doc.kind is ContentKind.TEXT:
            h.update(re.sub(r"\s+", " ", doc.text).strip().lower().encode("utf-8"))
        else:
            h.update(doc.data)
        h.update(b"\x1e")
    return h.hexdigest()[:32]


def _filters_dir(base: Path | None) -> Path:
    path = (base or config.cache_dir()) / "filters"
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_filter_set(documents: list[SourceDocument], filter_set: FilterSet, base: Path | None = None,
                    *, fp: str | None = None, excerpt: str | None = None) -> SavedFilterSet:
    """Save under the documents' fingerprint, or under `fp` when re-saving a set that was
    loaded from the cache (the original documents are then not available)."""
    fp = fp or fingerprint(documents)
    if excerpt is None:
        excerpt = " ".join(" ".join(d.text for d in documents).split())[:_EXCERPT_CHARS]
    entry = SavedFilterSet(fp, datetime.now().replace(microsecond=0), excerpt, filter_set)
    payload = {
        "fingerprint": fp,
        "saved_at": entry.saved_at.isoformat(),
        "excerpt": excerpt,
        "filter_set": filter_set.model_dump(mode="json"),
    }
    (_filters_dir(base) / f"{fp}.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return entry


def find_filter_set(documents: list[SourceDocument], base: Path | None = None) -> SavedFilterSet | None:
    path = _filters_dir(base) / f"{fingerprint(documents)}.json"
    return _read(path) if path.exists() else None


def list_filter_sets(base: Path | None = None) -> list[SavedFilterSet]:
    """All saved sets, newest first. Unreadable entries are skipped."""
    entries = [e for p in _filters_dir(base).glob("*.json") if (e := _read(p))]
    return sorted(entries, key=lambda e: e.saved_at, reverse=True)


def delete_filter_set(fp: str, base: Path | None = None) -> None:
    (_filters_dir(base) / f"{fp}.json").unlink(missing_ok=True)


def clear_cache(base: Path | None = None) -> int:
    """Delete everything in the cache (saved filters and cached open roles). Returns files removed."""
    root = base or config.cache_dir()
    count = sum(1 for p in root.rglob("*") if p.is_file())
    for child in root.iterdir():
        if child.is_dir():
            shutil.rmtree(child, ignore_errors=True)
        else:
            child.unlink(missing_ok=True)
    return count


def _read(path: Path) -> SavedFilterSet | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return SavedFilterSet(
            fingerprint=raw["fingerprint"],
            saved_at=datetime.fromisoformat(raw["saved_at"]),
            excerpt=raw.get("excerpt", ""),
            filter_set=FilterSet.model_validate(raw["filter_set"]),
        )
    except (OSError, KeyError, ValueError, ValidationError) as exc:
        log.warning("Ignoring unreadable saved filter set %s: %s", path.name, exc)
        return None

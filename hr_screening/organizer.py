"""Create the run's output folders, copy applications and write the reports.

<output>/<Job Title>_<YYYY-MM-DD_HHMM>/
    Top Match/     01_Jane_Doe/  01_Jane_Doe_Report.docx
    Close Match/   Backup/   Not Suitable/   Needs Review/
    Other Role/    Jane_Doe/  Jane_Doe_Other_Role_Report.docx
Originals are always copied, never moved.
"""

from __future__ import annotations

import logging
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import config
from .discovery import _is_ignored_name
from .filters import FilterSet
from .models import Tier
from .reports import write_other_role_report, write_tier_report
from .scoring import CandidateResult
from .system import long_path

log = logging.getLogger(__name__)

_ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}
MAX_NAME_CHARS = 60


@dataclass
class Placement:
    result: CandidateResult
    name: str                         # name used in outputs (pseudonym in anonymised mode)
    pseudonym: str
    application_dir: Path | None = None
    report: Path | None = None
    other_role_dir: Path | None = None
    other_role_report: Path | None = None
    errors: list[str] = field(default_factory=list)


def pseudonym(candidate_id: str) -> str:
    """'C007' -> 'Candidate 007'."""
    digits = "".join(ch for ch in candidate_id if ch.isdigit())
    return f"Candidate {digits or candidate_id}"


def output_name(result: CandidateResult, anonymised: bool) -> str:
    """Name shown in folders, reports and the spreadsheet."""
    c = result.candidate
    if anonymised:
        return pseudonym(c.candidate_id)
    if c.is_folder:
        return c.display_name                       # HR named the folder
    extracted = result.evaluation.candidate_name.strip() if result.evaluation else ""
    return " ".join(extracted.split()) or c.display_name


def safe_filename(text: str, max_len: int = MAX_NAME_CHARS) -> str:
    """Windows-safe file or folder name component."""
    text = _ILLEGAL.sub(" ", text)
    text = " ".join(text.split()).strip(" .")[:max_len].strip(" .")
    if not text or text.lower() in _RESERVED:
        text = f"_{text}" if text else "Unnamed"
    return text


def create_run_folder(output_root: Path, job_title: str, now: datetime | None = None, suffix: str = "") -> Path:
    now = now or datetime.now()
    base = f"{safe_filename(job_title, 50).replace(' ', '_')}_{now:%Y-%m-%d_%H%M}{suffix}"
    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    run_dir, n = output_root / base, 2
    while run_dir.exists():
        run_dir, n = output_root / f"{base}_{n}", n + 1
    run_dir.mkdir()
    return run_dir


def place_all(
    results: list[CandidateResult],
    filter_set: FilterSet,
    run_dir: Path,
    *,
    anonymised: bool = False,
    other_roles_enabled: bool = False,
) -> list[Placement]:
    """Copy every application into its folder(s) and write the reports. `results` must
    already be tiered (see scoring.assign_tiers). Per-candidate failures are recorded on the
    placement rather than stopping the run."""
    for tier in (Tier.TOP, Tier.CLOSE, Tier.BACKUP, Tier.NOT_SUITABLE):
        (run_dir / tier.value).mkdir(exist_ok=True)
    if other_roles_enabled:
        (run_dir / config.FOLDER_OTHER_ROLE).mkdir(exist_ok=True)

    used: dict[Path, set[str]] = {}
    names = _unique_names(results, anonymised)
    # Rank prefixes are zero-padded to the tier size so folders sort correctly (01..99, 001..250).
    tier_sizes: dict[Tier, int] = {}
    for r in results:
        tier_sizes[r.tier] = tier_sizes.get(r.tier, 0) + 1
    placements = []
    for r in results:
        name = names[r.candidate.candidate_id]
        p = Placement(result=r, name=name, pseudonym=pseudonym(r.candidate.candidate_id))
        stem = safe_filename(name).replace(" ", "_")

        tier_dir = run_dir / r.tier.value
        tier_dir.mkdir(exist_ok=True)
        width = max(2, len(str(tier_sizes[r.tier])))
        base = _unique(tier_dir, f"{r.rank:0{width}d}_{stem}", used)
        try:
            p.application_dir = _copy_application(r, tier_dir / base, anonymised, p.pseudonym)
        except OSError as exc:
            p.errors.append(f"Could not copy application: {exc}")
        if r.tier.is_shortlisted:
            try:
                p.report = write_tier_report(r, filter_set, name, tier_dir / f"{base}_Report.docx")
            except Exception as exc:
                log.exception("Report failed for %s", r.candidate.candidate_id)
                p.errors.append(f"Could not write report: {exc}")

        if r.other_role and other_roles_enabled:
            other_dir = run_dir / config.FOLDER_OTHER_ROLE
            other_base = _unique(other_dir, stem, used)
            try:
                p.other_role_dir = _copy_application(r, other_dir / other_base, anonymised, p.pseudonym)
                p.other_role_report = write_other_role_report(
                    r, filter_set, name, other_dir / f"{other_base}_Other_Role_Report.docx")
            except Exception as exc:
                log.exception("Other Role output failed for %s", r.candidate.candidate_id)
                p.errors.append(f"Could not write Other Role output: {exc}")
        placements.append(p)
    return placements


# --- helpers -----------------------------------------------------------------------

def _unique_names(results: list[CandidateResult], anonymised: bool) -> dict[str, str]:
    """Output names, disambiguating duplicates (two 'John Smith's) with their candidate ID."""
    raw = {r.candidate.candidate_id: output_name(r, anonymised) for r in results}
    counts: dict[str, int] = {}
    for name in raw.values():
        counts[name.lower()] = counts.get(name.lower(), 0) + 1
    return {cid: (f"{name} ({cid})" if counts[name.lower()] > 1 else name) for cid, name in raw.items()}


def _unique(folder: Path, base: str, used: dict[Path, set[str]]) -> str:
    taken = used.setdefault(folder, set())
    candidate, n = base, 2
    while candidate.lower() in taken or (folder / candidate).exists():
        candidate, n = f"{base}_{n}", n + 1
    taken.add(candidate.lower())
    return candidate


def _copy_application(r: CandidateResult, dest: Path, anonymised: bool, pseudo: str) -> Path:
    src = Path(long_path(r.candidate.source_path))
    if not src.exists():
        raise FileNotFoundError(f"original application no longer exists: {r.candidate.source_path}")
    Path(long_path(dest)).mkdir(parents=True, exist_ok=False)
    files = (
        [p for p in sorted(src.rglob("*")) if p.is_file()
         and not any(_is_ignored_name(part) for part in p.relative_to(src).parts)]
        if src.is_dir() else [src]
    )
    for i, f in enumerate(files, 1):
        if anonymised:
            # File names often contain the candidate's name; contents are not altered.
            target = dest / f"{pseudo} - Document {i}{f.suffix.lower()}"
        else:
            target = dest / (f.relative_to(src) if src.is_dir() else f.name)
            Path(long_path(target.parent)).mkdir(parents=True, exist_ok=True)
        # Long-path form: deep application folders inside a deep results folder can exceed
        # Windows' 260-character limit.
        shutil.copy2(long_path(f), long_path(target))
    return dest

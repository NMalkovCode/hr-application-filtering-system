"""End-to-end screening run, used by the UI and the command-line script.

    pipeline = ScreeningPipeline(client)
    prep = pipeline.prepare(request)           # read files, open roles, cost estimate (no evaluation yet)
    if prep.estimate.exceeds(limit): ...       # ask HR before spending
    outcome = pipeline.run(prep)               # evaluate, tier, write folders/reports/spreadsheet
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from . import config
from .careers import OpenRolesResult, load_open_roles
from .costs import CostEstimate, estimate_run_cost
from .discovery import discover_candidates, load_candidate
from .evaluator import Evaluator, Progress, evaluate_all
from .filters import FilterSet
from .llm import ClaudeClient
from .models import Candidate, ExtractionIssue, Tier
from .organizer import Placement, create_run_folder, place_all
from .scoring import assign_tiers
from .settings import TierThresholds
from .spreadsheet import RunInfo, write_candidate_key, write_summary
from .system import keep_awake
from .web import CareersError

log = logging.getLogger(__name__)

StatusCallback = Callable[[str, int, int], None]   # message, done, total


@dataclass
class RunRequest:
    applications_dir: Path
    output_dir: Path
    filter_set: FilterSet
    thresholds: TierThresholds = field(default_factory=TierThresholds)
    anonymised: bool = False
    concurrency: int = 4
    careers_url: str = ""
    careers_folder: str = ""


@dataclass
class Preparation:
    request: RunRequest
    candidates: list[Candidate]
    discovery_issues: list[ExtractionIssue]
    roles: OpenRolesResult
    roles_error: str            # set when the careers source could not be read (check skipped)
    estimate: CostEstimate
    evaluator: Evaluator


@dataclass
class RunOutcome:
    run_dir: Path
    placements: list[Placement]
    summary_path: Path
    key_path: Path | None
    cost_usd: float
    cancelled: bool

    def count(self, tier: Tier) -> int:
        return sum(1 for p in self.placements if p.result.tier is tier)

    @property
    def other_role_count(self) -> int:
        return sum(1 for p in self.placements if p.other_role_dir)


class ScreeningPipeline:
    def __init__(self, client: ClaudeClient):
        self.client = client

    def prepare(self, request: RunRequest, on_status: StatusCallback | None = None) -> Preparation:
        status = on_status or (lambda *_: None)
        problems = request.filter_set.validation_errors()
        if problems:
            raise ValueError("Filters are not valid: " + " ".join(problems))
        request.thresholds.validate()
        apps = Path(request.applications_dir).resolve()
        out = Path(request.output_dir).resolve()
        if out == apps or out.is_relative_to(apps):
            # Results inside the applications folder would be picked up as candidates next time.
            raise ValueError("Choose a results folder outside the applications folder.")

        status("Finding applications…", 0, 0)
        found = discover_candidates(request.applications_dir)
        if not found.candidates:
            raise FileNotFoundError("No applications were found in the selected folder.")
        total = len(found.candidates)
        for i, c in enumerate(found.candidates, 1):
            status(f"Reading applications ({i}/{total})…", i, total)
            load_candidate(c)
            c.release()   # keep only the size estimate; reloaded when evaluated

        roles, roles_error = OpenRolesResult(), ""
        if request.careers_url or request.careers_folder:
            status("Reading the company's other open roles…", 0, 0)
            try:
                roles = load_open_roles(
                    self.client, url=request.careers_url, folder=request.careers_folder,
                    exclude_title=request.filter_set.job_title, concurrency=request.concurrency,
                )
            except CareersError as exc:
                roles_error = str(exc)
                roles = OpenRolesResult(notes=[f"Other Role check skipped: {exc}"])

        evaluator = Evaluator(self.client, request.filter_set, roles.roles)
        estimate = estimate_run_cost(found.candidates, evaluator.system_prompt, self.client.model,
                                     already_spent_usd=self.client.usage.cost_usd)
        return Preparation(request, found.candidates, found.issues, roles, roles_error, estimate, evaluator)

    def run(
        self,
        prep: Preparation,
        on_progress: Callable[[Progress], None] | None = None,
        cancel: threading.Event | None = None,
        on_status: StatusCallback | None = None,
    ) -> RunOutcome:
        status = on_status or (lambda *_: None)
        req = prep.request
        cancel = cancel or threading.Event()
        started = datetime.now()

        with keep_awake():
            results = evaluate_all(prep.evaluator, prep.candidates, concurrency=req.concurrency,
                                   on_progress=on_progress, cancel=cancel)
        cancelled = cancel.is_set()
        ordered = assign_tiers(results, req.thresholds)

        status("Writing reports and copying applications…", 0, 0)
        run_dir = create_run_folder(req.output_dir, req.filter_set.job_title,
                                    suffix="_INCOMPLETE" if cancelled else "")
        other_roles_on = bool(prep.roles.roles)
        placements = place_all(ordered, req.filter_set, run_dir,
                               anonymised=req.anonymised, other_roles_enabled=other_roles_on)

        notes = list(prep.roles.notes)
        notes += [f"{i.path.name}: {i.message}" for i in prep.discovery_issues]
        if cancelled:
            notes.insert(0, "The run was cancelled; unprocessed applications are in Needs Review.")
        info = RunInfo(
            job_title=req.filter_set.job_title,
            started=started,
            finished=datetime.now(),
            model=config.MODELS[self.client.model].label,
            thresholds=req.thresholds,
            anonymised=req.anonymised,
            applications_dir=str(req.applications_dir),
            cost_usd=self.client.usage.cost_usd,
            other_roles_source=(req.careers_url or req.careers_folder) if other_roles_on else "",
            open_roles=prep.roles.roles,
            cancelled=cancelled,
            notes=notes,
        )
        summary = write_summary(run_dir / "Summary.xlsx", placements, req.filter_set, info)
        key = write_candidate_key(run_dir / "Candidate_Key.xlsx", placements) if req.anonymised else None
        return RunOutcome(run_dir, placements, summary, key, self.client.usage.cost_usd, cancelled)

"""Deterministic scoring, elimination, tiering and ranking.

Claude only judges each filter (met / partial / not met / no evidence) with evidence; every
number and placement below is computed here, so results are consistent and explainable.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from .evaluation import CandidateEvaluation, FilterJudgement, Judgement
from .filters import FilterSet, FilterType, ScreeningFilter
from .models import Candidate, OpenRole, Tier
from .settings import TierThresholds

log = logging.getLogger(__name__)

MAX_STRENGTHS = 4
MAX_GAPS = 3
MAX_ALT_REASONS = 3


@dataclass
class ScoredFilter:
    filter: ScreeningFilter
    result: Judgement
    evidence: str


@dataclass
class CandidateResult:
    candidate: Candidate
    evaluation: CandidateEvaluation | None = None
    scored: list[ScoredFilter] = field(default_factory=list)
    score: int = 0                      # 0-100 over all filters
    must_have_score: int = 0            # 0-100 over must-haves only (tie-breaker)
    failed_must_haves: list[ScreeningFilter] = field(default_factory=list)
    tier: Tier = Tier.NEEDS_REVIEW
    rank: int = 0                       # 1-based position within the tier
    # A role the candidate strongly fits (tracked in the spreadsheet even if not copied).
    alternative_role: OpenRole | None = None
    other_role: OpenRole | None = None  # set when also placed in the Other Role folder
    error: str = ""                     # why the candidate could not be assessed at all
    # Assessed, but sent to Needs Review rather than rejected (e.g. some files were unreadable).
    review_reason: str = ""

    @property
    def eliminated(self) -> bool:
        return bool(self.failed_must_haves)

    @property
    def name(self) -> str:
        return self.candidate.display_name

    @property
    def overall_fit(self) -> int:
        return self.evaluation.overall_fit if self.evaluation else 0

    @property
    def one_line_reason(self) -> str:
        if self.error:
            return self.error
        summary = ""
        if self.evaluation and self.evaluation.one_line_summary.strip():
            summary = self.evaluation.one_line_summary.strip()
        elif self.failed_must_haves:
            summary = "Does not meet: " + "; ".join(f.criterion for f in self.failed_must_haves)
        if self.review_reason:
            return f"{self.review_reason} Provisional assessment: {summary}" if summary else self.review_reason
        return summary


def needs_review(candidate: Candidate, reason: str) -> CandidateResult:
    return CandidateResult(candidate=candidate, tier=Tier.NEEDS_REVIEW, error=reason)


def score_evaluation(
    candidate: Candidate,
    evaluation: CandidateEvaluation,
    filter_set: FilterSet,
    open_roles: list[OpenRole] = (),
) -> CandidateResult:
    """Turn Claude's judgements into a scored (not yet tiered) result."""
    if not evaluation.is_application:
        return needs_review(candidate, "Files do not appear to be a job application.")

    evaluation = _tidy(evaluation)
    by_id: dict[str, FilterJudgement] = {}
    for j in evaluation.judgements:
        by_id.setdefault(j.filter_id.strip().upper(), j)

    scored = []
    for f in filter_set.filters:
        j = by_id.get(f.id.upper())
        if j is None:
            log.warning("No judgement for %s on %s; treating as no evidence", f.id, candidate.candidate_id)
            scored.append(ScoredFilter(f, Judgement.NO_EVIDENCE, "Not assessed"))
        else:
            scored.append(ScoredFilter(f, j.result, j.evidence.strip()))

    result = CandidateResult(candidate=candidate, evaluation=evaluation, scored=scored)
    result.score = _weighted_percent(scored)
    result.must_have_score = _weighted_percent([s for s in scored if s.filter.type is FilterType.MUST_HAVE])
    result.failed_must_haves = [
        s.filter for s in scored
        if s.filter.type is FilterType.MUST_HAVE and s.result in (Judgement.NOT_MET, Judgement.NO_EVIDENCE)
    ]
    result.alternative_role = _alternative_role(evaluation, open_roles)
    return result


def assign_tiers(results: list[CandidateResult], thresholds: TierThresholds) -> list[CandidateResult]:
    """Set tier and rank on every result. Returns results ordered by tier, then rank."""
    thresholds.validate()
    for r in results:
        r.review_reason = ""
        if r.error or r.evaluation is None:
            r.tier = Tier.NEEDS_REVIEW
        elif r.eliminated or r.score < thresholds.backup:
            if r.candidate.issues:
                # Never reject on a partial application: the unreadable file may be the CV.
                r.tier = Tier.NEEDS_REVIEW
                r.review_reason = _unreadable_reason(r)
            else:
                r.tier = Tier.NOT_SUITABLE
        elif r.score >= thresholds.top:
            r.tier = Tier.TOP
        elif r.score >= thresholds.close:
            r.tier = Tier.CLOSE
        else:
            r.tier = Tier.BACKUP

        # Other Role: a strong fit elsewhere. Shortlisted candidates are duplicated only when
        # the other role suits them clearly better; everyone else is suggested whenever the
        # fit is strong.
        if r.tier is Tier.NEEDS_REVIEW:
            if r.error:
                r.alternative_role = None
            r.other_role = None         # a strong alternative stays visible in the spreadsheet
            continue
        if r.alternative_role and (not r.tier.is_shortlisted or r.evaluation.alternative_is_better):
            r.other_role = r.alternative_role
        else:
            r.other_role = None

    tier_order = list(Tier)
    ordered = sorted(results, key=lambda r: (tier_order.index(r.tier), *_rank_key(r)))
    counters: dict[Tier, int] = {}
    for r in ordered:
        counters[r.tier] = counters.get(r.tier, 0) + 1
        r.rank = counters[r.tier]
    return ordered


# --- helpers -----------------------------------------------------------------------

def _rank_key(r: CandidateResult):
    """Score first; equal scores are separated by must-have strength, then the AI's overall-fit
    rating, then the number of filters fully met. Name is only a last resort for full ties."""
    met = sum(s.result is Judgement.MET for s in r.scored)
    return (-r.score, -r.must_have_score, -r.overall_fit, -met, r.name.lower(), r.candidate.candidate_id)


def _unreadable_reason(r: CandidateResult) -> str:
    files = ", ".join(sorted({i.path.name for i in r.candidate.issues}))
    return (f"Not shortlisted on the readable files, but {files} could not be read - check the full "
            "application before rejecting.")


def _weighted_percent(scored: list[ScoredFilter]) -> int:
    total = sum(s.filter.weight for s in scored)
    if not total:
        return 100  # e.g. no must-haves at all
    earned = sum(s.filter.weight * s.result.credit for s in scored)
    return int(round(100 * earned / total))


def _alternative_role(evaluation: CandidateEvaluation, open_roles) -> OpenRole | None:
    if evaluation.alternative_fit != "strong":
        return None
    wanted = evaluation.alternative_role_id.strip().upper()
    return next((role for role in open_roles if role.role_id.upper() == wanted), None)


def _tidy(e: CandidateEvaluation) -> CandidateEvaluation:
    """Enforce list lengths so reports always fit on one page."""
    def clean(items: list[str], limit: int) -> list[str]:
        return [s.strip() for s in items if s.strip()][:limit]

    return e.model_copy(update={
        "strengths": clean(e.strengths, MAX_STRENGTHS),
        "gaps": clean(e.gaps, MAX_GAPS),
        "alternative_reasons": clean(e.alternative_reasons, MAX_ALT_REASONS),
        "integrity_notes": clean(e.integrity_notes, 5),
    })

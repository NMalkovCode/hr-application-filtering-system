"""Builders for filter sets, candidates and evaluations used across tests."""

from __future__ import annotations

from pathlib import Path

from hr_screening.evaluation import CandidateEvaluation, FilterJudgement, Judgement
from hr_screening.filters import FilterCategory, FilterSet, FilterType, ScreeningFilter
from hr_screening.models import Candidate, ContentKind, OpenRole, SourceDocument

M, P, N, X = Judgement.MET, Judgement.PARTIAL, Judgement.NOT_MET, Judgement.NO_EVIDENCE


def filter_set() -> FilterSet:
    """F01, F02 must-haves (weights 5, 3); F03, F04 preferred (weights 2, 2). Total weight 12."""
    def f(i, text, t, w):
        return ScreeningFilter(id=f"F{i:02d}", criterion=text, type=t, weight=w, category=FilterCategory.SKILL)
    return FilterSet(job_title="Data Analyst", job_summary="Analyse data.", filters=[
        f(1, "At least 5 years of SQL", FilterType.MUST_HAVE, 5),
        f(2, "Degree in a quantitative subject", FilterType.MUST_HAVE, 3),
        f(3, "Python", FilterType.PREFERRED, 2),
        f(4, "Logistics experience", FilterType.PREFERRED, 2),
    ])


OPEN_ROLES = [
    OpenRole("R01", "Data Engineer", "Builds pipelines; Python, Spark, cloud."),
    OpenRole("R02", "Operations Manager", "Runs warehouse operations; people management."),
]


def candidate(name: str = "Jane Doe", cid: str = "C001", text: str = "CV text") -> Candidate:
    c = Candidate(candidate_id=cid, display_name=name, source_path=Path(f"apps/{name}"))
    c.documents.append(SourceDocument(Path(f"{name}.pdf"), ContentKind.TEXT, text=text))
    return c


def evaluation(results: list[Judgement], *, alt_id="none", alt_fit="none", alt_better=False,
               is_application=True, **overrides) -> CandidateEvaluation:
    data = dict(
        is_application=is_application,
        candidate_name="Jane Doe",
        judgements=[FilterJudgement(filter_id=f"F{i:02d}", result=r, evidence=f"evidence {i}")
                    for i, r in enumerate(results, 1)],
        verdict="Strong analyst.",
        strengths=["SQL at Acme"],
        gaps=[],
        one_line_summary="Strong SQL analyst.",
        overall_fit=5,
        alternative_role_id=alt_id,
        alternative_fit=alt_fit,
        alternative_is_better=alt_better,
        alternative_reasons=["Python pipelines"] if alt_fit == "strong" else [],
        alternative_summary="",
        integrity_notes=[],
    )
    data.update(overrides)
    return CandidateEvaluation(**data)

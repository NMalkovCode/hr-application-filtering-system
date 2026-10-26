"""Structured output Claude returns for each application."""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel


class Judgement(str, Enum):
    MET = "met"
    PARTIAL = "partial"
    NOT_MET = "not_met"
    NO_EVIDENCE = "no_evidence"

    @property
    def credit(self) -> float:
        return {"met": 1.0, "partial": 0.5}.get(self.value, 0.0)

    @property
    def label(self) -> str:
        return {"met": "Met", "partial": "Partially met", "not_met": "Not met",
                "no_evidence": "No evidence"}[self.value]


class FilterJudgement(BaseModel):
    filter_id: str
    result: Judgement
    evidence: str


class CandidateEvaluation(BaseModel):
    is_application: bool
    candidate_name: str
    judgements: list[FilterJudgement]
    verdict: str
    strengths: list[str]
    gaps: list[str]
    one_line_summary: str
    # Holistic 1-10 rating; only used to order candidates whose scores are equal.
    overall_fit: Literal[1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    alternative_role_id: str
    alternative_fit: Literal["strong", "moderate", "weak", "none"]
    alternative_is_better: bool
    alternative_reasons: list[str]
    alternative_summary: str
    integrity_notes: list[str]

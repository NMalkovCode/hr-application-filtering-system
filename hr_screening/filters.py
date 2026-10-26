"""Screening filters: what HR verifies before applications are processed."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

MAX_FILTERS = 25
MIN_WEIGHT, MAX_WEIGHT = 1, 5


class FilterType(str, Enum):
    MUST_HAVE = "must_have"   # not met -> candidate eliminated
    PREFERRED = "preferred"   # contributes to the score

    @property
    def label(self) -> str:
        return "Must-have" if self is FilterType.MUST_HAVE else "Preferred"


class FilterCategory(str, Enum):
    EXPERIENCE = "experience"
    SKILL = "skill"
    EDUCATION = "education"
    CERTIFICATION = "certification"
    LANGUAGE = "language"
    ELIGIBILITY = "eligibility"   # right to work, location, licence, clearance
    OTHER = "other"

    @property
    def label(self) -> str:
        return self.value.capitalize()


class ScreeningFilter(BaseModel):
    id: str
    criterion: str
    category: FilterCategory = FilterCategory.OTHER
    type: FilterType = FilterType.PREFERRED
    weight: int = Field(default=3, ge=MIN_WEIGHT, le=MAX_WEIGHT)
    # Why the filter exists, quoting the job description - shown to HR during verification.
    rationale: str = ""


class FilterSet(BaseModel):
    job_title: str
    job_summary: str = ""
    filters: list[ScreeningFilter]
    # Notes for HR, e.g. requirements that were reworded to avoid discrimination.
    warnings: list[str] = Field(default_factory=list)

    @property
    def must_haves(self) -> list[ScreeningFilter]:
        return [f for f in self.filters if f.type is FilterType.MUST_HAVE]

    @property
    def preferred(self) -> list[ScreeningFilter]:
        return [f for f in self.filters if f.type is FilterType.PREFERRED]

    def renumbered(self) -> "FilterSet":
        """Copy with filter IDs F01, F02, ... in the current order (after HR edits)."""
        filters = [f.model_copy(update={"id": f"F{i:02d}"}) for i, f in enumerate(self.filters, 1)]
        return self.model_copy(update={"filters": filters})

    def validation_errors(self) -> list[str]:
        """Problems that must be fixed before HR can press Verify."""
        errors = []
        if not self.job_title.strip():
            errors.append("Job title is empty.")
        if not self.filters:
            errors.append("Add at least one filter.")
        if len(self.filters) > MAX_FILTERS:
            errors.append(f"Too many filters ({len(self.filters)}); the maximum is {MAX_FILTERS}.")
        seen = set()
        for i, f in enumerate(self.filters, 1):
            text = " ".join(f.criterion.split()).lower()
            if not text:
                errors.append(f"Filter {i} has no criterion text.")
            elif text in seen:
                errors.append(f"Filter {i} duplicates another filter: '{f.criterion}'.")
            seen.add(text)
            if not MIN_WEIGHT <= f.weight <= MAX_WEIGHT:
                errors.append(f"Filter {i} weight must be between {MIN_WEIGHT} and {MAX_WEIGHT}.")
        return errors

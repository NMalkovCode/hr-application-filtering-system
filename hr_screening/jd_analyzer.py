"""Job description -> proposed screening filters (for HR to verify)."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from .extraction import extract_document
from .filters import MAX_FILTERS, FilterCategory, FilterSet, FilterType, ScreeningFilter
from .llm import ClaudeClient, LLMError, document_blocks
from .models import ContentKind, SourceDocument

SYSTEM_PROMPT = """\
You are an experienced recruitment specialist helping an HR team screen job applications. \
You turn a job description into a list of screening filters. HR reviews and edits the filters, \
then every application is checked against each filter using only what the application itself \
(CV, cover letter) says. Your filters therefore decide who is eliminated and how the rest are \
ranked, so they must be accurate, fair and checkable.

How to write filters:
- One requirement per filter, specific and observable in a CV: "At least 3 years' experience in \
B2B software sales", not "Sales experience". For soft skills, describe the evidence to look for: \
"Evidence of managing stakeholders, e.g. presenting to senior leadership".
- Do not bundle unrelated requirements into one filter, and merge duplicates.
- Typically 6-15 filters in total.
- type "must_have": only requirements the job description makes mandatory ("required", "must", \
"essential", "minimum") or that are legally necessary for the role (licence, professional \
registration, right to work when stated). Any applicant who fails a must-have is eliminated, so \
be conservative - usually 2-6 must-haves. Items described as desirable, preferred, a plus or a \
bonus are "preferred". When the description does not say, only core, non-negotiable items are \
must-haves.
- weight 1-5: how important the requirement is to success in the role (5 = central to the job). \
Must-haves get a weight too, because they also count towards the score.
- rationale: one short sentence quoting or paraphrasing the job description.
- When the description states years of experience, write "At least N years ...".

Fairness rules (mandatory):
- Never create filters on protected characteristics - age, sex or gender, marital or family \
status, pregnancy, race, ethnicity, nationality or national origin, religion or belief, \
disability, sexual orientation - or on proxies for them, such as photos, graduation year, \
"young/energetic team" or "digital native".
- Phrase language requirements as proficiency ("Professional fluency in English"), never \
"native speaker".
- Turn maximum-experience caps ("no more than 5 years") into minimum requirements only.
- Right-to-work, location or travel requirements are allowed when the description states them.
- If you reworded or dropped a requirement for these reasons, say so briefly in warnings.

Use warnings for anything else HR should know before verifying, for example: requirements that \
cannot be checked from a CV (such as availability for weekend shifts - these belong at interview, \
not in the filters), a vague description, or conflicting requirements. Keep each warning to one \
sentence. Return an empty list if there is nothing to flag.

job_title: the role's title as advertised. job_summary: one or two sentences describing the role.
If the material is not a job description, set is_job_description to false and return no filters.\
"""


class _ExtractedFilter(BaseModel):
    criterion: str
    category: FilterCategory
    type: FilterType
    weight: Literal[1, 2, 3, 4, 5]
    rationale: str


class _JobAnalysis(BaseModel):
    is_job_description: bool
    job_title: str
    job_summary: str
    filters: list[_ExtractedFilter]
    warnings: list[str]


class JobDescriptionError(LLMError):
    pass


def load_job_description(path: Path) -> list[SourceDocument]:
    """Read a job description file (.pdf/.docx/.txt, or a scan)."""
    return extract_document(Path(path))


def analyze_job_description(
    client: ClaudeClient,
    *,
    text: str | None = None,
    documents: list[SourceDocument] | None = None,
) -> FilterSet:
    """Ask Claude for proposed filters. Pass pasted `text` and/or documents loaded from a file."""
    documents = list(documents or [])
    if text and text.strip():
        documents.insert(0, SourceDocument(path=Path("pasted text"), kind=ContentKind.TEXT, text=text.strip()))
    if not any(d.text.strip() or d.data for d in documents):
        raise JobDescriptionError("The job description is empty.")

    content = document_blocks(documents, label="job_description")
    content.append({"type": "text", "text": "Create the screening filters for this job description."})

    analysis = client.structured(
        system=SYSTEM_PROMPT,
        content=content,
        output_model=_JobAnalysis,
        effort="high",
    )
    if not analysis.is_job_description:
        raise JobDescriptionError(
            "This does not look like a job description. Check that the right text or file was provided."
        )
    return _to_filter_set(analysis)


def _to_filter_set(analysis: _JobAnalysis) -> FilterSet:
    filters: list[ScreeningFilter] = []
    seen: set[str] = set()
    for f in analysis.filters:
        criterion = " ".join(f.criterion.split())
        key = criterion.lower()
        if not criterion or key in seen:
            continue
        seen.add(key)
        filters.append(ScreeningFilter(
            id="", criterion=criterion, category=f.category, type=f.type,
            weight=f.weight, rationale=f.rationale.strip(),
        ))
    warnings = [w.strip() for w in analysis.warnings if w.strip()]
    if len(filters) > MAX_FILTERS:
        warnings.append(f"Only the first {MAX_FILTERS} proposed filters are shown.")
        filters = filters[:MAX_FILTERS]
    if not filters:
        warnings.append("No screening filters could be derived from this job description - add them manually.")
    return FilterSet(
        job_title=" ".join(analysis.job_title.split()) or "Untitled role",
        job_summary=analysis.job_summary.strip(),
        filters=filters,
        warnings=warnings,
    ).renumbered()

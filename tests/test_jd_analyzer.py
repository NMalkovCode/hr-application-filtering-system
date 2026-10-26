from __future__ import annotations

from pathlib import Path

import pytest
from anthropic.lib._parse._transform import transform_schema

from hr_screening import jd_analyzer
from hr_screening.filters import FilterCategory, FilterSet, FilterType, ScreeningFilter
from hr_screening.jd_analyzer import JobDescriptionError, _ExtractedFilter, _JobAnalysis, analyze_job_description
from hr_screening.llm import ClaudeClient

from .conftest import make_docx
from .fakes import fake_message, install_fake


def _analysis(**overrides) -> _JobAnalysis:
    data = dict(
        is_job_description=True,
        job_title="  Senior   Data Analyst ",
        job_summary="Analyse data. ",
        filters=[
            _ExtractedFilter(criterion="At least 5 years' experience with SQL", category=FilterCategory.EXPERIENCE,
                             type=FilterType.MUST_HAVE, weight=5, rationale="'5+ years SQL required'"),
            _ExtractedFilter(criterion="Power BI dashboarding", category=FilterCategory.SKILL,
                             type=FilterType.PREFERRED, weight=3, rationale="Listed as desirable"),
            _ExtractedFilter(criterion="power bi  dashboarding", category=FilterCategory.SKILL,
                             type=FilterType.PREFERRED, weight=2, rationale="duplicate"),
        ],
        warnings=["Removed 'native English speaker'; replaced with professional fluency.", "  "],
    )
    data.update(overrides)
    return _JobAnalysis(**data)


def test_analysis_becomes_numbered_filter_set():
    client = ClaudeClient("sk-test")
    calls = install_fake(client, [fake_message(_analysis())])

    fs = analyze_job_description(client, text="We are hiring a Senior Data Analyst ...")

    assert fs.job_title == "Senior Data Analyst"
    assert [f.id for f in fs.filters] == ["F01", "F02"]  # duplicate removed
    assert fs.must_haves[0].criterion.startswith("At least 5 years")
    assert fs.warnings == ["Removed 'native English speaker'; replaced with professional fluency."]
    assert calls[0]["output_config"] == {"effort": "high"}
    assert "Fairness rules" in calls[0]["system"][0]["text"]
    assert calls[0]["messages"][0]["content"][0]["text"].startswith('<job_description file="pasted text">')


def test_file_input(tmp_path: Path):
    client = ClaudeClient("sk-test")
    calls = install_fake(client, [fake_message(_analysis())])
    docs = jd_analyzer.load_job_description(make_docx(tmp_path / "jd.docx", text="Job: analyst\nRequired: SQL"))
    analyze_job_description(client, documents=docs)
    assert "Required: SQL" in calls[0]["messages"][0]["content"][0]["text"]


def test_not_a_job_description():
    client = ClaudeClient("sk-test")
    install_fake(client, [fake_message(_analysis(is_job_description=False, filters=[]))])
    with pytest.raises(JobDescriptionError, match="does not look like"):
        analyze_job_description(client, text="Shopping list: eggs, milk")


def test_empty_input_makes_no_call():
    client = ClaudeClient("sk-test")
    calls = install_fake(client, [])
    with pytest.raises(JobDescriptionError, match="empty"):
        analyze_job_description(client, text="   ")
    assert calls == []


def test_no_filters_returns_empty_set_with_warning():
    client = ClaudeClient("sk-test")
    install_fake(client, [fake_message(_analysis(filters=[], warnings=[]))])
    fs = analyze_job_description(client, text="Vague job ad")
    assert fs.filters == [] and "add them manually" in fs.warnings[0]
    assert "Add at least one filter." in fs.validation_errors()


def test_output_schema_is_accepted_by_sdk():
    transform_schema(_JobAnalysis.model_json_schema())


def test_validation_errors_after_hr_edits():
    fs = FilterSet(job_title="Analyst", filters=[
        ScreeningFilter(id="F01", criterion="SQL"),
        ScreeningFilter(id="F02", criterion=" sql "),
        ScreeningFilter(id="F03", criterion=""),
    ])
    fs.filters[0] = fs.filters[0].model_copy(update={"weight": 9})
    errors = fs.validation_errors()
    assert any("duplicates" in e for e in errors)
    assert any("no criterion" in e for e in errors)
    assert any("weight" in e for e in errors)
    assert [f.id for f in FilterSet(job_title="x", filters=fs.filters[::-1]).renumbered().filters] == ["F01", "F02", "F03"]

"""A fake Claude for UI tests and screenshots: answers every request type the app makes."""

from __future__ import annotations

from pathlib import Path

from hr_screening.careers import _RoleSummary
from hr_screening.evaluation import CandidateEvaluation
from hr_screening.filters import FilterCategory, FilterType
from hr_screening.jd_analyzer import _ExtractedFilter, _JobAnalysis
from hr_screening.llm import ClaudeClient
from hr_screening.settings import Settings
from hr_screening.ui.context import AppContext, MemoryKeyStore

from .conftest import make_docx, make_text_pdf
from .fakes import fake_message, install_fake
from .helpers import M, N, P, X, evaluation

ANALYSIS = _JobAnalysis(
    is_job_description=True,
    job_title="Data Analyst",
    job_summary="Owns reporting and analysis for the warehouse network.",
    filters=[
        _ExtractedFilter(criterion="At least 5 years of SQL", category=FilterCategory.EXPERIENCE,
                         type=FilterType.MUST_HAVE, weight=5, rationale="'5+ years SQL essential'"),
        _ExtractedFilter(criterion="Degree in a quantitative subject", category=FilterCategory.EDUCATION,
                         type=FilterType.MUST_HAVE, weight=3, rationale="Listed under requirements"),
        _ExtractedFilter(criterion="Python (pandas)", category=FilterCategory.SKILL,
                         type=FilterType.PREFERRED, weight=2, rationale="Nice to have"),
        _ExtractedFilter(criterion="Logistics experience", category=FilterCategory.EXPERIENCE,
                         type=FilterType.PREFERRED, weight=2, rationale="Nice to have"),
    ],
    warnings=["'Native English speaker' was rephrased as professional fluency in English."],
)

PROFILES = {
    "PROFILE-TOP": [M, M, M, M],
    "PROFILE-CLOSE": [M, P, M, P],
    "PROFILE-OUT": [N, M, M, X],
}


def respond(kwargs):
    fmt = kwargs["output_format"]
    if fmt is _JobAnalysis:
        return fake_message(ANALYSIS)
    if fmt is _RoleSummary:
        title = kwargs["messages"][0]["content"][0]["text"].split(">\n", 1)[1].splitlines()[0]
        return fake_message(_RoleSummary(is_job_posting=True, title=title, summary=f"{title}: pipelines, Python, SQL."))
    assert fmt is CandidateEvaluation
    text = " ".join(b.get("text", "") for b in kwargs["messages"][0]["content"])
    system = kwargs["system"][0]["text"]
    for marker, results in PROFILES.items():
        if marker in text:
            alt = {}
            if marker == "PROFILE-OUT" and 'title="Data Engineer"' in system:
                role_id = system.split('title="Data Engineer"')[0].rsplit('id="', 1)[1][:3]
                alt = dict(alt_id=role_id, alt_fit="strong")
            return fake_message(evaluation(results, **alt), input_tokens=3000, output_tokens=1500)
    return fake_message(evaluation([X] * 4, is_application=False))


def fake_client_factory(api_key: str, model: str) -> ClaudeClient:
    client = ClaudeClient(api_key or "sk-none", model=model)
    install_fake(client, respond)
    return client


def make_context(tmp_path: Path, key: str | None = "sk-ant-test-key-123456") -> AppContext:
    settings = Settings(spending_limit_usd=0)
    return AppContext(settings=settings, settings_path=tmp_path / "settings.json", cache_base=tmp_path / "cache",
                      keys=MemoryKeyStore(key), client_factory=fake_client_factory)


def make_inputs(tmp_path: Path) -> tuple[Path, Path]:
    apps = tmp_path / "applications"
    for name, marker in (("Alice Shah", "PROFILE-TOP"), ("Bob Jones", "PROFILE-CLOSE"), ("Carol White", "PROFILE-OUT")):
        (apps / name).mkdir(parents=True)
        make_text_pdf(apps / name / "CV.pdf", f"{name} {marker} " * 20)
        make_docx(apps / name / "Cover letter.docx", text="Dear hiring manager " * 10, header="")
    (apps / "Dan Broken").mkdir()
    (apps / "Dan Broken" / "cv.pdf").write_bytes(b"not a pdf")
    roles = tmp_path / "open roles"
    roles.mkdir()
    (roles / "data_engineer.txt").write_text("Data Engineer\nBuild pipelines", encoding="utf-8")
    return apps, roles

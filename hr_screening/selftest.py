"""Offline self-test, runnable from the packaged exe:  HRScreening.exe --self-test [report.txt]

Checks that everything bundled into the exe works on this machine - without internet or an API
key: document reading, a full screening run with a stand-in AI, Word/Excel output, the Windows
credential store backend, the TLS setup and the user interface.
"""

from __future__ import annotations

import os
import sys
import tempfile
import traceback
from pathlib import Path

from . import __version__


def _stand_in_client():
    """A ClaudeClient whose answers are canned, so the pipeline runs offline."""
    from .careers import _RoleSummary
    from .evaluation import CandidateEvaluation, FilterJudgement, Judgement
    from .llm import ClaudeClient, Usage

    class StandIn(ClaudeClient):
        def __init__(self):
            super().__init__("sk-self-test", model="claude-opus-5-5")

        def structured(self, *, system, content, output_model, **_):
            self.usage.add(Usage(calls=1))
            if output_model is _RoleSummary:
                return _RoleSummary(is_job_posting=True, title="Data Engineer", summary="Builds data pipelines.")
            text = " ".join(b.get("text", "") for b in content)
            strong = "STRONG" in text
            results = [Judgement.MET] * 3 if strong else [Judgement.NOT_MET, Judgement.MET, Judgement.PARTIAL]
            return CandidateEvaluation(
                is_application=True, candidate_name="",
                judgements=[FilterJudgement(filter_id=f"F0{i}", result=r, evidence="Self-test evidence")
                            for i, r in enumerate(results, 1)],
                verdict="Self-test verdict.", strengths=["Self-test strength"], gaps=[] if strong else ["Gap"],
                one_line_summary="Self-test.", overall_fit=8 if strong else 3, alternative_role_id="R01",
                alternative_fit="none" if strong else "strong", alternative_is_better=False,
                alternative_reasons=["Pipelines"], alternative_summary="Suits engineering.", integrity_notes=[])

    return StandIn()


def _check_pipeline(work: Path) -> str:
    from docx import Document
    from PIL import Image, ImageDraw

    from .filters import FilterSet, FilterType, ScreeningFilter
    from .pipeline import RunRequest, ScreeningPipeline

    apps = work / "applications"
    (apps / "Strong Candidate").mkdir(parents=True)
    d = Document()
    d.add_paragraph("STRONG candidate with 8 years of SQL and a maths degree. " * 3)
    d.save(str(apps / "Strong Candidate" / "CV.docx"))
    (apps / "Other Candidate").mkdir()
    (apps / "Other Candidate" / "cv.txt").write_text("Data engineer, Airflow and Python. " * 5, encoding="utf-8")
    img = Image.new("RGB", (800, 1100), "white")
    ImageDraw.Draw(img).text((50, 50), "Scanned CV", fill="black")
    img.save(apps / "Other Candidate" / "scan.png")
    roles = work / "roles"
    roles.mkdir()
    (roles / "engineer.txt").write_text("Data Engineer\nPipelines", encoding="utf-8")

    fs = FilterSet(job_title="Self Test Analyst", filters=[
        ScreeningFilter(id="F01", criterion="SQL", type=FilterType.MUST_HAVE, weight=5),
        ScreeningFilter(id="F02", criterion="Degree", weight=3),
        ScreeningFilter(id="F03", criterion="Python", weight=2),
    ])
    pipeline = ScreeningPipeline(_stand_in_client())
    prep = pipeline.prepare(RunRequest(applications_dir=apps, output_dir=work / "out", filter_set=fs,
                                       careers_folder=str(roles)))
    outcome = pipeline.run(prep)
    expected = [outcome.summary_path,
                outcome.run_dir / "Top Match" / "01_Strong_Candidate_Report.docx",
                outcome.run_dir / "Other Role" / "Other_Candidate_Other_Role_Report.docx"]
    missing = [str(p) for p in expected if not p.exists()]
    if missing:
        raise AssertionError(f"missing outputs: {missing}")
    return f"{len(outcome.placements)} applications screened offline; reports and Summary.xlsx written"


def _check_pdf() -> str:
    import pypdf  # noqa: F401
    return "PDF reader available"


def _check_keyring() -> str:
    import keyring
    backend = type(keyring.get_keyring()).__name__
    if sys.platform == "win32" and "Win" not in backend:
        raise AssertionError(f"unexpected credential backend: {backend}")
    return f"credential store backend: {backend}"


def _check_tls() -> str:
    from .web import make_http_client
    with make_http_client():
        pass
    import anthropic
    anthropic.Anthropic(api_key="sk-self-test")
    return f"HTTPS client ready; anthropic SDK {anthropic.__version__}"


def _check_ui(work: Path) -> str:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from .settings import Settings
    from .ui.context import AppContext, MemoryKeyStore
    from .ui.main_window import MainWindow
    from .ui.widgets import apply_theme

    app = QApplication.instance() or QApplication([])
    apply_theme(app)
    window = MainWindow(AppContext(settings=Settings(), settings_path=work / "s.json", cache_base=work / "c",
                                   keys=MemoryKeyStore()))
    window.show()
    app.processEvents()
    window.close()
    return "main window opens"


def run_self_test(report_path: Path | None = None) -> int:
    lines = [f"HR Candidate Screening {__version__} self-test", f"Python {sys.version.split()[0]}, "
             f"{'packaged exe' if getattr(sys, 'frozen', False) else 'development'}", ""]
    ok = True
    with tempfile.TemporaryDirectory(prefix="hr_selftest_") as tmp:
        work = Path(tmp)
        os.environ["APPDATA"] = str(work / "appdata")   # never touch the real settings or cache
        checks = [("Documents", _check_pdf), ("Screening pipeline", lambda: _check_pipeline(work)),
                  ("Credential store", _check_keyring), ("Network setup", _check_tls),
                  ("User interface", lambda: _check_ui(work))]
        for name, check in checks:
            try:
                lines.append(f"[PASS] {name}: {check()}")
            except Exception:
                ok = False
                lines.append(f"[FAIL] {name}:\n{traceback.format_exc()}")
    lines.append("")
    lines.append("RESULT: OK" if ok else "RESULT: FAILED")
    text = "\n".join(lines)
    if report_path:
        Path(report_path).write_text(text, encoding="utf-8")
    try:
        print(text)
    except Exception:   # no console in the windowed exe
        pass
    return 0 if ok else 1

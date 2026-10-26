"""One-page .docx reports.

* Tier report (Top Match / Close Match / Backup): why the candidate fits the screened role.
* Other Role report: which other open role suits the candidate and why; its first line states
  the candidate's standing for the screened role.

Every report must fit on one A4 page. Text lengths are capped, and the filter checklist is
progressively compacted (shorter evidence, then no evidence column, ...) until a conservative
layout estimate fits the page. tests/test_reports.py checks the worst cases in Microsoft Word.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

from .evaluation import Judgement
from .filters import FilterSet, FilterType
from .models import Tier
from .scoring import CandidateResult
from .system import long_path

FONT = "Calibri"
GREY = RGBColor(0x59, 0x59, 0x59)
TIER_COLOURS = {
    Tier.TOP: RGBColor(0x1E, 0x7B, 0x34),
    Tier.CLOSE: RGBColor(0x1F, 0x5F, 0xA8),
    Tier.BACKUP: RGBColor(0xA6, 0x61, 0x00),
}
RESULT_COLOURS = {
    Judgement.MET: RGBColor(0x1E, 0x7B, 0x34),
    Judgement.PARTIAL: RGBColor(0xA6, 0x61, 0x00),
    Judgement.NOT_MET: RGBColor(0xB0, 0x1E, 0x1E),
    Judgement.NO_EVIDENCE: RGBColor(0x80, 0x80, 0x80),
}
TIER_HEADINGS = {
    Tier.TOP: "Why this is a top match",
    Tier.CLOSE: "Why this is a close match",
    Tier.BACKUP: "Why this is a backup option",
}

PAGE_W, PAGE_H = 21.0, 29.7
MARGIN_X, MARGIN_TOP, MARGIN_BOTTOM = 1.8, 1.5, 1.5
FOOTER_CM = 1.0
CONTENT_W = PAGE_W - 2 * MARGIN_X
CONTENT_H = PAGE_H - MARGIN_TOP - MARGIN_BOTTOM - FOOTER_CM

# Checklist column widths (cm): requirement (with its evidence underneath), type, result.
CHECKLIST_COLS = (CONTENT_W - 3.9, 1.8, 2.1)

MAX_VERDICT_WORDS = 60
MAX_BULLET_WORDS = 28
MAX_CRITERION_WORDS = 22
MAX_ROLE_SUMMARY_WORDS = 90


@dataclass(frozen=True)
class _Layout:
    body_pt: float
    table_pt: float
    evidence_words: int        # 0 = no evidence column
    evidence_for_met: bool
    max_strengths: int
    max_gaps: int
    criterion_words: int = MAX_CRITERION_WORDS
    verdict_words: int = MAX_VERDICT_WORDS
    bullet_words: int = MAX_BULLET_WORDS
    max_integrity: int = 3


# From most to least detailed; the first one whose estimate fits the page is used. The last
# ones only occur with unusually many, very long filters.
LAYOUTS = (
    _Layout(10, 8.5, 20, True, 4, 3),
    _Layout(10, 8.5, 12, True, 4, 3),
    _Layout(10, 8.5, 10, False, 4, 3),
    _Layout(10, 8, 0, False, 4, 3),
    _Layout(9.5, 8, 0, False, 3, 2),
    _Layout(9, 7.5, 0, False, 3, 2, criterion_words=14, verdict_words=45, bullet_words=22, max_integrity=2),
    _Layout(9, 7, 0, False, 2, 2, criterion_words=10, verdict_words=35, bullet_words=18, max_integrity=1),
    _Layout(8.5, 6.5, 0, False, 2, 1, criterion_words=8, verdict_words=30, bullet_words=16, max_integrity=1),
)


def generated_note() -> str:
    return (f"Generated {date.today():%d %b %Y} by HR Candidate Screening with AI assistance. "
            "Evidence is taken from the application; final decisions rest with HR.")


# --- public API --------------------------------------------------------------------

def write_tier_report(result: CandidateResult, filter_set: FilterSet, name: str, path: Path) -> Path:
    if not result.tier.is_shortlisted or result.evaluation is None:
        raise ValueError("Tier reports are only written for Top Match, Close Match and Backup candidates.")
    e = result.evaluation
    first_line = ""
    if result.other_role:
        first_line = (f"Also a strong fit for {result.other_role.title} — a copy of this application "
                      f"is in the Other Role folder.")
    elif result.alternative_role:
        first_line = f"Also a strong fit for {result.alternative_role.title}."

    layout = _choose_layout(result, filter_set, first_line)
    doc = _new_document(layout.body_pt)
    if first_line:
        _para(doc, first_line, italic=True, size=layout.body_pt, colour=TIER_COLOURS[result.tier], after=4)
    _para(doc, f"{name} — {filter_set.job_title}", bold=True, size=layout.body_pt + 5, after=1)
    must = filter_set.must_haves
    must_met = sum(1 for s in result.scored if s.filter.type is FilterType.MUST_HAVE and s.result is Judgement.MET)
    _status_line(doc, result.tier.value, TIER_COLOURS[result.tier], [
        f"Score {result.score}/100",
        f"Rank {result.rank} in {result.tier.value}",
        f"Must-haves fully met {must_met}/{len(must)}" if must else "No must-haves",
    ], layout.body_pt)

    _para(doc, _words(e.verdict, layout.verdict_words), size=layout.body_pt, after=4)
    _heading(doc, TIER_HEADINGS[result.tier], layout.body_pt)
    _bullets(doc, e.strengths[:layout.max_strengths] or ["See checklist below."], layout.body_pt, layout.bullet_words)
    if e.gaps:
        _heading(doc, "Gaps and risks", layout.body_pt)
        _bullets(doc, e.gaps[:layout.max_gaps], layout.body_pt, layout.bullet_words)
    if e.integrity_notes:
        _heading(doc, "Integrity notes", layout.body_pt, colour=RESULT_COLOURS[Judgement.NOT_MET])
        _bullets(doc, e.integrity_notes[:layout.max_integrity], layout.body_pt, layout.bullet_words)
    _heading(doc, "Filter checklist", layout.body_pt)
    _checklist(doc, result, layout)
    return _save(doc, path)


def write_other_role_report(result: CandidateResult, filter_set: FilterSet, name: str, path: Path) -> Path:
    role = result.other_role
    if role is None or result.evaluation is None:
        raise ValueError("Other Role reports need a candidate with an alternative role.")
    e = result.evaluation
    body = 10
    doc = _new_document(body)
    _para(doc, initial_role_line(result, filter_set), bold=True, size=body, after=6,
          colour=TIER_COLOURS.get(result.tier, RESULT_COLOURS[Judgement.NOT_MET]))
    _para(doc, f"{name} — better suited to {role.title}", bold=True, size=body + 5, after=1)
    _status_line(doc, "Other Role", TIER_COLOURS[Tier.CLOSE], [f"Suggested role: {role.title}"], body)

    summary = e.alternative_summary.strip() or f"The candidate's background aligns well with the {role.title} role."
    _para(doc, _words(summary, MAX_VERDICT_WORDS), size=body, after=4)
    _heading(doc, f"Why they suit {role.title}", body)
    _bullets(doc, e.alternative_reasons or ["See the role summary below."], body)

    _heading(doc, f"For the {filter_set.job_title} role", body)
    # The first line already names any failed must-have; prefer the assessed gaps here.
    points = list(e.gaps[:2])
    if not points and result.failed_must_haves:
        points.append("Does not meet must-have: " + "; ".join(_words(f.criterion, 12) for f in result.failed_must_haves[:3]))
    if not points:
        points.append(_words(e.verdict, MAX_BULLET_WORDS))
    _bullets(doc, points, body)

    _heading(doc, f"About the {role.title} role", body)
    _para(doc, _words(role.summary, MAX_ROLE_SUMMARY_WORDS), size=body - 0.5, italic=True, after=2)
    if role.source.startswith("http"):
        _para(doc, f"Posting: {role.source}", size=body - 1.5, colour=GREY, after=0)
    return _save(doc, path)


def initial_role_line(result: CandidateResult, filter_set: FilterSet) -> str:
    """First line of an Other Role report: the candidate's standing for the screened role."""
    job = filter_set.job_title
    if result.tier.is_shortlisted:
        return (f"Also suitable for {job}: {result.tier.value} ({result.score}/100) — "
                f"see the {result.tier.value} folder.")
    if result.failed_must_haves:
        unmet = "; ".join(_words(f.criterion, 12) for f in result.failed_must_haves[:2])
        more = f" (+{len(result.failed_must_haves) - 2} more)" if len(result.failed_must_haves) > 2 else ""
        return f"Not suitable for {job}: does not meet must-have — {unmet}{more}."
    return f"Not suitable for {job}: scored {result.score}/100, below the shortlist threshold."


# --- layout selection --------------------------------------------------------------

def _choose_layout(result: CandidateResult, filter_set: FilterSet, first_line: str) -> _Layout:
    for layout in LAYOUTS:
        if _estimate_height_cm(result, filter_set, first_line, layout) <= CONTENT_H:
            return layout
    return LAYOUTS[-1]


def _lines(text: str, width_cm: float, pt: float) -> int:
    """Conservative number of wrapped lines for `text` in a column `width_cm` wide."""
    # Calibri averages ~0.47 em per character; 0.0175 cm/pt is ~5% wider to stay conservative.
    chars_per_line = max(8, int(width_cm / (pt * 0.0175)))
    return max(1, sum(math.ceil(max(1, len(part)) / chars_per_line) for part in text.split("\n")))


def _estimate_height_cm(result: CandidateResult, filter_set: FilterSet, first_line: str, layout: _Layout) -> float:
    e = result.evaluation
    # Calibri's line height is ~1.22 em; x1.05 line spacing, plus a little margin.
    line = layout.body_pt * 1.32 * 0.0353      # cm per body line
    tline = layout.table_pt * 1.32 * 0.0353
    gap = 0.15
    h = 0.0
    if first_line:
        h += _lines(first_line, CONTENT_W, layout.body_pt) * line + gap
    h += 2 * line + gap                        # title (larger font)
    h += line + gap                            # status line
    h += _lines(_words(e.verdict, layout.verdict_words), CONTENT_W, layout.body_pt) * line + gap
    sections = [e.strengths[:layout.max_strengths] or ["x"], e.gaps[:layout.max_gaps],
                e.integrity_notes[:layout.max_integrity]]
    for items in sections:
        if items:
            h += line + gap                    # heading
            h += sum(_lines(_words(s, layout.bullet_words), CONTENT_W - 0.7, layout.body_pt) for s in items) * line
            h += len(items) * 0.05
    h += line + gap                            # checklist heading
    width = CHECKLIST_COLS[0] - 0.25
    h += tline + 0.15                          # header row
    for s in result.scored:
        n = _lines(_words(s.filter.criterion, layout.criterion_words), width, layout.table_pt)
        evidence = _evidence_text(s, layout)
        if evidence:
            n += _lines(evidence, width, layout.table_pt - 0.5)
        h += n * tline + 0.12                  # cell padding
    return h


def _evidence_text(scored, layout: _Layout) -> str:
    if not layout.evidence_words:
        return ""
    if scored.result is Judgement.MET and not layout.evidence_for_met:
        return ""
    return _words(scored.evidence, layout.evidence_words)


# --- document building -------------------------------------------------------------

def _new_document(body_pt: float) -> Document:
    doc = Document()
    section = doc.sections[0]
    section.page_width, section.page_height = Cm(PAGE_W), Cm(PAGE_H)
    section.left_margin = section.right_margin = Cm(MARGIN_X)
    section.top_margin, section.bottom_margin = Cm(MARGIN_TOP), Cm(MARGIN_BOTTOM)
    section.footer_distance = Cm(0.7)

    normal = doc.styles["Normal"]
    normal.font.name = FONT
    normal.font.size = Pt(body_pt)
    normal.element.rPr.rFonts.set(qn("w:eastAsia"), FONT)
    normal.paragraph_format.space_after = Pt(0)
    normal.paragraph_format.space_before = Pt(0)
    normal.paragraph_format.line_spacing = 1.05
    bullet = doc.styles["List Bullet"]
    bullet.font.size = Pt(body_pt)
    bullet.paragraph_format.space_after = Pt(1)

    footer = section.footer.paragraphs[0]
    footer.text = generated_note()
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    for run in footer.runs:
        run.font.size = Pt(7)
        run.font.color.rgb = GREY
    return doc


def _para(doc, text: str, *, bold=False, italic=False, size: float = 10, colour: RGBColor | None = None, after: float = 2):
    p = doc.add_paragraph()
    run = p.add_run(text)
    run.bold, run.italic = bold, italic
    run.font.size = Pt(size)
    if colour is not None:
        run.font.color.rgb = colour
    p.paragraph_format.space_after = Pt(after)
    return p


def _heading(doc, text: str, body_pt: float, colour: RGBColor | None = None):
    p = _para(doc, text, bold=True, size=body_pt + 1, colour=colour or RGBColor(0x26, 0x26, 0x26), after=1)
    p.paragraph_format.space_before = Pt(5)
    p.paragraph_format.keep_with_next = True
    return p


def _status_line(doc, label: str, colour: RGBColor, parts: list[str], body_pt: float):
    p = doc.add_paragraph()
    run = p.add_run(label)
    run.bold = True
    run.font.size = Pt(body_pt + 0.5)
    run.font.color.rgb = colour
    rest = p.add_run("   ·   " + "   ·   ".join(parts))
    rest.font.size = Pt(body_pt)
    rest.font.color.rgb = GREY
    p.paragraph_format.space_after = Pt(6)
    _bottom_border(p)


def _bullets(doc, items: list[str], body_pt: float, max_words: int = MAX_BULLET_WORDS):
    for item in items:
        p = doc.add_paragraph(_words(item, max_words), style="List Bullet")
        p.runs[0].font.size = Pt(body_pt)


def _checklist(doc, result: CandidateResult, layout: _Layout):
    header = "Requirement — evidence from the application" if layout.evidence_words else "Requirement"
    table = doc.add_table(rows=1, cols=3)
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    _cell_margins(table, top=20, bottom=20, left=60, right=60)

    for cell, text in zip(table.rows[0].cells, (header, "Type", "Result")):
        _cell_text(cell, text, layout.table_pt, bold=True)
        _shade(cell, "E7ECF2")
    for s in result.scored:
        cells = table.add_row().cells
        _cell_text(cells[0], _words(s.filter.criterion, layout.criterion_words), layout.table_pt)
        evidence = _evidence_text(s, layout)
        if evidence:
            _cell_text(cells[0], evidence, layout.table_pt - 0.5, colour=GREY, italic=True, new_paragraph=True)
        _cell_text(cells[1], s.filter.type.label, layout.table_pt - 0.5, colour=GREY)
        _cell_text(cells[2], s.result.label, layout.table_pt, bold=True, colour=RESULT_COLOURS[s.result])
    for row in table.rows:
        for cell, width in zip(row.cells, CHECKLIST_COLS):
            cell.width = Cm(width)
        _no_split(row)


def _cell_text(cell, text: str, pt: float, *, bold=False, italic=False, colour: RGBColor | None = None,
               new_paragraph=False):
    p = cell.add_paragraph() if new_paragraph else cell.paragraphs[0]
    run = p.add_run(text)
    run.bold, run.italic = bold, italic
    run.font.size = Pt(pt)
    if colour is not None:
        run.font.color.rgb = colour


def _shade(cell, hex_fill: str):
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hex_fill)
    cell._tc.get_or_add_tcPr().append(shd)


def _cell_margins(table, **margins_twips):
    tbl_pr = table._tbl.tblPr
    mar = OxmlElement("w:tblCellMar")
    for side, value in margins_twips.items():
        el = OxmlElement(f"w:{side}")
        el.set(qn("w:w"), str(value))
        el.set(qn("w:type"), "dxa")
        mar.append(el)
    tbl_pr.append(mar)


def _no_split(row):
    tr_pr = row._tr.get_or_add_trPr()
    el = OxmlElement("w:cantSplit")
    tr_pr.append(el)


def _bottom_border(paragraph):
    p_pr = paragraph._p.get_or_add_pPr()
    borders = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    for key, value in (("val", "single"), ("sz", "4"), ("space", "4"), ("color", "BFBFBF")):
        bottom.set(qn(f"w:{key}"), value)
    borders.append(bottom)
    p_pr.append(borders)


def _save(doc, path: Path) -> Path:
    path = Path(path)
    Path(long_path(path.parent)).mkdir(parents=True, exist_ok=True)
    doc.save(long_path(path))
    return path


def _words(text: str, limit: int) -> str:
    words = " ".join(str(text).split()).split(" ")
    if len(words) <= limit:
        return " ".join(words)
    return " ".join(words[:limit]).rstrip(",;:.") + "…"

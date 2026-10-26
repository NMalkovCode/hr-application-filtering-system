from __future__ import annotations

import pytest

from hr_screening.evaluation import FilterJudgement
from hr_screening.models import Tier
from hr_screening.scoring import assign_tiers, needs_review, score_evaluation
from hr_screening.settings import TierThresholds

from .helpers import OPEN_ROLES, M, N, P, X, candidate, evaluation, filter_set


def _score(results, **kw):
    return score_evaluation(candidate(), evaluation(results, **kw), filter_set(), OPEN_ROLES)


def test_weighted_score_with_partial_credit():
    # weights 5, 3, 2, 2 = 12. Met, Partial, Met, No evidence -> 5 + 1.5 + 2 + 0 = 8.5 / 12
    r = _score([M, P, M, X])
    assert r.score == round(100 * 8.5 / 12)
    assert r.must_have_score == round(100 * 6.5 / 8)
    assert not r.eliminated


@pytest.mark.parametrize("must_have_result", [N, X])
def test_failed_must_have_eliminates_regardless_of_score(must_have_result):
    r = _score([M, must_have_result, M, M])
    assert r.eliminated and [f.id for f in r.failed_must_haves] == ["F02"]
    (r,) = assign_tiers([r], TierThresholds(top=10, close=5, backup=1))
    assert r.tier is Tier.NOT_SUITABLE


def test_missing_judgement_counts_as_no_evidence():
    e = evaluation([M, M, M, M])
    e.judgements = [j for j in e.judgements if j.filter_id != "F03"]
    e.judgements.append(FilterJudgement(filter_id="F99", result=M, evidence="unknown id ignored"))
    r = score_evaluation(candidate(), e, filter_set())
    assert [s.result for s in r.scored] == [M, M, X, M]
    assert r.score == round(100 * 10 / 12)


def test_filter_ids_are_matched_case_insensitively():
    e = evaluation([M, M, M, M])
    for j in e.judgements:
        j.filter_id = j.filter_id.lower()
    assert score_evaluation(candidate(), e, filter_set()).score == 100


def test_not_an_application_needs_review():
    r = _score([], is_application=False)
    assert r.error and assign_tiers([r], TierThresholds())[0].tier is Tier.NEEDS_REVIEW


@pytest.mark.parametrize("score, tier", [
    (100, Tier.TOP), (80, Tier.TOP), (79, Tier.CLOSE), (65, Tier.CLOSE),
    (64, Tier.BACKUP), (50, Tier.BACKUP), (49, Tier.NOT_SUITABLE),
])
def test_tier_boundaries(score, tier):
    r = _score([M, M, M, M])
    r.score = score
    assert assign_tiers([r], TierThresholds(80, 65, 50))[0].tier is tier


def test_ranking_order_and_tie_breakers():
    a = score_evaluation(candidate("Amy", "C001"), evaluation([M, M, P, P]), filter_set())   # 83
    b = score_evaluation(candidate("Ben", "C002"), evaluation([M, M, M, M]), filter_set())   # 100
    c = score_evaluation(candidate("Cat", "C003"), evaluation([M, P, M, X]), filter_set())   # 71
    d = score_evaluation(candidate("Dan", "C004"), evaluation([P, M, M, M]), filter_set())   # 79, lower must-have
    e = score_evaluation(candidate("Eve", "C005"), evaluation([M, P, M, P]), filter_set())   # 79, higher must-have
    f = score_evaluation(candidate("Fay", "C006"), evaluation([N, M, M, M]), filter_set())   # eliminated
    g = needs_review(candidate("Gus", "C007"), "unreadable")

    ordered = assign_tiers([a, b, c, d, e, f, g], TierThresholds(80, 65, 50))
    assert [(r.name, r.tier, r.rank) for r in ordered] == [
        ("Ben", Tier.TOP, 1), ("Amy", Tier.TOP, 2),
        ("Eve", Tier.CLOSE, 1), ("Dan", Tier.CLOSE, 2), ("Cat", Tier.CLOSE, 3),
        ("Fay", Tier.NOT_SUITABLE, 1),
        ("Gus", Tier.NEEDS_REVIEW, 1),
    ]
    assert d.score == e.score and e.must_have_score > d.must_have_score


class TestOtherRole:
    def _tiered(self, results, **kw):
        return assign_tiers([_score(results, **kw)], TierThresholds())[0]

    def test_eliminated_candidate_with_strong_fit_goes_to_other_role(self):
        r = self._tiered([N, M, M, M], alt_id="R01", alt_fit="strong")
        assert r.tier is Tier.NOT_SUITABLE and r.other_role.title == "Data Engineer"

    def test_shortlisted_candidate_duplicated_only_if_clearly_better(self):
        assert self._tiered([M, M, M, M], alt_id="r02", alt_fit="strong", alt_better=True).other_role.role_id == "R02"
        not_better = self._tiered([M, M, M, M], alt_id="R02", alt_fit="strong", alt_better=False)
        assert not_better.other_role is None
        assert not_better.alternative_role.role_id == "R02"  # still tracked in the spreadsheet

    @pytest.mark.parametrize("alt_id, fit", [("R01", "moderate"), ("R99", "strong"), ("none", "none")])
    def test_no_other_role(self, alt_id, fit):
        r = self._tiered([N, M, M, M], alt_id=alt_id, alt_fit=fit)
        assert r.other_role is None and r.alternative_role is None


def test_write_up_lists_are_capped():
    r = _score([M, M, M, M], strengths=[f"s{i}" for i in range(9)] + ["  "], gaps=["g"] * 5)
    assert len(r.evaluation.strengths) == 4 and len(r.evaluation.gaps) == 3


def test_overall_fit_breaks_ties_before_name():
    zed = score_evaluation(candidate("Zed", "C001"), evaluation([M] * 4, overall_fit=9), filter_set())
    amy = score_evaluation(candidate("Amy", "C002"), evaluation([M] * 4, overall_fit=6), filter_set())
    bob = score_evaluation(candidate("Bob", "C003"), evaluation([M] * 4, overall_fit=6), filter_set())
    ordered = assign_tiers([amy, bob, zed], TierThresholds())
    assert [r.name for r in ordered] == ["Zed", "Amy", "Bob"]          # names only for full ties
    assert [r.rank for r in ordered] == [1, 2, 3]


def test_overall_fit_never_beats_a_higher_score():
    high_fit = score_evaluation(candidate("Hi", "C001"), evaluation([M, M, M, P], overall_fit=10), filter_set())
    low_fit = score_evaluation(candidate("Lo", "C002"), evaluation([M] * 4, overall_fit=1), filter_set())
    assert [r.name for r in assign_tiers([high_fit, low_fit], TierThresholds())] == ["Lo", "Hi"]


class TestPartlyUnreadable:
    def _with_issue(self, results, **kw):
        from pathlib import Path
        from hr_screening.models import ExtractionIssue
        c = candidate()
        c.issues.append(ExtractionIssue(Path("CV.docx"), "Word document is password-protected"))
        r = score_evaluation(c, evaluation(results, **kw), filter_set(), OPEN_ROLES)
        return assign_tiers([r], TierThresholds())[0]

    def test_would_be_rejected_goes_to_needs_review_with_provisional_assessment(self):
        r = self._with_issue([N, M, M, M], alt_id="R01", alt_fit="strong")
        assert r.tier is Tier.NEEDS_REVIEW and not r.error
        assert r.score == round(100 * 7 / 12)                         # provisional score kept
        assert "CV.docx could not be read" in r.one_line_reason
        assert "Provisional assessment: Strong SQL analyst." in r.one_line_reason
        assert r.other_role is None and r.alternative_role.title == "Data Engineer"

    def test_score_below_backup_also_goes_to_needs_review(self):
        # Partial must-haves (no elimination): (2.5 + 1.5) / 12 = 33, below Backup's 50.
        r = self._with_issue([P, P, X, X])
        assert not r.eliminated and r.score == 33 and r.tier is Tier.NEEDS_REVIEW

    def test_shortlisted_candidate_is_unaffected(self):
        r = self._with_issue([M] * 4)
        assert r.tier is Tier.TOP and r.review_reason == ""

    def test_without_issues_rejection_is_unchanged(self):
        r = assign_tiers([score_evaluation(candidate(), evaluation([N, M, M, M]), filter_set())], TierThresholds())[0]
        assert r.tier is Tier.NOT_SUITABLE


def test_one_line_reason_fallbacks():
    r = _score([N, M, M, M], one_line_summary="  ")
    assert r.one_line_reason == "Does not meet: At least 5 years of SQL"
    assert needs_review(candidate(), "File damaged").one_line_reason == "File damaged"

from __future__ import annotations

from pathlib import Path

import pytest

from hr_screening.costs import CostEstimate, estimate_run_cost
from hr_screening.models import Candidate

from .helpers import candidate


def test_estimate_scales_with_applications_and_model():
    cands = [candidate(cid=f"C{i}", text="x" * 16_000) for i in range(100)]   # ~4k tokens each
    opus = estimate_run_cost(cands, "p" * 20_000, "claude-opus-5-5")
    haiku = estimate_run_cost(cands, "p" * 20_000, "claude-haiku-5-5")
    assert 0 < opus.low_usd < opus.high_usd
    assert opus.candidates == 100
    # Opus: ~100 * (4k * $4 + 1.5k * $20) / 1M ≈ $4.6 low; high has long output and no cache.
    assert 3 < opus.low_usd < 7 and 12 < opus.high_usd < 20
    assert haiku.high_usd < opus.high_usd / 20


def test_unreadable_applications_are_not_counted():
    empty = Candidate("C9", "Empty", Path("x"))
    assert estimate_run_cost([empty, candidate()], "p", "claude-opus-5-5").candidates == 1


@pytest.mark.parametrize("limit, spent, exceeds", [(10, 0, False), (5, 0, False), (4.99, 0, True), (6, 1.5, True), (0, 0, False)])
def test_exceeds_limit(limit, spent, exceeds):
    assert CostEstimate(2.0, 5.0, 10, spent).exceeds(limit) is exceeds


def test_describe():
    assert CostEstimate(1.234, 4.5, 20, 0.3).describe() == (
        "Estimated cost for 20 applications: $1.23 – $4.50 (plus $0.30 already spent preparing the run).")

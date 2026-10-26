from __future__ import annotations

import threading
from datetime import date
from pathlib import Path

import pytest
from anthropic.lib._parse._transform import transform_schema

from hr_screening.evaluation import CandidateEvaluation
from hr_screening.evaluator import Evaluator, build_system_prompt, evaluate_all
from hr_screening.filters import FilterSet
from hr_screening.llm import ClaudeClient, InvalidAPIKey, RateLimited, Refused, ServiceUnavailable, Truncated
from hr_screening.models import Candidate, Tier
from hr_screening.scoring import assign_tiers
from hr_screening.settings import TierThresholds

from .helpers import OPEN_ROLES, M, N, P, candidate, evaluation, filter_set
from .fakes import fake_message, install_fake


def test_output_schema_is_accepted_by_sdk():
    transform_schema(CandidateEvaluation.model_json_schema())


def test_system_prompt_contains_job_context_and_escapes():
    fs = filter_set()
    fs.filters[2].criterion = "Python <pandas> & SQL"
    prompt = build_system_prompt(fs, OPEN_ROLES, today=date(2026, 10, 26))
    assert "Today's date: 2026-10-26" in prompt
    assert '<filter id="F01" type="Must-have" weight="5"' in prompt
    assert "Python &lt;pandas&gt; &amp; SQL" in prompt
    assert '<role id="R02" title="Operations Manager">' in prompt
    assert "None - set alternative_fit" in build_system_prompt(fs, [])


def test_prompt_is_identical_across_candidates_for_caching():
    fs = filter_set()
    assert build_system_prompt(fs, OPEN_ROLES) == build_system_prompt(fs.model_copy(deep=True), list(OPEN_ROLES))


def test_invalid_filters_are_rejected():
    with pytest.raises(ValueError, match="at least one filter"):
        Evaluator(ClaudeClient("sk-test"), FilterSet(job_title="x", filters=[]))


def test_evaluate_sends_application_and_scores():
    client = ClaudeClient("sk-test")
    calls = install_fake(client, [fake_message(evaluation([M, M, P, M]))])
    result = Evaluator(client, filter_set(), OPEN_ROLES).evaluate(candidate(text="10 years SQL"))

    kwargs = calls[0]
    assert kwargs["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert kwargs["output_config"] == {"effort": "medium"}
    assert kwargs["messages"][0]["content"][0]["text"] == '<application_file file="Jane Doe.pdf">\n10 years SQL\n</application_file>'
    assert result.score == round(100 * 11 / 12) and not result.error


def test_unreadable_candidate_needs_review_without_api_call(tmp_path: Path):
    (tmp_path / "Eve").mkdir()
    (tmp_path / "Eve" / "cv.pdf").write_bytes(b"garbage")
    client = ClaudeClient("sk-test")
    calls = install_fake(client, [])
    result = Evaluator(client, filter_set()).evaluate(
        Candidate(candidate_id="C001", display_name="Eve", source_path=tmp_path / "Eve"))
    assert calls == [] and "No readable content" in result.error and "cv.pdf" in result.error


def test_partially_unreadable_application_is_noted():
    c = candidate()
    from hr_screening.models import ExtractionIssue
    c.issues.append(ExtractionIssue(Path("letter.docx"), "damaged"))
    client = ClaudeClient("sk-test")
    install_fake(client, [fake_message(evaluation([M, M, M, M]))])
    result = Evaluator(client, filter_set()).evaluate(c)
    assert result.evaluation.integrity_notes == ["Not assessed (unreadable): letter.docx."]


def test_ai_error_becomes_needs_review_after_retries_run_out():
    client = ClaudeClient("sk-test")
    calls = install_fake(client, [RateLimited("slow down")] * 3)
    result = Evaluator(client, filter_set(), retry_delays=(0, 0)).evaluate(candidate())
    assert result.error == "slow down" and len(calls) == 3
    assert assign_tiers([result], TierThresholds())[0].tier is Tier.NEEDS_REVIEW


def test_transient_errors_are_retried():
    client = ClaudeClient("sk-test")
    calls = install_fake(client, [RateLimited("busy"), ServiceUnavailable("down"), fake_message(evaluation([M] * 4))])
    result = Evaluator(client, filter_set(), retry_delays=(0, 0, 0)).evaluate(candidate())
    assert not result.error and result.score == 100 and len(calls) == 3


def test_truncated_answer_is_retried_with_more_room():
    client = ClaudeClient("sk-test")
    calls = install_fake(client, [Truncated("cut off"), fake_message(evaluation([M] * 4))])
    Evaluator(client, filter_set(), retry_delays=(0,)).evaluate(candidate())
    assert [c["max_tokens"] for c in calls] == [16_000, 48_000]


def test_refusal_is_not_retried():
    client = ClaudeClient("sk-test")
    calls = install_fake(client, [Refused("declined")])
    result = Evaluator(client, filter_set(), retry_delays=(0, 0)).evaluate(candidate())
    assert result.error == "declined" and len(calls) == 1


def test_cancel_interrupts_retry_wait():
    import time
    client = ClaudeClient("sk-test")
    install_fake(client, [RateLimited("busy")])
    cancel = threading.Event()
    threading.Timer(0.2, cancel.set).start()
    started = time.monotonic()
    result = Evaluator(client, filter_set(), retry_delays=(60,)).evaluate(candidate(), cancel)
    assert time.monotonic() - started < 5
    assert result.error == "Not processed - run was cancelled."


def test_oversized_requests_go_to_needs_review():
    from hr_screening.models import ContentKind, SourceDocument
    client = ClaudeClient("sk-test")
    calls = install_fake(client, [])
    ev = Evaluator(client, filter_set())

    many_images = candidate()
    many_images.documents = [SourceDocument(Path(f"p{i}.jpg"), ContentKind.IMAGE, data=b"x", media_type="image/jpeg")
                             for i in range(101)]
    assert "too many images" in ev.evaluate(many_images).error

    huge = candidate()
    huge.documents = [SourceDocument(Path("scan.pdf"), ContentKind.PDF, data=b"x" * 22_000_000,
                                     media_type="application/pdf", page_count=10)]
    assert "too large to send" in ev.evaluate(huge).error
    assert calls == []


def test_documents_are_released_after_evaluation(tmp_path: Path):
    from .conftest import make_text_pdf
    folder = tmp_path / "Zoe"
    folder.mkdir()
    make_text_pdf(folder / "cv.pdf", "Zoe " * 400)
    c = Candidate(candidate_id="C001", display_name="Zoe", source_path=folder)
    from hr_screening.discovery import load_candidate
    load_candidate(c)
    tokens = c.estimated_tokens()
    c.release()
    assert c.documents == [] and c.estimated_tokens() == tokens and c.has_content

    client = ClaudeClient("sk-test")
    calls = install_fake(client, [fake_message(evaluation([M] * 4))])
    result = Evaluator(client, filter_set()).evaluate(c)          # reloads from disk
    assert "Zoe Zoe" in calls[0]["messages"][0]["content"][0]["text"]
    assert not result.error and c.documents == []


def _respond_by_name(kwargs):
    """Fake API: candidates named 'Strong*' meet everything, 'Weak*' fail a must-have."""
    text = kwargs["messages"][0]["content"][0]["text"]
    return fake_message(evaluation([M, M, M, M] if "Strong" in text else [N, M, M, M]),
                        input_tokens=1000, output_tokens=100)


def test_evaluate_all_parallel_keeps_order_and_reports_progress():
    client = ClaudeClient("sk-test")
    calls = install_fake(client, _respond_by_name)
    candidates = [candidate(f"{'Strong' if i % 2 else 'Weak'} {i}", f"C{i:03d}", text=f"{'Strong' if i % 2 else 'Weak'}")
                  for i in range(1, 21)]
    progress = []

    results = evaluate_all(Evaluator(client, filter_set()), candidates, concurrency=5, on_progress=progress.append)

    assert [r.candidate.candidate_id for r in results] == [c.candidate_id for c in candidates]
    assert all(r.eliminated == ("Weak" in r.name) for r in results)
    assert len(calls) == 20 and [p.done for p in progress] == list(range(1, 21))
    assert progress[-1].cost_usd == pytest.approx(client.usage.cost_usd) and client.usage.calls == 20


def test_cancel_skips_remaining_candidates():
    client = ClaudeClient("sk-test")
    install_fake(client, _respond_by_name)
    cancel = threading.Event()
    candidates = [candidate(f"Strong {i}", f"C{i:03d}") for i in range(1, 11)]

    results = evaluate_all(Evaluator(client, filter_set()), candidates, concurrency=2,
                           on_progress=lambda p: cancel.set(), cancel=cancel)

    assert results[0].error == "" and len(results) == 10
    assert all(r.error == "Not processed - run was cancelled." for r in results[1:])


def test_invalid_key_stops_the_batch():
    client = ClaudeClient("sk-test")
    install_fake(client, lambda kwargs: InvalidAPIKey("The API key was rejected."))
    with pytest.raises(InvalidAPIKey):
        evaluate_all(Evaluator(client, filter_set()), [candidate(cid=f"C{i}") for i in range(5)])

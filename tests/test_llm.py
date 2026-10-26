from __future__ import annotations

from pathlib import Path

import anthropic
import httpx2
import pytest
from pydantic import BaseModel

from hr_screening import llm
from hr_screening.llm import ClaudeClient, document_blocks, usage_cost
from hr_screening.models import ContentKind, SourceDocument

from .fakes import fake_message, install_fake


class Answer(BaseModel):
    value: str


def test_structured_call_shapes_request_and_tracks_cost():
    client = ClaudeClient("sk-test", model="claude-opus-5-5")
    calls = install_fake(client, [fake_message(Answer(value="ok"), input_tokens=2000, output_tokens=1000,
                                               cache_read=10_000)])
    result = client.structured(system="sys", content=[{"type": "text", "text": "hi"}],
                               output_model=Answer, effort="high", cache_system=True)

    assert result.value == "ok"
    (kwargs,) = calls
    assert kwargs["model"] == "claude-opus-5-5"
    assert kwargs["output_format"] is Answer
    assert kwargs["output_config"] == {"effort": "high"}
    assert kwargs["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert kwargs["fallbacks"] == "default" and kwargs["betas"] == ["server-side-fallback-2026-07-01"]
    assert "thinking" not in kwargs  # Opus 5.5 always thinks adaptively; never send `disabled`

    # 2000 * $4 + 1000 * $20 + 10,000 cached * $0.20, per million tokens
    assert client.usage.cost_usd == pytest.approx((2000 * 4 + 1000 * 20 + 10_000 * 0.2) / 1e6)
    assert client.usage.calls == 1


def test_haiku_has_no_fallback_parameter():
    client = ClaudeClient("sk-test", model="claude-haiku-5-5")
    calls = install_fake(client, [fake_message(Answer(value="ok"), model="claude-haiku-5-5")])
    client.structured(system="s", content=[], output_model=Answer)
    assert "fallbacks" not in calls[0] and "betas" not in calls[0]


def test_unknown_model_falls_back_to_default():
    assert ClaudeClient("sk-test", model="gpt-9").model == "claude-opus-5-5"


def test_missing_key():
    with pytest.raises(llm.InvalidAPIKey):
        ClaudeClient("")


@pytest.mark.parametrize("stop_reason, parsed, match", [
    ("refusal", None, "declined"),
    ("max_tokens", None, "cut off"),
    ("end_turn", None, "unexpected format"),
])
def test_bad_responses(stop_reason, parsed, match):
    client = ClaudeClient("sk-test")
    install_fake(client, [fake_message(parsed, stop_reason=stop_reason)])
    with pytest.raises(llm.ResponseProblem, match=match):
        client.structured(system="s", content=[], output_model=Answer)
    assert client.usage.calls == 1  # refused / truncated calls are still billed


def _status_error(cls, status, message="error"):
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    return cls(message, response=httpx2.Response(status, request=request), body=None)


@pytest.mark.parametrize("exc, expected, match", [
    (_status_error(anthropic.AuthenticationError, 401), llm.InvalidAPIKey, "rejected"),
    (_status_error(anthropic.RateLimitError, 429), llm.RateLimited, "rate limit"),
    (_status_error(anthropic.InternalServerError, 500), llm.ServiceUnavailable, "temporarily"),
    (_status_error(anthropic.BadRequestError, 400, "Your credit balance is too low"), llm.LLMError, "credit"),
    (anthropic.APIConnectionError(request=httpx2.Request("POST", "https://x")), llm.ConnectionProblem, "internet"),
])
def test_errors_are_translated_for_hr(exc, expected, match):
    client = ClaudeClient("sk-test")
    install_fake(client, [exc])
    with pytest.raises(expected, match=match):
        client.structured(system="s", content=[], output_model=Answer)


def test_schema_mismatch_during_streaming_is_retryable():
    from pydantic import ValidationError
    client = ClaudeClient("sk-test")
    try:
        Answer.model_validate({"wrong": 1})
    except ValidationError as exc:
        install_fake(client, [exc])
    with pytest.raises(llm.Unparseable) as info:
        client.structured(system="s", content=[], output_model=Answer)
    assert info.value.retryable


def test_retryable_flags():
    assert llm.RateLimited.retryable and llm.ServiceUnavailable.retryable and llm.ConnectionProblem.retryable
    assert llm.Truncated.retryable and not llm.Refused.retryable and not llm.InvalidAPIKey.retryable


def test_document_blocks():
    docs = [
        SourceDocument(Path("cv.docx"), ContentKind.TEXT, text="Jane"),
        SourceDocument(Path("scan.pdf"), ContentKind.PDF, data=b"%PDF-1.4", media_type="application/pdf"),
        SourceDocument(Path("photo.jpg"), ContentKind.IMAGE, data=b"\xff\xd8", media_type="image/jpeg"),
    ]
    blocks = document_blocks(docs, label="application")
    assert blocks[0] == {"type": "text", "text": '<application file="cv.docx">\nJane\n</application>'}
    assert blocks[1]["type"] == "document" and blocks[1]["source"]["data"] == "JVBERi0xLjQ="
    assert blocks[2]["type"] == "text" and blocks[3]["type"] == "image"
    assert blocks[3]["source"]["media_type"] == "image/jpeg"


def test_usage_cost_unknown_model_uses_default_prices():
    assert usage_cost("mystery", 1_000_000, 0) == pytest.approx(4.0)

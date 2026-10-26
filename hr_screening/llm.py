"""Thin wrapper around the Anthropic SDK: structured calls, document blocks, cost tracking,
and HR-friendly error messages."""

from __future__ import annotations

import base64
import json
import logging
import threading
from dataclasses import dataclass
from typing import Literal, TypeVar

import anthropic
from pydantic import BaseModel, ValidationError

from . import config
from .models import ContentKind, SourceDocument

log = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)
Effort = Literal["low", "medium", "high", "xhigh", "max"]

# Server-side refusal fallback: if a model's safety classifier declines a request, the API
# re-runs it on a suitable fallback model within the same call.
_FALLBACK_BETA = "server-side-fallback-2026-07-01"
_MODELS_WITH_FALLBACK = {"claude-opus-5-5", "claude-sonnet-5-5"}


# --- errors ------------------------------------------------------------------------

class LLMError(Exception):
    """An AI call failed. `str(exc)` is a message suitable for showing to HR."""

    retryable = False


class InvalidAPIKey(LLMError):
    pass


class ConnectionProblem(LLMError):
    retryable = True


class RateLimited(LLMError):
    retryable = True


class ServiceUnavailable(LLMError):
    retryable = True


class ResponseProblem(LLMError):
    """Refusal, truncated output or unparseable output."""


class Refused(ResponseProblem):
    pass


class Truncated(ResponseProblem):
    """Output hit max_tokens; retrying with a larger limit usually works."""
    retryable = True


class Unparseable(ResponseProblem):
    retryable = True


# --- usage / cost ------------------------------------------------------------------

@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_write_tokens: int = 0
    cache_read_tokens: int = 0
    cost_usd: float = 0.0
    calls: int = 0

    def add(self, other: "Usage") -> None:
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.cache_write_tokens += other.cache_write_tokens
        self.cache_read_tokens += other.cache_read_tokens
        self.cost_usd += other.cost_usd
        self.calls += other.calls


def usage_cost(model_id: str, input_tokens: int, output_tokens: int,
               cache_write_tokens: int = 0, cache_read_tokens: int = 0) -> float:
    info = config.MODELS.get(model_id) or config.MODELS[config.DEFAULT_MODEL]
    return (
        input_tokens * info.input_per_mtok
        + cache_write_tokens * info.input_per_mtok * 1.25
        + cache_read_tokens * info.cache_read_per_mtok
        + output_tokens * info.output_per_mtok
    ) / 1_000_000


# --- content helpers ---------------------------------------------------------------

def document_blocks(documents: list[SourceDocument], label: str = "document") -> list[dict]:
    """Turn extracted documents into Messages API content blocks."""
    blocks: list[dict] = []
    for doc in documents:
        if doc.kind is ContentKind.TEXT:
            blocks.append({
                "type": "text",
                "text": f'<{label} file="{doc.name}">\n{doc.text}\n</{label}>',
            })
        elif doc.kind is ContentKind.PDF:
            blocks.append({
                "type": "document",
                "title": doc.name,
                "source": {
                    "type": "base64",
                    "media_type": "application/pdf",
                    "data": base64.standard_b64encode(doc.data).decode("ascii"),
                },
            })
        else:
            blocks.append({"type": "text", "text": f'<{label} file="{doc.name}"> (scanned image follows)'})
            blocks.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": doc.media_type,
                    "data": base64.standard_b64encode(doc.data).decode("ascii"),
                },
            })
    return blocks


# --- client ------------------------------------------------------------------------

class ClaudeClient:
    """Thread-safe for concurrent calls; accumulates usage across all calls."""

    def __init__(self, api_key: str, model: str = config.DEFAULT_MODEL, max_retries: int = 4):
        if not api_key:
            raise InvalidAPIKey("No API key is set. Add your Anthropic API key in Settings.")
        self.model = model if model in config.MODELS else config.DEFAULT_MODEL
        self._client = anthropic.Anthropic(api_key=api_key, max_retries=max_retries, http_client=_http_client())
        self._lock = threading.Lock()
        self.usage = Usage()

    def check_access(self) -> None:
        """Validate the key and that the selected model is available (no tokens used)."""
        try:
            self._client.models.retrieve(self.model)
        except Exception as exc:
            raise _translate(exc) from exc

    def structured(
        self,
        *,
        system: str,
        content: list[dict],
        output_model: type[T],
        effort: Effort = "medium",
        max_tokens: int = 32_000,
        cache_system: bool = False,
    ) -> T:
        """Send one request and return the response parsed into `output_model`.

        `cache_system=True` marks the system prompt for prompt caching (use it when many
        calls share the same, long system prompt).
        """
        system_block: dict = {"type": "text", "text": system}
        if cache_system:
            system_block["cache_control"] = {"type": "ephemeral"}

        kwargs: dict = dict(
            model=self.model,
            max_tokens=max_tokens,
            system=[system_block],
            messages=[{"role": "user", "content": content}],
            output_config={"effort": effort},
            output_format=output_model,
        )
        if self.model in _MODELS_WITH_FALLBACK:
            kwargs.update(betas=[_FALLBACK_BETA], fallbacks="default")

        try:
            with self._client.beta.messages.stream(**kwargs) as stream:
                message = stream.get_final_message()
        except Exception as exc:
            raise _translate(exc) from exc

        self._record_usage(message)

        if message.stop_reason == "refusal":
            raise Refused(
                "The AI declined to process this item. It may contain content it could not "
                "assess; please review it manually."
            )
        if message.stop_reason == "max_tokens":
            raise Truncated("The AI response was cut off before it finished. Please retry.")
        try:
            parsed = message.parsed_output
        except Exception as exc:   # SDK raises if the JSON does not match the schema
            raise Unparseable("The AI returned a response in an unexpected format. Please retry.") from exc
        if parsed is None:
            raise Unparseable("The AI returned a response in an unexpected format. Please retry.")
        return parsed

    def _record_usage(self, message) -> None:
        u = message.usage
        call = Usage(
            input_tokens=u.input_tokens or 0,
            output_tokens=u.output_tokens or 0,
            cache_write_tokens=getattr(u, "cache_creation_input_tokens", 0) or 0,
            cache_read_tokens=getattr(u, "cache_read_input_tokens", 0) or 0,
            calls=1,
        )
        # Price by the model that actually served the request (a fallback may have run).
        served_by = getattr(message, "model", None) or self.model
        call.cost_usd = usage_cost(
            served_by, call.input_tokens, call.output_tokens,
            call.cache_write_tokens, call.cache_read_tokens,
        )
        with self._lock:
            self.usage.add(call)
        log.debug("Claude call: %s, $%.4f (%s)", call, call.cost_usd, served_by)


def _http_client():
    """SDK HTTP client that trusts the Windows certificate store, so it also works behind
    corporate proxies that inspect TLS traffic. Falls back to the SDK default."""
    try:
        import ssl

        import truststore
        return anthropic.DefaultHttpxClient(verify=truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT))
    except Exception as exc:  # pragma: no cover
        log.info("Using default certificate bundle: %s", exc)
        return None


def _translate(exc: Exception) -> LLMError:
    """Map SDK exceptions to messages HR can act on. Most specific first."""
    if isinstance(exc, LLMError):
        return exc
    if isinstance(exc, anthropic.AuthenticationError):
        return InvalidAPIKey("The API key was rejected. Check the key in Settings.")
    if isinstance(exc, anthropic.PermissionDeniedError):
        return InvalidAPIKey("This API key does not have permission to use the selected model.")
    if isinstance(exc, anthropic.NotFoundError):
        return LLMError("The selected AI model is not available for this API key. Choose another in Settings.")
    if isinstance(exc, anthropic.RateLimitError):
        return RateLimited(
            "The API rate limit was reached. Wait a minute and retry, or lower 'Parallel requests' in Settings."
        )
    if isinstance(exc, anthropic.BadRequestError):
        message = getattr(exc, "message", str(exc))
        if "credit balance" in message.lower():
            return LLMError("Your Anthropic account has insufficient credit. Top up in the Anthropic Console.")
        return LLMError(f"The AI service rejected the request: {message}")
    if isinstance(exc, anthropic.APIStatusError):
        if exc.status_code >= 500:
            return ServiceUnavailable("The AI service is temporarily unavailable. Please retry shortly.")
        return LLMError(f"The AI service returned an error ({exc.status_code}).")
    if isinstance(exc, anthropic.APITimeoutError):
        return ConnectionProblem("The AI service took too long to respond. Please retry.")
    if isinstance(exc, anthropic.APIConnectionError):
        return ConnectionProblem("Could not reach the AI service. Check your internet connection or proxy.")
    if isinstance(exc, (ValidationError, json.JSONDecodeError)):
        # The streamed JSON did not match the expected schema.
        return Unparseable("The AI returned a response in an unexpected format. Please retry.")
    log.exception("Unexpected error during AI call")
    return LLMError(f"Unexpected error during AI call: {type(exc).__name__}: {exc}")

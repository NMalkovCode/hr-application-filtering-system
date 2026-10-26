"""A stand-in for the Anthropic streaming API so tests never make network calls."""

from __future__ import annotations

import threading
from types import SimpleNamespace


class FakeStream:
    def __init__(self, message):
        self._message = message

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_final_message(self):
        return self._message


def fake_message(parsed, *, stop_reason="end_turn", model="claude-opus-5-5",
                 input_tokens=1000, output_tokens=500, cache_read=0, cache_write=0):
    return SimpleNamespace(
        parsed_output=parsed,
        stop_reason=stop_reason,
        model=model,
        usage=SimpleNamespace(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_input_tokens=cache_read,
            cache_creation_input_tokens=cache_write,
        ),
    )


def install_fake(client, responses):
    """Replace the SDK stream on `client` (a ClaudeClient). `responses` is either a list of
    messages/exceptions returned in order, or a callable(kwargs) -> message/exception (use
    that for parallel calls). Returns the list of kwargs each call received."""
    calls: list[dict] = []
    lock = threading.Lock()
    queue = None if callable(responses) else list(responses)

    def stream(**kwargs):
        with lock:
            calls.append(kwargs)
            item = responses(kwargs) if queue is None else queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return FakeStream(item)

    client._client.beta.messages.stream = stream  # type: ignore[method-assign]
    return calls

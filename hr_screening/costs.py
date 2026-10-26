"""Cost estimate shown before a run starts."""

from __future__ import annotations

from dataclasses import dataclass

from . import config
from .llm import usage_cost
from .models import Candidate

# Output per application (thinking + JSON), from typical to long.
OUTPUT_TOKENS_LOW = 1_500
OUTPUT_TOKENS_HIGH = 5_000
# Below this many tokens a prompt is not cached (512 for the Claude 5.5 models).
MIN_CACHEABLE_TOKENS = 512


@dataclass(frozen=True)
class CostEstimate:
    low_usd: float
    high_usd: float
    candidates: int
    already_spent_usd: float = 0.0     # e.g. reading the other open roles

    def exceeds(self, limit_usd: float) -> bool:
        return limit_usd > 0 and self.already_spent_usd + self.high_usd > limit_usd

    def describe(self) -> str:
        text = f"Estimated cost for {self.candidates} applications: ${self.low_usd:.2f} – ${self.high_usd:.2f}"
        if self.already_spent_usd >= 0.005:
            text += f" (plus ${self.already_spent_usd:.2f} already spent preparing the run)"
        return text + "."


def estimate_run_cost(candidates: list[Candidate], system_prompt: str, model: str,
                      already_spent_usd: float = 0.0) -> CostEstimate:
    """Range for evaluating `candidates` (documents must already be loaded)."""
    model = model if model in config.MODELS else config.DEFAULT_MODEL
    prompt_tokens = max(1, len(system_prompt) // 4)
    cacheable = prompt_tokens >= MIN_CACHEABLE_TOKENS
    low = high = 0.0
    assessable = [c for c in candidates if c.has_content and c.estimated_tokens() <= config.MAX_APPLICATION_TOKENS]
    for i, c in enumerate(assessable):
        app = c.estimated_tokens() + 50
        if cacheable:
            low += usage_cost(model, app, OUTPUT_TOKENS_LOW,
                              cache_write_tokens=prompt_tokens if i == 0 else 0,
                              cache_read_tokens=prompt_tokens if i else 0)
        else:
            low += usage_cost(model, app + prompt_tokens, OUTPUT_TOKENS_LOW)
        # High: nothing cached, long outputs, and applications 30% larger than estimated.
        high += usage_cost(model, int(app * 1.3) + prompt_tokens, OUTPUT_TOKENS_HIGH)
    return CostEstimate(round(low, 4), round(high, 4), len(assessable), already_spent_usd)

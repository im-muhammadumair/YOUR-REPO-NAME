"""Adaptive token budgets and context sizing.

A one-size-fits-all `max_output_tokens=4000` wastes money and blows up latency
on tiny questions. This module maps a task complexity tier to an appropriate
output budget, and trims candidate context so we never flood Gemini with
irrelevant chunks.
"""
from rag.model_registry import LIGHT, GENERAL, STRONG

# Output budget (tokens) per complexity tier. Keep answers proportionate:
# a one-line question should not produce a five-paragraph essay.
_OUTPUT_BUDGET = {
    LIGHT: 512,
    GENERAL: 1024,
    STRONG: 2048,
}

# Approximate input-token cost of a context character (Gemini tokenizer ~4:1).
_CHARS_PER_TOKEN = 4

# Hard limits guarding against accidental cost explosions.
MAX_INPUT_CONTEXT_CHARS = 24_000   # roughly 6000 tokens of context


def output_budget(tier: str) -> int:
    """Return a sensible max-output-token budget for a complexity tier."""
    return _OUTPUT_BUDGET.get(tier, _OUTPUT_BUDGET[GENERAL])


def budget_for(style: str, desired_tier: str = GENERAL) -> int:
    """Return an output budget, raising it for requests that want detail.

    Takes: style - "short", "normal", "detailed", or "action".
           desired_tier - the model tier the answer will be generated with.
    Returns: a max-output-tokens value.
    """
    base = output_budget(desired_tier)
    if style in ("detailed", "action"):
        return base * 2
    if style == "short":
        return max(150, base // 2)
    return base


def trim_context(chunks) -> list:
    """Return only the context that fits within the input budget.

    Takes: chunks - a list of dicts with a "text" field, already ranked best-first.
    Returns: the longest prefix of best-ranked chunks that fits the budget.
    """
    budget_chars = MAX_INPUT_CONTEXT_CHARS
    used = 0
    kept = []
    for chunk in chunks:
        if not chunk.get("text"):
            continue
        cost = max(len(chunk["text"]) // _CHARS_PER_TOKEN, 1)
        if used + cost > budget_chars and kept:
            break
        used += cost
        kept.append(chunk)
    return kept or chunks[:1]

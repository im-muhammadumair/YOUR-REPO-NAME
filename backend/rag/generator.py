"""Adaptive generation with escalation, health tracking and smart failover.

This module owns the *generation* Gemini calls. For each request it:

    1. picks a primary model tier from the request complexity (see model_router),
    2. generates with the cheapest suitable healthy model,
    3. records success/failure into model health,
    4. on failure, classifies it (retryable vs permanent) and moves to the next
       healthy model in the dynamically-built fallback chain,
    5. never lets a technical failure reach the caller - the RAG service turns a
       total failure into a friendly "please try again" message.

Escalation to a stronger model (for low-confidence answers) is driven by the
validator, which asks `generate` to use the STRONG tier via `escalation_tier`.
"""
import time

from config import (
    AI_MAX_GEMINI_CALLS,
    AI_MAX_RETRIES,
    GEMINI_API_KEY,
)

from google import genai
from google.genai import types

from rag.model_health import health
from rag.model_router import choose_models, choose_models_for_tier
from rag.token_manager import budget_for

MAX_ANSWER_CONTINUATIONS = 3

_client = None


def _get_client():
    global _client
    if _client is None:
        _client = genai.Client(api_key=GEMINI_API_KEY)
    return _client


def classify_error(exc) -> str:
    """Classify a generation exception for a smart handling decision.

    Returns one of:
      - "permanent": model gone/unsupported/auth/config - do not retry same model.
      - "retryable": rate limit / transient server problem - retry is worthwhile.
      - "unknown":   anything else.
    """
    text = str(exc).lower()
    if "permission_denied" in text or "invalid_argument" in text \
            or "api_key" in text or "unauthorized" in text:
        return "permanent"
    if "not_found" in text and "model" in text:
        return "permanent"
    if "quota" in text or "429" in text or "rate" in text \
            or "resource_exhausted" in text or "500" in text or "503" in text \
            or "internal" in text or "deadline" in text or "timeout" in text:
        return "retryable"
    return "unknown"


def _safe_prompt(prompt: str) -> str:
    return prompt


def _generate_once(model: str, prompt: str, max_tokens: int, temperature: float):
    """One raw generation attempt. Raises on failure."""
    return _get_client().models.generate_content(
        model=model,
        contents=_safe_prompt(prompt),
        config=types.GenerateContentConfig(
            temperature=temperature,
            max_output_tokens=max_tokens,
        ),
    )


def generate(complexity: str, prompt: str, style: str = "normal",
             escalation_tier: str | None = None):
    """Generate an answer with the cheapest suitable healthy model + failover.

    Takes: complexity - SMALL/NORMAL/COMPLEX/CRITICAL.
           prompt - the assembled user/system prompt text.
           style - short/normal/detailed, drives the token budget.
           escalation_tier - optional model tier override (used when the
                             validator asks for a stronger model).
    Returns: (text, model_used, calls_used)
             text - the answer text (may be "" on total failure).
             model_used - the model that produced it (or None).
             calls_used - how many Gemini calls were consumed.
    Raises: RuntimeError if no available model could produce an answer.
    """
    target_tier = escalation_tier or _tier_for(complexity)
    max_tokens = budget_for(style, target_tier)
    if escalation_tier:
        chain = choose_models_for_tier(escalation_tier)
    else:
        chain = choose_models(complexity)
    if not chain:
        raise RuntimeError("no available models")

    calls = 0
    for model in chain:
        if calls >= AI_MAX_GEMINI_CALLS:
            break
        # Determine retry budget once we know what kind of failure occurs.
        attempt = 0
        while True:
            calls += 1
            try:
                result = _generate_once(model, prompt, max_tokens, _temperature(complexity))
                health.record_success(model)
                return (result.text or "").strip(), model, calls
            except Exception as exc:
                kind = classify_error(exc)
                health.record_failure(model)
                if _retryable(kind) and attempt < AI_MAX_RETRIES and calls < AI_MAX_GEMINI_CALLS:
                    time.sleep(min(1.5 * (attempt + 1), 4))
                    attempt += 1
                    continue                 # retry the same model
                break                        # move to the next model in the chain
        if calls >= AI_MAX_GEMINI_CALLS:
            break

    raise RuntimeError("all available models failed")


# At module import we cannot know retry policy without an error, so track it via
# a small helper that the loop actually uses. (Kept simple for readability.)
def _retryable(kind: str) -> bool:
    return kind == "retryable"


def generate_stream(complexity: str, prompt: str, style: str = "normal",
                   escalation_tier: str | None = None):
    """Generate an answer with streaming, cheapest suitable healthy model + failover.

    Yields ``(token_text, model_used, is_final)`` tuples as tokens arrive.
    ``is_final`` is True only on the very last yield, after which the
    generator is done.  ``model_used`` is None until the first token arrives,
    then holds the model name for all subsequent yields.

    Raises RuntimeError if no available model could produce an answer.

    Takes: complexity - SMALL/NORMAL/COMPLEX/CRITICAL.
           prompt - the assembled user/system prompt text.
           style - short/normal/detailed, drives the token budget.
           escalation_tier - optional model tier override.
    Yields: (token_text, model_used, is_final)
    """
    target_tier = escalation_tier or _tier_for(complexity)
    max_tokens = budget_for(style, target_tier)
    chain = choose_models_for_tier(escalation_tier) if escalation_tier else choose_models(complexity)
    if not chain:
        raise RuntimeError("no available models")

    calls = 0
    for model in chain:
        if calls >= AI_MAX_GEMINI_CALLS:
            break
        attempt = 0
        while True:
            calls += 1
            try:
                emitted = ""
                truncated = False
                continuations = 0
                contents = prompt
                while True:
                    cycle_truncated = False
                    first = True
                    for chunk in _get_client().models.generate_content_stream(
                        model=model,
                        contents=contents,
                        config=types.GenerateContentConfig(
                            temperature=_temperature(complexity),
                            max_output_tokens=max_tokens,
                        ),
                    ):
                        text = chunk.text or ""
                        if text and first and continuations and emitted:
                            overlap = _overlap_prefix(emitted, text)
                            if overlap:
                                text = text[overlap:]
                            first = False
                        if text:
                            emitted += text
                            yield (text, model, False)
                        try:
                            candidates = getattr(chunk, "candidates", None) or []
                            if candidates:
                                reason = getattr(candidates[0], "finish_reason", None)
                                if getattr(reason, "name", "") == "MAX_TOKENS":
                                    cycle_truncated = True
                        except Exception:
                            pass
                    if not cycle_truncated:
                        break
                    continuations += 1
                    if continuations > MAX_ANSWER_CONTINUATIONS:
                        truncated = True
                        break
                    contents = (
                        prompt
                        + "\n\nYou were cut off while writing the answer. "
                        + "Continue the SAME answer from the exact point where "
                        + "it stopped. Do NOT repeat anything you already wrote.\n\n"
                        + "The answer stopped at:\n"
                        + emitted[-800:]
                    )
                health.record_success(model)
                yield ("TRUNCATED" if truncated else "", model, True)
                return
            except Exception as exc:
                kind = classify_error(exc)
                health.record_failure(model)
                if _retryable(kind) and attempt < AI_MAX_RETRIES and calls < AI_MAX_GEMINI_CALLS:
                    time.sleep(min(1.5 * (attempt + 1), 4))
                    attempt += 1
                    continue
                break
        if calls >= AI_MAX_GEMINI_CALLS:
            break

    raise RuntimeError("all available models failed")


def _temperature(complexity: str) -> float:
    return 0.2 if complexity != "CRITICAL" else 0.1


def _overlap_prefix(prev: str, new: str) -> int:
    """Length of the longest prefix of ``new`` that closes the tail of ``prev``.

    Used when continuing a truncated generation: Gemini re-emits the last few
    characters of the previous pass, so we drop that duplicated prefix before
    appending the continuation to the answer.
    """
    tail = prev[-300:]
    best = 0
    for n in range(min(len(tail), len(new)), 0, -1):
        if tail.endswith(new[:n]):
            best = n
            break
    return best


def _tier_for(complexity: str) -> str:
    from rag.query_router import SMALL, NORMAL, COMPLEX, CRITICAL
    if complexity == SMALL:
        return "LIGHT"
    if complexity == NORMAL:
        return "GENERAL"
    if complexity in (COMPLEX, CRITICAL):
        return "STRONG"
    return "GENERAL"

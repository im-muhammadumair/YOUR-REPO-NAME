"""Cost-aware model selection and dynamic failover chain.

Picks the *cheapest* model that is sufficiently capable for the task tier, and
builds a live fallback chain from the current availability + health state. The
chain is rebuilt per request from model_registry (which already filtered to
models the API confirmed) and model_health (which excludes broken models), so
it adapts automatically when Google changes available models.
"""
from rag.model_registry import (
    LIGHT,
    GENERAL,
    STRONG,
    registry,
)
from rag.model_health import health
from rag.query_router import SMALL, NORMAL, COMPLEX, CRITICAL


def _primary_tier(complexity: str) -> str:
    """Map a request complexity to the cheapest sufficient model tier."""
    if complexity in (SMALL,):
        return LIGHT
    if complexity in (NORMAL,):
        return GENERAL
    return STRONG


def _fallback_chain(primary_tier: str) -> list:
    """Build a healthy fallback chain starting at the primary tier.

    Order: primary tier (healthy first), then other tiers cheap->strong, with
    cooldowned/known-dead models excluded.
    """
    order = {LIGHT: 0, GENERAL: 1, STRONG: 2}
    tiers = sorted((LIGHT, GENERAL, STRONG), key=lambda t: abs(order[t] - order[primary_tier]))

    chain = []
    for tier in tiers:
        for name in registry.for_tier(tier):
            if name in chain:
                continue
            if health.is_usable(name):
                chain.append(name)
    return chain or registry.all_for_generation()


def choose_models(complexity: str) -> list:
    """Return the ordered list of models to try for a request.

    Takes: complexity - SMALL/NORMAL/COMPLEX/CRITICAL.
    Returns: a list of model names to attempt in order (primary first).
    """
    primary = _primary_tier(complexity)
    return _fallback_chain(primary)


def choose_models_for_tier(tier: str) -> list:
    """Return the ordered model list when the target tier is already decided.

    Used for escalation, where the validator has already decided a stronger
    tier (e.g. STRONG) is required.
    """
    if tier not in (LIGHT, GENERAL, STRONG):
        tier = GENERAL
    return _fallback_chain(tier)

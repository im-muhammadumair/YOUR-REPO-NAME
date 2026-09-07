"""Dynamic Gemini model discovery and capability registry.

Google can (and does) retire or gate model versions at any time - which is
exactly what happened when `gemini-2.5-flash` stopped being available to new
accounts. Instead of hardcoding one model, this module:

    1. asks the Gemini API for the models available to the current account,
    2. keeps only the text-generation models we can actually use,
    3. classifies each into a capability tier (LIGHT / GENERAL / STRONG), and
    4. exposes a queryable runtime registry.

The registry is built at application startup (see main.py) and is deliberately
resilient: if discovery ever fails, the configured preference list in
config.py is used as a static fallback so the application still starts.
"""
from dataclasses import dataclass, field

from config import (
    GEMINI_CHAT_MODEL,
    GEMINI_MODEL_CANDIDATES,
    GEMINI_RERANK_MODEL,
)

# Capability tiers, in increasing intelligence/cost.
LIGHT = "LIGHT"
GENERAL = "GENERAL"
STRONG = "STRONG"


@dataclass
class ModelInfo:
    """Runtime metadata for one usable Gemini text-generation model."""
    name: str                      # e.g. "models/gemini-flash-latest"
    tier: str                      # LIGHT / GENERAL / STRONG
    generation: bool = True
    rerank: bool = False           # whether it may also be used for reranking
    prefer: int = 0                # higher = preferred for its tier


@dataclass
class ModelRegistry:
    """In-memory registry of the currently available Gemini models."""

    # name -> ModelInfo, populated at startup.
    _models: dict = field(default_factory=dict)
    _order: list = field(default_factory=list)   # preferred order, cheap->strong
    _healthy: set = field(default_factory=set)

    def register(self, info: ModelInfo) -> None:
        self._models[info.name] = info
        if info.name not in self._healthy:
            self._healthy.add(info.name)

    def names(self) -> list:
        return list(self._models.keys())

    def get(self, name: str) -> ModelInfo | None:
        return self._models.get(name)

    # --- tier helpers ------------------------------------------------------
    def for_tier(self, tier: str) -> list:
        """Return names in the given tier, healthy ones first, then by pref."""
        tiered = [m.name for m in self._models.values() if m.tier == tier]
        tiered.sort(key=lambda n: (n not in self._healthy, -self.get(n).prefer))
        return tiered

    def all_for_generation(self) -> list:
        """Return all generation-capable names, cheap->strong preference."""
        order = {name: i for i, name in enumerate(self._order)}
        items = sorted(
            self._models.values(),
            key=lambda m: (m.name not in self._healthy, order.get(m.name, 99)),
        )
        return [m.name for m in items if m.generation]

    def all_for_rerank(self) -> list:
        return [m.name for m in self._models.values() if m.rerank]

    def best_rerank(self) -> str | None:
        names = self.all_for_rerank()
        return names[0] if names else None

    def mark_healthy(self, name: str) -> None:
        self._healthy.add(name)

    def mark_unhealthy(self, name: str) -> None:
        self._healthy.discard(name)

    def is_healthy(self, name: str) -> bool:
        return name in self._healthy

    def tier_of(self, name: str) -> str:
        info = self._models.get(name)
        return info.tier if info else GENERAL


# The single module-level registry instance, populated at startup.
registry = ModelRegistry()


def _tier_for_name(name: str) -> str:
    """Guess a starting tier for a model name before any live test.

    Uses naming conventions as a heuristic only; the registry improves it with
    real discovery ordering afterwards.
    """
    short = name.replace("models/", "").lower()
    if "pro" in short or "3.1" in short or "3.5" in short or "3.6" in short or "3.8" in short:
        return STRONG
    if "flash-lite" in short:
        return LIGHT
    return GENERAL


def _normalize(name: str) -> str:
    """Accept either 'gemini-x' or 'models/gemini-x'."""
    return name if name.startswith("models/") else f"models/{name}"


def discover(client) -> ModelRegistry:
    """Discover usable Gemini text-generation models and build the registry.

    Takes: client - an initialised google-genai client.
    Returns: a populated ModelRegistry.
    """
    reg = ModelRegistry()

    available = set()
    try:
        for model in client.models.list():
            if hasattr(model, "supported_actions") and "generateContent" in model.supported_actions:
                available.add(_normalize(model.name))
    except Exception:
        available = set()

    # Preference order defines the fallback chain: healthy flash-lite first,
    # then general flash, then strong pro. Only names the API confirmed are
    # registered, so obsolete/hardcoded models are filtered out automatically.
    preferred = [GEMINI_CHAT_MODEL] + GEMINI_MODEL_CANDIDATES + [GEMINI_RERANK_MODEL]
    seen = set()
    ordered = []
    for candidate in preferred:
        normalized = _normalize(candidate)
        if normalized in seen:
            continue
        seen.add(normalized)
        if normalized in available:
            ordered.append(normalized)

    # If none of the named candidates is available, fall back to anything the
    # API returned, ordered cheap->strong by name heuristic.
    if not ordered:
        ordered = sorted(
            (n for n in available if _generation_capable_hint(n)),
            key=lambda n: _tier_rank(_tier_for_name(n)),
        )

    # Assign tiers and prefer-weights. The first LIGHT is cheapest/preferred.
    tier_weights = {LIGHT: [], GENERAL: [], STRONG: []}
    for i, name in enumerate(ordered):
        tier = _tier_for_name(name)
        tier_weights[tier].append(name)

    for tier, names in tier_weights.items():
        for pos, name in enumerate(names):
            reg.register(ModelInfo(
                name=name,
                tier=tier,
                generation=True,
                rerank=True,             # any text model can score relevance
                prefer=(len(names) - pos),  # earlier in list = higher prefer
            ))

    # If the API returned nothing at all, seed with the configured candidates so
    # the app still starts (generation calls will resolve models lazily).
    if not reg.names():
        for candidate in preferred:
            normalized = _normalize(candidate)
            tier = _tier_for_name(normalized)
            reg.register(ModelInfo(
                name=normalized, tier=tier, generation=True, rerank=True,
                prefer=1,
            ))

    reg._order = reg.names()
    return reg


def _generation_capable_hint(name: str) -> bool:
    short = name.replace("models/", "").lower()
    banned = ("tts", "image", "computer-use", "robotics", "transcribe", "lyria")
    if any(b in short for b in banned):
        return False
    return "flash" in short or "pro" in short


def _tier_rank(tier: str) -> int:
    return {LIGHT: 0, GENERAL: 1, STRONG: 2}[tier]

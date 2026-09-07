"""Runtime model health tracking with cooldowns.

Repeatedly failing models are demoted or temporarily excluded so a request never
wastes time retrying a model that is known to be broken (e.g. the retired
`gemini-2.5-flash`). After a cool-down the model is tested again and restored if
it recovers.
"""
import time

from config import AI_HEALTH_COOLDOWN_SECONDS, AI_HEALTH_FAILURE_LIMIT

from rag.model_registry import ModelRegistry


class ModelHealth:
    """Tracks per-model success/failure and enforces cool-downs."""

    def __init__(self, registry: ModelRegistry | None = None):
        self.registry = registry
        # name -> {"failures": int, "cooldown_until": float}
        self._state: dict = {}

    def bind(self, registry: ModelRegistry) -> None:
        self.registry = registry

    def record_success(self, name: str) -> None:
        self._state.pop(name, None)
        if self.registry:
            self.registry.mark_healthy(name)

    def record_failure(self, name: str) -> None:
        entry = self._state.setdefault(name, {"failures": 0, "cooldown_until": 0.0})
        entry["failures"] += 1
        if entry["failures"] >= AI_HEALTH_FAILURE_LIMIT:
            entry["cooldown_until"] = time.time() + AI_HEALTH_COOLDOWN_SECONDS
            entry["failures"] = 0
            if self.registry:
                self.registry.mark_unhealthy(name)

    def is_usable(self, name: str) -> bool:
        entry = self._state.get(name)
        if entry and entry["cooldown_until"] > time.time():
            return False
        return True


# Single module-level health tracker, bound to the registry at startup.
health = ModelHealth()

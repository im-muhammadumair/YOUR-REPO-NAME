"""In-memory cache for safe, reusable grounded answers.

Only *general* (non-user-specific) policy answers are cached - e.g. "what is the
annual leave policy?". Personal answers ("what is MY balance?") must never be
cached because they are private and employee-specific; the caller signals this by
setting `personal=True` so the cache entry is skipped.

The cache key includes a fingerprint of the enabled document set and their
expected chunk counts, so cache entries are invalidated automatically whenever
documents are enabled/disabled or re-indexed (i.e. the retrieved context would
change). Because ChromaDB vectors are keyed by document, flipping a document
changes its membership and thus the fingerprint.
"""
import time
import hashlib
import json
import threading

from config import AI_CACHE_TTL_SECONDS

_lock = threading.Lock()
_store: dict = {}   # key -> {"answer","sources","grounded","expires"}


def _fingerprint(enabled_documents) -> str:
    """A stable fingerpring of the enabled document set.

    Takes: enabled_documents - dict of document_id -> info.
    Returns: a short hex fingerprint that changes when the set changes.
    """
    doc_ids = sorted(enabled_documents.keys()) if enabled_documents else []
    payload = json.dumps(doc_ids, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _key(question: str, fingerprint: str) -> str:
    q = question.strip().lower()
    return hashlib.sha256(f"{q}|{fingerprint}".encode("utf-8")).hexdigest()


def get(question: str, enabled_documents) -> dict | None:
    """Return a cached answer if a fresh, matching one exists."""
    fprint = _fingerprint(enabled_documents)
    key = _key(question, fprint)
    now = time.time()
    with _lock:
        entry = _store.get(key)
        if not entry:
            return None
        if entry["expires"] < now:
            _store.pop(key, None)
            return None
        return {
            "answer": entry["answer"],
            "sources": entry["sources"],
            "grounded": entry["grounded"],
            "cached": True,
        }


def put(question: str, enabled_documents, answer: str, sources, grounded: bool,
        personal: bool = False) -> None:
    """Store an answer in the cache if it is safe (non-personal) and reusable."""
    if personal:
        return
    if not answer:
        return
    fprint = _fingerprint(enabled_documents)
    key = _key(question, fprint)
    with _lock:
        _store[key] = {
            "answer": answer,
            "sources": sources,
            "grounded": grounded,
            "expires": time.time() + AI_CACHE_TTL_SECONDS,
        }


def clear() -> None:
    """Drop all cached entries (e.g. when an admin changes the index)."""
    with _lock:
        _store.clear()

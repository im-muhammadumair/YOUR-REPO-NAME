"""Multi-document hybrid retrieval with RRF fusion.

Searches the *entire* enabled knowledge base (never a single PDF), combines
BM25 lexical and ChromaDB vector signals using Reciprocal Rank Fusion, applies
metadata-aware boosting, expands matched chunks with their neighbours, and
selects a diverse, high-confidence candidate set for the reranker.

Pipeline
────────
    query
      → BM25 index (all enabled chunks)        ┐
      → Vector search (ChromaDB, all enabled)  ┤ parallel via ThreadPoolExecutor
      → BM25 query-variant lists (numeric/    ┤ cheap lexical rewrites
        contraction spellings)                ┘
      → RRF fusion of ranked lists
      → Metadata boosting (when user names a document)
      → Exhaustive rescue (widen pool for LIST / SUMMARY intents)
      → Neighbour expansion (±N chunk_index around matched chunks)
      → Diversity selection (avoid many chunks from same section)
      → Score-augmented candidate list → reranker
"""
from __future__ import annotations

import logging
import re
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

from rag.bm25 import BM25Index, load_chunks_for
from rag.config import RETRIEVAL_KNOBS, RAG_SCORE_THRESHOLD
from rag.embeddings import embed_query
from rag.ingestion import chroma_lock, collection
from rag.prompts import INTENT_LIST, INTENT_SUMMARY
from rag.query_router import RetrievalPlan

_log = logging.getLogger("rag.retriever")

# Shared thread pool for parallel retrieval (reused across requests).
_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="retriever")


# ── BM25 index lifecycle ───────────────────────────────────────────────────
# The BM25 index is rebuilt per-request from the enabled corpus. The corpus is
# small (hundreds of chunks), so a full rebuild is ~1-5 ms and avoids stale
# state across requests.

def _build_bm25_index(enabled_ids: set[str]) -> BM25Index | None:
    """Build a BM25 index over all enabled chunks.

    Returns None when the corpus is empty (caller handles this gracefully).
    """
    chunks = load_chunks_for(list(enabled_ids))
    if not chunks:
        return None
    return BM25Index(chunks)


# ── Vector search ───────────────────────────────────────────────────────────

def _vector_search(
    query: str,
    enabled_ids: set[str],
    top_k: int,
) -> list[dict]:
    """Run a ChromaDB vector search across all enabled documents.

    Returns a list of chunk dicts with ``similarity`` scores (1 - distance).
    """
    if not enabled_ids:
        return []

    query_embedding = embed_query(query)
    id_list = list(enabled_ids)

    if len(id_list) == 1:
        where_filter = {"document_id": id_list[0]}
    else:
        where_filter = {"$or": [{"document_id": d} for d in id_list]}

    with chroma_lock():
        result = collection().query(
            query_embeddings=[query_embedding],
            n_results=min(top_k, len(id_list) * 20),  # safety cap
            where=where_filter,
            include=["documents", "metadatas", "distances"],
        )

    records = []
    for i, distance in enumerate(result["distances"][0]):
        meta = result["metadatas"][0][i]
        similarity = 1.0 - distance
        if similarity < RAG_SCORE_THRESHOLD:
            continue
        records.append({
            "document_id":   meta.get("document_id"),
            "document_name": meta.get("document_name"),
            "category":      meta.get("category"),
            "source_file":   meta.get("source_file"),
            "page":          meta.get("page"),
            "chunk_index":   meta.get("chunk_index"),
            "heading":       meta.get("heading") or "",
            "section":       meta.get("section") or "",
            "text":          result["documents"][0][i],
            "distance":      distance,
            "similarity":    similarity,
        })

    return records


# ── BM25 search ─────────────────────────────────────────────────────────────

def _bm25_search(
    query: str,
    bm25_index: BM25Index,
    top_k: int,
) -> list[dict]:
    """Run a BM25 search and normalise the result into the same shape as vector
    results so RRF fusion can work on a single structure.

    BM25 scores are stored as ``bm25_score``; ``similarity`` is set to 0.0
    so the two paths don't confuse each other.
    """
    results = bm25_index.search(query, top_k=top_k)
    for r in results:
        # Normalise to shared schema
        r.setdefault("similarity", 0.0)
        r.setdefault("document_id", r.get("meta", {}).get("document_id"))
        r.setdefault("document_name", r.get("meta", {}).get("document_name"))
        r.setdefault("category", r.get("meta", {}).get("category"))
        r.setdefault("source_file", r.get("meta", {}).get("source_file"))
        r.setdefault("page", r.get("meta", {}).get("page"))
        r.setdefault("chunk_index", r.get("meta", {}).get("chunk_index"))
        r.setdefault("heading", r.get("meta", {}).get("heading", ""))
        r.setdefault("section", r.get("meta", {}).get("section", ""))
    return results


# ── Query-variant expansion ─────────────────────────────────────────────────
# Cheap lexical rewrites of the user's query (numbers spelled ↔ digits,
# contractions expanded). Each variant is run through BM25 and its ranked list
# is folded into the RRF fusion with a reduced weight, boosting recall when the
# document spells things differently from the user ("0g" vs "zero grams",
# "grade 17" vs "grade seventeen").

_NUMBER_WORDS = {
    0: "zero", 1: "one", 2: "two", 3: "three", 4: "four", 5: "five",
    6: "six", 7: "seven", 8: "eight", 9: "nine", 10: "ten", 11: "eleven",
    12: "twelve", 13: "thirteen", 14: "fourteen", 15: "fifteen", 16: "sixteen",
    17: "seventeen", 18: "eighteen", 19: "nineteen", 20: "twenty",
    30: "thirty", 40: "forty", 50: "fifty", 60: "sixty", 70: "seventy",
    80: "eighty", 90: "ninety", 100: "hundred",
}
_WORD_TO_NUMBER = {w: str(n) for n, w in _NUMBER_WORDS.items()}
_WORD_NUMBER_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(w) for w in _WORD_TO_NUMBER) + r")\b", re.I,
)

_CONTRACTION_MAP = {
    "can't": "cannot", "won't": "will not", "don't": "do not",
    "doesn't": "does not", "didn't": "did not", "isn't": "is not",
    "aren't": "are not", "i'm": "i am", "it's": "it is",
    "you're": "you are", "that's": "that is",
}

_VARIANT_WEIGHT_PENALTY = 0.5  # variant BM25 lists carry half the main weight
_MAX_VARIANTS = 3


def _digits_to_words(query: str) -> str:
    def repl(match):
        n = int(match.group(0))
        return _NUMBER_WORDS.get(n, match.group(0))
    return re.sub(r"\d+", repl, query)


def _words_to_digits(query: str) -> str:
    def repl(match):
        return _WORD_TO_NUMBER[match.group(0).lower()]
    return _WORD_NUMBER_RE.sub(repl, query)


def _expand_contractions(query: str) -> str:
    out = query
    for source, target in _CONTRACTION_MAP.items():
        out = re.sub(r"\b" + source + r"\b", target, out, flags=re.I)
    return out


def _query_variants(question: str) -> list[str]:
    """Return up to ``_MAX_VARIANTS`` cheap lexical variants of a question."""
    q = question.strip()
    seen = {q.lower()}
    variants: list[str] = []

    for candidate in (
        _digits_to_words(q),
        _words_to_digits(q),
        _expand_contractions(q),
    ):
        candidate = candidate.strip()
        low = candidate.lower()
        if not low or low in seen:
            continue
        seen.add(low)
        variants.append(candidate)
        if len(variants) >= _MAX_VARIANTS:
            break

    return variants


# ── RRF fusion ──────────────────────────────────────────────────────────────

def _rrf_fuse(
    ranked_lists: list[list[dict]],
    weights: list[float],
    k: float = 60.0,
) -> list[dict]:
    """Fuse multiple ranked lists using weighted Reciprocal Rank Fusion.

    Each ranked list is a list of chunk dicts sorted by relevance (best first).
    ``weights`` must have the same length as ``ranked_lists`` and each weight
    is the importance of that retrieval path.

    Returns: a single fused list sorted by descending RRF score, with each
    chunk carrying the max ``bm25_score`` and max ``similarity`` seen across
    lists.
    """
    # Accumulate RRF scores per chunk key
    rrf_scores: dict[tuple, float] = defaultdict(float)
    # Keep one canonical chunk dict per key (the one with the highest raw score)
    canonical: dict[tuple, dict] = {}

    for ranked_list, weight in zip(ranked_lists, weights):
        for rank, chunk in enumerate(ranked_list, 1):
            key = (chunk.get("document_id"), chunk.get("chunk_index"))
            rrf_scores[key] += weight * (1.0 / (k + rank))

            # Keep the chunk dict with the highest similarity or bm25_score
            existing = canonical.get(key)
            if existing is None:
                canonical[key] = chunk
            else:
                # Prefer the one with more information
                if chunk.get("similarity", 0) > existing.get("similarity", 0):
                    canonical[key] = chunk
                elif chunk.get("bm25_score", 0) > existing.get("bm25_score", 0):
                    canonical[key] = chunk

    # Sort by RRF score descending
    sorted_keys = sorted(rrf_scores.keys(), key=lambda k: -rrf_scores[k])

    results = []
    for key in sorted_keys:
        chunk = dict(canonical[key])
        chunk["rrf_score"] = round(rrf_scores[key], 6)
        results.append(chunk)

    return results


# ── Metadata boosting ───────────────────────────────────────────────────────

def _apply_metadata_boost(
    candidates: list[dict],
    metadata_filter: dict | None,
    boost: float = 0.15,
) -> list[dict]:
    """Boost candidates that match the metadata filter.

    Only applied when the user explicitly named a document/category. The boost
    is additive and small — it tilts the ranking without discarding other docs.
    """
    if not metadata_filter:
        return candidates

    filter_key = next(iter(metadata_filter), None)
    filter_val = metadata_filter.get(filter_key, "") if filter_key else ""

    if not filter_val:
        return candidates

    filter_val_lower = filter_val.lower()

    for chunk in candidates:
        match_val = str(chunk.get(filter_key, "")).lower()
        if filter_val_lower in match_val:
            chunk["rrf_score"] = chunk.get("rrf_score", 0) * (1 + boost)

    # Re-sort after boosting
    candidates.sort(key=lambda c: c.get("rrf_score", 0), reverse=True)
    return candidates


# ── Neighbour expansion ─────────────────────────────────────────────────────

def _expand_neighbours(
    candidates: list[dict],
    enabled_ids: set[str],
    window: int,
) -> list[dict]:
    """Expand the candidate set with neighbouring chunks from the same document.

    For each matched chunk, pull ``±window`` chunks by chunk_index from the
    same document_id.  This recovers surrounding context (the "parent" in a
    parent-child architecture) without returning an entire PDF.

    Neighbours are appended *after* the originally matched chunks so they rank
    lower unless the reranker promotes them.
    """
    if window <= 0 or not candidates:
        return candidates

    # Build a map of all chunks by (document_id → chunk_index → chunk)
    all_chunks = load_chunks_for(list(enabled_ids))
    doc_index: dict[str, dict[int, dict]] = defaultdict(dict)
    for c in all_chunks:
        doc_id = c.get("meta", {}).get("document_id")
        ci = c.get("meta", {}).get("chunk_index")
        if doc_id is not None and ci is not None:
            doc_index[doc_id][ci] = {
                "document_id":   doc_id,
                "document_name": c.get("meta", {}).get("document_name"),
                "category":      c.get("meta", {}).get("category"),
                "source_file":   c.get("meta", {}).get("source_file"),
                "page":          c.get("meta", {}).get("page"),
                "chunk_index":   ci,
                "text":          c.get("text", ""),
                "similarity":    0.0,
                "bm25_score":    0.0,
                "rrf_score":     0.0,
                "is_neighbor":   True,
            }

    # Collect keys already in the candidate set
    existing_keys: set[tuple] = {
        (c.get("document_id"), c.get("chunk_index")) for c in candidates
    }

    neighbours = []
    for cand in candidates:
        doc_id = cand.get("document_id")
        ci = cand.get("chunk_index")
        if doc_id is None or ci is None:
            continue

        for offset in range(-window, window + 1):
            if offset == 0:
                continue
            neighbour_ci = ci + offset
            key = (doc_id, neighbour_ci)
            if key in existing_keys:
                continue
            existing_keys.add(key)

            neighbour = doc_index.get(doc_id, {}).get(neighbour_ci)
            if neighbour:
                neighbours.append(neighbour)

    return candidates + neighbours


# ── Diversity selection ─────────────────────────────────────────────────────

def _diversity_select(
    candidates: list[dict],
    max_count: int,
) -> list[dict]:
    """Select the top candidates while enforcing diversity across documents.

    Greedily alternates between documents so that evidence from multiple
    sources is preferred over many chunks from the same section.
    """
    if len(candidates) <= max_count:
        return candidates

    by_doc: dict[str, list[dict]] = defaultdict(list)
    for c in candidates:
        doc_id = c.get("document_id") or "_unknown"
        by_doc[doc_id].append(c)

    selected: list[dict] = []
    doc_iters = {doc_id: iter(chunks) for doc_id, chunks in by_doc.items()}

    while len(selected) < max_count:
        added_any = False
        for doc_id in list(doc_iters.keys()):
            if len(selected) >= max_count:
                break
            try:
                selected.append(next(doc_iters[doc_id]))
                added_any = True
            except StopIteration:
                del doc_iters[doc_id]
        if not added_any:
            break

    return selected


# ── Confidence signal ───────────────────────────────────────────────────────

def _retrieval_confidence(
    candidates: list[dict],
    bm25_count: int,
    vector_count: int,
) -> float:
    """Estimate retrieval quality from multiple signals.

    Returns a float in [0, 1] — higher when the retrieval paths agree and
    there are several strong candidates.
    """
    if not candidates:
        return 0.0

    # RRF score strength
    avg_rrf = sum(c.get("rrf_score", 0) for c in candidates[:10]) / min(len(candidates), 10)

    # Path agreement: both BM25 and vector found results
    agreement = 1.0 if (bm25_count > 0 and vector_count > 0) else 0.5

    # Candidate count strength
    count_strength = min(len(candidates) / 10.0, 1.0)

    # Cross-document diversity
    doc_ids = {c.get("document_id") for c in candidates if c.get("document_id")}
    diversity = min(len(doc_ids) / 2.0, 1.0)

    return round(
        0.3 * min(avg_rrf * 10, 1.0)   # normalise avg_rrf roughly
        + 0.25 * agreement
        + 0.25 * count_strength
        + 0.2 * diversity,
        3,
    )


# ── Main retrieval function ─────────────────────────────────────────────────

def retrieve(
    question: str,
    enabled_document_ids: set[str],
    plan: RetrievalPlan,
) -> tuple[list[dict], float]:
    """Run the full hybrid retrieval pipeline and return candidates + confidence.

    Parameters
    ----------
    question : str
        The (possibly rewritten) search query.
    enabled_document_ids : set[str]
        The set of document IDs the admin has enabled for AI chat.
    plan : RetrievalPlan
        The retrieval plan produced by query_router.plan_retrieval().

    Returns
    -------
    (candidates, confidence)
        candidates: list of chunk dicts ready for the reranker.
        confidence: retrieval quality signal in [0, 1].
    """
    if not enabled_document_ids:
        return [], 0.0

    # ── Stage 1: Build BM25 index from enabled corpus ────────────────────
    bm25_index = _build_bm25_index(enabled_document_ids)

    # ── Stage 2: Run both retrieval paths in parallel ─────────────────────
    bm25_future = None
    vector_future = None

    if bm25_index and bm25_index.N > 0:
        bm25_future = _pool.submit(_bm25_search, question, bm25_index, plan.bm25_k)

    vector_future = _pool.submit(_vector_search, question, enabled_document_ids, plan.vector_k)

    bm25_results = bm25_future.result() if bm25_future else []
    vector_results = vector_future.result()

    # ── Stage 2b: BM25 query-variant lists (lexical recall boost) ────────
    variant_results = []
    if bm25_index and bm25_index.N > 0:
        for variant in _query_variants(question):
            variant_list = _bm25_search(variant, bm25_index, plan.bm25_k)
            if variant_list:
                variant_results.append(variant_list)

    # ── Stage 3: RRF fusion ──────────────────────────────────────────────
    ranked_lists = []
    weights = []

    if bm25_results:
        ranked_lists.append(bm25_results)
        weights.append(plan.bm25_weight)

    # Variant lists carry half the main BM25 weight so the original query stays
    # dominant while alternate spellings can still surface missing chunks.
    for variant_list in variant_results:
        ranked_lists.append(variant_list)
        weights.append(plan.bm25_weight * _VARIANT_WEIGHT_PENALTY)

    if vector_results:
        ranked_lists.append(vector_results)
        weights.append(plan.vector_weight)

    if not ranked_lists:
        return [], 0.0

    # Normalise weights to sum to 1.0
    total_weight = sum(weights)
    if total_weight > 0:
        weights = [w / total_weight for w in weights]

    fused = _rrf_fuse(ranked_lists, weights, k=plan.candidate_k)

    # ── Stage 4: Metadata boosting ───────────────────────────────────────
    fused = _apply_metadata_boost(fused, plan.metadata_filter)

    # ── Stage 5: Trim to candidate_k ─────────────────────────────────────
    candidates = fused[:plan.candidate_k]

    # Exhaustive rescue: for LIST / SUMMARY questions with thin evidence,
    # widen the pool so the generator has enough chunks for a complete answer.
    if (
        plan.intent in (INTENT_LIST, INTENT_SUMMARY)
        and len(candidates) < max(plan.candidate_k // 2, 10)
    ):
        candidates = fused[: plan.candidate_k * 2]

    # ── Stage 6: Neighbour expansion ─────────────────────────────────────
    candidates = _expand_neighbours(
        candidates, enabled_document_ids, plan.neighbor_window,
    )

    # ── Stage 7: Diversity selection (down to rerank_k) ──────────────────
    candidates = _diversity_select(candidates, plan.rerank_k)

    # ── Stage 8: Confidence ──────────────────────────────────────────────
    confidence = _retrieval_confidence(
        candidates, len(bm25_results), len(vector_results),
    )

    _log.info(
        "retrieved %d candidates (bm25=%d, vector=%d, fused=%d, "
        "confidence=%.3f, profile=%s)",
        len(candidates), len(bm25_results), len(vector_results),
        len(fused), confidence, plan.profile,
    )

    return candidates, confidence

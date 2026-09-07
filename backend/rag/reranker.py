"""Local heuristic reranker — fast, zero-API-call relevance scoring.

Replaces the Gemini-based reranker with a deterministic scorer that works
entirely in-process. This keeps the reranking step fast and cheap; Gemini is
reserved for generation only.

Scoring combines:
  1. Lexical overlap (Jaccard-like token overlap between query and chunk).
  2. Bigram overlap (word-level pairs shared by query and chunk).
  3. Exact-term bonus (query tokens that appear verbatim in the chunk).
  4. Numeric boost (chunk contains a number/amount named in the query).
  5. Document-name bonus (chunk from a document whose name is mentioned in the
     query).
  6. BM25 score (when available from the BM25 retrieval path).
  7. Vector similarity (when available from the ChromaDB retrieval path).

After scoring, duplicates are removed, the top-N candidates are selected, and
a confidence signal is derived from the surviving evidence set.
"""
from __future__ import annotations

import re

from rag.bm25 import tokenize


# ── Scoring weights (tuned for the HR corpus) ───────────────────────────────

W_LEXICAL    = 0.10   # unigram token overlap between query and chunk
W_EXACT      = 0.20   # exact query tokens found in chunk
W_DOC_NAME   = 0.07   # document name mentioned in query
W_HEADING    = 0.08   # query tokens appear in chunk's heading/section text
W_NUMERIC    = 0.05   # chunk contains a number/amount named in the query
W_BIGRAM     = 0.10   # shared word bigrams (phrase-level evidence)
W_BM25       = 0.25   # normalised BM25 score
W_SIMILARITY = 0.15   # normalised vector similarity

# Spelled-out numbers so numeric boosts catch "seventeen" and "17" alike.
_SPELLED_NUMBERS = {
    "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4",
    "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9",
    "ten": "10", "eleven": "11", "twelve": "12", "thirteen": "13",
    "fourteen": "14", "fifteen": "15", "sixteen": "16", "seventeen": "17",
    "eighteen": "18", "nineteen": "19", "twenty": "20",
    "thirty": "30", "forty": "40", "fifty": "50", "sixty": "60",
    "seventy": "70", "eighty": "80", "ninety": "90", "hundred": "100",
}
# Longest-first so "seventeen" wins over "seven"; \b guards against
# substring-only coincidences like "one" inside "someone".
_SPELLED_RE = re.compile(
    r"\b(?:" + "|".join(sorted(_SPELLED_NUMBERS, key=len, reverse=True)) + r")\b", re.I,
)
_NUMBER_RE = re.compile(r"\d+")


# ── Deduplication ───────────────────────────────────────────────────────────

def _distinct(records: list[dict]) -> list[dict]:
    """Remove duplicate chunks while preserving order."""
    seen: set[tuple] = set()
    result = []
    for record in records:
        key = (record.get("document_id"), record.get("chunk_index"))
        if key in seen:
            continue
        seen.add(key)
        result.append(record)
    return result


# ── Heuristic scoring ───────────────────────────────────────────────────────

def _token_overlap(query_tokens: list[str], chunk_tokens: list[str]) -> float:
    """Jaccard-like overlap: |intersection| / |union|."""
    if not query_tokens or not chunk_tokens:
        return 0.0
    q_set = set(query_tokens)
    c_set = set(chunk_tokens)
    intersection = q_set & c_set
    union = q_set | c_set
    return len(intersection) / len(union) if union else 0.0


def _exact_term_bonus(query_tokens: list[str], chunk_text: str) -> float:
    """Fraction of query tokens found verbatim in the chunk (case-insensitive)."""
    if not query_tokens:
        return 0.0
    low = chunk_text.lower()
    hits = sum(1 for t in query_tokens if t in low)
    return hits / len(query_tokens)


def _bigram_overlap(query_tokens: list[str], chunk_tokens: list[str]) -> float:
    """Jaccard overlap of word bigrams — captures phrase-level evidence."""
    if len(query_tokens) < 2 or len(chunk_tokens) < 2:
        return 0.0
    q_bigrams = set(zip(query_tokens, query_tokens[1:]))
    c_bigrams = set(zip(chunk_tokens, chunk_tokens[1:]))
    union = q_bigrams | c_bigrams
    if not union:
        return 0.0
    return len(q_bigrams & c_bigrams) / len(union)


def _text_numbers(text: str) -> set[str]:
    """All numeric amounts in a text as digit strings (spelled words included)."""
    numbers = {m.group(0) for m in _NUMBER_RE.finditer(text)}
    for match in _SPELLED_RE.finditer(text):
        numbers.add(_SPELLED_NUMBERS[match.group(0).lower()])
    return numbers


def _numeric_boost(query: str, chunk_text: str) -> float:
    """Reward chunks containing a number/amount the query explicitly names.

    Digits and spelled-out numbers normalise to the same token, so "grade 17"
    matches a chunk saying "Grade 17" *and* one saying "grade seventeen".
    """
    query_numbers = _text_numbers(query)
    if not query_numbers:
        return 0.0
    chunk_numbers = _text_numbers(chunk_text)
    if not chunk_numbers:
        return 0.0
    hits = len(query_numbers & chunk_numbers)
    return min(hits / len(query_numbers), 1.0)


def _doc_name_bonus(query: str, chunk: dict) -> float:
    """Bonus when the query mentions the chunk's document name."""
    doc_name = (chunk.get("document_name") or "").lower()
    if not doc_name:
        return 0.0
    # Check if any significant word from the doc name appears in the query.
    name_words = [w for w in doc_name.split() if len(w) > 3]
    if not name_words:
        return 0.0
    query_low = query.lower()
    hits = sum(1 for w in name_words if w in query_low)
    return min(hits / len(name_words), 1.0)


def _heading_bonus(query: str, chunk: dict) -> float:
    """Bonus when query tokens appear in the chunk's heading/section text.

    Mirrors the reference reranker's +0.15 heading boost: a chunk whose heading
    ("Dairy Products", "Meat, Poultry, Eggs") mentions a query word is more
    relevant than a body chunk that happens to share a common term.
    """
    head = f"{chunk.get('section') or ''} {chunk.get('heading') or ''}".lower()
    if not head.strip():
        return 0.0
    query_tokens = tokenize(query)
    if not query_tokens:
        return 0.0
    hits = sum(1 for t in query_tokens if t in head)
    return min(hits / len(query_tokens), 1.0)


def _normalise(value: float, max_val: float) -> float:
    """Clamp and normalise a score to [0, 1]."""
    if max_val <= 0:
        return 0.0
    return max(0.0, min(1.0, value / max_val))


def _compute_relevance(
    query: str,
    query_tokens: list[str],
    chunk: dict,
    bm25_norm: float,
) -> float:
    """Single weighted relevance score for a chunk (all signals agree)."""
    chunk_text = chunk.get("text", "")
    chunk_tokens = tokenize(chunk_text)

    return round(
        W_LEXICAL     * _token_overlap(query_tokens, chunk_tokens)
        + W_EXACT     * _exact_term_bonus(query_tokens, chunk_text)
        + W_DOC_NAME  * _doc_name_bonus(query, chunk)
        + W_HEADING   * _heading_bonus(query, chunk)
        + W_NUMERIC   * _numeric_boost(query, chunk_text)
        + W_BIGRAM    * _bigram_overlap(query_tokens, chunk_tokens)
        + W_BM25      * bm25_norm
        + W_SIMILARITY * chunk.get("similarity", 0.0),
        6,
    )


def score_chunk(query: str, chunk: dict) -> float:
    """Score a single chunk's relevance to the query, context-free.

    BM25 raw scores are mapped to [0, 1) with ``x / (x + 1)`` so a standalone
    call is meaningful without a batch to normalise against.

    Returns a float where higher = more relevant.
    """
    query_tokens = tokenize(query)
    bm25_raw = chunk.get("bm25_score", 0.0)
    bm25_norm = bm25_raw / (bm25_raw + 1.0) if bm25_raw > 0 else 0.0
    return _compute_relevance(query, query_tokens, chunk, bm25_norm)


def _normalise_and_score(query: str, candidates: list[dict]) -> list[dict]:
    """Score all candidates, normalising BM25 across the batch."""
    if not candidates:
        return []

    # Find BM25 max for normalisation
    bm25_scores = [c.get("bm25_score", 0.0) for c in candidates]
    bm25_max = max(bm25_scores) if bm25_scores else 1.0

    query_tokens = tokenize(query)
    for chunk in candidates:
        bm25_norm = _normalise(chunk.get("bm25_score", 0.0), bm25_max)
        chunk["score"] = _compute_relevance(query, query_tokens, chunk, bm25_norm)

    # Sort by score descending
    candidates.sort(key=lambda c: c["score"], reverse=True)
    return candidates


# ── Confidence signal ───────────────────────────────────────────────────────

def _confidence(chunks: list[dict], final_k: int) -> float:
    """Derive a confidence signal from the selected chunks.

    Higher when there are several strong, agreeing chunks from multiple
    documents; lower when there is a single weak or sparse hit.
    """
    if not chunks:
        return 0.0
    avg_score = sum(c.get("score", 0.0) for c in chunks) / len(chunks)
    coverage  = min(len(chunks) / float(final_k), 1.0)

    # Cross-document bonus: reward evidence from multiple sources
    doc_ids = {c.get("document_id") for c in chunks if c.get("document_id")}
    diversity = min(len(doc_ids) / 2.0, 1.0)  # 2+ docs = full bonus

    return round(0.5 * avg_score + 0.25 * coverage + 0.25 * diversity, 3)


# ── Context formatting ──────────────────────────────────────────────────────

def format_context(chunks: list[dict]) -> str:
    """Turn selected chunks into a compact, cited context block for Gemini."""
    sections = []
    for i, chunk in enumerate(chunks, 1):
        source = chunk.get("document_name") or chunk.get("document_id") or "Unknown"
        page = chunk.get("page")
        location = f"{source}, page {page}" if page else source
        sections.append(f"[Excerpt {i} - {location}]\n{chunk['text']}")
    return "\n\n".join(sections)


# ── Main entry point ────────────────────────────────────────────────────────

def select_and_compress(
    question: str,
    candidates: list[dict],
    final_count: int | None = None,
    rerank_k: int | None = None,
) -> tuple[list[dict], float, str]:
    """Deduplicate, rerank and compress candidate chunks.

    Parameters
    ----------
    question : str
        The user's question.
    candidates : list[dict]
        Raw chunks from the retriever (may include bm25_score and/or similarity).
    final_count : int | None
        How many chunks to keep (default RAG_FINAL_CONTEXT_CHUNKS).
    rerank_k : int | None
        How many candidates to score before trimming to final_count.

    Returns
    -------
    (final_chunks, confidence, context)
    """
    from rag.config import RAG_FINAL_CONTEXT_CHUNKS

    final_count = final_count or RAG_FINAL_CONTEXT_CHUNKS
    rerank_k = rerank_k or final_count * 4  # score 4x what we keep

    # Step 1: deduplicate
    distinct = _distinct(candidates)

    # Step 2: score all candidates
    scored = _normalise_and_score(question, distinct)

    # Step 3: take top rerank_k for final selection
    top_candidates = scored[:rerank_k]

    # Step 4: trim to final_count
    final_chunks = top_candidates[:final_count]

    # Step 5: build context string
    context = format_context(final_chunks)

    # Step 6: confidence
    confidence = _confidence(final_chunks, final_count)

    return final_chunks, confidence, context

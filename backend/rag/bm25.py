"""Lightweight BM25 lexical retrieval engine for the HR knowledge base.

A pure-Python Okapi BM25 implementation that builds an in-memory inverted
index over all enabled chunks stored in ChromaDB. The corpus is small (hundreds
of chunks at most), so a full in-memory index is both fast and practical; there
is no external dependency.

Key design choices:
  - Corpus is loaded from ChromaDB ``collection().get()``, so every vector
    already stored there is also BM25-accessible.
  - The index is immutable per query; callers load once per retrieval cycle.
  - ``tokenize`` is intentionally lightweight (whitespace + lowercase) so rare
    HR identifiers (Grade 17, Basic Pay Scale) are matched verbatim rather than
    being stemmed away.
  - An exact-match bonus rewards chunks that contain the whole query phrase
    verbatim (+2.0) or its individual significant tokens (+0.5 each) — the
    classic trick for precise policy lookups ("grade 17", "page 42"), which
    raw BM25's term-frequency IDF can underweight.

Typical usage::

    from rag.bm25 import BM25Index
    from rag.ingestion import collection

    all_chunks = _load_chunks_for(document_ids)
    idx = BM25Index(all_chunks)
    results = idx.search("Basic Pay Scale", top_k=20)
"""

import math
import re
from collections import Counter
from typing import Sequence

# ── Okapi BM25 defaults ────────────────────────────────────────────────────
K1 = 1.5   # Term frequency saturation parameter.
B  = 0.75  # Length-normalisation parameter (0 = no length normalisation).

# ── Exact-match bonus ──────────────────────────────────────────────────────
# Rewards chunks that literally contain the user's query — verbatim phrase
# (-punctuation) or significant individual tokens. Boosts precision for exact
# policy lookups that BM25's length-normalised term frequency would dilute.
BONUS_EXACT_PHRASE = 2.0   # whole query string appears in the chunk
BONUS_TOKEN        = 0.5   # per significant (>3 char) query token found


# ── Tokenisation ────────────────────────────────────────────────────────────

# Split on non-alphanumeric characters; keep hyphens inside words.
_WORD_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9\-]*[A-Za-z0-9]|[A-Za-z0-9]", re.UNICODE)


def tokenize(text: str) -> list[str]:
    """Lowercase whitespace- and punctuation-split tokenisation.

    Keeps compound HR terms like ``Grade-17`` or ``Basic-Pay-Scale`` intact
    when hyphens are surrounded by alphanumerics.  Returns a flat list of
    lowercased tokens.
    """
    return [tok.lower() for tok in _WORD_RE.findall(text)]


def exact_match_bonus(query_phrase: str, chunk_text: str) -> float:
    """Reward chunks matching the query verbatim.

    ``query_phrase`` should be the whitespace-joined, lowercased query tokens
    (i.e. punctuation-robust). Returns +2.0 when the full phrase appears in the
    chunk, plus +0.5 for every significant (>3 char) query token also present.
    """
    low = chunk_text.lower()
    bonus = 0.0
    if query_phrase and query_phrase in low:
        bonus += BONUS_EXACT_PHRASE
    for tok in query_phrase.split():
        if len(tok) > 3 and tok in low:
            bonus += BONUS_TOKEN
    return bonus


# ── Chunk loading helper ────────────────────────────────────────────────────

def load_chunks_for(document_ids: Sequence[str]) -> list[dict]:
    """Fetch all chunk records from ChromaDB for the given document IDs.

    Each chunk dict contains the keys ``id``, ``text`` and ``metadata`` (which
    includes ``document_id``, ``document_name``, ``page``, ``chunk_index``, etc.
    exactly as stored during ingestion).

    If ``document_ids`` is empty, chunks from *all* collections are returned
    (used by the global-search path).

    Returns: a list of chunk dicts, each with keys ``id``, ``text``, ``meta``.
    """
    from rag.ingestion import chroma_lock, collection

    col = collection()

    if not document_ids:
        with chroma_lock():
            result = col.get(include=["documents", "metadatas"])
    else:
        id_list = list(document_ids)
        where = (
            {"document_id": id_list[0]}
            if len(id_list) == 1
            else {"$or": [{"document_id": d} for d in id_list]}
        )
        with chroma_lock():
            result = col.get(where=where, include=["documents", "metadatas"])

    ids      = result.get("ids") or []
    docs     = result.get("documents") or []
    metas    = result.get("metadatas") or []

    chunks = []
    for i, chunk_id in enumerate(ids):
        chunks.append({
            "id":   chunk_id,
            "text": docs[i] if i < len(docs) else "",
            "meta": metas[i] if i < len(metas) else {},
        })

    return chunks


# ── BM25 index ──────────────────────────────────────────────────────────────

class BM25Index:
    """An in-memory Okapi BM25 index over a set of chunk records.

    Construction tokenises every chunk and builds a term-frequency table and a
    reverse index (term → set of doc indices) so scoring is fast at query time.

    Parameters
    ----------
    chunks : list[dict]
        Each dict must have ``"text"`` and ``"meta"`` keys (as returned by
        ``load_chunks_for``).
    k1 : float
        BM25 term-frequency saturation parameter.
    b  : float
        BM25 length normalisation parameter.
    """

    def __init__(self, chunks: list[dict], k1: float = K1, b: float = B):
        self.k1 = k1
        self.b  = b
        self.N  = len(chunks)
        self.chunks = chunks

        # Per-doc structures
        self.doc_lengths: list[int] = []               # number of tokens per doc
        self.avg_doc_length: float = 1.0                # avoid division by zero
        self.doc_term_freqs: list[Counter] = []         # Counter(term → freq)

        # Global structures
        self.df: Counter = Counter()                     # doc-frequency per term
        self.postings: dict[str, set[int]] = {}          # term → set of doc idx

        self._build()

    # ── Build ────────────────────────────────────────────────────────────

    def _build(self):
        total_len = 0
        for idx, chunk in enumerate(self.chunks):
            tokens = tokenize(chunk.get("text", ""))
            self.doc_lengths.append(len(tokens))
            total_len += len(tokens)

            tf = Counter(tokens)
            self.doc_term_freqs.append(tf)

            # Update global DF and postings
            unique_terms = tf.keys()
            for term in unique_terms:
                self.df[term] += 1
                if term not in self.postings:
                    self.postings[term] = set()
                self.postings[term].add(idx)

        self.avg_doc_length = (total_len / self.N) if self.N else 1.0

    # ── Scoring ──────────────────────────────────────────────────────────

    def _idf(self, term: str) -> float:
        """Standard Okapi IDF with smoothing to prevent negative scores."""
        n = self.df.get(term, 0)
        return math.log((self.N - n + 0.5) / (n + 0.5) + 1.0)

    def _score_doc(self, query_tokens: list[str], doc_idx: int) -> float:
        """Score a single document against the tokenised query."""
        dl = self.doc_lengths[doc_idx]
        tf = self.doc_term_freqs[doc_idx]
        score = 0.0

        for term in query_tokens:
            term_freq = tf.get(term, 0)
            if term_freq == 0:
                continue
            idf = self._idf(term)
            numerator   = term_freq * (self.k1 + 1)
            denominator = term_freq + self.k1 * (1 - self.b + self.b * dl / self.avg_doc_length)
            score += idf * numerator / denominator

        return score

    # ── Public API ───────────────────────────────────────────────────────

    def search(self, query: str, top_k: int = 20) -> list[dict]:
        """Run a BM25 search and return the top-k matching chunks.

        Returns: a list of chunk dicts, each augmented with a ``bm25_score``
                 key, sorted by descending score. Empty if nothing scored > 0.
        """
        if self.N == 0:
            return []

        query_tokens = tokenize(query)
        if not query_tokens:
            return []

        # Pre-filter: only docs that contain at least one query term.
        candidate_docs: set[int] = set()
        for term in query_tokens:
            candidate_docs |= self.postings.get(term, set())

        if not candidate_docs:
            return []

        # Normalised query phrase for the exact-match bonus (punctuation-free).
        query_phrase = " ".join(query_tokens)

        scored = []
        for doc_idx in candidate_docs:
            s = self._score_doc(query_tokens, doc_idx)
            if s > 0:
                s += exact_match_bonus(query_phrase, self.chunks[doc_idx].get("text", ""))
                scored.append((doc_idx, s))

        scored.sort(key=lambda x: -x[1])

        results = []
        for doc_idx, score in scored[:top_k]:
            chunk = dict(self.chunks[doc_idx])
            chunk["bm25_score"] = round(score, 6)
            results.append(chunk)

        return results

    def has_term(self, term: str) -> bool:
        """Fast existence check — useful for metadata-aware filtering."""
        return term.lower() in self.postings

"""RAG-specific settings and shared helpers.

These values tune how documents are indexed and retrieved. They are mostly
derived from the application-wide config in backend/config.py so the RAG layer
never reads raw environment variables itself - it just imports the resolved
constants.
"""
from config import (
    CHROMA_COLLECTION,
    CHROMA_DIR,
    GEMINI_API_KEY,
    GEMINI_CHAT_MODEL,
    GEMINI_EMBED_MODEL,
    GEMINI_RERANK_MODEL,
    RAG_BM25_K,
    RAG_CANDIDATE_K,
    RAG_EMBEDDING_DIMENSIONS,
    RAG_FINAL_CONTEXT_CHUNKS,
    RAG_NEIGHBOR_WINDOW,
    RAG_RERANK_K,
    RAG_RRF_K,
    RAG_SCORE_THRESHOLD,
    RAG_TOP_K,
    RAG_VECTOR_K,
)

# Wrapped in a dict so the caller can mutate per-query without touching config.
RETRIEVAL_KNOBS = {
    "candidate_k": dict(RAG_CANDIDATE_K),
    "bm25_k": RAG_BM25_K,
    "vector_k": RAG_VECTOR_K,
    "rrf_k": RAG_RRF_K,
    "rerank_k": RAG_RERANK_K,
    "final_context_k": RAG_FINAL_CONTEXT_CHUNKS,
    "neighbor_window": RAG_NEIGHBOR_WINDOW,
}

__all__ = [
    "CHROMA_COLLECTION",
    "CHROMA_DIR",
    "GEMINI_API_KEY",
    "GEMINI_CHAT_MODEL",
    "GEMINI_EMBED_MODEL",
    "GEMINI_RERANK_MODEL",
    "RAG_EMBEDDING_DIMENSIONS",
    "RAG_FINAL_CONTEXT_CHUNKS",
    "RAG_SCORE_THRESHOLD",
    "RAG_TOP_K",
    "RETRIEVAL_KNOBS",
]

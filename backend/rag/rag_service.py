"""RAG orchestration service — planner-driven pipeline with SSE status events.

Coordinates the entire answer pipeline for one user question:

    question
      → normalisation + follow-up resolution              (textutil / query_router)
      → retrieval plan (profile, weights, top-k)          (query_router.plan_retrieval)
      → cache lookup                                      (cache)
      → hybrid retrieval (BM25 + vector + RRF + expand)  (retriever.retrieve)
      → local heuristic rerank                            (reranker.select_and_compress)
      → generation with streaming + failover              (generator.generate_stream)
      → grounded validation + escalation                  (validator)

Every answer is grounded ONLY in the retrieved PDF excerpts. SQLite / structured
employee data is never used as an answer source. If the evidence is insufficient
the service says so honestly; if every model fails it returns a friendly
"please try again" message rather than exposing a technical error.

SSE status events
─────────────────
Callers can pass a ``status_cb(message)`` callable. The service calls it with
user-facing status strings at each pipeline stage so the frontend can display
a live activity bubble. Status events are **never** fake — they correspond to
the actual operation currently executing.
"""
from __future__ import annotations

import logging
from typing import Callable

from rag import cache
from rag import prompts
from rag.query_router import (
    COMPLEX,
    CRITICAL,
    DEEP,
    EXACT,
    is_personal,
    needs_retrieval,
    personal_deferral,
    plan_retrieval,
    RetrievalPlan,
)
from rag.reranker import select_and_compress
from rag.retriever import retrieve

_log = logging.getLogger("rag")

# ── Greeting reply (no document retrieval needed, no policy facts) ───────────
_GREETING_REPLY = (
    "Hello! I can help with questions about the company's HR documents and "
    "policies. Simply ask me about anything in the enabled PDFs, for example "
    "the leave policy or the employee handbook."
)

# ── Friendly error (never leak internal details) ────────────────────────────
_FRIENDLY_ERROR = (
    "I wasn't able to generate an answer right now. "
    "Please try again in a moment."
)

_NO_DOCS_REPLY = (
    "No documents are enabled for AI chat yet. An administrator "
    "must turn on 'Use this PDF for AI Chat' for the relevant "
    "policies before I can answer from them."
)

_NO_EVIDENCE_REPLY = (
    "I could not find enough relevant information in the enabled "
    "documents to answer that reliably. Please try rephrasing your "
    "question or ask about a different topic."
)


# ── Helpers ─────────────────────────────────────────────────────────────────

def _style_for(complexity: str, intent: str | None = None) -> str:
    from rag.prompts import INTENT_ACTION_REQUIRED, INTENT_EMPLOYEE_RESPONSIBILITY, INTENT_PROCEDURE
    if intent in (INTENT_ACTION_REQUIRED, INTENT_EMPLOYEE_RESPONSIBILITY, INTENT_PROCEDURE):
        return "action"
    return {COMPLEX: "detailed", CRITICAL: "detailed"}.get(complexity, "normal")


def _build_sources(chunks: list[dict]) -> list[dict]:
    """Deduplicate chunks by (document_name, page) for the source citation list."""
    from utils.helpers import sign_file_link
    from urllib.parse import quote

    sources = []
    seen: set[tuple] = set()
    for chunk in chunks:
        key = (chunk.get("document_name"), chunk.get("page"))
        if key in seen:
            continue
        seen.add(key)
        source_file = chunk.get("source_file")
        file_url = None
        if source_file:
            token = sign_file_link(source_file)
            file_url = f"/api/documents/file?token={quote(token, safe='')}"
        page = chunk.get("page")
        if file_url and page:
            file_url = f"{file_url}#page={page}"
        sources.append({
            "document_name": chunk.get("document_name") or chunk.get("document_id"),
            "page":          page,
            "source_file":   source_file,
            "file_url":      file_url,
        })
    return sources


def _noop_status(msg: str) -> None:
    """Default no-op status callback."""
    pass


# ── Non-streaming answer (kept for backward compatibility) ──────────────────

def answer_question(question: str, enabled_documents: dict) -> dict:
    """Produce a grounded, PDF-only answer (non-streaming).

    Parameters
    ----------
    question : str
        The user's question.
    enabled_documents : dict
        document_id → {name, category, file} for every enabled doc.

    Returns
    -------
    dict with keys ``answer``, ``sources``, ``grounded``.
    """
    return _answer_question_impl(question, enabled_documents, history=None, status_cb=_noop_status)


# ── Streaming answer (SSE) ─────────────────────────────────────────────────

def answer_question_stream(
    question: str,
    enabled_documents: dict,
    history: list[dict] | None = None,
    status_cb: Callable[[str], None] | None = None,
) -> dict:
    """Produce a grounded, PDF-only answer with SSE status events.

    Parameters
    ----------
    question : str
        The user's question.
    enabled_documents : dict
        document_id → {name, category, file} for every enabled doc.
    history : list[dict] | None
        Conversation history for follow-up resolution.
    status_cb : callable | None
        Called with user-facing status strings at each pipeline stage.

    Returns
    -------
    dict with keys ``answer``, ``sources``, ``grounded``. The answer is
    produced via streaming generation.
    """
    cb = status_cb or _noop_status
    return _answer_question_impl(question, enabled_documents, history=history, status_cb=cb)


# ── Core implementation ─────────────────────────────────────────────────────

def _answer_question_impl(
    question: str,
    enabled_documents: dict,
    history: list[dict] | None,
    status_cb: Callable[[str], None],
) -> dict:
    cb = status_cb

    # ── Cache lookup ──────────────────────────────────────────────────────
    cached = cache.get(question, enabled_documents)
    if cached:
        cb("Found cached answer")
        from rag.tables import normalize_answer_tables
        cached["answer"] = normalize_answer_tables(cached["answer"])
        return cached

    # ── No documents enabled: HR-bot mode with deflection ───────────────
    if not enabled_documents:
        if is_personal(question):
            return {"answer": personal_deferral(), "sources": [], "grounded": False}
        if not needs_retrieval(question):
            return {"answer": _GREETING_REPLY, "sources": [], "grounded": False}
        return {"answer": _NO_DOCS_REPLY, "sources": [], "grounded": False}

    # ── Build retrieval plan ──────────────────────────────────────────────
    enabled_ids = set(enabled_documents.keys())
    plan = plan_retrieval(
        question,
        history=history,
        num_enabled_docs=len(enabled_ids),
    )

    # ── Retrieve candidates ───────────────────────────────────────────────
    cb(f"Searching {len(enabled_ids)} document{'s' if len(enabled_ids) != 1 else ''}")
    candidates, confidence = retrieve(plan.search_query, enabled_ids, plan)

    if not candidates:
        return {"answer": _NO_EVIDENCE_REPLY, "sources": [], "grounded": False}

    doc_count = len({c.get("document_id") for c in candidates if c.get("document_id")})

    # ── Decompose: if complex, search sub-queries too ─────────────────────
    if plan.sub_queries:
        cb(f"Breaking into {len(plan.sub_queries)} sub-questions")
        for sq in plan.sub_queries:
            extra_candidates, _ = retrieve(sq, enabled_ids, plan)
            candidates.extend(extra_candidates)

        # Re-deduplicate after merging sub-query results
        from rag.reranker import _distinct
        candidates = _distinct(candidates)

    # ── Rerank ────────────────────────────────────────────────────────────
    cb("Ranking relevant passages")
    final_chunks, confidence, context = select_and_compress(
        question, candidates,
        final_count=plan.final_context_k,
        rerank_k=plan.rerank_k,
    )

    if not final_chunks:
        return {"answer": _NO_EVIDENCE_REPLY, "sources": [], "grounded": False}

    # ── Completeness verdict (backend-computed, pre-generation) ──────────
    from rag.validator import completeness_verdict
    verdict = completeness_verdict(confidence)

    # ── Generate ──────────────────────────────────────────────────────────
    from rag.generator import generate

    system = prompts.system_prompt(grounded=True)
    user   = prompts.rag_prompt(
        question, context, intent=plan.intent, history=history, verdict=verdict,
    )
    prompt = f"{system}\n\n{user}"

    try:
        answer, model_used, calls_used = generate(
            plan.complexity, prompt, style=_style_for(plan.complexity, plan.intent),
        )
    except Exception as exc:
        _log.warning("generation failed: %s", exc)
        return {"answer": _FRIENDLY_ERROR, "sources": [], "grounded": False}

    # ── Validate + escalate ───────────────────────────────────────────────
    from rag.validator import validate
    if plan.profile == EXACT:
        accept_decision = {"accept": True, "escalate": False}
    else:
        accept_decision = validate(plan.complexity, confidence, answer, grounded=True)
    if accept_decision["escalate"]:
        cb("Strengthening answer")
        try:
            answer, model_used, calls_used = generate(
                plan.complexity, prompt, style="detailed", escalation_tier="STRONG",
            )
        except Exception:
            pass  # keep the original answer if escalation fails

    sources = _build_sources(final_chunks)

    # Deterministically repair malformed Markdown tables in the generated
    # answer without changing its content.
    from rag.tables import normalize_answer_tables, repair_inline_sources
    answer = repair_inline_sources(
        normalize_answer_tables(answer or _FRIENDLY_ERROR), final_chunks,
    )

    result = {
        "answer": answer or _FRIENDLY_ERROR,
        "sources": sources,
        "grounded": True,
        "verdict": verdict,
        "accept": accept_decision["accept"],
        "escalate": accept_decision["escalate"],
    }

    # ── Cache ─────────────────────────────────────────────────────────────
    cache.put(question, enabled_documents, result["answer"],
              result["sources"], result["grounded"])

    return result

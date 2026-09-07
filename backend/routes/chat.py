"""AI chat endpoints — non-streaming and SSE streaming.

Routes a user's question to the RAG system. Only documents the admin has
explicitly enabled for AI are searched, and the answer is grounded strictly
in the retrieved context (see rag.rag_service). When documents are enabled
(AI mode), questions always run through retrieval and generation — personal /
greeting deflections only apply in HR-bot mode when no documents are enabled.

SSE streaming
─────────────
POST /api/chat/stream returns a ``text/event-stream`` response. Each frame is
a JSON object prefixed with ``data: ``:

    {"type": "status", "message": "Searching 3 documents"}
    {"type": "status", "message": "Generating answer..."}
    {"type": "done",   "answer": "Employees receive ...",
                        "sources": [...], "grounded": true}

Live status events are streamed while the pipeline runs, but the answer is
delivered in one piece inside the final ``done`` frame (no token streaming).
The frontend shows live status in an activity bubble, then renders the full
answer at once.
"""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from auth.dependencies import get_authenticated_user
from config import GEMINI_API_KEY
from database.connection import get_db
from database.models import Document
from sqlalchemy import select

from rag.rag_service import _FRIENDLY_ERROR, _NO_EVIDENCE_REPLY
from rag.generator import generate_stream as _gen_stream
from rag.query_router import plan_retrieval, COMPLEX, CRITICAL
from rag.retriever import retrieve
from rag.reranker import select_and_compress, _distinct
from rag import cache, prompts
from rag.validator import validate, completeness_verdict
from utils.helpers import sign_file_link
from urllib.parse import quote

router = APIRouter()
_log = logging.getLogger("rag")


# ── Request schemas ─────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    """The payload a client sends to ask a grounded question."""
    question: str
    document_id: str | None = None
    history: list[dict] | None = None   # for follow-up resolution


# ── Helpers ─────────────────────────────────────────────────────────────────

def _enabled_documents(db, document_id=None) -> dict:
    """Return the documents the admin has enabled for AI.

    Returns: a dict mapping document_id -> {name, category, file}.
    """
    query = select(Document).where(Document.ai_enabled.is_(True))
    if document_id:
        query = query.where(Document.document_id == document_id)
    documents = db.scalars(query).all()
    return {
        doc.document_id: {
            "name":     doc.name,
            "category": doc.category,
            "file":     doc.file,
        }
        for doc in documents
    }


def _sse_frame(event_type: str, payload: dict) -> str:
    """Format a Server-Sent Events frame."""
    return f"data: {json.dumps({'type': event_type, **payload})}\n\n"


# ── Non-streaming endpoint (backward compatible) ────────────────────────────

@router.post("/api/chat")
def chat(request: ChatRequest, _=Depends(get_authenticated_user), db=Depends(get_db)):
    """Answer a user question grounded in admin-enabled documents (JSON)."""
    question = (request.question or "").strip()

    if not question:
        raise HTTPException(status_code=400, detail="Question cannot be empty")

    if not GEMINI_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="AI chat is not configured. An administrator must set the "
                   "GEMINI_API_KEY in the backend .env file.",
        )

    enabled = _enabled_documents(db, document_id=request.document_id)

    if not enabled:
        return {
            "answer": (
                "No documents are enabled for AI chat yet. An administrator "
                "must turn on 'Use this PDF for AI Chat' for the relevant "
                "policies before I can answer from them."
            ),
            "sources": [],
            "grounded": False,
        }

    try:
        from rag.rag_service import answer_question
        result = answer_question(question, enabled)
    except Exception as exc:
        _log.warning("chat generation failed: %s", exc)
        return {
            "answer": (
                "I wasn't able to generate an answer right now. "
                "Please try again in a moment."
            ),
            "sources": [],
            "grounded": False,
        }

    return result


# ── SSE streaming endpoint ──────────────────────────────────────────────────

@router.post("/api/chat/stream")
async def chat_stream(request: ChatRequest, _=Depends(get_authenticated_user), db=Depends(get_db)):
    """Answer a user question with SSE status events + token streaming.

    Returns a ``text/event-stream`` response. The frontend reads this with a
    fetch ReadableStream to drive a live activity bubble and streamed answer.
    """
    question = (request.question or "").strip()

    if not question:
        raise HTTPException(status_code=400, detail="Question cannot be empty")

    if not GEMINI_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="AI chat is not configured.",
        )

    enabled = _enabled_documents(db, document_id=request.document_id)

    if not enabled:
        async def empty_stream():
            yield _sse_frame("status", {"message": "Checking documents..."})
            yield _sse_frame("done", {
                "answer": (
                    "No documents are enabled for AI chat yet. An administrator "
                    "must turn on 'Use this PDF for AI Chat' for the relevant "
                    "policies before I can answer from them."
                ),
                "sources": [],
                "grounded": False,
            })
        return StreamingResponse(empty_stream(), media_type="text/event-stream")

    def generate_stream():
        # ── Cache check ───────────────────────────────────────────────────
        cached = cache.get(question, enabled)
        if cached:
            yield _sse_frame("status", {"message": "Found cached answer"})
            from rag.tables import normalize_answer_tables, repair_inline_sources
            yield _sse_frame("done", {
                "answer": normalize_answer_tables(cached["answer"]),
                "sources": cached.get("sources", []),
                "grounded": cached.get("grounded", False),
            })
            return

        # ── Plan ──────────────────────────────────────────────────────────
        enabled_ids = set(enabled.keys())
        plan = plan_retrieval(question, history=request.history, num_enabled_docs=len(enabled_ids))

        # ── Retrieve ──────────────────────────────────────────────────────
        yield _sse_frame("status", {"message": f"Searching {len(enabled_ids)} document{'s' if len(enabled_ids) != 1 else ''}"})
        candidates, confidence = retrieve(plan.search_query, enabled_ids, plan)

        if not candidates:
            yield _sse_frame("done", {
                "answer": _NO_EVIDENCE_REPLY,
                "sources": [],
                "grounded": False,
            })
            return

        # ── Sub-query decomposition ───────────────────────────────────────
        if plan.sub_queries:
            yield _sse_frame("status", {"message": f"Breaking into {len(plan.sub_queries)} sub-questions"})
            for sq in plan.sub_queries:
                extra, _ = retrieve(sq, enabled_ids, plan)
                candidates.extend(extra)
            candidates = _distinct(candidates)

        # ── Rerank ────────────────────────────────────────────────────────
        yield _sse_frame("status", {"message": "Ranking relevant passages"})
        final_chunks, confidence, context = select_and_compress(
            question, candidates,
            final_count=plan.final_context_k,
            rerank_k=plan.rerank_k,
        )

        if not final_chunks:
            yield _sse_frame("done", {
                "answer": _NO_EVIDENCE_REPLY,
                "sources": [],
                "grounded": False,
            })
            return

        # ── Completeness verdict (backend-computed, pre-generation) ───────
        verdict = completeness_verdict(confidence)

        # ── Generate with streaming ───────────────────────────────────────
        system = prompts.system_prompt(grounded=True)
        user   = prompts.rag_prompt(
            question, context, intent=plan.intent, history=request.history,
            verdict=verdict,
        )
        prompt = f"{system}\n\n{user}"

        style = "detailed" if plan.complexity in (COMPLEX, CRITICAL) else "normal"

        yield _sse_frame("status", {"message": "Generating answer..."})

        answer_parts = []
        model_used = None
        truncated = False

        try:
            for token_text, model, is_final in _gen_stream(plan.complexity, prompt, style=style):
                if is_final:
                    truncated = token_text == "TRUNCATED"
                    break
                answer_parts.append(token_text)
                model_used = model
        except Exception as exc:
            _log.warning("stream generation failed: %s", exc)
            yield _sse_frame("done", {
                "answer": _FRIENDLY_ERROR,
                "sources": [],
                "grounded": False,
            })
            return

        answer = "".join(answer_parts).strip()

        # ── Validate + escalate ───────────────────────────────────────────
        if plan.profile == "EXACT":
            accept_decision = {"accept": True, "escalate": False}
        else:
            accept_decision = validate(plan.complexity, confidence, answer, grounded=True)
        if accept_decision["escalate"]:
            yield _sse_frame("status", {"message": "Strengthening answer"})
            try:
                answer_parts_esc = []
                esc_truncated = False
                for token_text, model, is_final in _gen_stream(
                    plan.complexity, prompt, style="detailed", escalation_tier="STRONG",
                ):
                    if is_final:
                        esc_truncated = token_text == "TRUNCATED"
                        break
                    answer_parts_esc.append(token_text)
                escaped = "".join(answer_parts_esc).strip()
                if escaped and not esc_truncated:
                    answer = escaped
            except Exception:
                pass

        from rag.tables import normalize_answer_tables, repair_inline_sources
        answer_raw = normalize_answer_tables(answer or _FRIENDLY_ERROR)
        answer = repair_inline_sources(answer_raw, final_chunks)

        sources = []
        seen = set()
        for chunk in final_chunks:
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

        # ── Done ──────────────────────────────────────────────────────────
        yield _sse_frame("done", {
            "answer": answer or _FRIENDLY_ERROR,
            "sources": sources,
            "grounded": True,
            "verdict": verdict,
            "accept": accept_decision["accept"],
            "escalate": accept_decision["escalate"],
        })

        # ── Cache ─────────────────────────────────────────────────────────
        if not truncated:
            cache.put(question, enabled, answer, sources, True)

    return StreamingResponse(generate_stream(), media_type="text/event-stream")

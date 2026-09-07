"""Adaptive retrieval planner and query classifier.

Decides *how* each user question should be searched and reranked by breaking
down the retrieval pipeline into four profiles:

    EXACT   – factual lookups (names, dates, numbers, grades, identifiers)
    NORMAL  – general policy / conceptual HR questions (the common case)
    COMPLEX – multi-part or multi-intent queries needing decomposition
    DEEP    – cross-document, ambiguous, or high-risk questions needing the
              full retrieval pipeline with broad candidate pools

For every question the planner returns a ``RetrievalPlan`` dataclass that
drives the rest of the RAG pipeline (retriever → reranker → generator).

Module public API
─────────────────
classify_complexity(q)   – SMALL / NORMAL / COMPLEX / CRITICAL (model tier)
classify_intent(q)       – user intent category (DEFINITION, ACTION_REQUIRED, etc.)
plan_retrieval(q)        – RetrievalPlan with profile, weights, top-k, etc.
is_personal(q)           – whether the question targets the employee's own data
personal_deferral()      – canned deflection string
needs_retrieval(q)       – whether the question needs document knowledge at all
decompose_query(q)       – split complex queries into sub-queries
resolve_followup(q, history) – resolve pronouns / anaphora from context
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from rag.textutil import extract_exact_terms, has_followup_reference, normalize_query

# ── Existing complexity tiers (used by the model router for LIGHT/GENERAL/STRONG)
SMALL   = "SMALL"
NORMAL  = "NORMAL"
COMPLEX = "COMPLEX"
CRITICAL = "CRITICAL"

# ── Retrieval profiles (used by the retriever / planner)
EXACT  = "EXACT"
# NORMAL, COMPLEX already defined above; DEEP is new.
DEEP   = "DEEP"

# ── Intent types (from prompts.py) ──────────────────────────────────────────
from rag.prompts import (
    INTENT_DEFINITION,
    INTENT_OVERVIEW,
    INTENT_LIST,
    INTENT_FACTUAL_LOOKUP,
    INTENT_EXPLANATION,
    INTENT_ACTION_REQUIRED,
    INTENT_EMPLOYEE_RESPONSIBILITY,
    INTENT_PROCEDURE,
    INTENT_COMPARISON,
    INTENT_IMPACT,
    INTENT_SUMMARY,
    INTENT_DOCUMENT_SPECIFIC,
    INTENT_UNKNOWN,
)

# ── Signal word lists ───────────────────────────────────────────────────────

# Exact / factual signals: the query clearly names a concrete thing.
_EXACT_TRIGGERS = [
    "what is the", "what are the", "who is the", "who is",
    "what is grade", "what is the annual", "what is the basic",
    "what is the employee", "what is the secretary",
    "what is the date", "what is the amount",
    "page", "section", "clause", "part",
]

# Complex / multi-intent signals.
_COMPLEX_TRIGGERS = [
    "compare", "contrast", "difference between", "which one applies",
    "explain in detail", "why", "if i", "what happens when",
    "recommend", "weigh", "versus", "vs", "decide", "unusual",
    "also tell", "and also", "in addition", "what about",
]

# Multi-part signals: multiple intents in one sentence.
_MULTI_PART_MARKERS = [
    " and ", " also ", " as well as ", " in addition to ",
    " , ", " what about ", " tell me about ",
]

# Deep / high-risk signals: cross-document reasoning, ambiguity, financial.
_DEEP_TRIGGERS = [
    "compare all", "across all policies", "conflicting", "contradict",
    "financial", "budget", "compensation", "pay structure",
    "complex", "detailed analysis", "cross-document", "full comparison",
]

# Document title triggers: when the user explicitly names a document, boost it.
_DOC_TITLE_TRIGGERS = [
    "it security", "employee handbook", "payroll", "salary structure",
    "leave policy", "code of conduct", "administrative", "hr policy",
    "onboarding", "benefits", "safety",
]

# Personal / self-data questions (deflected, not answered from PDFs).
_PERSONAL_TRIGGERS = [
    "my leave", "my balance", "my salary", "my pay", "my attendance",
    "my department", "my desk", "my employee id", "my id", "my phone",
    "my extension", "my annual leave", "my sick leave", "my casual leave",
    "my payslip", "my payroll", "my basic", "leave balance", "how many leaves",
    "used leave", "my entitlements",
]

# ── Intent classification signals ────────────────────────────────────────────

_ACTION_TRIGGERS = [
    "what do i need to", "what should i do", "what am i required",
    "what must i", "what do employees need to", "what rules do",
    "what are the requirements", "what are the obligations",
    "what do i need to follow", "how do i comply", "what should employees",
    "what are my responsibilities", "what am i responsible",
    "what do i have to", "what is expected of", "what are the do's",
    "what are the don'ts", "what am i supposed to",
    "policies do i need to follow", "rules do i need to follow",
    "requirements do i need to follow", "policies should i follow",
    "rules should i follow", "policies apply to employees",
]

# Partial action patterns (combined with other words to form action queries)
_ACTION_PARTIALS = [
    ("need to follow", ["do i", "should i", "must i", "policies", "rules"]),
    ("need to comply", ["do i", "should i"]),
    ("responsible for", ["what am i", "what are employees"]),
    ("expected to do", ["what should i", "what are employees"]),
    ("obligations", ["what are", "employee", "my"]),
]

_LIST_TRIGGERS = [
    "what are the", "what are those", "tell me the", "list the",
    "enumerate", "name the", "give me a list", "what policies",
    "what rules", "what requirements", "what procedures",
]

_DEFINITION_TRIGGERS = [
    "what is the", "what is a", "what does", "define", "definition",
    "meaning of", "explain what", "what kind of", "what type of",
]

_COMPARISON_TRIGGERS = [
    "compare", "difference between", "how does .+ compare",
    "versus", " vs ", "which one", "what's the difference",
]

_PROCEDURE_TRIGGERS = [
    "how do i", "how to", "steps to", "process for",
    "procedure for", "what's the process", "what's the procedure",
    "how can i", "how does one",
]

_IMPACT_TRIGGERS = [
    "how does this affect", "what happens if", "impact of",
    "consequences of", "what are the implications",
    "how does this impact", "what effect",
]

_OVERVIEW_TRIGGERS = [
    "tell me about", "give me an overview", "what can you tell me about",
    "describe", "summarize", "summarise", "what's the general",
    "what are the main", "what are the key",
]

_PERSONAL_DEFERRAL = (
    "That's about your personal HR record, so I can only answer questions about "
    "the company's documents and policies. You can check your own balance and "
    "records directly in the HR portal. For specific policy questions about "
    "these topics, I'm happy to help."
)

# Greetings / chit-chat that need no document retrieval.
_GREETINGS = [
    "hi", "hello", "hey", "good morning", "good afternoon", "good evening",
    "thanks", "thank you", "who are you", "what can you do",
]


# ── Helpers ─────────────────────────────────────────────────────────────────

def _contains(text: str, words: list[str]) -> bool:
    low = text.lower()
    return any(w in low for w in words)


def _word_count(text: str) -> int:
    return len(text.split())


def _and_or_count(text: str) -> int:
    low = text.lower()
    return low.count(" and ") + low.count(" or ") + low.count(", ")


# ── Public API (preserved from old module) ─────────────────────────────────

def is_personal(question: str) -> bool:
    """Whether a question targets the employee's own private records."""
    return _contains(question, _PERSONAL_TRIGGERS)


def personal_deferral() -> str:
    return _PERSONAL_DEFERRAL


def needs_retrieval(question: str) -> bool:
    """Whether a question requires document retrieval (vs pure chit-chat)."""
    q = question.strip().lower()
    return not any(q == g or q.startswith(g) for g in _GREETINGS)


def classify_complexity(question: str) -> str:
    """Return SMALL / NORMAL / COMPLEX / CRITICAL for the model router."""
    q = question.strip()

    if _contains(q, _PERSONAL_TRIGGERS):
        return NORMAL  # personal deflection doesn't need a strong model

    if _and_or_count(q) >= 2 or _word_count(q) > 25:
        return COMPLEX
    if _contains(q, _COMPLEX_TRIGGERS) or _and_or_count(q) == 1 and _word_count(q) > 12:
        return COMPLEX
    if _contains(q, _EXACT_TRIGGERS):
        return SMALL
    if _word_count(q) > 8 or _contains(q, ["policy", "procedure", "how"]):
        return NORMAL
    return SMALL


def classify_intent(question: str) -> str:
    """Classify the user's intent from their question.

    Returns one of the INTENT_* constants that shapes the answer format.
    This is a fast, local heuristic — no LLM call.
    """
    q = question.strip().lower()
    wc = _word_count(q)

    # Action-required / employee responsibility (check first — most specific)
    if _contains(q, _ACTION_TRIGGERS):
        # Distinguish between personal action and general procedure
        if any(w in q for w in ["how do i", "how to", "steps", "process", "procedure"]):
            return INTENT_PROCEDURE
        return INTENT_ACTION_REQUIRED

    # Partial action patterns: combine partial phrase with context words
    for partial, context_words in _ACTION_PARTIALS:
        if partial in q and any(cw in q for cw in context_words):
            return INTENT_ACTION_REQUIRED

    # Procedure
    if _contains(q, _PROCEDURE_TRIGGERS):
        return INTENT_PROCEDURE

    # Comparison
    if _contains(q, _COMPARISON_TRIGGERS):
        return INTENT_COMPARISON

    # Impact
    if _contains(q, _IMPACT_TRIGGERS):
        return INTENT_IMPACT

    # List
    if _contains(q, _LIST_TRIGGERS):
        return INTENT_LIST

    # Definition
    if _contains(q, _DEFINITION_TRIGGERS):
        if wc <= 8:
            return INTENT_DEFINITION
        return INTENT_EXPLANATION

    # Overview / general
    if _contains(q, _OVERVIEW_TRIGGERS):
        return INTENT_OVERVIEW

    # Factual lookup (short questions with specific identifiers)
    if wc <= 6 and bool(re.search(r"\bgrade\s+\d+|\bpage\s+\d+|\bsection\s+\d+", q)):
        return INTENT_FACTUAL_LOOKUP

    # Default: depends on question length
    if wc <= 6:
        return INTENT_FACTUAL_LOOKUP
    if wc <= 12:
        return INTENT_OVERVIEW
    return INTENT_EXPLANATION


# ── Retrieval plan ──────────────────────────────────────────────────────────

@dataclass
class RetrievalPlan:
    """Drives the entire retrieval → reranking → generation pipeline.

    Produced by ``plan_retrieval()`` and consumed by the retriever and reranker.
    """
    # Query classification
    profile: str = NORMAL            # EXACT / NORMAL / COMPLEX / DEEP
    complexity: str = NORMAL         # SMALL / NORMAL / COMPLEX / CRITICAL
    intent: str = INTENT_UNKNOWN     # user intent category (shapes answer format)

    # Search weights (BM25 weight + vector weight = 1.0 for NORMAL; varies
    # by profile so exact queries favour BM25 and conceptual queries favour
    # vector search).
    bm25_weight: float = 0.5
    vector_weight: float = 0.5

    # Candidate pool sizes
    bm25_k: int = 30
    vector_k: int = 30
    candidate_k: int = 30           # after fusion, before rerank
    rerank_k: int = 20              # how many get the heuristic reranker
    final_context_k: int = 5        # sent to Gemini

    # Neighbour expansion
    neighbor_window: int = 1

    # Metadata filter (None = search all enabled docs; dict = restrict)
    metadata_filter: dict | None = None

    # Sub-queries from decomposition (empty list = no decomposition)
    sub_queries: list[str] = field(default_factory=list)

    # The (possibly rewritten) search query
    search_query: str = ""

    # Conversation-followup flag
    is_followup: bool = False


# Default per-profile settings
_PROFILE_DEFAULTS: dict[str, dict] = {
    EXACT: {
        "bm25_weight": 0.75,
        "vector_weight": 0.25,
    },
    NORMAL: {
        "bm25_weight": 0.5,
        "vector_weight": 0.5,
    },
    COMPLEX: {
        "bm25_weight": 0.45,
        "vector_weight": 0.55,
    },
    DEEP: {
        "bm25_weight": 0.4,
        "vector_weight": 0.6,
    },
}


def _detect_metadata_filter(question: str) -> dict | None:
    """Return a metadata constraint when the user explicitly names a document.

    Returns None when the query is ambiguous — global search must never discard
    documents based on uncertain metadata.
    """
    low = question.lower()
    for trigger in _DOC_TITLE_TRIGGERS:
        if trigger in low:
            return {"category": trigger}  # rough hint; retriever uses it loosely
    return None


def _detect_profile(question: str) -> str:
    """Choose EXACT / NORMAL / COMPLEX / DEEP based on query signals."""
    q = question.strip()

    # Explicit deep signals
    if _contains(q, _DEEP_TRIGGERS):
        return DEEP

    # Multi-part detection: 3+ intents in one query
    intents = _and_or_count(q)
    wc = _word_count(q)
    if intents >= 2 or (intents >= 1 and wc > 20):
        return COMPLEX

    # Exact factual: short, contains exact triggers, or contains identifiers
    exact_hits = sum(1 for t in _EXACT_TRIGGERS if t in q.lower())
    has_identifiers = bool(re.search(r"\b\d{4}\b|\bgrade\s+\d+|\bpage\s+\d+\b", q.lower()))
    if exact_hits >= 2 or (exact_hits >= 1 and wc <= 10) or has_identifiers:
        return EXACT

    # Complex trigger words
    if _contains(q, _COMPLEX_TRIGGERS):
        return COMPLEX

    return NORMAL


def _decompose(question: str) -> list[str]:
    """Split a multi-intent query into independent sub-queries.

    Only activated for COMPLEX / DEEP profiles. Returns [original] when no
    clear decomposition is possible.
    """
    q = question.strip()

    # Split on explicit conjunctions / punctuation
    parts = re.split(r"\s+(?:and|also|as well as|in addition to)\s+", q, flags=re.I)
    parts = [p.strip().rstrip("?.,;") + "?" for p in parts if p.strip()]

    # Filter out trivially short fragments that lose meaning alone
    meaningful = [p for p in parts if _word_count(p) >= 3]

    if len(meaningful) >= 2:
        return meaningful

    # Try splitting on commas if conjunction split didn't work
    comma_parts = [p.strip() for p in q.split(",") if _word_count(p.strip()) >= 3]
    if len(comma_parts) >= 2:
        return [p.rstrip("?.,;") + "?" for p in comma_parts]

    return [q]


def _rewrite_followup(question: str, history: list[dict] | None) -> str:
    """Resolve pronouns and anaphora using conversation history.

    If there is no history or the query does not reference prior context,
    returns the question unchanged. This is a purely local transformation —
    no LLM call.
    """
    if not history or not has_followup_reference(question):
        return question

    # Find the last substantive bot answer (has content > 20 chars).
    last_topic = ""
    for msg in reversed(history):
        if msg.get("sender") == "bot" and len(msg.get("text", "")) > 20:
            last_topic = msg["text"][:120]
            break

    if not last_topic:
        return question

    # Extract likely topic nouns from the last answer (simple heuristic).
    topic_words = [w for w in last_topic.lower().split()
                   if len(w) > 3 and w.isalpha()
                   and w not in {"this", "that", "with", "from", "have", "been", "will"}]

    if not topic_words:
        return question

    # Replace obvious pronouns with the most salient topic word.
    replacement = topic_words[0]
    rewritten = question
    pronoun_map = {
        "it": replacement, "its": replacement + "'s",
        "this": replacement, "that": replacement,
        "they": "employees", "their": "employees'",
        "them": "employees",
    }
    for pronoun, repl in pronoun_map.items():
        pattern = re.compile(r"\b" + pronoun + r"\b", re.I)
        rewritten = pattern.sub(repl, rewritten, count=1)

    return rewritten


# ── Main planner ────────────────────────────────────────────────────────────

def plan_retrieval(
    question: str,
    history: list[dict] | None = None,
    num_enabled_docs: int = 0,
) -> RetrievalPlan:
    """Build the full retrieval plan for a question.

    Parameters
    ----------
    question : str
        The raw user question.
    history : list[dict] | None
        Conversation history (messages with ``sender`` and ``text`` keys) for
        follow-up resolution.
    num_enabled_docs : int
        How many documents are enabled for AI chat; used to scale candidate
        pool sizes.

    Returns
    -------
    RetrievalPlan
        Complete plan consumed by the retriever and reranker.
    """
    from rag.config import RETRIEVAL_KNOBS

    raw = question.strip()
    normalized = normalize_query(raw)
    complexity = classify_complexity(raw)
    profile = _detect_profile(normalized)
    intent = classify_intent(raw)

    # Follow-up resolution
    is_followup = has_followup_reference(normalized) and bool(history)
    search_query = _rewrite_followup(normalized, history) if is_followup else normalized

    # Metadata filter (only if user explicitly names a document)
    metadata_filter = _detect_metadata_filter(raw)

    # Decompose if multi-part
    sub_queries = []
    if profile in (COMPLEX, DEEP):
        sub_queries = _decompose(search_query)
        if len(sub_queries) <= 1:
            sub_queries = []  # decomposition failed; fall through

    # Scale candidate counts with number of enabled docs
    knobs = RETRIEVAL_KNOBS
    scale = max(1.0, num_enabled_docs / 3.0)  # baseline is 3 docs

    profile_defaults = _PROFILE_DEFAULTS.get(profile, _PROFILE_DEFAULTS[NORMAL])

    plan = RetrievalPlan(
        profile=profile,
        complexity=complexity,
        intent=intent,
        bm25_weight=profile_defaults["bm25_weight"],
        vector_weight=profile_defaults["vector_weight"],
        bm25_k=min(int(knobs["bm25_k"] * scale), 120),
        vector_k=min(int(knobs["vector_k"] * scale), 80),
        candidate_k=min(int(knobs["candidate_k"][profile] * scale), 150),
        rerank_k=min(int(knobs["rerank_k"] * scale), 60),
        final_context_k=knobs["final_context_k"],
        neighbor_window=knobs["neighbor_window"],
        metadata_filter=metadata_filter,
        sub_queries=sub_queries,
        search_query=search_query,
        is_followup=is_followup,
    )

    return plan

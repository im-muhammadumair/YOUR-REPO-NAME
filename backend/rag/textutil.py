"""Lightweight text normalisation and typo-correction utilities for the RAG layer.

These helpers clean up user queries *before* retrieval without calling an LLM.
Heavy-handed normalisation (stemming, lemmatisation) is avoided because HR
documents contain domain-specific terms (Grade-17, Basic-Pay-Scale) that must
survive normalisation intact.

Design principle:
  1. Lowercase + whitespace collapse.
  2. Obvious typo correction via a curated HR-domain dictionary (tiny, fast).
  3. Pronoun / anaphora resolution with conversation context is left to the
     query_router, which has access to the conversation history.
"""

import re

# ── Common HR-domain misspellings (extend as real user errors surface) ──────
_TYPO_MAP: dict[str, str] = {
    "salry":     "salary",
    "salery":    "salary",
    "securty":   "security",
    "securiy":   "security",
    "employe":   "employee",
    "employeе":  "employee",
    "strucutre": "structure",
    "strucure":  "structure",
    "managment": "management",
    "managemnt": "management",
    "plicy":     "policy",
    "ploicy":    "policy",
    "incrament":  "increment",
    "incerment":  "increment",
    "attndance": "attendance",
    "attendence": "attendance",
    "payrol":    "payroll",
    "pay slip":  "payslip",
    "reimbrsement": "reimbursement",
    "reimbursement": "reimbursement",
    "confidnetial":  "confidential",
    "confidential":  "confidential",
    "entiteled":  "entitled",
    "benifits":   "benefits",
    "benifits":   "benefits",
}

# Pre-compiled whitespace pattern for collapse.
_MULTI_SPACE = re.compile(r"\s+")


def normalize_query(text: str) -> str:
    """Lowercase, collapse whitespace, and fix obvious HR-domain typos.

    This is a *cheap* normalisation pass intended to run on every query before
    retrieval. It does not change the semantics of correctly-spelled terms.

    >>> normalize_query("  What  is  the  SALRY  structure?  ")
    'what is the salary structure?'
    """
    text = text.lower().strip()
    text = _MULTI_SPACE.sub(" ", text)

    # Word-level typo correction.
    words = text.split()
    corrected = []
    for w in words:
        # Strip trailing punctuation for lookup, re-attach afterwards.
        core = w.strip("?!.,;:")
        punct = w[len(core):]
        replacement = _TYPO_MAP.get(core, core)
        corrected.append(replacement + punct)

    return " ".join(corrected)


def extract_exact_terms(text: str) -> list[str]:
    """Pull likely exact identifiers from a query (for metadata boosting).

    Returns individual tokens that look like proper nouns, numbers, dates,
    grades, or identifiers — the kinds of terms BM25 excels at finding but
    semantic search sometimes misses.

    >>> extract_exact_terms("What is Grade 17?")
    ['grade', '17']
    """
    tokens = re.findall(r"[A-Za-z0-9\-]+", text.lower())
    return [t for t in tokens if len(t) > 1 or t.isdigit()]


def has_followup_reference(text: str) -> bool:
    """Detect likely pronouns / anaphora pointing at conversation context.

    Returns True when the query appears to reference something from the
    previous turn ("it", "this", "that", "their", "how does it affect…").
    The query_router should resolve these before retrieval.
    """
    low = text.lower().strip()
    references = {
        "it", "its", "this", "that", "these", "those",
        "they", "their", "them", "he", "she", "his", "her",
    }
    words = set(low.split())
    return bool(words & references)

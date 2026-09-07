"""Grounding and confidence checks for generated answers.

The core guarantee of this system: the answer is grounded ONLY in the retrieved
PDF excerpts. This validator decides whether the retrieval evidence was strong
enough to trust the answer, and whether the task justifies escalating to a
stronger model.

It deliberately does NOT run a second Gemini model on every easy answer - that
would waste tokens. Escalation is triggered only when:
    - the retrieval confidence is low, or
    - the task itself is complex/critical and a second pass adds real value.
"""
from rag.query_router import COMPLEX, CRITICAL, NORMAL

# Completeness verdicts (backend-computed from retrieval confidence, not
# self-asserted by the model — the model only prints the line we dictate).
VERIFIED     = "VERIFIED"
LIKELY       = "LIKELY"
NOT_VERIFIED = "NOT_VERIFIED"

# The exact final line the generator is told to print for each verdict.
VERDICT_LINE = {
    VERIFIED:     "Completeness: VERIFIED — this answer is fully supported by the provided documents.",
    LIKELY:       "Completeness: LIKELY — this answer is mostly supported by the documents; some details may depend on interpretation.",
    NOT_VERIFIED: "Completeness: NOT_VERIFIED — the retrieved documents could not fully confirm this answer.",
}


def completeness_verdict(confidence: float) -> str:
    """Map retrieval confidence to a completeness verdict.

    Thresholds mirror the escalation boundaries in ``validate`` so the verdict
    and the escalation path always agree.
    """
    if confidence >= 0.55:
        return VERIFIED
    if confidence >= 0.35:
        return LIKELY
    return NOT_VERIFIED


def validate(complexity: str, confidence: float, answer: str, grounded: bool):
    """Return whether the answer should be accepted or escalated.

    Takes: complexity - SMALL/NORMAL/COMPLEX/CRITICAL.
           confidence - retrieval confidence in [0,1] from the reranker.
           answer - the generated answer text.
           grounded - whether any retrieved chunks were used.
    Returns: a dict {accept, escalate} where exactly one is True.
    """
    if not answer:
        return {"accept": False, "escalate": True}

    # No evidence found + not already grounded -> no point escalating a
    # "not enough info" answer.
    if not grounded:
        return {"accept": True, "escalate": False}

    # Complex/critical tasks get a stronger model pass when confidence is low.
    if complexity in (COMPLEX, CRITICAL) and confidence < 0.55:
        return {"accept": False, "escalate": True}

    # Normal tasks escalate only when retrieval confidence is very low.
    if complexity == NORMAL and confidence < 0.35:
        return {"accept": False, "escalate": True}

    return {"accept": True, "escalate": False}

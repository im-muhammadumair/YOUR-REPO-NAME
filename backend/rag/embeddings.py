"""Gemini embedding wrappers.

Thin helpers that turn text into vectors using Google's Gemini embedding API.
Two kinds of embedding are produced:
  - document embeddings (task_type=RETRIEVAL_DOCUMENT) for stored chunks, and
  - query embeddings (task_type=RETRIEVAL_QUERY) for the user's question.

Using matching task types keeps the vector spaces aligned, which meaningfully
improves retrieval accuracy.
"""
from google import genai

from config import GEMINI_API_KEY

from rag.config import GEMINI_EMBED_MODEL, RAG_EMBEDDING_DIMENSIONS

# A single shared client is configured once so repeated calls reuse it instead
# of reinitialising per request.
_client = None


def _get_client():
    """Create (once) and return the shared Gemini client.

    Returns: the google-genai client configured with the API key.
    """
    global _client
    if _client is None:
        _client = genai.Client(api_key=GEMINI_API_KEY)
    return _client


def embed_documents(texts, batch_size=96):
    """Embed a list of chunk texts for storage/retrieval.

    Documents use the RETRIEVAL_DOCUMENT task type so their vectors are
    optimised to be found by a query. Texts are processed in batches because
    the API accepts a limited number of items per request.

    Takes: texts - a list of strings to embed.
           batch_size - how many texts to send per API call.
    Returns: a list of embedding vectors (lists of floats), one per input text.
    """
    if not texts:
        return []

    client = _get_client()
    embeddings = []

    for start in range(0, len(texts), batch_size):
        batch = texts[start:start + batch_size]
        result = client.models.embed_content(
            model=GEMINI_EMBED_MODEL,
            contents=batch,
            config={
                "task_type": "RETRIEVAL_DOCUMENT",
                "output_dimensionality": RAG_EMBEDDING_DIMENSIONS,
            },
        )
        for emb in result.embeddings:
            embeddings.append(emb.values)

    return embeddings


def embed_query(text):
    """Embed a single user question for retrieval.

    Queries use the RETRIEVAL_QUERY task type so they compare correctly with
    the RETRIEVAL_DOCUMENT vectors stored in ChromaDB.

    Takes: text - the user's question.
    Returns: a single embedding vector (list of floats).
    """
    client = _get_client()
    result = client.models.embed_content(
        model=GEMINI_EMBED_MODEL,
        contents=[text],
        config={
            "task_type": "RETRIEVAL_QUERY",
            "output_dimensionality": RAG_EMBEDDING_DIMENSIONS,
        },
    )
    return result.embeddings[0].values

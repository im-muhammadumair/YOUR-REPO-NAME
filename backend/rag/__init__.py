"""RAG / AI package.

Keeps all retrieval-augmented-generation logic (embeddings, ingestion, model
routing, retrieval, reranking, generation and orchestration) in one isolated
folder so it does not interfere with the existing HR domain code in routes/ and
database/.

The single public entry point for answering a question is
`rag.rag_service.answer_question`, used by routes/chat.py.
"""

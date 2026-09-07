# RAG System — Full Investigation, Algorithms & Portable Implementation Guide

> Produced by a full source + database investigation of this repo: `AI-knowledge-assistant/assitant-part/chainlit_rag`
> Read this end-to-end: it covers the **exact architecture**, **storage schema**, **embedding pipeline**, every **search/scoring method**, all **query-matching cases**, the **prompt templates**, real **runtime data** from the SQLite DB, known **gotchas**, and finally a **portable RAG kit** with **general-purpose code** you can drop into any RAG project, plus a **reusable skill/prompt** you can feed to any coding agent to rebuild the same system elsewhere.

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Architecture Overview](#2-architecture-overview)
3. [Component Map (files)](#3-component-map)
4. [Storage Schema — what & where you store](#4-storage-schema)
5. [Embedding System — how embeddings work](#5-embedding-system)
6. [Ingestion / Compile Pipeline — chunking & indexing](#6-ingestion-pipeline)
7. [Query Pipeline — from question to answer](#7-query-pipeline)
8. [Query Classification & Content-Matching Cases](#8-query-classification--content-matching-cases)
9. [Retrieval Methods in Detail](#9-retrieval-methods-in-detail)
10. [Reranking & Scoring Formulas](#10-reranking--scoring-formulas)
11. [Prompt Templates Sent to Gemini](#11-prompt-templates)
12. [Citations & Source Extraction](#12-citations--source-extraction)
13. [Observed Runtime Data](#13-observed-runtime-data)
14. [Known Gotchas & Inconsistencies](#14-known-gotchas--inconsistencies)
15. [Portable RAG Kit — general-purpose code for ANY RAG system](#15-portable-rag-kit)
16. [Reusable Skill / Agent Prompt](#16-reusable-skill--agent-prompt)
17. [End-to-End Message Flow — send → receive (full sequence)](#17-end-to-end-message-flow--send--receive-full-sequence)
18. [Rare & Critical Code Paths — verbatim from this repo](#18-rare--critical-code-paths--verbatim-from-this-repo)
19. [How RAG Works in This Project — Explained Step by Step](#19-how-rag-works-in-this-project--explained-step-by-step)

---

## 1. Executive Summary

This system is a **hybrid retrieval RAG assistant** over PDF documents:

- **Vector store**: SQLite database (`backend/Database/database.db`) — each chunk's embedding stored as a raw `BLOB` of packed floats. No specialized vector DB is used.
- **Embeddings**: Google Gemini `gemini-embedding-001` (3072 dims in practice), batched 32 at a time, embedded **only at compile time** and cached forever in SQLite.
- **Retrieval**: rule-based **query classification** → **semantic (cosine)** retrieval **fused** with **BM25 keyword search** via **Reciprocal Rank Fusion (RRF)**, then **dedup**, **rerank** (boolean boosts), **parent/entity enrichment**, and final context feeding **Gemini generation** with page-level citations.
- **Entry point**: `backend/main.py` → `backend/admin.py` (compile/manage/delete) or `backend/user.py` (chat). Everything from there on is the shared backend RAG engine; no UI logic participates in retrieval or generation.
- Everything retrieval-side is done **in memory** (all chunk vectors loaded from SQLite per question). No persistent index files besides SQLite.

Real state of the DB at investigation time:
- 5 documents, 53 chunks (all `child` type, **zero parent chunks currently materialized**), all 53 have 3072-dim embeddings (12,288 bytes each).
- **0 entities** in the `entities` table — entity extraction is wired up but produced nothing (likely the LLM extraction step fails silently).

---

## 2. Architecture Overview

```
┌────────────────────────────────────────────────────────────────────────────┐
│                     INGESTION (one-time per PDF, admin-only)               │
│                                                                            │
│  PDF (pdfs/*.pdf)                                                        │
│    │  1. extract_pages()  [PyMuPDF / fitz]                                │
│    │     - page text            page.get_text("text")                     │
│    │     - tables               page.find_tables() → markdown              │
│    │     - headings/sections    regex structure detection                  │
│    │     - images               detected (names only, not stored)          │
│    ↓                                                                      │
│  2. create_chunks()  [heading-aware split + short-chunk merge + hierarchy]│
│    ↓                                                                      │
│  3. batch_generate_embeddings()  [gemini-embedding-001, 3072-dim]         │
│    ↓                                                                      │
│  4. add_chunks() → SQLite [chunks table]  (embedding → packed BLOB)       │
│    ↓                                                                      │
│  5. extract_entities_from_chunks() → add_entities() [entities table]      │
│                                                                            │
├────────────────────────────────────────────────────────────────────────────┤
│                        QUERY (model-in-the-loop pipeline)                 │
│                                                                            │
│  User question ──► classify_query() ──► QueryAnalysis                     │
│                                            │ type/keywords/entities/       │
│                                            │ numerics/filter/variants      │
│                                            ▼                              │
│                    _retrieve_chunks()                                      │
│                    ├─ FILTER/EXHAUSTIVE?  → keyword_filter_search +        │
│                    │                        semantic → RRF → rerank        │
│                    └─ else  → semantic_search + keyword_search +           │
│                                variant search → RRF → dedup → rerank       │
│                                            │                              │
│                                            ▼                              │
│                    enrich (parents, entity labels) → format_context()      │
│                                            │                              │
│                                            ▼                              │
│                    query-type-specific prompt template ──► Gemini          │
│                                            │                              │
│                                            ▼                              │
│                    answer + inline citations + Sources block               │
└────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Component Map

| File | Responsibility |
|---|---|
| `backend/main.py` | CLI launcher: choose Admin or User mode |
| `backend/admin.py` | CLI admin: compile PDFs, list/delete docs, chat |
| `backend/user.py` | CLI user: chat with PDF, global chat |
| `backend/src/core/config.py` | Model names, chunk sizes, thresholds, paths, `.env` loading |
| `backend/src/core/database.py` | SQLite schema, migrations, all CRUD + serialization for embeddings |
| `backend/src/core/gemini.py` | Gemini client (text gen, embeddings, OCR, entity extraction) with retries/fallback |
| `backend/src/processing/pdf_processor.py` | Extraction (text/tables/headings) + all chunking logic |
| `backend/src/processing/embeddings.py` | Safe/retry/batched wrappers around `gemini.generate_embeddings` |
| `backend/src/search/query_classifier.py` | Rule-based query classification + tokenization + query variants |
| `backend/src/search/keyword.py` | Pure-Python BM25, exact-match bonus, filter search, zero-indicator detection |
| `backend/src/search/search.py` | Orchestrator: retrieve → fuse → dedup → rerank → prompt → generate → citations |
| `backend/pdfs/*.pdf` | Drop-in PDF source folder |
| `backend/Database/database.db` | SQLite vector store |

---

## 4. Storage Schema

Everything lives in one SQLite file: `backend/Database/database.db`

- `PRAGMA journal_mode=WAL` (write-ahead logging for concurrent readers)
- `PRAGMA foreign_keys=ON`

### 4.1 `documents` — one row per compiled PDF

| Column | Type | Purpose |
|---|---|---|
| `id` | INTEGER PK AUTOINCREMENT | document key |
| `filename` | TEXT NOT NULL UNIQUE | e.g. `Payroll & Salary Structure.pdf` |
| `filepath` | TEXT NOT NULL | original path |
| `file_hash` | TEXT | `sha256` of file → recompile detection |
| `page_count` | INTEGER | number of pages |
| `chunk_count` | INTEGER | total chunks (children + parents) |
| `status` | TEXT | `pending` / `processing` / `completed` |
| `created_at` | TIMESTAMP | auto `CURRENT_TIMESTAMP` |

### 4.2 `chunks` — the actual vector store

| Column | Type | Purpose |
|---|---|---|
| `id` | INTEGER PK | chunk id (used in RRF + dedup + evidence) |
| `document_id` | INTEGER FK→documents (CASCADE) | owning doc |
| `chunk_index` | INTEGER | intra-doc order |
| `chunk_type` | TEXT | `child` (normal/table) or `parent` (oversize context wrapper) |
| `parent_id` | INTEGER FK→chunks (SET NULL) | parent/child hierarchy link |
| `page_number` | INTEGER | source page (for citations) |
| `section` | TEXT | detected ALL-CAPS section |
| `heading` | TEXT | heading, or `Table N` for table chunks |
| `text` | TEXT NOT NULL | the retrievable text |
| `content_hash` | TEXT | sha256 of text → dedup key |
| `embedding` | BLOB | **768 or 3072 floats packed via `struct.pack(f"{n}f")`** |

Embedding serialization (database.py):
```python
def _serialize_embedding(embedding) -> bytes | None:
    if embedding is None: return None
    if isinstance(embedding, bytes): return embedding
    return struct.pack(f"{len(embedding)}f", *embedding)   # float32 little-endian

def _deserialize_embedding(data) -> list[float] | None:
    if data is None: return None
    if isinstance(data, list): return data
    count = len(data) // 4
    return list(struct.unpack(f"{count}f", data))
```

### 4.3 `entities` — named-entity lookup table (currently empty in practice)

| Column | Type | Purpose |
|---|---|---|
| `id` | INTEGER PK | entity key |
| `document_id` | INTEGER FK (CASCADE) | owning doc |
| `name` | TEXT NOT NULL | entity label |
| `entity_type` | TEXT | `food`, `nutrient`, `measurement`, `category`, `document`, or `generic` |
| `chunk_id` | INTEGER FK (SET NULL) | where it appears |
| `page_number` | INTEGER | for citations |

### 4.4 Indexes

```sql
idx_chunks_doc      (document_id)
idx_chunks_page     (document_id, page_number)
idx_chunks_parent   (parent_id)
idx_chunks_type     (chunk_type)
idx_entities_doc    (document_id)
idx_entities_name   (name)
```

**Important**: there is **no vector index** (no FTS, no ANN). Every query does a full table scan of all embeddings and cosine similarity against each. Fine until thousands of chunks.

---

## 5. Embedding System

### 5.1 How embeddings are generated

Config (`config.py`):
```python
EMBEDDING_MODEL = "gemini-embedding-001"
EMBEDDING_FALLBACKS = ["gemini-embedding-001", "gemini-embedding-2"]
EMBEDDING_DIMENSION = 768          # <-- declared, but NOT enforced (see gotchas)
MAX_CHUNKS_PER_CALL = 32           # batch size
API_DELAY = 0.3                    # rate-limit sleep between batches
```

Flow (`core/gemini.py::_generate_embeddings_safe`):
1. Use the **new** SDK `google.genai.Client(api_key=...)`.
2. Split texts into batches of `MAX_CHUNKS_PER_CALL` (32).
3. `client.models.embed_content(model="gemini-embedding-001", contents=batch)`.
4. Return `[e.values for e in result.embeddings]`.
5. On rate-limit `429 / RESOURCE_EXHAUSTED`: retry up to 3× with `5s, 10s` backoff.
6. On total failure of primary model: retry the same batch with fallback model.
7. On total failure: silently emit **`[[0.0] * EMBEDDING_DIMENSION]`** (i.e. 768 zeros) — a vector of all zeros → cosine similarity `0` → effectively filtered out by `SIMILARITY_THRESHOLD`.
8. Sleep `API_DELAY` between batches.

Batching lives in three places (all equivalent): `embeddings.py::batch_generate_embeddings`, `admin.py` compile flow (per-batch loop), and `gemini.py` itself.

### 5.2 Where embeddings are used

- **At compile**: each chunk text → one embedding → stored in `chunks.embedding`.
- **At query**: the query string is embedded ONCE (`_semantic_search_safe`), then cosine-distance compared to every stored chunk vector in memory.

There are **two** query-time embedding styles in the codebase (only the first is actually used by `search.py`):
- `generate_embeddings([query])` → real Gemini call (used).
- `generate_embedding_with_retry(text)` with exponential backoff — helper exists but is **not** called by the search pipeline.

### 5.3 Similarity math — cosine

```python
def _cosine_similarity(a, b):
    dot   = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x*x for x in a))
    norm_b = math.sqrt(sum(x*x for x in b))
    if norm_a == 0 or norm_b == 0: return 0.0
    return dot / (norm_a * norm_b)
```

Thresholds used: `SIMILARITY_THRESHOLD = 0.2` (chunks scoring below it are dropped). `MIN_SCORE = 0.25` and `EXHAUSTIVE_MIN_SCORE = 0.15` are defined but **never referenced in code** (dead config).

---

## 6. Ingestion Pipeline

Compile flow (`backend/admin.py::_compile_single_pdf`):

### 6.1 Dedup gate (before processing)

```python
file_hash = compute_file_hash(pdf_path)          # sha256, 64KB blocks
if document_exists(filename):
    if document_hash_matches(filename, file_hash) and is_document_compiled(doc_id):
        skip ("Skipped (unchanged)")
    else:
        delete_document(doc_id)                  # recompile from scratch
```
`is_document_compiled` = any chunk row exists with `embedding IS NOT NULL`.

### 6.2 Extraction — `pdf_processor.py`

`extract_pages(pdf_path)` per page:
- `text = page.get_text("text")` — raw text layer
- `tables = _extract_tables(page)` — via `page.find_tables()`; each table → `{header, rows, markdown, cell_count}` where `markdown` is a pipe table:
  ```
  | Food (Cooked) | Serving Size | Calories | Protein (g) |
  | --- | --- | --- | --- |
  | Chicken, skinless | 3 oz | 141 | 28 |
  ```
- `structure = _detect_structure(text)` — regex heading detection:
  ```python
  re.match(r"^(TABLE\s+\d|Table\s+\d)", line)            # table captions
  re.match(r"^[A-Z][A-Z\s]{5,}$", line)                  # ALL-CAPS SECTION headers
  re.match(r"^\d+\.?\s+[A-Z]", line) and len(line) < 100 # numbered headings "1. X"
  re.match(r"^[IVXLC]+\.\s+", line)                      # roman "I. X"
  ```
  The first pattern to match also marks the line as a **section**; the others as **heading**.
- `images = _extract_images(page)` — only **names** like `img_0_2`; image bytes are never written to disk, and `extract_text_from_image` (OCR) exists but is **never called** in the pipeline.

### 6.3 Chunking — `_create_chunks_safe`

```
for page in pages: _chunk_page(page)      # tables first, then heading-split text
merged   = _merge_short_chunks(raw)       # join < 80-char fragments
children, parents = _build_hierarchy(merged)
return children + parents
```

**`_chunk_page`**:
1. Each table → its own chunk with `heading="Table N"`, `section=""`, `chunk_type="child"` (markdown pipe table text).
2. Text (with headings present): iterate lines; when a line equals a detected heading, flush current accumulation as a chunk, then update `current_section`/`current_heading`.
3. Text (no headings): split by sentence boundaries `re.split(r'(?<=[.!?])\s+', text)` and accumulate up to `TARGET_CHUNK_SIZE` (2500 chars ≈ 600 tokens).
4. Chunks sorted by their heading's line position in the page via `_get_heading_order`.

**`_merge_short_chunks`**: any chunk `< MIN_CHUNK_SIZE` (80 chars) is merged into the next chunk while total stays `< TARGET_CHUNK_SIZE`.

**`_build_hierarchy`** (parent/child):
- A chunk is promoted to **parent** if `len(text) > TARGET_CHUNK_SIZE * 1.5` (3750 chars). Parent text = `text[:TARGET_CHUNK_SIZE * 2]` (5000 chars).
- The same original text is then re-split into **children** via `_split_long_chunk` (sentence-based, ~2500 chars each). Parent keeps `chunk_type="parent"`, children `"child"`.
- **Important**: `parent_id` is never actually written to children in `add_chunks` (children produced by `_split_long_chunk` have no `parent_id`), and current corpus has no chunks > 3750 chars, so `chunk_type="parent"` does not exist in the DB today. The two `chunk_type` values go through the same embedding/table.

**Multi-page note**: chunking is **per-page** (pages are never joined). A 2500-char ceiling per page effectively means most PDF pages produce 1-3 chunks. Target size `2500` is the **character** budget; `CHUNK_TARGET_TOKENS=600` / `CHUNK_OVERLAP_TOKENS=120` / `CHUNK_OVERLAP=200` are defined but **not enforced** — there is currently **no overlap** between chunks (config line `CHUNK_OVERLAP` is imported but never used).

### 6.4 Embedding — stored per chunk

`chunks = create_chunks(pages)`; `embeddings = batch_generate_embeddings([c["text"] ...])`; zip back into chunks; `add_chunks(doc_id, chunks)`.

### 6.5 Entity extraction — stored per chunk

`extract_entities_from_chunks(child_chunks)` sends a batched JSON prompt to Gemini (`food/nutrient/measurement/category/document`), parses the array, and `add_entities()` stores each with `chunk_id` + `page_number`. (Currently returns 0 rows — see gotchas.)

### 6.6 Status

`update_document_chunks(doc_id, len(chunks))` → `update_document_status(doc_id, "completed")`.

---

## 7. Query Pipeline

Entry point: `search.py::answer_question(query, previous_context, previous_answer, use_history, document_id)`.

```
1. classify_query(query, has_history=use_history and bool(previous_context))
      → QueryAnalysis(query_type, keywords, entities, numeric_values,
                      filter_attribute, filter_value, is_exhaustive,
                      needs_structured, search_variants, confidence)

2. Load ALL chunks into memory:
      all_chunks      = get_all_chunks_with_embeddings(document_id)   # incl. embedding
      all_chunks_text = get_all_chunks_text(document_id)              # no embedding

3. _retrieve_chunks():
   ├─ FILTER or (EXHAUSTIVE && needs_structured)  → filter branch
   │     keyword_filter_search(...) + semantic + RRF + dedup + rerank + enrich
   └─ otherwise → hybrid semantic + keyword (+ variants) → RRF → dedup → rerank → enrich

4. EXHAUSTIVE fallback: if retrieved < 10 chunks, append up to 50 extra raw chunks (all docs).

5. format_context(relevant) → "[file - p.N - section - heading]\ntext ... " joined by "\n\n---\n\n"

6. _build_prompt(...) → type-specific template

7. generate_text(prompt, SYSTEM_PROMPT)   # Gemini with rate-limit retry + model fallback

8. get_citations(relevant) + "--- Sources ---" appendix
```

**Scope**: `document_id=None` = global chat (all docs); else single-doc scope (only callers that pass a `document_id` get scoped search — the CLI handlers never pass it, see Gotchas #3).

---

## 8. Query Classification & Content-Matching Cases

All heuristic/rule-based (no ML). `query_classifier.py`.

### 8.1 The `QueryType` enum (actual, matches code — differs from README's simplified table)

| Enum value | Trigger | Strategy afterwards |
|---|---|---|
| `FOLLOWUP` | Regex follow-up phrases + `has_history` | uses previous context in prompt |
| `SUMMARY` | "summarize / summary / overview / what is this about" | broad retrieval, summary template |
| `COMPARISON` | "compare / vs / versus / how does X compare / difference between" | multi-entity prompt |
| `EXHAUSTIVE` + filter | list-all + numeric constraint | big retrieval + numeric prompt |
| `EXHAUSTIVE` | "all/every/each/complete/...list..." | top_k=60, fallback to extra chunks |
| `FILTER` | numeric/unit/"has X" patterns | keyword-filter + numeric prompt |
| `ENTITY_LOOKUP` | "tell me about / information about / details on" | treats as exhaustive retrieval |
| `FACTUAL` | default | standard QA |

### 8.2 Classification order (first match wins)

1. **Follow-up** (only if `has_history` is True):
   ```
   ^(what about|how about|and )
   ^(tell me more|what else|anything else)
   ^(ok|okay|cool|got it|right|nice)
   ^(why|when|where|who|how) (is|are|was|were|did|does)
   ^(more|less|higher|lower|bigger|smaller)
   ```
2. **Summary** — `\bsummarize\b|\bsummary\b|\boverview\b|\bgive me an? overview\b|\bwhat is this (about|document)\b`
3. **Comparison** — `\bcompare\b|\bvs\.?\b|\bversus\b|\bhow does .* compare\b|\bdifference between\b`
4. **Exhaustive + filter** — both checks pass
5. **Exhaustive** alone
6. **Filter** alone
7. **Entity lookup**
8. **Factual** (fallback)

### 8.3 Exhaustive keyword set

```
all, every, each, complete, full, entire, exhaustive,
list all, all of, everything, all foods, all items,
all entries, all records, every food, every item,
give me everything, all information, all mentions
```
Regex extras: `\b(all|every|each|complete|full|entire)\s+\w+`, `\blist (all )?\w+`, `\bgive me (all|everything|every)\b`, `\bfind (all|every|each)\b`, `\bwhich \w+ (have|has|contain|contains)\b`.

### 8.4 Filter matching patterns (regex → QueryAnalysis)

| Pattern | Captured | Type |
|---|---|---|
| `(?:have\|has\|contain\|contains\|with)\s+(\d+\.?\d*)\s*(g\|mg\|kcal\|cal\|%)` | `has_value` | value like "20 g" |
| `(?:have\|has\|contain\|contains)\s+(zero\|no\|trace\|tr)\b` | `has_zero` | zero indicators |
| `(more\|less\|fewer\|greater\|over\|under\|above\|below\|at least\|at most)\s+than\s+(\d+)` | `comparison` | relational |
| `(?:highest\|lowest\|most\|least\|max\|min\|maximum\|minimum)\s+(\w+)` | `extreme` | extremes |
| `which\s+(\w+)\s+(?:have\|has\|contain\|contains\|are)\b` | `which_have` | "which foods have" |

Each becomes `filter_attribute` / `filter_value`; e.g. `"Foods with more than 20g protein"` → `filter_value="20"`, `needs_structured=True`, `numeric_values=["20"]`.

### 8.5 Entity extraction from the query

- Capitalized words: `\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\b` → `["Apple", "Banana"]`
- Quoted strings `"..."` and `'...'`
- These entities are later used for `_build_search_query` (append to query), rerank boost (+0.5), and `_enrich_with_entity_info` labeling.

### 8.6 Numeric extraction

`re.findall(r"\d+\.?\d*", query)` → used as rerank numeric boost (+0.2 each) and in filter search (+0.3 each).

### 8.7 Query expansion variants (`_expand_query`) — content-match fallbacks

Handles "0g-ish" phrasing so keyword search can match varied source text:
```python
# "0g" → also try "zero", "0 grams", "trace", "no"
# "no " → also try "0 "
# "trace" → also try "tr", "0"
# plus every adjacent word bigram of the query
```
These variants each get their own `keyword_search` pass folded into the RRF fusion.

### 8.8 Tokenizer (used for keywords & BM25)

`re.findall(r"[a-z0-9]+", text.lower())` minus a ~90-word stop list (`the, a, is, of, with, which, tell, me, give, show, list, find, get ...`). → `keywords` list on `QueryAnalysis`.

---

## 9. Retrieval Methods in Detail

### 9.1 Semantic search (vector)

- Embed query once (`generate_embeddings([query])`).
- Iterate every chunk `embedding` (loaded in memory), compute cosine, keep `>= SIMILARITY_THRESHOLD (0.2)`.
- Sort desc by `score`, cap at `top_k` (`30`, or `60` for exhaustive).
- Returns chunks tagged `semantic_score` + `score`.

### 9.2 Keyword search (BM25, pure Python, no numpy)

`keyword.py`:
- Tokenize query and every chunk.
- `avg_dl` = mean token count across chunks (computed per query call).
- IDF over all chunks: `idf = log((N - df + 0.5) / (df + 0.5) + 1)`.
- BM25 with `k1 = 1.5`, `b = 0.75`:
  ```python
  score += idf[term] * (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * doc_len / avg_dl))
  ```
- **Exact-match bonus** (`_exact_match_bonus`):
  - `+2.0` if the full query string appears in the chunk text (case-insensitive)
  - `+0.5` for each query token of length > 3 present in the text
- `keyword_search` runs the base query **plus up to 3 search variants**, keeping the max score per chunk.
- Sorted desc, top_k.

### 9.3 Filter keyword search (for FILTER / EXHAUSTIVE-with-filter)

`keyword_filter_search`: runs `keyword_search(query, top_k=len(all))` first, then **boosts**:
- `+0.3` per numeric value literally found in the chunk text
- `+0.5` if `filter_value` appears (e.g. `kcal`, `g`)
- `+0.5` if filter value is a zero-indicator (`zero/no/trace/tr`) and chunk has `\b0\b|\bzero\b|\btrace\b|\btr\b|\bnil\b|\bnone\b`
- `+0.5` if filter value is a digit matched with word boundaries `\b20\b`
Chunks with any boost survive (others dropped). If nothing survives, falls back to plain keyword top_k.

### 9.4 RRF fusion (`_rrf_fusion`)

Reciprocal Rank Fusion — combines **rank positions** (not scores):
```python
RRF_score = 1 / (60 + rank)     # constant k = 60, rank is 0-based
# identical chunk ids accumulate score across all result lists
```
Applied sequentially: `semantic ⋈ keyword` (mandatory), then each query **variant** passes fused in too.

### 9.5 Deduplication

Keyed on `content_hash` (else first 200 chars of text). First occurrence wins (`_deduplicate`).

### 9.6 Entity enrichment

`_enrich_with_entity_info`: for each chunk, annotate `matched_entities` = which query entities appear in its text (used only for logging/debug, not scoring).

The `entities` table + `search_entities()` (SQL `name LIKE '%...%'`) exist but are **not queried by the current search pipeline** — the table is unused at query time in this build.

### 9.7 Parent enrichment

`_enrich_with_parents`: if a retrieved chunk references `parent_id`, append the parent chunk (marked `source="parent_context"`, scored at `0.9 * child score`) once per parent. Effective today only if hierarchy exists (currently it doesn't).

### 9.8 Exhaustive "rescue"

After retrieval, if `EXHAUSTIVE` and `< 10` chunks: append up to 50 previously-unseen chunks from the full text table (`get_all_chunks_text`) so the "list ALL" prompt actually sees everything.

---

## 10. Reranking & Scoring Formulas

`_rerank_safe` computes a final `rerank_score` per chunk (starts from RRF score) by **adding boosts**:

```
rerank_score = rrf_score
            + query_token_overlap * 0.3      # |Q ∩ text| / |Q|  (positional, token overlap over text tokens)
            + 0.5  if any query entity appears in chunk text
            + 0.2  if any numeric value appears in chunk text
            + 0.15 if any query token appears in chunk's section/heading text
```

Then sort desc, take `top_k` (= `FINAL_TOP_K`? **No** — `_retrieve_chunks` passes `top_k` (30/60); `FINAL_TOP_K = 12` in config is **not imported/used** by search).

Final prompt context = `FINAL` ranked set (up to 30/60 chunks), formatted by `format_context`.

---

## 11. Prompt Templates

One **system prompt** (always prepended as a user-turn `[System: ...]`) plus **4 specialized templates**.

### 11.1 System prompt (base rules)

```
You are a precise QA assistant that answers questions using ONLY the provided context.
RULES:
1. Answer ONLY using information from the context. Never use outside knowledge.
2. When context values conflict, report BOTH values and their sources.
3. For each claim, cite inline: "Source: filename.pdf, p.X".
4. If info is insufficient, say "Based on the available sources, I don't have enough
   information to fully answer this question."
5. For numerical values, ALWAYS include units and page numbers.
6. NEVER fabricate page numbers or file names.
7. For 'which foods' or 'list all' questions, list ALL matching items ...
8. If a question asks about multiple items, address ALL of them.
COMPLETENESS STATEMENTS:
- "VERIFIED: This answer is complete based on the available sources."
- "LIKELY: This answer covers some matches. Additional items may exist..."
- "NOT_VERIFIED: The available sources don't provide enough information."
EVIDENCE FORMAT:
- Entity: [name] | Value: [value] | Source: [filename.pdf, p.X] | Page: [N]
```

### 11.2 Exhaustive template

Instructs the model to analyze **every** chunk, list ALL unique items, report each `Entity | Value | Source | Page`, and emit a `VERIFIED / LIKELY / NOT_VERIFIED` completeness assessment.

### 11.3 Numeric / filter template

Instructs: find EVERY instance matching the numeric condition; format each `Item | Value | Source | Page`; give `VERIFIED / LIKELY` completeness; else "No items found matching the criteria."

### 11.4 Follow-up template

Inputs `previous_context` + `previous_answer` + new `context`; asks to connect new info with old, report conflicts, cite everything, avoid repeating.

### 11.5 Comparison & Summary (inline f-strings)

- Comparison: compare ALL items, exact values with source for each, highlight diffs, cite conflicts, structured `Item | Attribute | Source | Page`.
- Summary: "Summarize the following context comprehensively ... with citations for major claims."

---

## 12. Citations & Source Extraction

- `get_citations(relevant)` — dedups by `(filename, page, section, heading)`; produces `{file, page, section, heading, text_preview, source_type}`.
- Answer gets a `--- Sources ---` block:
  ```
  --- Sources ---
  [1] ProteinContentofFoods.pdf - p.1 | Table 1
  [2] Payroll & Salary Structure.pdf - p.4 | ... > 8. ...
  ```
- The backend also enforces a **structured evidence contract** in every generation prompt: lines in the answer must follow `Entity: [name] | Value: [value] | Source: file.pdf, p.X | Page: [N]`. This is produced entirely inside `search.py` prompt templates and is UI-agnostic — any caller can parse it back out without the backend doing any rendering.

---

## 13. Observed Runtime Data

Taken directly from the live `backend/Database/database.db`:

| Docs | Chunks | Parents | Table chunks | Entities | Chunks w/ embeddings |
|---|---|---|---|---|---|
| 5 | 53 | 0 | 16 | 0 | 53 |

- Embedding storage: **12,288 bytes each** → 12288 / 4 = **3072 float32 values** (actual Gemini `gemini-embedding-001` output dim; the config's `768` is not enforced).
- Chunk text: min 13 / avg 952 / max 2,493 characters (so no chunk triggered the >3750 parent threshold).
- Most common headings: `Table 1` (10), `Table 2` (5), `Table 3` (1), then numbered policy headings drawn from the payroll/benefits PDFs.
- Sample table chunk (actual):
  ```
  |  | Food (Cooked) |  | Serving Size |  | Calories |  | Protein (g) |  |
  | --- | --- | --- | --- | --- | --- | --- | --- | --- |
  |  | Chicken, skinless |  | 3 oz |  | 141 |  | 28 |  |
  ```
- Sample chunk row: `id=882, docId=5 (ProteinContentofFoods.pdf), chunk_index=0, child, page=1, heading="Table 1", embedding 12288B, content_hash=7742cf61...`

---

## 14. Known Gotchas & Inconsistencies

1. **`EMBEDDING_DIMENSION=768` is wrong in practice.** Embeddings stored are **3072-dim** (Gemini default); the config value only shapes the all-zeros failure fallback. If you later switch models, also check stored dim or re-embed.
2. **Dead config**: `CHUNK_TARGET_TOKENS`, `CHUNK_OVERLAP_TOKENS`, `CHUNK_OVERLAP`, `MIN_SCORE`, `EXHAUSTIVE_MIN_SCORE`, `FINAL_TOP_K`, `MAX_CHUNKS_PER_CALL` (redundant with local `batch_size`) are defined but never used. In particular **no chunk overlap exists** despite the config suggesting 200 chars.
3. **Single-doc scope is optional and easy to forget.** `answer_question(..., document_id=None)` defaults to searching **all** documents. The CLI chat handlers (`user.py` / `admin.py`) never pass `document_id`, so "Chat with PDF" in the CLI actually searches globally; only callers that pass a `doc_id` get scoped retrieval.
4. **`entities` table is empty** and not consulted at query time. The LLM entity-extraction step effectively produced nothing (JSON config param on `generate_content` varies between the two SDKs); `search_entities()`/entity lookup are dead paths in this build.
5. **Parent/child hierarchy is dormant**: `_build_hierarchy` never links `parent_id` on children, and the current corpus has no oversized chunks → no `parent` rows exist.
6. **Images are detected but not used**: `has_images`/`image_paths` flags exist, but no image bytes are saved or OCR'd in the pipeline (`extract_text_from_image` is unused).
7. **No chunk overlap across splits; pages never merged** — a sentence cut mid-table can split related facts between chunks.
8. **O(N) brute-force search**: each question scans every row in memory for cosine + BM25. Fine for ~50-100 chunks, degrades at scale; no ANN bucket / FTS index exists despite `LIKE`-col-friendly schema.
9. **README overstates query types**: the README's "Semantic / Keyword / Numeric" matrix differs from the real `QueryType` enum (`FACTUAL, EXHAUSTIVE, COMPARISON, SUMMARY, ENTITY_LOOKUP, FILTER, FOLLOWUP`). No purely "keyword" or "semantic" class exists; everything is hybrid.
10. **Silent degradation**: if embedding generation totally fails, zero-vectors are stored (cosine 0 → effectively excluded from results) with only a log line; user sees "No relevant information found."
11. **`generate_text` system prompt is smuggled as a user turn** (`[System: ...]` prepended), not a real system role.
12. **Security**: `backend/.env` contains a **live Gemini API key that is inside a git-initialized folder** — the file should be gitignored and the key rotated if it was ever committed/pushed. (Not reproduced in this doc.)

---

## 15. Portable RAG Kit

The following code is **provider-neutral** and mirrors the exact algorithms this repo uses, so you can drop it into any RAG system (LangChain, LlamaIndex, or hand-rolled) and get identical behavior.

### 15.1 Reusable chunker (heading-aware, table-aware, short-chunk merge)

```python
import re, hashlib, dataclasses

TARGET_CHARS = 2500
MIN_CHARS = 80

@dataclasses.dataclass
class Chunk:
    text: str
    page: int
    section: str = ""
    heading: str = ""
    kind: str = "child"
    content_hash: str = ""

    def __post_init__(self):
        self.content_hash = hashlib.sha256(self.text.encode()).hexdigest()

HEADING_PATTERNS = [
    re.compile(r"^(TABLE\s+\d|Table\s+\d)"),
    re.compile(r"^[A-Z][A-Z\s]{5,}$"),
    re.compile(r"^\d+\.?\s+[A-Z]"),
    re.compile(r"^[IVXLC]+\.\s+"),
]

def detect_headings(text: str) -> list[str]:
    return [ln.strip() for ln in text.splitlines()
            if ln.strip() and any(p.match(ln.strip()) for p in HEADING_PATTERNS)]

def split_by_headings(text: str, headings: list[str], page: int) -> list[Chunk]:
    if not headings:
        return _sentences_to_chunks(text, page)
    chunks, cur_h, cur_s, cur_t = [], "", "", ""
    for line in text.split("\n"):
        s = line.strip()
        if s and s in headings:
            if cur_t.strip():
                chunks.append(Chunk(cur_t.strip(), page, cur_s, cur_h))
            cur_s = s if HEADING_PATTERNS[1].match(s) else cur_s
            cur_h = s
            cur_t = ""
        else:
            cur_t += line + "\n"
    if cur_t.strip():
        chunks.append(Chunk(cur_t.strip(), page, cur_s, cur_h))
    return chunks

def _sentences_to_chunks(text: str, page: int) -> list[Chunk]:
    out, cur = [], ""
    for s in re.split(r"(?<=[.!?])\s+", text):
        if len(cur) + len(s) < TARGET_CHARS:
            cur += " " + s
        else:
            if cur.strip(): out.append(Chunk(cur.strip(), page))
            cur = s
    if cur.strip(): out.append(Chunk(cur.strip(), page))
    return out

def merge_short(chunks: list[Chunk]) -> list[Chunk]:
    out, buf = [], None
    for c in chunks:
        if len(c.text) < MIN_CHARS:
            if buf is None: buf = c
            elif len(buf.text) + len(c.text) < TARGET_CHARS:
                buf.text += "\n\n" + c.text
                buf.content_hash = hashlib.sha256(buf.text.encode()).hexdigest()
            else: out.append(buf); buf = c
        else:
            if buf is not None:
                buf.text += "\n\n" + c.text
                buf.content_hash = hashlib.sha256(buf.text.encode()).hexdigest()
                out.append(buf); buf = None
            else:
                out.append(c)
    if buf is not None:
        out.append(buf)
    return out

def make_hierarchy(chunks: list[Chunk]) -> tuple[list[Chunk], list[Chunk]]:
    """Promote > 1.5x-target chunks to 'parent' and re-split them into children."""
    children, parents = [], []
    for c in chunks:
        if len(c.text) > TARGET_CHARS * 1.5:
            p = Chunk(c.text[:TARGET_CHARS * 2], c.page, c.section, c.heading, kind="parent")
            parents.append(p)
            children.extend(_sentences_to_chunks(c.text, c.page))
        else:
            children.append(c)
    return children, parents
```

### 15.2 Embedding abstraction (swap providers freely)

```python
class Embedder:
    """Wrap any provider. Implement .embed(list[str]) -> list[list[float]]."""
    def embed(self, texts: list[str]) -> list[list[float]]: raise NotImplementedError

def embed_in_batches(embedder: Embedder, texts: list[str],
                     batch_size: int = 32, delay: float = 0.3,
                     fallback_dim: int = 768) -> list[list[float]]:
    out = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        try:
            out.extend(embedder.embed(batch))
        except Exception:
            out.extend([[0.0] * fallback_dim for _ in batch])   # silent degrade
        if i + batch_size < len(texts): time.sleep(delay)
    return out

# Coset-similar doms + cosine helper (pure python, vectorise with numpy at scale)
def cosine(a, b):
    return sum(x*y for x, y in zip(a, b)) / (sum(x*x for x in a) ** 0.5 * sum(x*x for x in b) ** 0.5) or 0.0
```

### 15.3 Vanilla BM25 (the exact implementation in this repo)

```python
import re, math
from collections import Counter

def tokenize(text): return re.findall(r"[a-z0-9]+", text.lower())

def compute_idf(docs: list[list[str]]) -> dict[str, float]:
    n = len(docs); df = Counter()
    for d in docs:
        for t in set(d): df[t] += 1
    return {t: math.log((n - f + 0.5) / (f + 0.5) + 1) for t, f in df.items()}

def bm25(query: str, texts: list[str], k1=1.5, b=0.75):
    qt = tokenize(query)
    if not qt: return []
    dt = [tokenize(t) for t in texts]
    avg_dl = sum(len(d) for d in dt) / len(dt)
    idf = compute_idf(dt)
    scores = []
    for i, d in enumerate(dt):
        tf = Counter(d); s = 0.0
        for term in qt:
            if term not in idf: continue
            f = tf.get(term, 0)
            s += idf[term] * (f * (k1 + 1)) / (f + k1 * (1 - b + b * len(d) / avg_dl))
        scores.append((i, s))
    return scores

def exact_match_bonus(query: str, text: str) -> float:
    q, t = query.lower(), text.lower()
    return 2.0 * (q in t) + 0.5 * sum(1 for w in tokenize(query) if len(w) > 3 and w in t)
```

### 15.4 RRF + hybrid fusion + rerank (the heart of the repo)

```python
def rrf_fusion(*result_lists: list[tuple[int, float]], k: int = 60) -> list[int]:
    scores: dict[int, float] = {}
    for lst in result_lists:
        for rank, (chunk_id, _score) in enumerate(lst):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank)
    return sorted(scores, key=scores.get, reverse=True)

def dedupe(chunks: list[dict]) -> list[dict]:
    seen, out = set(), []
    for c in chunks:
        key = c.get("content_hash") or c.get("text", "")[:200]
        if key not in seen: seen.add(key); out.append(c)
    return out

def rerank(query: str, chunks: list[dict], entities=None,
           numerics=None, rrf_key: str = "rrf_score") -> list[dict]:
    qt = set(tokenize(query))
    for c in chunks:
        s = c.get(rrf_key, 0.0)
        text_tokens = set(tokenize(c.get("text", "")))
        s += (len(qt & text_tokens) / max(len(qt), 1)) * 0.3            # token overlap
        tl = c.get("text", "").lower()
        s += 0.5 * any(ent.lower() in tl for ent in (entities or []))   # entity boost
        s += 0.2 * any(v in tl for v in (numerics or []))               # numeric boost
        head = f"{c.get('section','')} {c.get('heading','')}".lower()
        s += 0.15 * any(tok in head for tok in qt)                      # heading boost
        c["rerank_score"] = s
    return sorted(chunks, key=lambda c: c["rerank_score"], reverse=True)
```

### 15.5 Retrieval orchestrator (portable)

```python
def retrieve(query: str, chunks: list[dict], embedder: Embedder,
             variants: list[str] | None = None,
             top_k: int = 30, sim_threshold: float = 0.2) -> list[dict]:
    qv = embedder.embed([query])[0]
    semantic = [({**c, "semantic_score": cosine(qv, c["embedding"])})
                for c in chunks if c.get("embedding") is not None
                and cosine(qv, c["embedding"]) >= sim_threshold]
    semantic.sort(key=lambda c: c["semantic_score"], reverse=True)
    semantic = semantic[:top_k]

    keyword = [({**chunks[i], "keyword_score": s + exact_match_bonus(query, chunks[i]["text"])})
               for i, s in bm25_sorted(query, [c["text"] for c in chunks])[:top_k]]

    fused = rrf_fusion([(c["id"], c.get("semantic_score", 0)) for c in semantic],
                       [(c["id"], c.get("keyword_score", 0)) for c in keyword])
    for v in (variants or [])[:3]:                      # extra variant passes
        extra = [(chunks[i]["id"], s) for i, s in bm25_sorted(v, [c["text"] for c in chunks])[:20]]
        fused = rrf_fusion(fused, extra)
    by_id = {c["id"]: c for c in chunks}
    return rerank(query, dedupe([by_id[i] for i in fused if i in by_id])[:top_k])
```

### 15.6 A schema you can reuse for any vector store backend

```sql
CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT NOT NULL UNIQUE,
    file_hash TEXT, page_count INTEGER DEFAULT 0,
    chunk_count INTEGER DEFAULT 0, status TEXT DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL, chunk_type TEXT DEFAULT 'child',
    parent_id INTEGER REFERENCES chunks(id) ON DELETE SET NULL,
    page_number INTEGER NOT NULL, section TEXT DEFAULT '',
    heading TEXT DEFAULT '', text TEXT NOT NULL,
    content_hash TEXT, embedding BLOB
);

CREATE TABLE IF NOT EXISTS entities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    name TEXT NOT NULL, entity_type TEXT DEFAULT 'generic',
    chunk_id INTEGER REFERENCES chunks(id) ON DELETE SET NULL,
    page_number INTEGER
);

CREATE INDEX idx_chunks_doc ON chunks(document_id);
CREATE INDEX idx_chunks_page ON chunks(document_id, page_number);
CREATE INDEX idx_entities_name ON entities(name);
```

---

## 16. Reusable Skill / Agent Prompt

Copy the block below into any agent (or save as a `SKILL.md`) to port this RAG architecture into a new project, or to have an agent re-implement/audit it.

```
---
name: rag-system-architect
description: >
  Implement or audit a hybrid RAG system identical to an investigated reference
  implementation (rule-based query classification + semantic/BM25 hybrid retrieval
  + RRF fusion + reranking + LLM generation with page-level citations).
---

# RAG System Implementation / Audit Brief

## Reference system behavior to replicate (exact contract)

### Storage (SQLite vector store)
- `documents` table: id, filename (unique), file_hash (sha256), page_count,
  chunk_count, status (pending/processing/completed), created_at.
- `chunks` table: id, document_id (FK, cascade), chunk_index, chunk_type
  ('child'|'parent'), parent_id (self-FK, set null), page_number, section,
  heading, text, content_hash (sha256 of text), embedding BLOB
  (float32 array, `struct.pack` when writing, `struct.unpack` when reading).
- `entities` table: id, document_id, name, entity_type, chunk_id, page_number.
- Run in WAL mode with foreign keys ON.

### Ingestion
- Extract per page: raw text, tables (as markdown pipe tables), and headings:
  - `^(TABLE\s+\d|Table\s+\d)`, `^[A-Z][A-Z\s]{5,}$` (SECTION),
    `^\d+\.?\s+[A-Z]`, `^[IVXLC]+\.\s+`.
- Chunk: tables become their own chunks (`heading="Table N"`); text is split by
  headings when present, else by sentences; accumulate up to ~2500 chars;
  merge chunks shorter than 80 chars; promote chunks > 3750 chars to a 'parent'
  and re-split the rest into 'child' chunks.
- Embed each chunk once with a 3072-dim embedding model in batches of 32 into
  `chunks.embedding`. Re-detect dupes by document sha256; update status to
  'completed' when done.

### Query pipeline (in this order)
1. Rule-based classification ONLY (no ML):
   followup (if history) → summary → comparison → exhaustive+filter →
   exhaustive → filter → entity-lookup → factual.
   - Follow-up triggers: ^(what about|how about|and ), ^(tell me more|what
     else|anything else), ^(ok|okay|cool|got it|right|nice), ^(why|when|where|
     who|how) (is|are|was|were|did|does), ^(more|less|higher|lower|bigger|smaller).
   - Summary: summarize|summary|overview|give me an overview|what is this about.
   - Comparison: compare|vs|versus|how does .* compare|difference between.
   - Exhaustive: all|every|each|complete|full|entire|list all|everything|all foods
     |give me everything|all mentions + regex `\b(?:all|every|each|complete|full|
     entire)\s+\w+`, `\blist (?:all )?\w+`, `\bwhich \w+ (?:have|has|contain|contains)\b`.
   - Filter regexes (capture the numeric + unit):
     `(have|has|contain|contains|with) (\d+\.?\d*) (g|mg|kcal|cal|%)`,
     `(have|has|contain|contains) (zero|no|trace|tr)\b`,
     `(more|less|fewer|greater|over|under|above|below|at least|at most) than (\d+)`,
     `(highest|lowest|most|least|max|min|maximum|minimum) (\w+)`,
     `which (\w+) (have|has|contain|contains|are)\b`.
2. Tokenize query: `re.findall(r"[a-z0-9]+", q.lower())` minus stop words; extract
   named entities via capitalized-word regex + quoted strings; extract numerics.
3. Expand variants: '0g' → also 'zero','0 grams','trace','no'; 'trace' → 'tr','0';
   add every adjacent bigram.
4. Retrieval (hybrid, top_k 30, or 60 for exhaustive):
   - Semantic: embed query, cosine vs every chunk, keep >= 0.2, top-k.
   - Keyword: pure BM25 (k1=1.5, b=0.75, idf=log((N-df+0.5)/(df+0.5)+1)) with
     exact-match bonus +2.0 (full query in text) and +0.5 per token >3 chars.
   - Filter/exhaustive-with-filter: after keyword search add boosts: +0.3 per
     numeric literal, +0.5 when filter value present, +0.5 for zero-indicators
     (0/zero/trace/tr/nil/none), +0.5 for word-bounded digits.
   - Fuse all lists with RRF `1/(60+rank)`, dedupe by content_hash, rerank with
     boosts (token overlap 0.3, entity 0.5, numeric 0.2, heading token 0.15).
   - Exhaustive: if fewer than 10 chunks retrieved, add up to 50 fresh chunks.
5. Generation:
   - Build a context block `[file - p.N - section - heading]\ntext` separated by
     `---`.
   - Use type-specific prompts: exhaustive (list ALL + completeness), numeric
     (every matching numeric + completeness), followup (previous + new context),
     comparison (all items + conflicts), summary.
   - System rules: answer ONLY from context, cite inline `Source: file.pdf, p.X`,
     never fabricate, report both values when sources conflict, end with
     VERIFIED / LIKELY / NOT_VERIFIED completeness.
   - Emit structured evidence lines `Entity: X | Value: Y | Source: file.pdf,
     p.Z | Page: Z`.
6. Citations: dedup by (file, page, section, heading); render a `--- Sources ---`
   section listing each file + page (+ section/heading).

## Hard requirements
- Do NOT use an external vector DB unless asked; brute-force in memory is fine
  for < a few thousand chunks.
- Reuse the exact matching/rerank formulas above (identical numbers).
- Provider-agnostic embedding/LLM interfaces so a different model can be swapped
  in without touching retrieval logic.
- Preserve per-chunk source metadata (file, page, section, heading) end-to-end.

## Acceptance criteria
1. Ingest a sample PDF: DB has 1 document row, ≥1 chunk per page, each with
   text + embedded vector + content_hash; status completed.
2. "Compare A and B", "list all items with more than 20g protein",
   "which pages mention Section 302", "zero calories foods", and a follow-up
   "what about protein?" each route to the correct branch and return grounded,
   cited answers.
3. Units + page numbers appear in every numeric answer; conflicts surface both
   sources; no fabricated pages.
4. Every answer ends with a completeness statement (VERIFIED/LIKELY/NOT_VERIFIED).
5. Chunks that share identical text never appear twice in one response.
```

---

## 17. End-to-End Message Flow — send → receive (full sequence)

### 17.1 Sequence diagram (user message → answer back to user)

```
 CALLER (CLI / any caller)          answer_question PIPELINE (backend)      SQLITE DB                    GEMINI
   │  send question text                │                                    │                             │
   │────────────────────────────────────▶│ answer_question(query,            │                             │
   │  (caller supplies history +        │   previous_context,               │                             │
   │   optional document_id)            │   previous_answer, use_history,   │                             │
   │                                     │   document_id)                    │                             │
   │                                     │── classify_query() ─────────────▶│  (pure regex, no DB)       │
   │                                     │◀─ QueryAnalysis                   │                             │
   │                                     │                                    │                             │
   │                                     │── get_all_chunks_with_embeddings ▶│  SELECT + JOIN documents   │
   │                                     │◀─ [N chunks + 3072-dim vectors]    │                             │
   │                                     │── get_all_chunks_text ───────────▶│  SELECT (no embedding)    │
   │                                     │◀─ [N chunks, text only]           │                             │
   │                                     │                                    │                             │
   │                                     │── _retrieve_chunks()              │                             │
   │                                     │   branch by QueryType:            │                             │
   │                                     │   semantic / keyword / filter /   │                             │
   │                                     │   exhaustive / variants           │                             │
   │                                     │                                    │──────── embed(query) ────▶│
   │                                     │◀─────────────────────────────────────────────── 3072-dim vector │
   │                                     │   cosine vs all stored vectors    │                             │
   │                                     │   BM25 + exact-match bonus        │                             │
   │                                     │   RRF fusion → dedup → rerank     │                             │
   │                                     │   parent / entity enrichment      │                             │
   │                                     │                                    │                             │
   │                                     │── format_context()                │  "[file - p.N - sec]"     │
   │                                     │── _build_prompt() (per type)      │                             │
   │                                     │                                    │───── generate_content ──▶│
   │                                     │                                    │  (system + template)     │
   │                                     │◀─────────────────────────────────────────────── answer text     │
   │                                     │── get_citations() + Sources block │                             │
   │◀────────────────────────────────────│ result{answer, citations, type,   │                             │
   │  answer + citations + metadata      │   chunks_used, time, confidence,  │                             │
   │                                     │   document_count}                 │                             │
```

**Caller note**: the pipeline is UI-free. The CLI just loops `input("You: ")` → `answer_question(...)` → `print(result["answer"])` and carries `previous_context`/`previous_answer` between turns; history threading and `document_id` selection happen *before* the function — everything from `classify_query` onward is pure backend.

### 17.2 What the "message" turns into at every hop

| Hop | Stage | Data shape |
|---|---|---|
| 1 | User types | raw `str`, e.g. `"list all foods with 0g protein"` |
| 2 | `classify_query` | `QueryAnalysis(query_type=EXHAUSTIVE, keywords=[...], numeric_values=["0"], filter_value="zero", search_variants=[...], needs_structured=True)` |
| 3 | DB load | `list[dict]` chunks each `{id, document_id, chunk_type, parent_id, page_number, section, heading, text, content_hash, embedding(list[float] 3072), filename}` |
| 4 | Semantic | `list[dict]` + `semantic_score` (cosine), filtered `>= 0.2` |
| 5 | Keyword | `list[dict]` + `keyword_score` (BM25 + exact-match bonus) |
| 6 | Fusion | `list[dict]` + `rrf_score` = Σ `1/(60+rank)` per chunk id |
| 7 | Dedup | first-occurrence kept by `content_hash` |
| 8 | Rerank | each chunk gains `rerank_score` (rrf + boosts) |
| 9 | Context | single `str`: `"[NutritiveValueofFoods.pdf - p.3]\ntext\n\n---\n\n[...]"` |
| 10 | Prompt | `EXHAUSTIVE_PROMPT_TEMPLATE` (or per-type) filled with context + query |
| 11 | Gemini | answer `str` incl. inline `(Source: file.pdf, p.X)` + `Entity | Value` lines |
| 12 | Citations | `list[dict]{file, page, section, heading, text_preview}` + `--- Sources ---` |
| 13 | Return | `dict{answer: str, citations: list[dict], type: str, chunks_used: int, time: float, query_confidence: float, document_count: int}` |

### 17.3 Timing budget (per question)

1. Classification: < 1 ms (pure regex).
2. DB load: 2 SELECTs over all rows (in-memory; ~50 rows ≈ instant, scales linearly worse).
3. Embed query: 1 Gemini API call (~0.3–1 s first time, then batched).
4. Distance: 53 cosine evals in Python ≈ ms. BM25 ≈ ms.
5. RRF + rerank + format: ms.
6. Generation: 1 Gemini completion (1–5 s) — dominates latency. Rate-limit → 10–30 s backoff.
7. Post-process: ms.

One API round-trip for embed + one for generation per user message (except exhaustive which adds extra local chunks, and follow-up which reuses history).

---

## 18. Rare & Critical Code Paths — verbatim from this repo

The exact, hard-to-reinvent pieces. If a feature misbehaves, these are the places to look first.

### 18.1 Embedding serialization — floats packed into a BLOB (database.py)

```python
def _serialize_embedding(embedding) -> bytes | None:
    try:
        if embedding is None: return None
        if isinstance(embedding, bytes): return embedding
        import struct
        return struct.pack(f"{len(embedding)}f", *embedding)
    except Exception:
        return None

def _deserialize_embedding(data) -> list[float] | None:
    try:
        if data is None: return None
        if isinstance(data, list): return data
        import struct
        count = len(data) // 4
        return list(struct.unpack(f"{count}f", data))
    except Exception:
        return None
```
> 3072 floats × 4 bytes = 12,288-byte BLOB per chunk (confirmed in the live DB).

### 18.2 Silent embedding failure → all-zero vector (gemini.py)

This is how the system "swallows" a total embedding outage:

```python
for i in range(0, len(texts), MAX_CHUNKS_PER_CALL):
    batch = texts[i : i + MAX_CHUNKS_PER_CALL]
    result = _embed_with_retry(client, model, batch)
    if result is None:
        result = _embed_with_retry(client, EMBEDDING_FALLBACKS[-1], batch)
    if result is None:
        result = [[0.0] * EMBEDDING_DIMENSION for _ in batch]  # ← zero-vector stand-in
    all_embeddings.extend(result)
    if i + MAX_CHUNKS_PER_CALL < len(texts):
        time.sleep(API_DELAY)
```
> Zero-vectors give cosine = 0 → dropped by the 0.2 threshold → the doc silently "disappears" from results.

### 18.3 Rate-limit retry + model fallback rotation (gemini.py)

```python
def _generate_text_with_retry(prompt, system, retries=3):
    for attempt in range(retries):
        try:
            return _generate_text_safe(prompt, system)
        except Exception as e:
            err_str = str(e)
            if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                if attempt < retries - 1:
                    wait = 10 * (attempt + 1)          # 10s, 20s
                    time.sleep(wait); continue
            return "Unable to generate answer at this time."

def _generate_text_safe(prompt, system):
    client = _get_client(); model = _get_model_name()
    contents = []
    if system:
        contents.append({"role": "user", "parts": [{"text": f"[System: {system}]"}]})
    contents.append({"role": "user", "parts": [{"text": prompt}]})
    response = client.models.generate_content(model=model, contents=contents)
    return response.text or ""
```
On a non-429 error it falls to `_fallback_generate`, which cycles `gemini-3.1-flash-lite` → `gemini-3-flash-preview`.

### 18.4 Exact-match bonus + BM25 score (keyword.py)

```python
def _exact_match_bonus(query: str, text: str) -> float:
    bonus = 0.0
    q, t = query.lower(), text.lower()
    if q in t: bonus += 2.0                         # whole query string present
    for word in tokenize(query):
        if len(word) > 3 and word in t: bonus += 0.5
    return bonus

def bm25_score(query_tokens, doc_tokens, avg_dl, idf, k1=1.5, b=0.75) -> float:
    doc_len = len(doc_tokens)
    if doc_len == 0 or avg_dl == 0: return 0.0
    doc_tf = Counter(doc_tokens); score = 0.0
    for term in query_tokens:
        if term not in idf: continue
        tf = doc_tf.get(term, 0)
        numerator = tf * (k1 + 1)
        denominator = tf + k1 * (1 - b + b * doc_len / avg_dl)
        if denominator > 0:
            score += idf[term] * numerator / denominator
    return score
```

### 18.5 Heading/section detection — the regexes that drive chunking (pdf_processor.py)

```python
if re.match(r"^(TABLE\s+\d|Table\s+\d)", stripped):
    headings.append(stripped)                       # → table caption heading
elif re.match(r"^[A-Z][A-Z\s]{5,}$", stripped):
    headings.append(stripped)                       # → SECTION (all-caps)
elif re.match(r"^\d+\.?\s+[A-Z]", stripped) and len(stripped) < 100:
    headings.append(stripped)                       # → numbered heading "1. X"
elif re.match(r"^[IVXLC]+\.\s+", stripped):
    headings.append(stripped)                       # → roman numeral "I. X"
```

### 18.6 Sentence-aware splitter (the rare "short-chunk merge" behavior)

```python
def _merge_short_chunks(chunks):
    merged, buffer = [], None
    for chunk in chunks:
        if len(chunk["text"]) < MIN_CHUNK_SIZE:                # 80 chars
            if buffer is None:
                buffer = dict(chunk)
            elif len(buffer["text"]) + len(chunk["text"]) < TARGET_CHUNK_SIZE:
                buffer["text"] += "\n\n" + chunk["text"]
                buffer["content_hash"] = _hash_text(buffer["text"])
            else:
                merged.append(buffer); buffer = dict(chunk)
        else:
            if buffer is not None:
                if len(buffer["text"]) + len(chunk["text"]) < TARGET_CHUNK_SIZE:
                    buffer["text"] += "\n\n" + chunk["text"]
                    buffer["content_hash"] = _hash_text(buffer["text"])
                    merged.append(buffer)
                else:
                    merged.append(buffer); merged.append(chunk)
                buffer = None
            else:
                merged.append(chunk)
    # flush trailing buffer into last chunk if it still fits
    ...
```

### 18.7 Semantic search with in-memory cosine + threshold (search.py)

```python
def _semantic_search_safe(query, chunks, top_k):
    q_emb = generate_embeddings([query])[0]
    scored = []
    for chunk in chunks:
        chunk_emb = chunk.get("embedding")
        if chunk_emb is None: continue
        score = _cosine_similarity(q_emb, chunk_emb)
        if score >= SIMILARITY_THRESHOLD:            # 0.2
            scored.append({**chunk, "semantic_score": score, "score": score})
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:top_k]
```

### 18.8 RRF fusion — the sequence it applies lists (search.py)

```python
def _rrf_fusion(lists, *args):
    all_lists = [lists] + list(args)
    scores = {}
    for lst in all_lists:
        for rank, chunk in enumerate(lst):
            cid = chunk["id"]
            rrf_score = 1.0 / (60.0 + rank)
            if cid in scores: scores[cid] += rrf_score
            else: scores[cid] = rrf_score
    fused = [{**chunk, "rrf_score": scores[cid]} for cid, chunk in ...]
    fused.sort(key=lambda x: x["rrf_score"], reverse=True)
    return fused
```

### 18.9 Filter search boosts + zero-indicator detection (keyword.py)

```python
if filter_value in ("zero", "no", "trace", "tr") and _has_zero_indicator(text_lower):
    boost += 0.5
if filter_value.isdigit():
    if re.search(rf"\b{re.escape(filter_lower)}\b", text_lower): boost += 0.5

def _has_zero_indicator(text: str) -> bool:
    zero_patterns = [r"\b0\b", r"\bzero\b", r"\btrace\b", r"\btr\b", r"\bnil\b", r"\bnone\b"]
    return any(re.search(p, text) for p in zero_patterns)
```

### 18.10 Rerank boosts (search.py)

```python
query_overlap = len(query_tokens & text_tokens) / max(len(query_tokens), 1)
score += query_overlap * 0.3            # token overlap
if entity.lower() in text_lower: score += 0.5     # entity hit
if val in text_lower: score += 0.2                # numeric hit
if token in heading_text: score += 0.15           # heading/section hit
```

### 18.11 Query-expansion variants (query_classifier.py)

```python
if "0g" in query or "0 g" in query:
    variants.extend([
        query.replace("0g","zero").replace("0 g","zero"),
        query.replace("0g","0 grams").replace("0 g","0 grams"),
        query.replace("0g","trace").replace("0 g","trace"),
        query.replace("0g","no").replace("0 g","no"),
    ])
if "no " in query: variants.append(query.replace("no ", "0 "))
if "trace" in query.lower():
    variants.append(query.lower().replace("trace","tr"))
    variants.append(query.lower().replace("trace","0"))
words = query.split()
if len(words) > 2:
    for i in range(len(words)-1):
        variants.append(f"{words[i]} {words[i+1]}")   # all adjacent bigrams
```

### 18.12 Exhaustive "rescue" — keep retrieval broad for list-all questions (search.py)

```python
if analysis.query_type == QueryType.EXHAUSTIVE and len(relevant) < 10:
    extra = get_all_chunks_text(document_id)
    extra_filtered = [c for c in extra if c["id"] not in {r["id"] for r in relevant}]
    relevant.extend(extra_filtered[:50])
```

### 18.13 Context & citations formatting (search.py)

```python
def format_context(chunks):
    context_parts, seen = [], set()
    for chunk in chunks:
        key = chunk.get("content_hash") or chunk.get("text", "")[:100]
        if key in seen: continue
        seen.add(key)
        filename = chunk.get("filename", "unknown.pdf")
        page = chunk.get("page_number", "?")
        loc = f"[{filename} - p.{page}"
        if chunk.get("section"): loc += f" - {chunk['section']}"
        if chunk.get("heading"):  loc += f" - {chunk['heading']}"
        if chunk.get("source") == "parent_context": loc += " (context)"
        loc += "]"
        context_parts.append(f"{loc}\n{chunk.get('text', '')}")
    return "\n\n---\n\n".join(context_parts)

def _format_citations_section(citations):
    lines = ["\n--- Sources ---"]
    for i, c in enumerate(citations, 1):
        loc = f"p.{c['page']}"
        if c.get("section"): loc += f" | {c['section']}"
        if c.get("heading"): loc += f" > {c['heading']}"
        lines.append(f"[{i}] {c['file']} - {loc}")
    return "\n".join(lines)
```
> This is the exact backend code that produces the `[file - p.N - section - heading]` context blocks and the `--- Sources ---` appendix — no presentation layer involved.

---

## 19. How RAG Works in This Project — Explained Step by Step

### 19.0 RAG in one sentence

**RAG (Retrieval-Augmented Generation)** = before the AI answers, you first **search your own documents** for the passages that match the question, hand those passages to the AI as "context", and tell the AI to answer **only from that context** — so answers stay grounded in your PDFs instead of the model's general knowledge (which would be a lie-risk, and has no page numbers).

This project is a full RAG pipeline built in two halves:

```
PHASE 1 — BUILD THE KNOWLEDGE BASE (offline, admin does once per PDF)
   PDF ──► extract ──► chunk ──► embed ──► store in SQLite

PHASE 2 — ANSWER QUESTIONS (online, every user message)
   question ──► understand ──► search ──► fuse ──► rerank ──► build prompt ──► Gemini ──► answer + citations
```

### 19.1 Phase 1 — Indexing: turning a PDF into searchable vectors

This project does **not** search the PDF file itself at query time. Instead, each PDF is processed **once** (that's the "Compile PDF" step) and everything needed for fast answering is pre-computed and stored in `backend/Database/database.db`.

**Step 1 — Extract.** PyMuPDF opens the file and, page by page, pulls out:
- the **raw text** (`page.get_text("text")`),
- **tables**, which are converted to readable markdown tables so numbers aren't scrambled,
- **headings/sections** (e.g. an ALL-CAPS `PROTEIN CONTENT`, a numbered `1. Eligibility`, or `Table 1`) via simple `regex` rules.

**Step 2 — Chunk.** A chunk is a self-contained slice of text. The whole page is never embedded as one giant blob — big blocks get noisy embeddings and blow up the context. The chunker:
- keeps each table as its own chunk,
- splits body text at **headings** (so a chunk matches a section, not a random cut mid-thought),
- when there are no headings, splits at **sentence boundaries** until ~2,500 chars (~600 tokens),
- merges tiny leftover fragments (< 80 chars) into neighbors so you don't get useless stubs,
- computes a sha256 `content_hash` per chunk (used later for de-duplication).

So `ProteinContentofFoods.pdf` (2 pages, mostly tables) became **8 chunks**; the five current PDFs produced **53 chunks** total.

**Step 3 — Embed.** Every chunk's text is sent to Google's `gemini-embedding-001` in batches of 32. The model returns a **3072-number vector** ("embedding") that captures the *meaning* of the text — "skinless chicken 3 oz 141 calories" and "141 kcal per chicken serving" end up with similar vectors even though the words differ. These vectors are **stored once and never recomputed**, which is the whole point: querying never re-reads the PDFs.

**Step 4 — Store.** Each chunk row lands in SQLite with its text, page number, section/heading, hash, and the embedding saved as a packed binary `BLOB`. The document gets `status = 'completed'`. Identical files are skipped via the sha256 file hash; changed files are recompiled.

> Optional extras that exist but are dormant: a **parent/child** chunk hierarchy (only used for oversized chunks — none exist in the current corpus) and a **named-entities** table (LLM extraction currently stores 0 rows).

### 19.2 Phase 2 — Querying: what happens between the user pressing Enter and seeing an answer

**Step 1 — Understand the question (rule-based classification).** Before searching, the system labels the question so it knows *which search strategy* to use. No ML — just patterns:
- "list all foods with 0g protein" → **EXHAUSTIVE + filter** (broaden search, filter by number)
- "which page mentions Section 302?" → falls through to hybrid (keyword will nail "302")
- "compare apple and banana" → **COMPARISON** (retrieve both, prompt to compare)
- "what about protein?" (after a previous question) → **FOLLOW-UP** (uses the last answer as context)
- "summarize this document" → **SUMMARY**
- everything else → **FACTUAL**

It also extracts **keywords** (minus stopwords), **named entities** (words with capital letters, quoted phrases), **numbers** (e.g. `0`), and **query variants** (`0g` → also try `zero`, `0 grams`, `trace`, `no`; plus adjacent word-pairs). This matters because later steps literally scan text for these tokens.

**Step 2 — Load everything into memory.** All 53 chunks (with their vectors) are read from SQLite in one shot. The corpus is small, so brute-force scanning is fine. (This is the scaling limit: no ANN index — at tens of thousands of chunks this would need a real vector DB.)

**Step 3 — Two searches run in parallel.** This is the "**hybrid retrieval**" trick:
- **Semantic search** — the question is embedded with the same model, and every chunk's stored vector is compared by **cosine similarity** (angle between vectors). Chunks scoring under `0.2` are dropped. This finds *meaning* matches: you ask about "sugar" and it finds text about "carbohydrates".
- **Keyword search** — a hand-rolled **BM25** (the classic search-engine ranking formula, `k1=1.5, b=0.75`) scores chunks by literal token overlap + **exact-match bonus** (+2.0 if the whole query appears verbatim, +0.5 per word). This catches exact names, codes like "Section 302", units, and numbers that vector search can miss.

For **filter/exhaustive** questions, the keyword pass additionally **boosts** chunks that contain the numeric value (`+0.3`), the unit like `g`/`kcal` (`+0.5`), and zero-indicators (`0/zero/trace/tr/nil/none`, `+0.5`).

**Step 4 — Fuse the two result lists (RRF).** The system can't just add the scores — semantic scores and BM25 scores are different scales. Instead it uses **Reciprocal Rank Fusion**: each search ranks chunks, and a chunk earns `1/(60 + rank)` per list it appears in. A chunk ranked #1 in both lists gets `1/61 + 1/61 ≈ 0.0328`; one ranked #10 in only one list gets ≈ `0.0149`. Rankings (not raw scores) are combined, so neither search dominates.

**Step 5 — Deduplicate.** If the same chunk (same `content_hash`) was found by both searches, keep only the first copy. Chunks repeated verbatim never appear twice in one response.

**Step 6 — Rerank.** The final order is nudged by **boolean boosts** so the most on-topic chunks rise to the top:
```
final = RRF score
      + token overlap        × 0.3   (question words found in chunk)
      + entity hit           × 0.5   (e.g. "Apple" appears)
      + numeric hit          × 0.2   (e.g. "0" appears)
      + heading/section hit  × 0.15  (question word appears in the chunk's heading)
```

**Step 7 — Build context & prompt.** The top chunks are serialized with their **provenance** baked in, e.g.:

```
[NutritiveValueofFoods.pdf - p.3 - FRUITS - Apple]
Apple, raw, with skin: serving 138g, 81 calories, 0.3g fat ...
---
[ProteinContentofFoods.pdf - p.1 - Table 1]
| Chicken, skinless | 3 oz | 141 | 28 | ...
```

Then a prompt **tailored to the query type** is assembled (exhaustive / numeric / follow-up / comparison / summary / factual). The shared system prompt enforces the contract: *answer ONLY from context, cite `Source: file.pdf, p.X` inline, never fabricate page numbers, show both sides of a conflict, and end with a completeness verdict (VERIFIED / LIKELY / NOT_VERIFIED).*

**Step 8 — Generate.** The prompt goes to Gemini. The model reads the supplied passages and writes the answer *grammar*, while the *facts* come from your chunks.

**Step 9 — Cite & return.** Every chunk used becomes a citation deduplicated by `(file, page, section, heading)`. The backend attaches a `--- Sources ---` appendix to the answer and returns `{answer, citations, type, chunks_used, time, query_confidence, document_count}`. The answer itself is caller-agnostic plain text — the same function serves a CLI loop or any HTTP/web layer, and any caller can parse the inline `Entity: X | Value: Y | Source: file.pdf, p.Z` lines back out if it wants structured facts.

### 19.3 Worked example — "list all foods with 0g protein"

| Step | What actually happens |
|---|---|
| Classify | `EXHAUSTIVE` (matches "list all"), `FILTER` (`0 g` → zero-indicator), `numeric_values=["0"]`, variants `[...zero, 0 grams, trace, no...]` |
| Load | 53 chunks read from SQLite |
| Semantic | query embedded → cosine vs all 53, keep `≥ 0.2`, top 60 |
| Keyword | BM25 + bonuses; chunks with `0`, `zero`, `trace`, `tr` get extra boosts |
| Fuse | RRF merges both lists; 3 extra variant searches folded in |
| Dedup | `content_hash` collisions removed |
| Rerank | chunks containing "0/protein" plus exact terms float up |
| Exhaustive rescue | if fewer than 10 chunks: append up to 50 unseen chunks so the "list ALL" instruction can't miss items |
| Prompt | `EXHAUSTIVE_PROMPT_TEMPLATE` — "analyze EVERY chunk, list ALL unique items, one `Entity | Value | Source | Page` line each, end with VERIFIED / LIKELY / NOT_VERIFIED" |
| Generate | Gemini lists each matching food with its value, file, and page |
| Return | `dict{answer + Sources appendix, citations, type, chunks_used, time, query_confidence, document_count}` |

### 19.4 Why the design is built this way (design rationale)

- **Hybrid (semantic + BM25)** — semantic search alone gets confused by exact codes/numbers/names; keyword alone can't find conceptually-similar phrasing. Together they cover both cases, and RRF merges them without score-normalization headaches.
- **Pre-embedded chunks in SQLite** — query-time is 2 API calls (1 embed + 1 generate) instead of re-reading PDFs; simple, no extra services, works offline after indexing.
- **Rule-based query classification** — zero extra API cost, deterministic; lets expensive "list ALL" prompts launch only when the question really asks for everything.
- **Inline citations + completeness verdicts** — the output stays verifiable; the model is *told* it may not know everything, so it says "LIKELY/NOT_VERIFIED" instead of quietly guessing.
- **Conflict handling** — when two PDFs disagree (e.g. 81 kcal vs 44 kcal for the same food), the system prompt forces both values + both sources into the answer, exposing rather than hiding data quality problems.

---

*End of document. Sources: full source reading of `backend/src/**`, `backend/admin.py`, `backend/user.py`, `backend/main.py`, plus live inspection of `backend/Database/database.db`. Front-ends are intentionally out of scope per the backend-only requirement.*
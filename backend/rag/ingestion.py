"""Document ingestion pipeline for RAG.

Turns a PDF (or text file) into searchable chunks stored in ChromaDB:

    PDF -> extract text -> clean -> chunk -> embed -> store in ChromaDB

Also provides helpers to remove a document's chunks (deindex) and to detect
whether an indexed document has changed (via a content fingerprint), so
unchanged PDFs are never re-embedded unnecessarily.
"""
import hashlib
import re
import threading

import chromadb
import pymupdf

from config import CHROMA_COLLECTION, CHROMA_DIR, STORAGE_DIR

from rag.config import GEMINI_EMBED_MODEL
from rag.embeddings import embed_documents

# Rough token estimate: roughly 4 characters per token. Chunk size is tuned to
# stay well under the embedding model's 2048-token input limit.
CHUNK_WORDS = 350
CHUNK_OVERLAP_WORDS = 60

_statuses = {"not_indexed", "indexing", "ready", "error"}

# Cached ChromaDB client and collection (avoid repeated creation).
_chroma_client = None
_chroma_collection = None

# ChromaDB is not thread-safe: all collection access (query/get/upsert/delete)
# must be serialised so parallel background workers never touch it together.
_chroma_lock = threading.RLock()


def chroma_lock():
    """Return a re-entrant lock guarding all ChromaDB collection access.

    Every read (query/get) or write (upsert/delete) against the shared
    collection must hold this lock so concurrent AI requests (each backed by
    their own thread) never hit ChromaDB at the same time.

    Returns: a threading.RLock used as a context manager: ``with chroma_lock():``
    """
    return _chroma_lock


def _client():
    """Return the shared persistent ChromaDB client.

    Returns: a chromadb PersistentClient rooted at the configured Chroma dir.
    """
    global _chroma_client
    with _chroma_lock:
        if _chroma_client is None:
            _chroma_client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    return _chroma_client


def collection():
    """Return (creating if needed) the single ChromaDB collection.

    Returns: the chromadb Collection used to store all HR document chunks.
    """
    global _chroma_collection
    with _chroma_lock:
        if _chroma_collection is None:
            _chroma_collection = _client().get_or_create_collection(name=CHROMA_COLLECTION)
    return _chroma_collection


def file_md5(relative_path):
    """Return a stable fingerprint of a document's file content.

    Used to detect whether an indexed PDF has changed so we only re-embed
    documents that actually changed.

    Takes: relative_path - storage-relative path of the file.
    Returns: a hex md5 digest as a string, or None if the file is missing.
    """
    path = STORAGE_DIR / relative_path

    if not path.is_file():
        return None

    digest = hashlib.md5()

    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(65536), b""):
            digest.update(block)

    return digest.hexdigest()


def text_extractor_for(relative_path):
    """Return the right extraction function for a stored file.

    PDFs are parsed page-by-page with PyMuPDF so page numbers can be tracked
    for citations. Plain text files are read directly.

    Takes: relative_path - storage-relative path of the file.
    Returns: a callable that yields (page_number, page_text) tuples.
    Raises: ValueError if the file type is not supported.
    """
    path = STORAGE_DIR / relative_path
    suffix = path.suffix.lower()

    if suffix == ".txt":
        def read_txt():
            with open(path, "r", encoding="utf-8", errors="ignore") as handle:
                yield 1, handle.read()
        return read_txt

    if suffix == ".pdf":
        def read_pdf():
            with pymupdf.open(path) as document:
                for index in range(document.page_count):
                    yield index + 1, document.load_page(index).get_text()
        return read_pdf

    raise ValueError(f"Unsupported document type for AI: {suffix or 'none'}")


def extract_text(relative_path):
    """Extract per-page text and tables from a stored document.

    Takes: relative_path - storage-relative path of the file.
    Returns: a list of (page_number, prose_text, table_markdowns) tuples.
             ``prose_text`` is the page text with table regions removed so the
             prose chunks never duplicate the (already clean) table chunks.
             ``table_markdowns`` is a list of markdown pipe-table strings for
             the tables detected on that page (empty for text files).
    """
    extractor = text_extractor_for(relative_path)
    pages = []

    for page_number, text in extractor():
        prose, tables = _page_split(relative_path, page_number, text)
        if not prose and not tables:
            continue
        pages.append((page_number, prose, tables))

    return pages


def _page_split(relative_path, page_number, raw_text):
    """Split a page's raw text into (non-table prose, markdown tables).

    For PDFs this uses PyMuPDF's layout analysis: words that fall inside a
    detected table's bounding box are removed from the prose and the table is
    rendered as a clean markdown pipe table. This prevents the table body from
    being double-indexed as both a markdown chunk and messy prose.
    """
    path = STORAGE_DIR / relative_path
    if path.suffix.lower() != ".pdf":
        return clean_text(raw_text), []

    try:
        with pymupdf.open(path) as document:
            page = document.load_page(page_number - 1)
            tables = page.find_tables()
            table_bboxes = [t.bbox for t in tables.tables]
            markdowns = [_table_to_markdown(t) for t in tables.tables]

            # Collect words NOT inside any table bbox.
            words = page.get_text("words")
            kept = []
            for x0, y0, x1, y1, word, *_ in words:
                inside = any(
                    x0 >= b[0] - 2 and y0 >= b[1] - 2 and x1 <= b[2] + 2 and y1 <= b[3] + 2
                    for b in table_bboxes
                )
                if not inside:
                    kept.append(word)

            prose = clean_text(" ".join(kept)) if kept else ""
            return prose, [md for md in markdowns if md]
    except Exception:
        return clean_text(raw_text), []


def _table_to_markdown(table) -> str:
    """Render a PyMuPDF table as a clean markdown pipe table.

    ``Table.to_markdown()`` fills spanned columns with placeholder names
    (``Col1``, ``Col3``, …) and pads every row with empty cells, which leaks
    into retrieved chunks and makes the model echo bogus "unknown columns".
    This rebuilds the table from ``table.extract()``:
      1. drops columns that are empty in every row (the placeholder columns),
      2. merges single-cell span notes (e.g. "(1% fat)") into the preceding row,
      3. emits a compact header + data pipe table with no junk cells.
    """
    rows = [
        [str(c).strip() if c is not None else "" for c in (row if isinstance(row, list) else [row])]
        for row in table.extract()
    ]
    if not rows:
        return ""

    width = max(len(r) for r in rows)
    padding = [""] * width

    def get(row, col):
        return row[col] if col < len(row) else ""

    # 1. Keep only columns that hold content in at least one row.
    keep = [
        col
        for col in range(width)
        if any(get(r, col) for r in rows)
    ]
    trimmed = [[get(r, col) for col in keep] for r in rows]

    # 2. Merge single-cell span notes into the previous row's first cell so
    #    "Cottage Cheese" + "(1% fat)" become "Cottage Cheese (1% fat)".
    finalized = [trimmed[0]] if trimmed else []
    for row in trimmed[1:]:
        non_empty = [(i, c) for i, c in enumerate(row) if c]
        if len(non_empty) == 1 and finalized:
            idx, text = non_empty[0]
            if not text.startswith(("[", "#")):
                finalized[-1][0] = (finalized[-1][0] + " " + text).strip()
                continue
        finalized.append(row)

    # 3. Emit the markdown table.
    header = finalized[0] if finalized else []
    if not header:
        return ""
    lines = ["| " + " | ".join(header) + " |"]
    lines.append("|" + "---|" * len(header))
    for row in finalized[1:]:
        cells = row[:len(header)] + [""] * (len(header) - len(row))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def clean_text(text):
    """Normalise raw extracted text so chunks are clean and consistent.

    Removes excessive whitespace, page-break junk, and repeated blank lines
    while keeping paragraph structure for meaningful chunking.

    Takes: text - the raw text.
    Returns: the cleaned text.
    """
    if not text:
        return ""

    # Collapse form-feed characters (PyMuPDF uses them between pages).
    text = text.replace("\x0c", " ")

    # Normalise a run of any whitespace to a single space within a line.
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    lines = [line for line in lines if line]

    # Drop noisy junk lines (copyright/replacement chars, lone punctuation).
    lines = [ln for ln in lines if not re.fullmatch(r"[©\uFFFD\s•\-_~#*]+", ln)]

    # Join into paragraphs separated by blank lines.
    return "\n\n".join(lines)
    return "\n\n".join(lines)


def chunk_text(pages):
    """Split per-page text and tables into semantic, structure-preserving chunks.

    This mirrors the reference RAG system's heading- and table-aware chunker:

      * Each detected table becomes its own chunk rendered as a clean markdown
        pipe table, so the entire row (``| Chicken, skinless | 3 oz | 141 | 28 |``)
        stays together — a query for "protein in chicken" can match both the
        food name and its value in one chunk.
      * Text is split on detected headings (ALL-CAPS sections, numbered and
        roman headings, "Table N" captions) when present; heading and section
        are carried as metadata for scoring and context.
      * Short fragments (< ``CHUNK_MERGE_MIN`` chars) are merged into the next
        chunk so we don't index throwaway two-word scraps separately.
      * Plain text (no tables / headings) is chunked on sentence boundaries up
        to the target word budget, with a small overlap for continuity.

    Takes: pages - a list of (page_number, cleaned_text, table_markdowns) tuples.
    Returns: a list of dicts: {"text","page","heading","section"}.
    """
    chunks = []

    for page_number, page_text, table_markdowns in pages:
        # ── 1. Tables → one markdown chunk each ─────────────────────────
        table_chunks = [
            {
                "text": t,
                "page": page_number,
                "heading": _table_caption(t),
                "section": "",
            }
            for t in table_markdowns
        ]

        # ── 2. Heading-aware text chunks (exclude table blocks) ─────────
        raw_lines = [ln.strip() for ln in page_text.split("\n")]
        headings = _detect_headings(raw_lines)
        text_chunks = _split_by_headings(
            [ln for ln in raw_lines if ln], headings, page_number,
        )

        merged = _merge_short_chunks(table_chunks + text_chunks)

        for part in merged:
            text = (part.get("text") or "").strip()
            if not text:
                continue
            chunks.append({
                "text": text,
                "page": part.get("page", page_number),
                "heading": part.get("heading") or "",
                "section": part.get("section") or "",
            })

    return chunks


# ── Table + heading helpers (reference RAG schema) ──────────────────────────

def _table_caption(markdown: str) -> str:
    """Best-effort caption for a markdown table, e.g. 'Table: Protein (g)'."""
    lines = [ln for ln in markdown.splitlines() if ln.strip().startswith("|")]
    if not lines:
        return "Table"
    header = lines[0].strip()
    cells = [c.strip() for c in header.strip("|").split("|")]
    skip = {"col1", "col3", "col5", "col7", "col9", ""}
    meaningful = [c for c in cells if c.lower() not in skip]
    return ("Table: " + " | ".join(meaningful))[:120]


_HEADING_PATTERNS = (
    (re.compile(r"^TABLE\s+\d|^Table\s+\d"), "table"),
    (re.compile(r"^[A-Z][A-Z\s]{5,}$"), "section"),
    (re.compile(r"^\d+\.?\s+[A-Z]"), "heading"),
    (re.compile(r"^[IVXLC]+\.\s+"), "heading"),
)


def _detect_headings(lines):
    """Return dict of normalized heading line → kind ('table'|'section'|'heading')."""
    found = {}
    for line in lines:
        if not line:
            continue
        for pattern, kind in _HEADING_PATTERNS:
            if pattern.match(line):
                found.setdefault(line, kind)
                break
    return found


def _split_by_headings(lines, headings, page_number):
    """Split page lines into chunks grouped under their nearest heading."""
    if not headings:
        return _sentences_to_chunks("\n".join(lines), page_number)

    chunks = []
    current_heading = ""
    current_section = ""
    current_text = ""
    current_page = page_number

    for line in lines:
        if line in headings:
            if current_text.strip():
                chunks.append({
                    "text": current_text.strip(),
                    "page": current_page,
                    "heading": current_heading,
                    "section": current_section,
                })
            kind = headings[line]
            if kind == "section":
                current_section = line
                current_heading = ""
            else:
                current_heading = line
            current_text = ""
            current_page = page_number
        else:
            current_text += line + "\n"
            current_page = page_number

    if current_text.strip():
        chunks.append({
            "text": current_text.strip(),
            "page": current_page,
            "heading": current_heading,
            "section": current_section,
        })

    return chunks


_CHUNK_WORDS = 200         # target words per chunk for plain text
_CHUNK_OVERLAP_WORDS = 40  # word overlap between consecutive plain chunks
CHUNK_MERGE_MIN = 80       # chars; fragments shorter than this get merged


def _sentences_to_chunks(text, page_number):
    """Chunk plain text on sentence boundaries (no headings/tables)."""
    sentences = re.split(r"(?<=[.!?])\s+", text)
    chunks = []
    cur_words = []

    def flush():
        if cur_words:
            chunks.append({
                "text": " ".join(cur_words).strip(),
                "page": page_number,
                "heading": "",
                "section": "",
            })

    for sentence in sentences:
        if not sentence.strip():
            continue
        words = sentence.split()
        if cur_words and len(cur_words) + len(words) > _CHUNK_WORDS:
            flush()
            # Overlap: carry the tail of the completed chunk into the next one.
            carried = cur_words[-_CHUNK_OVERLAP_WORDS:][:] if _CHUNK_OVERLAP_WORDS else []
            cur_words = list(carried)
        cur_words.extend(words)

    flush()
    return chunks


def _merge_short_chunks(chunks):
    """Merge fragments shorter than ``CHUNK_MERGE_MIN`` into the following chunk.

    Table chunks are never merged (they are self-contained). Returns a new list.
    """
    merged = []
    pending = None

    for part in chunks:
        text = part.get("text") or ""
        is_short = len(text.strip()) < CHUNK_MERGE_MIN
        is_table = bool(part.get("heading", "").startswith("Table"))

        if is_short and not is_table:
            if pending is None:
                pending = dict(part)
            else:
                pending["text"] = pending["text"] + "\n\n" + text
                pending["page"] = part.get("page", pending.get("page"))
        else:
            if pending is not None:
                merged.append(dict(pending))
                pending = None
            if is_short and is_table:
                merged.append(dict(part))
            else:
                merged.append(dict(part))

    if pending is not None:
        merged.append(dict(pending))

    return merged


def index_document(document, report_status=None):
    """Index a single document into ChromaDB.

    Extracts, cleans, and chunks the PDF, embeds the chunks, and stores them
    with rich metadata so retrieval can filter and cite by document, category,
    and page.

    Takes: document - a Document ORM object (must have file/name/category and
                      document_id).
           report_status - optional callable(status) for progress reporting.
    Returns: the number of chunks indexed.
    Raises: ValueError/OSError on unsupported or unreadable files so the caller
            can mark the document as having an error.
    """
    if report_status:
        report_status("indexing")

    chunks = []
    pages = extract_text(document.file)

    # If the PDF produced no readable text (e.g. scanned images), treat as an
    # error rather than silently indexing nothing.
    if not pages:
        raise ValueError("No readable text found in this document")

    chunks = chunk_text(pages)
    texts = [chunk["text"] for chunk in chunks]

    if not texts:
        raise ValueError("No usable content found in this document")

    embeddings = embed_documents(texts)

    ids = [f"{document.document_id}:{i}" for i in range(len(chunks))]
    metadatas = []

    for i, chunk in enumerate(chunks):
        metadatas.append({
            "document_id": document.document_id,
            "document_name": document.name,
            "category": document.category,
            "source_file": document.file,
            "page": chunk["page"],
            "chunk_index": i,
            "heading": chunk.get("heading", "") or "",
            "section": chunk.get("section", "") or "",
            "embedding_model": GEMINI_EMBED_MODEL,
            "fingerprint": file_md5(document.file),
        })

    # Re-insert atomically in one batched upsert. ChromaDB deduplicates by id,
    # so unchanged chunks are replaced, not duplicated.
    with chroma_lock():
        collection().upsert(
            ids=ids,
            documents=texts,
            embeddings=embeddings,
            metadatas=metadatas,
        )

    return len(chunks)


def deindex_document(document_id):
    """Remove every chunk belonging to a document from ChromaDB.

    Takes: document_id - the id of the document to remove.
    Returns: the number of chunks removed (0 if none existed).
    """
    with chroma_lock():
        result = collection().delete(where={"document_id": document_id})

    # ChromaDB's delete returns a result object exposing how many records it
    # removed; fall back to 0 for older/simpler responses.
    if isinstance(result, dict):
        return result.get("deleted") or 0

    try:
        return getattr(result, "deleted", 0) or 0
    except (AttributeError, TypeError):
        return 0


def is_indexed(document_id):
    """Check whether any chunks exist in ChromaDB for a document.

    Takes: document_id - the document id to check.
    Returns: True if at least one chunk is present, False otherwise.
    """
    with chroma_lock():
        result = collection().get(where={"document_id": document_id})
    return bool(result.get("ids"))


def indexed_fingerprints(document_id):
    """Return the set of file fingerprints stored for a document.

    Takes: document_id - the document id to inspect.
    Returns: a set of fingerprint strings (usually one, but can be more).
    """
    with chroma_lock():
        result = collection().get(
            where={"document_id": document_id},
            include=["metadatas"],
        )
    return {meta.get("fingerprint") for meta in (result.get("metadatas") or [])}


def normalize_status(status):
    """Return a canonical indexing status.

    Guards against stray values so the UI always sees one of the known states.

    Takes: status - a raw status string.
    Returns: a value from {"not_indexed","indexing","ready","error"}.
    """
    return status if status in _statuses else "not_indexed"

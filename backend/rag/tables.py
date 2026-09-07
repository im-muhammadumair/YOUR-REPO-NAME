"""Deterministic Markdown table normalisation for generated RAG answers.

The LLM reliably gets the *content* right but sometimes emits a structurally
inconsistent table (jagged rows, a heading/source line stuffed inside the
table, placeholder columns like ``Col3``, or an extra trailing cell). This
module repairs the *presentation* of generated tables without changing the RAG
pipeline: it never invents, drops, swaps, or reorders values.

Repairs applied to every detected table block:
  1. Recognise the header row (the row above the ``---`` separator, or the
     first row when no separator is present).
  2. Drop rows that are clearly prose/headings/source notes disguised as data
     (e.g. a single non-numeric cell like "Source: Protein, page 1") and re-
     emit them as ordinary paragraphs outside the table.
  3. Sanitise placeholder cells (``Col1``/``Col3``/``**bold**`` markers).
  4. Snap every data row to the header width - shorter rows are padded (values
     preserved), longer rows have the surplus non-tabular cells removed.
  5. Drop columns that are empty in every row (leftovers from spanned cells).
  6. Rebuild a clean pipe table with a ``---`` separator.
"""
from __future__ import annotations

import re

_SEPARATOR_CELL = re.compile(r"^:?-{2,}:?$")
_PLACEHOLDER_CELL = re.compile(r"^(?:col\d+|__+)$", re.IGNORECASE)
_PROSE_FIRST_CELL = re.compile(
    r"^\s*(?:"
    r"source\b|based\s+on|note\b|completeness|confidence|"
    r"here\s+is|the\s+(?:following|table|list)\b|list\s+of|table\s+of|"
    r"below\s+is|above\s+is|page\s*\d|p\.?\s*\d|instruction|summary|"
    r"overview|title\b|heading\b|totals?\b"
    r")[:,. ]",
    re.IGNORECASE,
)


def split_row(line: str) -> list[str]:
    """Split a pipe-table line into trimmed cell strings."""
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _clean_cell(cell: str) -> str:
    """Strip emphasis/spacing markers from a single cell's text."""
    return cell.replace("**", "").replace("__", "").strip()


def _is_separator(cells: list[str]) -> bool:
    return bool(cells) and all(_SEPARATOR_CELL.match(c) for c in cells)


def _looks_like_data_row(cells: list[str], header_width: int) -> bool:
    """True when a row carries actual tabular data rather than stray prose.

    A row that has content in only its first cell while the header is wider
    and the cell reads like a sentence/heading/source note is treated as
    prose, not data. Multi-cell rows are always kept.
    """
    non_empty = [c for c in cells if c and not _PLACEHOLDER_CELL.match(c)]
    if not non_empty:
        return False
    if header_width >= 2 and len(non_empty) == 1:
        first = non_empty[0]
        if _PROSE_FIRST_CELL.match(first) or first.endswith(":"):
            return False
        if len(first) > 45:  # long sentence stuffed into one cell
            return False
        if re.fullmatch(r"(?:page|p)\s*\d+", first, re.IGNORECASE):
            return False
    return True


def _to_markdown(header: list[str], rows: list[list[str]]) -> str:
    lines = ["| " + " | ".join(header) + " |"]
    lines.append("|" + "---|" * len(header))
    for row in rows:
        line_cells = row[: len(header)] + [""] * (len(header) - len(row))
        lines.append("| " + " | ".join(line_cells) + " |")
    return "\n".join(lines)


_CONTINUATION_CELL = re.compile(r"^(?:\([^)]*\)|\d*[a-z]?\.?continued\b|cont\.?)$", re.IGNORECASE)


def _is_prose_cell(cell: str) -> bool:
    """True when a cell reads like a heading/intro/source note, not a label.

    Used to prune sentences the model mistakenly placed into the header row,
    e.g. "Here is the table showing ...:" merged into the first header cell.
    """
    c = cell.strip()
    if not c:
        return False
    return bool(_PROSE_FIRST_CELL.match(c))


def _prose_text(cells: list[str]) -> str:
    return "  ".join(c.strip() for c in cells if c.strip())


def _normalise_block(lines: list[str]) -> str | None:
    """Turn one candidate table block into a cleaned table + stray prose lines."""

    parsed = [split_row(line) for line in lines if line.strip()]
    parsed = [cells for cells in parsed if any(c.strip() for c in cells)]
    if not parsed:
        return None

    seps = [i for i, c in enumerate(parsed) if _is_separator(c)]
    sep_set = set(seps)

    leading_prose: list[str] = []

    def header_keep(header_cells: list[str]) -> tuple[list[int], list[str]]:
        """Col indices to keep; stray heading/intro cells are returned as prose."""
        keep: list[int] = []
        prose: list[str] = []
        for i, cell in enumerate(header_cells):
            c = cell.strip()
            if not c or _PLACEHOLDER_CELL.match(c):
                continue
            if _is_prose_cell(c):
                prose.append(c)
                continue
            keep.append(i)
        return keep, prose

    # The header is the row directly above a separator (try each; the model may
    # have inserted a stray heading row first). Fall back to the first row that
    # plausibly is a header.
    header_row_idx: int | None = None
    keep: list[int] = []
    header_cells: list[str] = []
    dropped_header_prose: list[str] = []
    seen_headers: set[int] = set()
    for s in seps:
        idx = s - 1
        if idx < 0 or idx in seen_headers:
            continue
        seen_headers.add(idx)
        k, prose = header_keep(parsed[idx])
        if k:
            header_row_idx, keep, header_cells = idx, k, parsed[idx]
            dropped_header_prose = prose
            break
    if header_row_idx is None and 0 not in seen_headers:
        k, prose = header_keep(parsed[0])
        if k:
            header_row_idx, keep, header_cells = 0, k, parsed[0]
            dropped_header_prose = prose
    if header_row_idx is None:
        # No row above a separator looks like a header: promote the first
        # non-separator row with real content.
        for idx, cells in enumerate(parsed):
            if idx in sep_set:
                continue
            if len([c for c in cells if c.strip()]) < 2:
                continue
            k, prose = header_keep(cells)
            if k:
                header_row_idx, keep, header_cells = idx, k, cells
                dropped_header_prose = prose
                break

    if header_row_idx is None or not keep:
        return None  # nothing tabular left; keep the block as plain text

    # Lines above the real header are stray headings/intros (one place each).
    for r in parsed[:header_row_idx]:
        if not _is_separator(r) and any(c.strip() for c in r):
            t = _prose_text(r)
            if t and t not in leading_prose:
                leading_prose.append(t)
    for c in dropped_header_prose:
        if c and c not in leading_prose:
            leading_prose.append(c)

    header = [_clean_cell(header_cells[i]) for i in keep]
    width = len(header)
    raw_header_len = len(header_cells)
    dropped_positions = set(range(raw_header_len)) - set(keep)

    def masked(cells: list[str]) -> list[str]:
        length = len(cells)
        if length == width:
            # Data matches the surviving header width 1:1 (the model merged a
            # heading into the header row only).
            return [_clean_cell(cells[j]) if j < length else "" for j in range(width)]
        if length == raw_header_len:
            # Data mirrors the full header incl. placeholder columns.
            if not any(cells[i].strip() for i in dropped_positions if i < length):
                return [_clean_cell(cells[orig]) for orig in keep]
            return [_clean_cell(cells[j]) if j < length else "" for j in range(width)]
        return [_clean_cell(cells[j]) if j < length else "" for j in range(width)]

    class_rows = [
        r for r in parsed[header_row_idx + 1:] if not _is_separator(r)
    ]

    # Classify data vs prose rows. Prose/source rows slipped inside the table
    # are re-emitted outside it (nothing is discarded).
    data_rows: list[list[str]] = []
    prose_rows: list[list[str]] = []
    for cells in class_rows:
        m = masked(cells)
        if _looks_like_data_row(m, width):
            data_rows.append(m)
        else:
            prose_rows.append(cells)

    if not data_rows:
        return None

    # Merge lone continuation cells ("(1% fat)" after "Cottage Cheese") into
    # the previous row's first column instead of keeping a padded blank row.
    merged: list[list[str]] = []
    for row in data_rows:
        non_empty = [c for c in row if c]
        if (
            len(non_empty) == 1 and merged and _CONTINUATION_CELL.match(non_empty[0])
        ):
            if merged[-1][0]:
                merged[-1][0] = merged[-1][0] + " " + non_empty[0]
            continue
        merged.append(row)
    data_rows = merged

    # Drop columns that ended up empty everywhere (spanned-cell leftovers).
    occupied = [
        c for c in range(width)
        if header[c] or any(r[c] for r in data_rows)
    ]
    if not occupied:
        return None
    header = [header[c] for c in occupied]
    data_rows = [[r[c] for c in occupied] for r in data_rows]

    text = _to_markdown(header, data_rows)
    if prose_rows:
        text += "\n\n" + "\n".join(
            "  ".join(c for c in (_clean_cell(cell) for cell in cells) if c)
            for cells in prose_rows
        )
    if leading_prose:
        text = "\n\n".join(leading_prose) + "\n\n" + text
    return text


def normalize_answer_tables(text: str) -> str:
    """Normalise every Markdown table in a generated answer.

    Non-table content is returned byte-for-byte untouched.
    """
    if not isinstance(text, str) or "|" not in text:
        return text

    out_lines: list[str] = []
    buffer: list[str] = []
    in_table = False

    def flush():
        nonlocal buffer
        if not buffer:
            return
        normalised = _normalise_block(buffer)
        if normalised is not None:
            out_lines.append(normalised)
        else:
            out_lines.extend(buffer)
        buffer = []

    for line in text.split("\n"):
        has_pipe = "|" in line
        if has_pipe:
            buffer.append(line)
            in_table = True
        else:
            if in_table:
                flush()
                in_table = False
            out_lines.append(line)

    if in_table:
        flush()

    return "\n".join(out_lines).rstrip("\n")


# ── Inline source citation repair ──────────────────────────────────────────

_CITATION_RE = re.compile(r"\(\s*\*([^*]+?)\*\s*,?\s*([^()]*?)\s*\)")
_PAGE_MARK = re.compile(r"(?i)\b(page[s]?|p\.?)\b")


def _doc_pages_from_chunks(chunks) -> dict[str, list]:
    """Map each source document name to the real pages the chunks came from."""
    doc_pages: dict[str, list] = {}
    for chunk in chunks:
        name = chunk.get("document_name") or chunk.get("document_id")
        if not name:
            continue
        page = chunk.get("page")
        pages = doc_pages.setdefault(name, [])
        if page is not None and page not in pages:
            pages.append(page)
    return doc_pages


def _strip_non_alnum(text: str) -> str:
    return re.sub(r"[^0-9a-z]+", "", text.lower())


def _match_doc(name: str, doc_pages: dict[str, list]):
    norm = _strip_non_alnum(name or "")
    if not norm:
        return None, None
    for real_name, pages in doc_pages.items():
        real_norm = _strip_non_alnum(real_name)
        if norm in real_norm or real_norm in norm:
            return real_name, pages
    return None, None


def _format_pages(pages: list) -> str:
    values = sorted(int(p) for p in pages if str(p).isdigit())
    if not values:
        return ""
    if len(values) == 1:
        return f"page {values[0]}"
    return "pages " + ", ".join(str(v) for v in values[:-1]) + f" and {values[-1]}"


def repair_inline_sources(answer: str, chunks) -> str:
    """Cross-check and correct the inline citations in a generated answer.

    The model sometimes cites a document page that was not in the retrieval
    result, leaves the page blank, or cites a writer's name instead of the
    document. This function rewrites every ``(*Document*, page N)`` style
    citation so its page numbers are exactly the pages that were actually
    retrieved for that document. Unverifiable citations (writer names, unknown
    documents) are reduced to plain text so no wrong source is presented.

    Non-citation text is returned unchanged.
    """
    if not isinstance(answer, str) or "<" in answer:
        return answer

    doc_pages = _doc_pages_from_chunks(chunks or [])
    if not doc_pages:
        return answer

    def replace(match: re.Match) -> str:
        italic = (match.group(1) or "").strip()
        tail = (match.group(2) or "").strip()

        page_claim = ""
        page_mark = _PAGE_MARK.search(italic)
        if page_mark:
            doc_text = italic[: page_mark.start()].rstrip(", ").strip()
            page_claim = italic[page_mark.start() :]
        else:
            doc_text = italic
            page_claim = tail

        real_name, real_pages = _match_doc(doc_text, doc_pages)

        if real_name is None:
            return doc_text

        claimed = [int(n) for n in re.findall(r"\d+", page_claim or "")]
        reliable = [p for p in claimed if p in real_pages]

        if reliable:
            pages = reliable
        else:
            pages = real_pages

        formatted = _format_pages(pages)
        if not formatted:
            return f"(*{real_name}*)"
        return f"(*{real_name}*, {formatted})"

    return _CITATION_RE.sub(replace, answer)
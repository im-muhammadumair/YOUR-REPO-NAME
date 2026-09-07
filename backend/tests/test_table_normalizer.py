"""Deterministic Markdown-table normalisation for generated RAG answers.

Covers malformed-table repairs (column count, heading/source rows inside the
table, placeholder columns, continuation cells) and guarantees that correct
non-table text is returned unchanged.
"""
import pytest

from rag.tables import normalize_answer_tables, repair_inline_sources


def _table(header, rows, separator=True):
    lines = ["| " + " | ".join(header) + " |"]
    if separator:
        lines.append("|" + "---|" * len(header))
    lines += ["| " + " | ".join(row) + " |" for row in rows]
    return "\n".join(lines)


def _data_rows(out):
    lines = out.split("\n")
    for i, l in enumerate(lines):
        if l.strip().startswith("|--"):
            return [x for x in lines[i + 1:] if x.strip() and x.strip().startswith("|")]
    return []


HEADER4 = ["Food", "Serving Size", "Calories", "Protein (g)"]
HEADING = ("Here is the table showing 5 foods with the lowest amount of protein "
           "based on the provided documents:")


@pytest.mark.parametrize("bad", [
    # Intro sentence merged into the FIRST CELL of the header row (reported bug
    # seen in long chat messages). Data rows have no heading column.
    (
        _table([HEADING, "Food", "Serving Size", "Calories", "Protein (g)"],
               [["Spinach, cooked", "1/2 cup", "41", "3"],
                ["Quinoa", "1/2 cup", "111", "4"]])
    ),
    # Intro sentence as its own row above a too-narrow separator, with the
    # real header promoted from below.
    (
        f"| {HEADING} |\n"
        "|---|---|\n"
        "| Food | Serving Size | Calories | Protein (g) |\n"
        "| Spinach, cooked | 1/2 cup | 41 | 3 |\n"
        "| Quinoa | 1/2 cup | 111 | 4 |\n"
    ),
    # Intro row above a one-cell separator plus repeated separator rows inside
    # the data (common when the model re-emits the separator after each row).
    (
        f"| {HEADING} |\n"
        "|---|\n"
        "| Food | Serving Size | Calories | Protein (g) |\n"
        "|---|---|---|---|\n"
        "| Spinach, cooked | 1/2 cup | 41 | 3 |\n"
        "|---|---|---|---|\n"
        "| Quinoa | 1/2 cup | 111 | 4 |\n"
    ),
])
def test_heading_stays_outside_the_table(bad):
    """The intro sentence must never land inside a table cell or row."""
    out = normalize_answer_tables(bad)
    assert HEADING in out                      # heading preserved as prose
    assert out.index(HEADING) < out.index("| Food |")  # and placed before table
    data_lines = _data_rows(out)
    assert data_lines == [
        "| Spinach, cooked | 1/2 cup | 41 | 3 |",
        "| Quinoa | 1/2 cup | 111 | 4 |",
    ]


def test_heading_in_header_cell_plus_source_row():
    raw = _table([HEADING, "Food", "Serving Size", "Calories", "Protein (g)"],
                 [["Spinach, cooked", "1/2 cup", "41", "3"],
                  ["Quinoa", "1/2 cup", "111", "4"],
                  ["Source: Protein, page 1", "", "", "", ""]])
    out = normalize_answer_tables(raw)
    # heading and source are prose, kept outside the table's pipe rows
    assert HEADING in out
    assert out.index(HEADING) < out.index("| Food |")
    assert "Source: Protein, page 1" in out
    assert "Source: Protein, page 1" not in out.split("|")[1]
    # values aligned and intact
    assert _data_rows(out) == [
        "| Spinach, cooked | 1/2 cup | 41 | 3 |",
        "| Quinoa | 1/2 cup | 111 | 4 |",
    ]


@pytest.mark.parametrize("bad,expected_good", [
    # Heading row accidentally placed inside the table.
    (
        _table(HEADER4, [["HERE IS THE TABLE OF INGREDIENTS", "", "", ""],
                         ["Spinach, cooked", "1/2 cup", "41", "3"]]),
        [["Spinach, cooked", "1/2 cup", "41", "3"]],
    ),
    # Source line stuffed into the last table row.
    (
        _table(HEADER4, [["Spinach, cooked", "1/2 cup", "41", "3"],
                         ["Source: Protein, page 1", "", "", ""]]),
        [["Spinach, cooked", "1/2 cup", "41", "3"]],
    ),
    # Jagged rows: a missing cell and an extra trailing cell.
    (
        _table(HEADER4, [["Spinach, cooked", "1/2 cup", "41", "3"],
                         ["Quinoa", "111", "4"],
                         ["Green Peas", "1/2 cup", "59", "4", "extra"]]),
        [["Spinach, cooked", "1/2 cup", "41", "3"],
         ["Quinoa", "111", "4", ""],
         ["Green Peas", "1/2 cup", "59", "4"]],
    ),
    # Placeholder columns (Col1/Col3/...) compacted; values stay aligned.
    (
        "| Col1 | Food | Col3 | Serving Size | Col5 | Calories | Col7 | Protein (g) | Col9 |\n"
        "|---|---|---|---|---|---|---|---|---|\n"
        "| | Spinach, cooked | | 1/2 cup | | 41 | | 3 | |\n"
        "| | Quinoa | | 1/2 cup | | 111 | | 4 | |\n",
        [["Spinach, cooked", "1/2 cup", "41", "3"],
         ["Quinoa", "1/2 cup", "111", "4"]],
    ),
    # Continuation cell merged into the previous row.
    (
        _table(HEADER4, [["Cottage Cheese", "4 oz", "81", "14"],
                         ["(1% fat)", "", "", ""],
                         ["Regular Yogurt", "1 cup", "100", "11"]]),
        [["Cottage Cheese (1% fat)", "4 oz", "81", "14"],
         ["Regular Yogurt", "1 cup", "100", "11"]],
    ),
])
def test_malformed_tables_are_repaired(bad, expected_good):
    """Values survive (order + column placement) with junk rows removed."""
    out = normalize_answer_tables(bad)
    assert out.split("\n")[1].strip().startswith("|--")  # separator regenerated
    data_lines = _data_rows(out)
    assert len(data_lines) == len(expected_good)
    for line, expected in zip(data_lines, expected_good):
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        assert cells == expected


def test_table_without_separator_gets_one():
    raw = ("| Food | Protein (g) |\n"
           "| Spinach, cooked | 3 |\n"
           "| Quinoa | 4 |\n")
    out = normalize_answer_tables(raw)
    assert out.split("\n")[1].strip().startswith("|--")
    assert "Spinach, cooked" in out and "Quinoa" in out


def test_correct_answer_is_untouched():
    raw = ("Here is the table of ingredients with the lowest protein content:\n\n"
           "| Food | Serving Size | Calories | Protein (g) |\n"
           "|---|---|---:|---:|\n"
           "| Spinach, cooked | 1/2 cup | 41 | 3 |\n"
           "| Quinoa | 1/2 cup | 111 | 4 |\n\n"
           "Source: Protein, page 1\n\n"
           "Completeness: LIKELY - this answer is mostly supported by the documents.")
    out = normalize_answer_tables(raw)
    # prose, values, ordering and verdict line are all preserved
    for line in ("Here is the table of ingredients with the lowest protein content:",
                 "| Spinach, cooked | 1/2 cup | 41 | 3 |",
                 "| Quinoa | 1/2 cup | 111 | 4 |",
                 "Source: Protein, page 1",
                 "Completeness: LIKELY - this answer is mostly supported by the documents."):
        assert line in out
    assert out.index("Spinach, cooked") < out.index("Quinoa")


def test_plain_non_table_response_untouched():
    raw = ("The food with the most protein is chicken, with 28 grams per 3 oz serving.\n\n"
           "Completeness: LIKELY - this answer is mostly supported by the documents.")
    assert normalize_answer_tables(raw) == raw


def test_single_column_table_kept():
    raw = ("| Food |\n"
           "|---|\n"
           "| Spinach, cooked |\n"
           "| Quinoa |\n")
    out = normalize_answer_tables(raw)
    assert out.strip().startswith("| Food |")
    assert "| Spinach, cooked |" in out and "| Quinoa |" in out


def test_values_never_lost_or_reordered():
    foods = ["Chicken, skinless", "Steak", "Turkey", "Lamb", "Pork", "Ham", "Egg"]
    rows = [[str(i + 1), food, str(28 - i * 2)] for i, food in enumerate(foods)]
    raw = _table(["Rank", "Food", "Protein (g)"], rows)
    out = normalize_answer_tables(raw)
    cells = [[c.strip() for c in r.strip().strip("|").split("|")]
             for r in _data_rows(out)]
    assert [r[1] for r in cells] == foods          # food order preserved
    assert [r[2] for r in cells] == [str(28 - i * 2) for i in range(len(foods))]
    assert [r[0] for r in cells] == [str(i + 1) for i in range(len(foods))]


def test_dynamic_tables_across_widths_and_mixing():
    """Dynamically generated tables of every width stay valid after repair."""
    for width in range(1, 7):
        header = [f"H{i}" for i in range(width)]
        rows = []
        for r in range(4):
            cells = [f"r{r}c{c}" for c in range(width)]
            if width > 1 and r == 1:
                cells = cells[: width - 1]  # ragged on purpose
            if r == 2:
                cells = cells + [f"junk{r}"]  # surplus on purpose
            rows.append(cells)
        out = normalize_answer_tables(_table(header, rows))
        header_line = out.split("\n")[0]
        header_w = len(header_line.strip().strip("|").split("|"))
        for line in out.split("\n")[1:]:
            if not line.strip() or line.strip().startswith("|--"):
                continue
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            assert len(cells) == header_w, (width, cells)


# ── Inline source citation repair ──────────────────────────────────────────

def _chunks(*specs):
    return [
        {"document_name": name, "document_id": name, "page": page}
        for name, page in specs
    ]


def test_no_citation_when_no_chunks():
    answer = "Some prose without any reference."
    assert repair_inline_sources(answer, []) == answer


def test_correct_citation_is_kept():
    chunks = _chunks(("Attendance Policy", 1), ("Attendance Policy", 2))
    answer = "You get benefits (*Attendance Policy*, page 1)."
    out = repair_inline_sources(answer, chunks)
    assert "(*Attendance Policy*, page 1)" in out


def test_wrong_page_is_corrected_to_retrieved_pages():
    chunks = _chunks(("Attendance Policy", 1), ("Attendance Policy", 2))
    answer = "You get benefits (*Attendance Policy*, page 7)."
    out = repair_inline_sources(answer, chunks)
    assert "page 7" not in out
    assert "pages 1 and 2" in out


def test_blank_page_is_filled_with_retrieved_pages():
    chunks = _chunks(("Benefits Guide", 3))
    answer = "Benefits are described here (*Benefits Guide*)."
    out = repair_inline_sources(answer, chunks)
    assert "(*Benefits Guide*, page 3)" in out


def test_partially_wrong_pages_keep_only_verified_ones():
    chunks = _chunks(("Benefits Guide", 3), ("Benefits Guide", 7))
    answer = "See (*Benefits Guide*, page 3 and 99)."
    out = repair_inline_sources(answer, chunks)
    assert "page 3" in out
    assert "99" not in out
    assert "and 7" not in out


def test_writer_name_citation_is_reduced_to_plain_text():
    chunks = _chunks(("Attendance Policy", 1))
    answer = "Ask (*Misty and Matt, page 4*) if unsure."
    out = repair_inline_sources(answer, chunks)
    assert "Misty and Matt" in out
    assert "page" not in out


def test_italic_includes_page_claim():
    chunks = _chunks(("Employee Benefits Guide", 3))
    answer = "Benefits (*Employee Benefits Guide, page 3*)."
    out = repair_inline_sources(answer, chunks)
    assert "(*Employee Benefits Guide*, page 3)" in out


def test_html_content_is_left_untouched():
    chunks = _chunks(("Paper", 5))
    answer = "<p><strong>Keep</strong> the (*Paper*, page 5) reference.</p>"
    assert repair_inline_sources(answer, chunks) == answer
"""Reconstruct a table's HTML from the PDF text layer (pdftext), CPU-only.

Ported from the datalab pdftext_backfill task, trimmed to the deterministic,
per-block core (no cross-page cluster consensus, no LLM orphan/header/garble
calls — those reduce to their documented deterministic fallbacks). Given the
pdftext spans inside a Table block's bbox, it sweeps several grid
parameterizations, scores them with a deterministic judge, and emits
``<table>`` HTML. Returns ``(html, score)`` or ``None`` when no grid resolves.

Input ``lines``: ``[(spans, y0, y1), ...]`` with ``spans = [(text, x0, x1), ...]``
in PDF points, matching the shape pdftext's dictionary_output yields per line.
"""

import itertools
import re
from collections import Counter, defaultdict
from html import escape
from statistics import median

MIN_CELLS_PER_ROW = 2  # a "data row" has >= this many tokens (2 supports two-column tables; the judge filters degenerate grids)
MIN_TABLE_ROWS = 3  # need at least this many data rows to treat it as a table
GAP_MIN_PT = 2.5  # projection: gaps narrower than this don't separate columns
PROJ_FRACS = (0.01, 0.03, 0.10)  # projection row-frequency thresholds to sweep
GRID_REGULARITY = 0.5

_PUA = re.compile("[\ue000-\uf8ff\ufffd]")  # private-use area + replacement char
_GARBLE_CHAR_FRAC = 0.02  # >2% private-use / replacement chars => garbled
# Leader runs (TOC dot leaders, form underscores/dashes) - not real cells;
# gridding them as columns explodes the column count, so they're dropped.
_LEADER_ONLY = re.compile(r"^[.·•…_\-\s]+$")
_NUMISH = re.compile(r"^-?[\d,.]*\d[\d,.]*%?$")
_NUM_TOK = re.compile(r"-?[\d,]+(\.\d+)?%?")
_YEAR = re.compile(r"^(19|20)\d\d$")
_PCTISH = re.compile(r"(less than|to less|%)")


# --------------------------------------------------------------------------- #
# garble gate (deterministic prefilter only)
# --------------------------------------------------------------------------- #
def _garble_ok(lines) -> bool:
    """True if the text layer looks clean. Deterministic: reject only on a high
    fraction of private-use / replacement glyphs (mojibake / bad encoding)."""
    text = " ".join(t for spans, _, _ in lines[:40] for t, _, _ in spans)
    if not text:
        return False
    return len(_PUA.findall(text)) / len(text) <= _GARBLE_CHAR_FRAC


# --------------------------------------------------------------------------- #
# header band split
# --------------------------------------------------------------------------- #
def _numfrac(spans) -> float:
    return sum(1 for t, _, _ in spans if _NUMISH.match(t)) / max(len(spans), 1)


def _find_header_band(lines):
    """y of the first DATA line (span-rich AND numeric-majority); everything
    above is the header band. None when the table has no numeric transition."""
    ys = [
        y0
        for spans, y0, _ in lines
        # Strictly more numeric than text: a 2-token (title, page#) TOC row is
        # exactly 0.5 and must not anchor the data region, or everything above
        # it gets swallowed into the header band.
        if len(spans) >= MIN_CELLS_PER_ROW and _numfrac(spans) > 0.5
    ]
    return min(ys) if ys else None


# --------------------------------------------------------------------------- #
# grid candidates
# --------------------------------------------------------------------------- #
def _grid_span(data_rows, bucket: str, placements=None):
    """Span-structure grid: K = modal span count; cuts = midpoints of the
    per-column median x0 over exact-K anchor rows."""
    if len(data_rows) < MIN_TABLE_ROWS:
        return None
    k = Counter(len(r) for r in data_rows).most_common(1)[0][0]
    if k < 2:
        return None
    anchors = [r for r in data_rows if len(r) == k]
    if len(anchors) < 3:
        return None
    col_x = [median(a[j][1] for a in anchors) for j in range(k)]
    cut_xs = [(col_x[j] + col_x[j + 1]) / 2 for j in range(k - 1)]

    grid, counts = [], []
    for row in data_rows:
        cells, cnts = [""] * k, [0] * k
        if placements is not None:
            placements.append([])
        for t, x0, x1 in row:
            pos = x0 if bucket == "x0" else (x0 + x1) / 2
            c = min(sum(1 for cx in cut_xs if pos >= cx), k - 1)
            cells[c] = f"{cells[c]} {t}".strip() if cells[c] else t
            cnts[c] += 1
            if placements is not None:
                placements[-1].append(c)
        grid.append(cells)
        counts.append(cnts)
    return k, cut_xs, grid, counts


def _grid_proj(data_rows, frac: float, placements=None):
    """Whitespace-gap projection grid: an x position belongs to a column iff
    covered by a span in > frac of rows."""
    if len(data_rows) < MIN_TABLE_ROWS:
        return None
    lo = min(x0 for r in data_rows for _, x0, _ in r)
    hi = max(x1 for r in data_rows for _, _, x1 in r)
    n = int(hi - lo) + 2
    cov = [0] * n
    for r in data_rows:
        for _, x0, x1 in r:
            for i in range(int(x0 - lo), min(int(x1 - lo) + 1, n)):
                cov[i] += 1
    thr = frac * len(data_rows)
    runs, i = [], 0
    while i < n:
        if cov[i] > thr:
            j = i
            while j < n and cov[j] > thr:
                j += 1
            runs.append((lo + i, lo + j))
            i = j
        else:
            i += 1
    if not runs:
        return None
    cols = [runs[0]]
    for c in runs[1:]:
        if c[0] - cols[-1][1] < GAP_MIN_PT:
            cols[-1] = (cols[-1][0], c[1])
        else:
            cols.append(c)
    k = len(cols)
    if k < 2:
        return None
    cut_xs = [(cols[j][1] + cols[j + 1][0]) / 2 for j in range(k - 1)]

    grid, counts = [], []
    for row in data_rows:
        cells, cnts = [""] * k, [0] * k
        if placements is not None:
            placements.append([])
        for t, x0, x1 in row:
            best, bo = None, 0.0
            for j, (c0, c1) in enumerate(cols):
                o = max(0.0, min(x1, c1) - max(x0, c0))
                if o > bo:
                    best, bo = j, o
            if best is None:
                cx = (x0 + x1) / 2
                best = min(
                    range(k), key=lambda j: abs((cols[j][0] + cols[j][1]) / 2 - cx)
                )
            cells[best] = f"{cells[best]} {t}".strip() if cells[best] else t
            cnts[best] += 1
            if placements is not None:
                placements[-1].append(best)
        grid.append(cells)
        counts.append(cnts)
    return k, cut_xs, grid, counts


def _candidates(data_rows, placements=None) -> dict:
    out = {}
    for bucket in ("x0", "center"):
        trace = [] if placements is not None else None
        g = _grid_span(data_rows, bucket, trace)
        if g:
            out[f"span-{bucket}"] = g
            if placements is not None:
                placements[f"span-{bucket}"] = trace
    for frac in PROJ_FRACS:
        trace = [] if placements is not None else None
        g = _grid_proj(data_rows, frac, trace)
        if g:
            out[f"proj-{int(frac * 100)}"] = g
            if placements is not None:
                placements[f"proj-{int(frac * 100)}"] = trace
    return out


# --------------------------------------------------------------------------- #
# deterministic judge
# --------------------------------------------------------------------------- #
def _cell_class(c: str) -> str:
    c = c.strip()
    if not c:
        return "empty"
    if _YEAR.match(c):
        return "year"
    if _NUMISH.match(c):
        return "num"
    if _PCTISH.search(c):
        return "range"
    return "text"


def _score_grid(k, grid, counts, n_header_cells) -> float:
    """Composite in [0,1]: type purity, compound-cell penalty, fill,
    header-count agreement, spans-per-cell (double weight)."""
    nonempty = [c for r in grid for c in r if c.strip()]
    if not nonempty:
        return 0.0
    fill = len(nonempty) / max(k * len(grid), 1)
    compound = sum(
        1
        for c in nonempty
        if len(_NUM_TOK.findall(c)) >= 2
        and _cell_class(c) == "text"
        and sum(ch.isdigit() for ch in c) > len(c) * 0.4
    )
    no_compound = 1 - compound / len(nonempty)
    purs = []
    for j in range(k):
        cc = Counter(_cell_class(r[j]) for r in grid)
        cc.pop("empty", None)
        if cc:
            purs.append(cc.most_common(1)[0][1] / sum(cc.values()))
    purity = sum(purs) / len(purs) if purs else 0.0
    hdr = 0.5 if n_header_cells is None else max(0.0, 1 - abs(n_header_cells - k) / k)
    occ = [c for row in counts for c in row if c > 0]
    one_span = sum(1 for c in occ if c == 1) / max(len(occ), 1)
    return (purity + no_compound + fill + hdr + 2 * one_span) / 6


def _pick_winner(cands: dict, n_header_cells):
    best_name, best, best_score = None, None, -1.0
    for name, (k, cut_xs, grid, counts) in cands.items():
        s = _score_grid(k, grid, counts, n_header_cells)
        if s > best_score:
            best_name, best, best_score = name, (k, cut_xs, grid, counts), s
    return best_name, best, best_score


# --------------------------------------------------------------------------- #
# headers + wrapped lines
# --------------------------------------------------------------------------- #
def _full_intervals(cut_xs: list) -> list:
    edges = [-1e9, *cut_xs, 1e9]
    return list(itertools.pairwise(edges))


def _avg_col_width(cut_xs: list) -> float:
    widths = [b - a for a, b in itertools.pairwise(cut_xs)]
    return (sum(widths) / len(widths)) if widths else 100.0


def _stitch_band_headers(
    band_lines, cut_xs, k, records=None, bounds=None, intervals=None
):
    """Assign each header span to its unique containing column interval;
    stitch top-to-bottom. Returns (names, n_named)."""
    full = intervals or (
        list(itertools.pairwise([bounds[0], *cut_xs, bounds[1]]))
        if bounds
        else _full_intervals(cut_xs)
    )
    parts = defaultdict(list)
    for index, (spans, _y0) in sorted(enumerate(band_lines), key=lambda t: t[1][1]):
        for span_index, (t, x0, x1) in enumerate(spans):
            containing = [j for j, (f0, f1) in enumerate(full) if f0 <= x0 and x1 <= f1]
            j = containing[0] if len(containing) == 1 else None
            if j is None and records is not None:
                records[index][span_index]["reason"] = "header_crosses_columns"
            if j is not None:
                parts[j].append(t)
                if records is not None:
                    records[index][span_index].update(
                        status="emitted",
                        section="header",
                        row=0,
                        column=j,
                        reason="header_center",
                    )
    # Unfilled header columns are left blank rather than "column_N" - a blank
    # <th> reads cleaner than a placeholder label in the output.
    names = [" ".join(parts[j]) if parts.get(j) else "" for j in range(k)]
    return names, sum(1 for j in range(k) if parts.get(j))


def _attach_wrapped_lines(
    lines, first_data_y, grid_y, cut_xs, records=None, bounds=None, intervals=None
):
    """Merge short mid-table text lines (wrapped cell continuations) into the
    row above, in the aligned text column. Deterministic merge-up (the pre-LLM
    fallback): numeric spans and non-text columns are never attached."""
    full = intervals or (
        list(itertools.pairwise([bounds[0], *cut_xs, bounds[1]]))
        if bounds
        else _full_intervals(cut_xs)
    )
    height = median(max(1, y1 - y0) for _, y0, y1 in lines)
    latest = [[y] * (len(cut_xs) + 1) for _, y in grid_y]
    wrap_gaps = defaultdict(list)
    k = len(cut_xs) + 1
    col_texty = []
    for j in range(k):
        vals = [cells[j] for cells, _ in grid_y if cells[j].strip()]
        texty = sum(1 for v in vals if _cell_class(v) == "text")
        col_texty.append(bool(vals) and texty >= 0.5 * len(vals))

    for index, (spans, y0, _y1) in sorted(enumerate(lines), key=lambda t: t[1][1]):
        if y0 < first_data_y or any(y0 == y for _, y in grid_y):
            continue
        above = [i for i, g in enumerate(grid_y) if g[1] <= y0]
        if not above:
            continue
        ti = above[-1]
        for span_index, (t, x0, x1) in enumerate(spans):
            containing = [j for j, (f0, f1) in enumerate(full) if f0 <= x0 and x1 <= f1]
            j = containing[0] if len(containing) == 1 else None
            if j is None or not col_texty[j] or _cell_class(t) != "text":
                if records is not None:
                    records[index][span_index]["reason"] = (
                        "continuation_not_text_column"
                    )
                continue
            gap = y0 - latest[ti][j]
            if gap > 1.5 * height:
                if records is not None:
                    records[index][span_index]["reason"] = "continuation_gap"
                continue
            if ti == len(grid_y) - 1 and not any(
                abs(gap - known) <= height / 2 for known in wrap_gaps[j]
            ):
                if records is not None:
                    records[index][span_index]["reason"] = (
                        "trailing_text_without_wrap_evidence"
                    )
                continue
            if ti < len(grid_y) - 1:
                wrap_gaps[j].append(gap)
            latest[ti][j] = y0
            target = grid_y[ti][0]
            target[j] = f"{target[j]} {t}".strip() if target[j] else t
            if records is not None:
                records[index][span_index].update(
                    status="emitted",
                    section="body",
                    row=ti,
                    column=j,
                    reason="merge_previous_row",
                )


_SYMBOL_ONLY = re.compile(r"^[^\w]{1,2}$")


def _merge_marker_columns(names, grid, records=None):
    """Merge symbol-marker columns into their right neighbor.

    A column whose every non-empty DATA value is a short non-alphanumeric
    symbol (checkboxes, bullets, tick marks) is a row *marker*, not a data
    column - keeping it separate splits "(checkbox) CODE" into two cells and
    shifts the header row out of alignment with the data columns. Runs after
    header extraction so the header row doesn't mask an all-symbol column."""
    if not grid:
        return names, grid
    k = len(grid[0])
    j = 0
    while k > 1 and j < k - 1:
        vals = [row[j] for row in grid if row[j].strip()]
        if (
            len(vals) >= 2
            and all(_SYMBOL_ONLY.match(v.strip()) for v in vals)
            and (not names or not names[j] or _SYMBOL_ONLY.match(names[j].strip()))
        ):
            for row in grid:
                row[j : j + 2] = [f"{row[j]} {row[j + 1]}".strip()]
            if names:
                names[j : j + 2] = [f"{names[j]} {names[j + 1]}".strip()]
            if records is not None:
                for record in records:
                    if record.get("column", -1) > j:
                        record["column"] -= 1
            k -= 1
        else:
            j += 1
    return names, grid


def _build_html(names, grid, has_header: bool) -> str:
    out = ["<table>"]
    if has_header:
        out.append("<thead><tr>")
        out += [f"<th>{escape(n)}</th>" for n in names]
        out.append("</tr></thead>")
    out.append("<tbody>")
    for cells in grid:
        out.append("<tr>" + "".join(f"<td>{escape(c)}</td>" for c in cells) + "</tr>")
    out.append("</tbody></table>")
    return "".join(out)


def _line_tokens(line: dict, bbox, excluded=None, preserve_placeholders=False):
    """Tokenize a pdftext line into (text, x0, x1) cells inside ``bbox``.

    Prefer WORD-level tokens split on intra-line character gaps: pdftext often
    merges adjacent table cells into one span, which collapses the column
    structure the grid heuristics rely on. Re-splitting the chars at gaps
    wider than ~a quarter of the line height recovers per-cell tokens. Falls
    back to raw spans when char data isn't kept."""
    bx0, by0, bx1, by1 = bbox

    def inside(x0, y0, x1, y1):
        return bx0 <= (x0 + x1) / 2 <= bx1 and by0 <= (y0 + y1) / 2 <= by1

    tokens = []
    have_chars = False
    for s in line.get("spans", []):
        chars = s.get("chars") or []
        if not chars:
            continue
        have_chars = True
        cur = None  # [text, x0, x1]
        for c in chars:
            cx0, cy0, cx1, cy1 = c["bbox"]
            if not inside(cx0, cy0, cx1, cy1):
                continue
            ch = c.get("char", "")
            # Split threshold: half the char height. 0.25x mis-split words in
            # condensed fonts (letter gaps can reach ~0.3x height); real cell
            # and column gaps sit well above 0.5x.
            gap = 0.5 * max(cy1 - cy0, 1.0)
            if cur is None:
                cur = [ch, cx0, cx1]
            elif cx0 - cur[2] > gap:
                tokens.append(cur)
                cur = [ch, cx0, cx1]
            else:
                cur[0] += ch
                cur[2] = cx1
        if cur is not None:
            tokens.append(cur)

    if not have_chars:
        # No char data: fall back to span-level tokens.
        for s in line.get("spans", []):
            t = (s.get("text") or "").strip()
            sx0, sy0, sx1, sy1 = s["bbox"]
            if t and inside(sx0, sy0, sx1, sy1):
                tokens.append([t, sx0, sx1])

    out = []
    for text, x0, x1 in tokens:
        text = text.strip()
        if text and (
            not _LEADER_ONLY.match(text)
            or text in ("-", "--")
            or (preserve_placeholders and set(text) == {"_"})
        ):
            out.append((text, round(x0, 1), round(x1, 1)))
        elif text and excluded is not None:
            line_bbox = line.get("bbox") or [0, 0, 0, 0]
            excluded.append(
                dict(
                    text=text,
                    bbox=[x0, line_bbox[1], x1, line_bbox[3]],
                    status="excluded",
                    reason="leader_only",
                )
            )
    return out


def table_lines_from_pdftext(
    pdftext_page: dict, bbox, diagnostics=None, preserve_placeholders=False
) -> list:
    """Extract ``[(tokens, y0, y1)]`` lines (tokens = ``[(text, x0, x1)]``) from a
    cached pdftext page, restricted to ``bbox`` (x0, y0, x1, y1, in pdftext/PDF
    points). Tokens are word-level (see _line_tokens). Feeds
    reconstruct_table_html."""
    bx0, by0, bx1, by1 = bbox
    excluded = [] if diagnostics is not None else None
    lines = []
    for block in pdftext_page.get("blocks", []):
        for line in block.get("lines", []):
            lb = line.get("bbox")
            # Cheap reject: _line_tokens only keeps chars whose center lies in
            # the table bbox, and every char is contained in the line bbox, so a
            # line whose bbox is disjoint from the table region can contribute
            # nothing. Skipping it avoids re-scanning the whole page's char
            # layer once per table (was O(tables x page_chars)). Lines without a
            # bbox fall through to the full per-char check.
            if lb is not None and (
                lb[2] < bx0 or lb[0] > bx1 or lb[3] < by0 or lb[1] > by1
            ):
                continue
            toks = _line_tokens(line, bbox, excluded, preserve_placeholders)
            if toks:
                lb = lb or [0, 0, 0, 0]
                lines.append((toks, round(lb[1], 1), round(lb[3], 1)))
    if diagnostics is not None:
        diagnostics["source_scope"] = "tokens_selected_by_existing_pdftext_extraction"
        diagnostics["coordinate_basis"] = "token_x_and_source_line_y"
        diagnostics["excluded_scope"] = "selected_leader_tokens_only"
        diagnostics["excluded_spans"] = [
            dict(occurrence=f"excluded:{i}", **r) for i, r in enumerate(excluded)
        ]
    return lines


def _merge_same_row_fragments(lines):
    groups, active = [], []
    ambiguous = False
    for index, (spans, y0, y1) in sorted(enumerate(lines), key=lambda item: item[1][1]):
        active = [group for group in active if group[2] > y0]
        candidates = []
        for group in active:
            disjoint = all(
                x1 <= other0 or other1 <= x0
                for _, x0, x1 in spans
                for _, other0, other1, _ in group[0]
            )
            if not disjoint:
                continue
            needed = 0.6 * max(1, min(y1 - y0, group[5]))
            if min(y1, group[4]) - max(y0, group[3]) >= needed:
                candidates.append(group)
            elif min(y1, group[2]) - max(y0, group[1]) >= needed:
                ambiguous = True
        if len(candidates) == 1:
            group = candidates[0]
            group[0].extend(
                (t, x0, x1, (index, j)) for j, (t, x0, x1) in enumerate(spans)
            )
            group[1], group[2] = min(y0, group[1]), max(y1, group[2])
            group[3], group[4] = max(y0, group[3]), min(y1, group[4])
            group[5] = min(group[5], y1 - y0)
        else:
            ambiguous = ambiguous or len(candidates) > 1
            group = [
                [(t, x0, x1, (index, j)) for j, (t, x0, x1) in enumerate(spans)],
                y0,
                y1,
                y0,
                y1,
                y1 - y0,
            ]
            groups.append(group)
            active.append(group)
    merged, origins = [], []
    for spans, y0, y1, *_ in groups:
        spans.sort(key=lambda span: span[1])
        merged.append(([(t, x0, x1) for t, x0, x1, _ in spans], y0, y1))
        origins.append([origin for _, _, _, origin in spans])
    return merged, origins, ambiguous


def reconstruct_table_html(lines, diagnostics=None):
    """Reconstruct a table only when every selected span has an assignment.

    Assignment establishes geometric placement, not semantic completeness.
    """
    merged, origins, ambiguous = _merge_same_row_fragments(lines)
    trace = {} if diagnostics is None else diagnostics
    result = _reconstruct_table_html(merged, trace)
    for record in trace.get("spans", []):
        row, column = map(int, record["occurrence"].split(":"))
        original_row, original_column = origins[row][column]
        text, x0, x1 = lines[original_row][0][original_column]
        record.update(
            occurrence=f"{original_row}:{original_column}",
            bbox=[x0, lines[original_row][1], x1, lines[original_row][2]],
        )
    trace.get("spans", []).sort(
        key=lambda record: tuple(map(int, record["occurrence"].split(":")))
    )
    trace["source_coverage"] = "accounted" if result else "unknown"
    if ambiguous or trace.get("ambiguous_column_intervals"):
        trace["source_coverage"] = "unresolved"
        if ambiguous:
            trace["ambiguous_row_fragments"] = True
        trace["requires_review"] = True
        return None
    if any(record["status"] == "unresolved" for record in trace.get("spans", [])):
        trace["source_coverage"] = "unresolved"
        trace["requires_review"] = True
        return None
    return result


def _reconstruct_table_html(lines, diagnostics=None):
    """Reconstruct ``(html, score)`` from a table's pdftext lines, or None.

    ``lines``: [(spans, y0, y1)], spans = [(text, x0, x1)] in PDF points.
    """
    records = None
    if diagnostics is not None:
        records = [
            [
                dict(
                    occurrence=f"{i}:{j}",
                    text=t,
                    bbox=[x0, y0, x1, y1],
                    status="unresolved",
                    reason="no_grid",
                )
                for j, (t, x0, x1) in enumerate(spans)
            ]
            for i, (spans, y0, y1) in enumerate(lines)
        ]
        diagnostics.update(
            source_kind=(
                "digital_text" if _garble_ok(lines) else "corrupt_or_empty_text"
            ),
            source_check="private_use_and_replacement_glyph_fraction_first_40_lines",
            completeness="unknown",
            spans=[r for row in records for r in row],
        )
    if not lines or not _garble_ok(lines):
        return None

    first_data_y = _find_header_band(lines)
    if first_data_y is None:
        # No numeric transition to mark the header. Fall back to the first
        # span-rich data row: sparse lines above it are a (possibly multi-line)
        # header band, so their text is captured instead of dropped.
        rich_ys = [y0 for spans, y0, _ in lines if len(spans) >= MIN_CELLS_PER_ROW]
        if rich_ys:
            alt_y = min(rich_ys)
            if any(y0 < alt_y for _, y0, _ in lines):
                first_data_y = alt_y
                rich = [
                    (spans, y0)
                    for spans, y0, _ in lines
                    if len(spans) >= MIN_CELLS_PER_ROW
                ]
                if (
                    len(rich) > 1
                    and all(_cell_class(t) == "text" for t, _, _ in rich[0][0])
                    and any(_cell_class(t) == "num" for t, _, _ in rich[1][0])
                ):
                    first_data_y = rich[1][1]
    if first_data_y is not None:
        data = [
            (spans, y0)
            for spans, y0, _ in lines
            if y0 >= first_data_y and len(spans) >= MIN_CELLS_PER_ROW
        ]
        band = [(spans, y0) for spans, y0, _ in lines if y0 < first_data_y]
        n_hdr = (
            len([1 for spans, _ in band for t, x0, x1 in spans if (x1 - x0) < 200])
            or None
        )
    else:
        data = [
            (spans, y0) for spans, y0, _ in lines if len(spans) >= MIN_CELLS_PER_ROW
        ]
        band, n_hdr = [], None

    if data:
        left = median(min(x0 for _, x0, _ in spans) for spans, _ in data)
        height = median(max(1, y1 - y0) for _, y0, y1 in lines)
        retained = []
        for spans, y0 in data:
            if (
                retained
                and min(x0 for _, x0, _ in spans) > left + height / 2
                and y0 - retained[-1][1] <= 1.5 * height
                and all(_cell_class(t) == "text" for t, _, _ in spans)
            ):
                continue
            retained.append((spans, y0))
        data = retained
    data_rows = [spans for spans, _ in data]
    placements = {} if diagnostics is not None else None
    cands = _candidates(data_rows, placements)
    if not cands:
        return None
    _name, best, score = _pick_winner(cands, n_hdr)
    if not best:
        return None
    k, cut_xs, grid, counts = best
    if diagnostics is not None:
        diagnostics.update(candidate=_name, reconstruction_score=score)
        for record in diagnostics["spans"]:
            record["reason"] = "not_assigned"
        data_indices = [
            i for i, (spans, y0, _) in enumerate(lines) if (spans, y0) in data
        ]
        for row, (index, columns) in enumerate(zip(data_indices, placements[_name])):
            for record, column in zip(records[index], columns):
                record.update(
                    status="emitted",
                    section="body",
                    row=row,
                    column=column,
                    reason="grid_assignment",
                )

    columns = [[] for _ in range(k)]
    for (spans, _), assigned in zip(data, placements[_name]):
        for (text, x0, x1), column in zip(spans, assigned):
            columns[column].append((x0, x1))
    if diagnostics is not None and any(
        columns[j]
        and columns[j + 1]
        and max(right for _, right in columns[j])
        > min(left for left, _ in columns[j + 1])
        for j in range(k - 1)
    ):
        diagnostics["ambiguous_column_intervals"] = True
    for spans, _ in band:
        for text, x0, x1 in spans:
            column = min(sum(x0 >= cut for cut in cut_xs), k - 1)
            next_left = (
                min((left for left, _ in columns[column + 1]), default=float("inf"))
                if column + 1 < k
                else float("inf")
            )
            if x1 <= next_left:
                columns[column].append((x0, x1))
    attachment_cuts = []
    for column in range(k - 1):
        if columns[column] and columns[column + 1]:
            right = max(x1 for _, x1 in columns[column])
            left = min(x0 for x0, _ in columns[column + 1])
            attachment_cuts.append(
                (right + left) / 2 if right <= left else cut_xs[column]
            )
        else:
            attachment_cuts.append(cut_xs[column])
    bounds = (
        min(x0 for spans, _, _ in lines for _, x0, _ in spans),
        max(x1 for spans, _, _ in lines for _, _, x1 in spans),
    )
    intervals = [
        (
            max((right for _, right in columns[j - 1]), default=bounds[0])
            if j
            else bounds[0],
            min((left for left, _ in columns[j + 1]), default=bounds[1])
            if j + 1 < k
            else bounds[1],
        )
        for j in range(k)
    ]
    if band:
        band_records = (
            [records[i] for i, (_, y0, _) in enumerate(lines) if y0 < first_data_y]
            if records is not None
            else None
        )
        names, n_named = _stitch_band_headers(
            band, attachment_cuts, k, band_records, bounds, intervals
        )
        has_header = True
    else:
        # No geometric header band: treat the first data row as the header
        # (the common header-in-first-row case); avoids emitting column_N junk.
        names, has_header = [], False

    if len(grid) < MIN_TABLE_ROWS:
        return None

    if data:
        grid_y = list(zip(grid, [y0 for _, y0 in data[-len(grid) :]]))
        _attach_wrapped_lines(
            lines,
            first_data_y if first_data_y is not None else data[0][1],
            grid_y,
            attachment_cuts,
            records,
            bounds,
            intervals,
        )
        grid = [g for g, _ in grid_y]

    if not has_header and grid:
        names, grid, has_header = grid[0], grid[1:], True
        if diagnostics is not None:
            for record in diagnostics["spans"]:
                if record.get("status") == "emitted":
                    if record["row"] == 0:
                        record["section"] = "header"
                    else:
                        record["row"] -= 1
        if len(grid) < 1:
            return None

    names, grid = _merge_marker_columns(
        names, grid, diagnostics["spans"] if diagnostics is not None else None
    )

    return _build_html(names, grid, has_header), score

"""The extraction pipeline: for every page, draw it, read its text, find
axes and graphs, find the markers (or bars / line vertices), name their
series from the legends and map each point through its graph's axes.
"""

import collections
import re
import sys

from .axes import drop_duplicate_axes, find_axes
from .charts import find_bars, find_line_series
from .context import PAGE, SETTINGS
from .document import Document
from .errbars import find_error_bars
from .fragments import rebuild_fragmented_circles, rebuild_strip_discs
from .geometry import bbox_of, rect_distance
from .graphs import (
    add_panel_graphs, build_graphs, forget_graphs, graph_for_symbol, graph_rotation,
    set_graph_backgrounds)
from .interpreter import Interpreter
from .labels import apply_axis_multipliers, resolve_shared_labels
from .legend import SeriesNamer, find_page_legend, legend_for_lines
from .meta import graph_meta
from .occlusion import cover_rects, drop_hidden_glyphs
from .outlined_text import outlined_text
from .rows import make_rows
from .scales import find_break_marks
from .styles import guess_tool
from .symbols import (drop_covered_bits, drop_hidden_dots, drop_highlight_boxes,
                      drop_outline_rings, drop_specks, find_symbols)
from .text import attach_vector_minus, merge_texts
from .titles import find_figure_caption, text_lines
from .tools import PathsByX, graph_tool
from .twin import twin_axes, warn_twin_unsure


class Options:
    """What to report (from the command line)."""

    def __init__(self, inside_only=False, max_frac=0.1, debug=False, exclude_legend=False,
                 errbars=False):
        self.inside_only = inside_only        # drop symbols outside the axes box
        self.max_frac = max_frac              # largest marker, as part of the plot
        self.debug = debug                    # axis details on stderr
        self.exclude_legend = exclude_legend  # drop legend-key markers
        self.errbars = errbars                # low/high ends of error bars


def extract(pdf_path, pages=None, inside_only=False, max_frac=0.1, debug=False,
            exclude_legend=False, password=b"", info=None, errbars=False):
    """Return the data point rows of a PDF file (one dict per point).
    `pages` limits the work to a set of page numbers.  If `info` is a dict
    it receives 'graphs' (number of graphs found) and 'warnings'."""
    with open(pdf_path, "rb") as f:
        pdf = Document(f.read(), password)
    opts = Options(inside_only, max_frac, debug, exclude_legend, errbars)
    if info is None:
        info = {}
    info["graphs"] = 0
    info["warnings"] = pdf.warnings
    rows = []
    for pno, page in enumerate(pdf.pages(), 1):
        if not pages or pno in pages:
            try:
                rows += extract_page(pdf, pno, page, opts, info)
            except Exception as e:     # a bug must not lose the other pages
                if opts.debug:
                    raise
                pdf.warn("page %d could not be analysed (%s: %s)" % (pno, type(e).__name__, e))
            finally:
                forget_page()          # the page's cached answers (and memory)
    return rows


def forget_page():
    """Drop what was cached about the page just done (graph lookups that
    hold on to its graphs; results cached on subpaths go with them)."""
    forget_graphs()


def drop_symbols_in_prose(symbols, texts, graphs):
    """A marker drawn in a line of running text outside every graph - the
    sample markers in a caption ("Binomial(20, 1/2) (* * *)"), a bullet in
    the body text - is no data point and no legend key: text on both sides
    on its baseline, within 0.75 of a font size, in a line of three words or
    more
    (of three letters or more; a legend row "o Group A o Group B" has
    fewer; and no bigger than the text: a legend key's box is).  The line
    must reach beyond the page's graphs by more than 15% of their width (a
    legend row stays within them).  A run of
    such markers close together counts as one (text left
    of the first and right of the last).  A dot under 0.3 of the font size
    just after text on a line within a font size of it (a full stop drawn
    as a shape after a formula's superscript) needs no words around it.
    Symbols with a clipping box belong to the graph they were clipped to."""
    if not symbols or not texts:
        return symbols
    lines = _text_lines(texts)
    if not lines:
        return symbols
    outside = sorted((s for s in symbols if not s.get("clip")      # (clipped: in a graph)
                      and not any(rect_distance(g["rect"], s["cx"], s["cy"]) == 0 for g in graphs)),
                     key=lambda s: s["cx"])
    # runs of markers along one baseline, left to right
    runs = []
    for s in outside:
        for r in reversed(runs[-50:]):
            q = r[-1]
            if abs(q["cy"] - s["cy"]) <= 0.3 * max(s["size"], q["size"]) and \
                    s["cx"] - q["cx"] <= 3 * max(s["size"], q["size"]) + 2:
                r.append(s)
                break
        else:
            runs.append([s])
    all_lines = lines
    # a line of running text reaches beyond the figure (a caption, the body
    # text); a legend row lies within it
    if graphs:
        gx0 = min(g["rect"][0] for g in graphs)
        gx1 = max(g["rect"][2] for g in graphs)
        reach = 0.15 * (gx1 - gx0)
        lines = [ln for ln in lines if ln[2][0][0] < gx0 - reach or ln[2][-1][1] > gx1 + reach]
    drop = set()
    for run in runs:
        x0 = min(s["cx"] - s["size"] / 2 for s in run)
        x1 = max(s["cx"] + s["size"] / 2 for s in run)
        cy = sum(s["cy"] for s in run) / len(run)
        size = max(s["size"] for s in run)
        if any(_in_line(ln, x0, x1, cy, size) for ln in lines) or \
                any(_after_text(ln, x0, cy, size) for ln in all_lines):
            drop.update(id(s) for s in run)
    return [s for s in symbols if id(s) not in drop]


def _text_lines(texts):
    """Lines of horizontal text: (baseline, font size, the items' x spans,
    whether the line has three words or more)."""
    rows = collections.defaultdict(list)
    for t in texts:
        if t.get("up", (0, 1))[0] != 0 or not t["text"].strip():
            continue
        rows[round(t["p0"][1])].append(t)
    out = []
    for items in rows.values():
        items.sort(key=lambda t: t["p0"][0])
        size = sorted(t.get("size") or 1.0 for t in items)[len(items) // 2]
        prose = len(_WORD.findall(" ".join(t["text"] for t in items))) >= 3
        out.append((items[0]["p0"][1], size, [(t["p0"][0], t["p1"][0]) for t in items], prose))
    return out


def _after_text(ln, x0, cy, msize):
    """A tiny mark (under 0.3 of the font size) just after text on a line
    within a font size of it (a full stop after a superscript)."""
    base, size, spans, _ = ln
    if msize >= 0.3 * size or not base - size <= cy <= base + size:
        return False
    return any(x0 - 0.75 * size <= e <= x0 + 0.1 * size for _, e in spans)


def _in_line(ln, x0, x1, cy, msize):
    base, size, spans, prose = ln
    if msize > size or not (prose or msize < 0.3 * size):
        return False        # (a mark in a line of text is no bigger than the text)
    if not base - 0.3 * size <= cy <= base + 0.9 * size:
        return False
    left = any(x0 - 0.75 * size <= e <= x0 + 0.1 * size for _, e in spans)
    right = any(x1 - 0.1 * size <= b <= x1 + 0.75 * size for b, _ in spans)
    return left and right


def drop_corner_ticks(symbols, graphs):
    """Ticks drawn across the axis line (seen with Excel) meet where the
    axes meet: the first x tick and the first y tick there make a '+' one
    or two tick lengths across.  Such a plus, on a tick of each axis at the corner
    where the axis lines cross, is not a data point."""
    corners = []
    for g in graphs:
        ax = {a.get("orient"): a for a in (g.get("x"), g.get("y")) if a}
        if set(ax) != {"x", "y"} or ax["x"].get("pos") is None or ax["y"].get("pos") is None:
            continue
        cx, cy = ax["y"]["pos"], ax["x"]["pos"]
        L = max(ax["x"].get("tick_len") or 0, ax["y"].get("tick_len") or 0)
        tol = max(0.5, 0.15 * L)
        if any(abs(t - cx) <= tol for t in ax["x"].get("tick_pos", ())) and \
                any(abs(t - cy) <= tol for t in ax["y"].get("tick_pos", ())):
            corners.append((cx, cy, L, tol))
    if not corners:
        return symbols
    return [s for s in symbols if not (
        s["shape"] == "plus" and any(
            abs(s["cx"] - cx) <= tol and abs(s["cy"] - cy) <= tol and 0.7 * L <= s["size"] <= 2.2 * L
            for cx, cy, L, tol in corners))]


def extract_page(pdf, pno, page, opts, info):
    """The pipeline for one page: draw it, read its text, find the axes and
    graphs, find the markers (or bars / line vertices), name the series from
    the legends and map every point through its graph's axes."""
    PAGE.reset()
    PAGE.number = pno
    it = Interpreter(pdf)
    it.run_page(page)
    texts, text_parts, blobs = read_page_text(it)
    graphs = find_page_graphs(it, texts, pno, opts.debug)
    if not graphs:
        return []
    info["graphs"] += len(graphs)
    # graphs are numbered through the document: info carries the count
    first_no = info.setdefault("graph_no", 0) + 1
    info["graph_no"] += len(graphs)
    symbols = drop_corner_ticks(find_page_symbols(pdf, pno, it, text_parts), graphs)
    symbols = drop_symbols_in_prose(symbols, texts, graphs)
    symbols = drop_box_dashes(symbols, texts, text_boxes(it.paths), graphs)
    describe_graphs(graphs, texts, symbols, first_no, opts.debug)
    by_x = PathsByX(it.paths)
    for g in graphs:
        x0, _, x1, _ = g["rect"]
        mine = by_x.between(x0 - 0.1 * (x1 - x0), x1 + 0.1 * (x1 - x0))
        g["tool"] = graph_tool(g, mine, it.glyph_symbols) or pdf.tool
        g["tool_guess"] = guess_tool(g["rect"], mine, it.texts, it.glyph_symbols)
    line_names = add_bars_and_lines(graphs, symbols, it.paths, texts)
    # the resolution of each symbol's coordinates (from the path drawing it)
    res_of = {p["idx"]: p.get("res") for p in it.paths}
    for s in symbols:
        if s.get("res") is None:
            s["res"] = res_of.get(s["idx"])
    legend = find_page_legend(symbols, texts, blobs, graphs, it.paths)
    if opts.debug and legend:
        print("[debug] legend keys: %s" % sorted(set(legend.values())), file=sys.stderr)
    namer = SeriesNamer(symbols, legend, graphs, line_names)
    twin_axes(graphs, symbols, namer, texts, pdf.warnings, opts.debug)
    bars = find_error_bars(symbols, graphs, it.paths,
                           lambda s: graph_for_symbol(graphs, s)[1]) if opts.errbars else {}
    rows = make_rows(pno, graphs, symbols, legend, namer, opts, bars)
    warn_twin_unsure(graphs, rows, pdf.warnings)
    info.setdefault("meta", []).extend(graph_meta(pno, graphs, rows))
    return rows


def read_page_text(it):
    """All text of the page: real text (minus glyphs painted over by later
    boxes) and text drawn as glyph outlines, read by shape.  Returns
    (texts, outline parts that are text, unreadable outlined words)."""
    it.texts = drop_hidden_glyphs(it.texts, it.paths, it.images)
    PAGE.break_marks = find_break_marks(it.paths)
    blobs = []
    out_texts, text_parts = outlined_text(it.paths, blobs, cover_rects(it.paths, it.images))
    texts = merge_texts(it.texts) + merge_texts(out_texts)
    attach_vector_minus(texts, it.paths)
    PAGE.nominal_labels = [t for t in texts if t["text"].strip()
                           and len(t["text"].strip()) <= 40] + blobs
    return texts, text_parts, blobs


def drop_box_dashes(symbols, texts, boxes, graphs):
    """A dashed border round a note drawn as a row of small filled squares:
    four or more squares of one size on an edge of a box that encloses text
    (smaller than a quarter of the largest graph) are its dashes."""
    if not boxes or not texts or not graphs:
        return symbols
    big = max((g["rect"][2] - g["rect"][0]) * (g["rect"][3] - g["rect"][1]) for g in graphs)
    notes = []
    for b in boxes:
        if (b[2] - b[0]) * (b[3] - b[1]) > 0.25 * big:
            continue        # (a plot area or chart frame, not a note)
        if any(b[0] - 0.5 <= t["bbox"][0] and t["bbox"][2] <= b[2] + 0.5 and
               b[1] - 0.5 <= t["bbox"][1] and t["bbox"][3] <= b[3] + 0.5 for t in texts if t["text"].strip()):
            notes.append(b)
    if not notes:
        return symbols

    # squares on each edge of each note box; a border is a row of four or
    # more of one size (a marker alone on a frame's edge is a point)
    edges = collections.defaultdict(list)
    for s in symbols:
        if s["shape"] not in ("square", "rectangle"):
            continue
        tol = 0.75 * s["size"] + 0.5
        for bi, (x0, y0, x1, y1) in enumerate(notes):
            if not (x0 - tol <= s["cx"] <= x1 + tol and y0 - tol <= s["cy"] <= y1 + tol):
                continue
            for side, d in (("l", abs(s["cx"] - x0)), ("r", abs(s["cx"] - x1)),
                            ("b", abs(s["cy"] - y0)), ("t", abs(s["cy"] - y1))):
                if d <= tol:
                    edges[(bi, side, round(s["size"], 1))].append(id(s))
    dashes = {i for ids in edges.values() if len(ids) >= 4 for i in ids}
    return [s for s in symbols if id(s) not in dashes]


def text_boxes(paths):
    """Axis-aligned rectangles that may enclose text: filled boxes and
    closed outlines (call-outs with a border, notes on a coloured ground)."""
    out = []
    for p in paths:
        for sp in p["subpaths"]:
            if not sp["segs"] or any(seg[0] != "l" for seg in sp["segs"]):
                continue
            v = [sp["start"]] + [seg[1] for seg in sp["segs"]]
            if not 4 <= len(v) <= 5 or not (p["fill"] or sp.get("closed") or len(v) == 5):
                continue
            x0, y0, x1, y1 = bbox_of(v)
            if min(x1 - x0, y1 - y0) < 3 or any(
                    min(abs(q[0] - x0), abs(q[0] - x1)) > 0.5 or min(abs(q[1] - y0), abs(q[1] - y1)) > 0.5
                    for q in v):
                continue
            out.append((x0, y0, x1, y1))
    return out


def prose_inside(g, texts, boxes=()):
    """The words (of three letters or more) of running text inside a graph's
    plot box, its own axis labels apart: the text items on one baseline are
    joined into lines, and only lines of three words or more count (the
    names beside points, legend entries and notes are shorter).  Text
    enclosed by a border or a filled box smaller than half the plot box
    (notes describing the data) does not count."""
    own = {id(t) for k in ("x", "y") for _, t in g[k].get("labels", ())}
    x0, y0, x1, y1 = g["rect"]
    half = 0.5 * (x1 - x0) * (y1 - y0)
    notes = [b for b in boxes if (b[2] - b[0]) * (b[3] - b[1]) < half]

    def boxed(t):
        tb = t["bbox"]
        return any(b[0] - 0.5 <= tb[0] and tb[2] <= b[2] + 0.5 and b[1] - 0.5 <= tb[1] and tb[3] <= b[3] + 0.5
                   for b in notes)
    items = sorted((t for t in texts if id(t) not in own and t["text"].strip()
                    and x0 <= t["center"][0] <= x1 and y0 <= t["center"][1] <= y1 and not boxed(t)),
                   key=lambda t: (-round(t["p0"][1], 1), t["p0"][0]))
    lines = []           # [baseline y, right end, size, text]
    for t in items:
        size = t.get("size") or 1.0
        for ln in lines[-8:]:
            if abs(ln[0] - t["p0"][1]) <= 0.3 * size and -0.5 * size <= t["p0"][0] - ln[1] <= 1.5 * size:
                ln[1] = max(ln[1], t["p1"][0])
                ln[3] += " " + t["text"]
                break
        else:
            lines.append([t["p0"][1], t["p1"][0], size, t["text"]])
    return sum(len(_WORD.findall(ln[3])) for ln in lines if len(ln[3].split()) >= 3)


_WORD = re.compile(r"[^\W\d_]{3,}")


def drop_tables(graphs, texts, debug=False, boxes=()):
    """A ruled table (column headings, row names, shaded cells) can pass for
    a graph with a category axis each way; but text fills its 'plot': an
    item in at least half of the cells its rows and columns make.  Such a
    graph is no graph (a chart with categories both ways, such as a dot
    matrix, holds markers, not text, in its cells).  Nor is a 'graph' whose
    box holds more words of running text than --max-words (default 20)."""
    out = []
    for g in graphs:
        mx, my = g["x"]["map"], g["y"]["map"]
        if prose_inside(g, texts, boxes) > SETTINGS.max_words:
            # a 'plot' full of running text: axes made of a text page's
            # rules, bracket glyphs and numbers in the prose (real graphs
            # hold a few words of it at most: legends, notes)
            if debug:
                print("[debug] graph rect %s holds running text: no graph" % (
                    tuple(round(v, 2) for v in g["rect"]),), file=sys.stderr)
            continue
        if not (mx and my and mx["kind"] == "nominal" and my["kind"] == "nominal"):
            out.append(g)
            continue
        own = {id(t) for k in ("x", "y") for _, t in g[k].get("labels", ())}
        xr, yr = ({"x": 0, "y": 1}[g[k]["orient"]] for k in ("x", "y"))
        xt = [p for p, _ in mx["ticks"]]
        yt = [p for p, _ in my["ticks"]]
        x0, y0, x1, y1 = g["rect"]
        cells = set()
        for t in texts:
            cx, cy = t["center"]
            if id(t) in own or not (x0 <= cx <= x1 and y0 <= cy <= y1):
                continue
            c = (cx, cy)
            cells.add((min(range(len(xt)), key=lambda i: abs(xt[i] - c[xr])),
                       min(range(len(yt)), key=lambda j: abs(yt[j] - c[yr]))))
        n = len(xt) * len(yt)
        if n >= 4 and len(cells) >= 0.5 * n:
            if debug:
                print("[debug] graph rect %s is a table: text in %d of its %d cells" % (
                    tuple(round(v, 2) for v in g["rect"]), len(cells), n), file=sys.stderr)
            continue
        out.append(g)
    return out


def find_page_graphs(it, texts, pno, debug):
    """Axes (ticks + labels + value mapping) paired into graphs."""
    axes = drop_duplicate_axes(resolve_shared_labels(find_axes(it.paths, texts, debug)))
    apply_axis_multipliers(axes, texts)
    graphs = add_panel_graphs(build_graphs(axes), axes, it.paths)
    graphs = drop_tables(graphs, texts, debug, text_boxes(it.paths))
    if debug:
        for g in graphs:
            print("[debug] page %d graph rect %s  x:%s  y:%s" % (
                pno, tuple(round(v, 2) for v in g["rect"]), g["x"]["map"], g["y"]["map"]),
                file=sys.stderr)
    if graphs:
        PAGE.graph_rects = [g["rect"] for g in graphs]
        # where each graph's x tick labels end: text just below them is its
        # axis title, not the title of a graph further down
        PAGE.xlabel_zones = [(g["rect"][0], g["rect"][2],
                              min(tx["bbox"][1] for _, tx in g["x"]["labels"]))
                             for g in graphs if g["x"].get("labels") and g["x"]["orient"] == "x"]
        sizes = sorted(tx["size"] for g in graphs for k in ("x", "y")
                       for _, tx in g[k].get("labels", ()))
        PAGE.label_size = sizes[len(sizes) // 2] if sizes else 0.0
        set_graph_backgrounds(graphs, it.paths)
    return graphs


def find_page_symbols(pdf, pno, it, text_parts):
    """The marker symbols of the page.  Markers outside the axis ranges are
    kept, even when the plot clips them out of view; each symbol notes the
    clipping box it was drawn with ('clip'), which tells which graph it
    belongs to."""
    symbols = find_symbols(it.paths, it.glyph_symbols, text_parts)
    symbols = rebuild_fragmented_circles(it.paths, symbols, text_parts, pdf.warnings)
    symbols = rebuild_strip_discs(it.paths, symbols)
    symbols = [s for s in symbols if s["idx"] not in PAGE.hiding_paths]
    symbols = drop_hidden_dots(drop_outline_rings(drop_highlight_boxes(symbols)), it.paths)
    symbols = drop_specks(drop_covered_bits(symbols, it.paths))
    clip_of = {p["idx"]: p.get("clip") for p in it.paths}
    for s in symbols:
        # (glyph markers carry their own clipping box)
        s["clip"] = clip_of[s["idx"]] if s["idx"] in clip_of else s.get("clip")
    return symbols


def describe_graphs(graphs, texts, symbols, first_no, debug):
    """Number, title, figure number and caption, and orientation of each
    graph."""
    lines = None
    for no, g in enumerate(graphs, first_no):
        g["no"] = no
        g["rot"], g["title"] = graph_rotation(g, texts, symbols)
        if lines is None:
            lines = text_lines(texts)
        g["figure"], g["caption"] = find_figure_caption(g["rect"], lines, PAGE.graph_rects)
        if g["figure"] and g["title"] and re.match(
                r"(?i)\s*fig(ure|\.)?\s*%s\b" % re.escape(g["figure"]), g["title"]):
            g["title"] = ""     # the caption below, taken for want of a title: not one
        if g["rot"]:
            # turned graph: the axis running across the page carries the
            # data y values, the one running up/down the page the x values
            g["x"], g["y"] = g["y"], g["x"]
            if "x2" in g or "y2" in g:            # a second scale follows its axis
                x2, y2 = g.pop("x2", None), g.pop("y2", None)
                if y2 is not None:
                    g["x2"] = y2
                if x2 is not None:
                    g["y2"] = x2
        if debug:
            print("[debug] graph %d title: %r rotation: %d" % (no, g["title"], g["rot"]),
                  file=sys.stderr)
            if g["figure"]:
                print("[debug] graph %d figure %s: %r" % (no, g["figure"], g["caption"]),
                      file=sys.stderr)


def add_bars_and_lines(graphs, symbols, paths, texts):
    """Graphs without marker symbols: report their bars (bar charts,
    histograms) or, failing that, the vertices of their data lines.  Short
    bars that look like squares are bars too.  Extends `symbols` in place;
    returns {id(line vertex symbol): series name from a line legend}."""
    line_names = {}
    owner = {}
    for s in symbols:
        if s["shape"] != "rectangle":
            owner.setdefault(id(graph_for_symbol(graphs, s)[1]), []).append(s)

    def bars_of(g):
        return [b for b in find_bars(g, paths) if graph_for_symbol(graphs, b)[1] is g]

    for g in graphs:
        marks = owner.get(id(g), [])
        bars = None
        if marks and all(s["shape"] == "square" for s in marks):
            bars = bars_of(g)
            bar_paths = {b["idx"] for b in bars}
            short = [s for s in marks if s["idx"] in bar_paths]
            # short bars taken for squares are bars; squares that are no
            # bars (legend keys of the bar colours) stay, if the bars are
            # most of the shapes
            if bars and (len(short) == len(marks) or len(bars) >= 3 * (len(marks) - len(short))):
                gone = {id(s) for s in short}
                symbols[:] = [s for s in symbols if id(s) not in gone]
                marks = []
        if marks:
            continue
        bars = bars_of(g) if bars is None else bars
        symbols += bars
        if bars:
            continue
        series = find_line_series(g, paths)
        names = legend_for_lines(series, paths, texts)
        for k, line in enumerate(series):
            for q in line["points"]:
                sym = {"shape": "line", "cx": q[0], "cy": q[1], "size": 0.0,
                       "filled": False, "rgb": line["rgb"], "idx": line["idx"]}
                if k in names:
                    line_names[id(sym)] = names[k]
                symbols.append(sym)
    return line_names

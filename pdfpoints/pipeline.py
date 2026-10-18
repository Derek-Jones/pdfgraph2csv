"""The extraction pipeline: for every page, draw it, read its text, find
axes and graphs, find the markers (or bars / line vertices), name their
series from the legends and map each point through its graph's axes.
"""

import sys

from .axes import drop_duplicate_axes, find_axes
from .charts import find_bars, find_line_series
from .colours import color_name
from .context import PAGE
from .document import Document
from .fragments import rebuild_fragmented_circles
from .graphs import (
    add_panel_graphs, build_graphs, clip_graph, graph_for_symbol, graph_rotation,
    set_graph_backgrounds)
from .interpreter import Interpreter
from .labels import apply_axis_multipliers, resolve_shared_labels
from .legend import SeriesNamer, find_page_legend, legend_for_lines
from .occlusion import cover_rects, drop_hidden_glyphs
from .outlined_text import outlined_text
from .scales import find_break_marks, map_value
from .symbols import LINE_SHAPES, drop_highlight_boxes, find_symbols
from .text import attach_vector_minus, merge_texts


class Options:
    """What to report (from the command line)."""

    def __init__(self, inside_only=False, max_frac=0.1, debug=False, exclude_legend=False):
        self.inside_only = inside_only        # drop symbols outside the axes box
        self.max_frac = max_frac              # largest marker, as part of the plot
        self.debug = debug                    # axis details on stderr
        self.exclude_legend = exclude_legend  # drop legend-key markers


def extract(pdf_path, pages=None, inside_only=False, max_frac=0.1, debug=False,
            exclude_legend=False, password=b"", info=None):
    """Return the data point rows of a PDF file (one dict per point).
    `pages` limits the work to a set of page numbers.  If `info` is a dict
    it receives 'graphs' (number of graphs found) and 'warnings'."""
    with open(pdf_path, "rb") as f:
        pdf = Document(f.read(), password)
    opts = Options(inside_only, max_frac, debug, exclude_legend)
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
    return rows


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
    symbols = find_page_symbols(pdf, pno, it, text_parts)
    describe_graphs(graphs, texts, symbols, first_no, opts.debug)
    line_names = add_bars_and_lines(graphs, symbols, it.paths, texts)
    legend = find_page_legend(symbols, texts, blobs, graphs, it.paths)
    if opts.debug and legend:
        print("[debug] legend keys: %s" % sorted(set(legend.values())), file=sys.stderr)
    namer = SeriesNamer(symbols, legend, graphs, line_names)
    return make_rows(pno, graphs, symbols, legend, namer, opts)


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


def find_page_graphs(it, texts, pno, debug):
    """Axes (ticks + labels + value mapping) paired into graphs."""
    axes = drop_duplicate_axes(resolve_shared_labels(find_axes(it.paths, texts, debug)))
    apply_axis_multipliers(axes, texts)
    graphs = add_panel_graphs(build_graphs(axes), axes, it.paths)
    if debug:
        for g in graphs:
            print("[debug] page %d graph rect %s  x:%s  y:%s" % (
                pno, tuple(round(v, 2) for v in g["rect"]), g["x"]["map"], g["y"]["map"]),
                file=sys.stderr)
    if graphs:
        PAGE.graph_rects = [g["rect"] for g in graphs]
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
    symbols = [s for s in symbols if s["idx"] not in PAGE.hiding_paths]
    symbols = drop_highlight_boxes(symbols)
    clip_of = {p["idx"]: p.get("clip") for p in it.paths}
    for s in symbols:
        s["clip"] = clip_of.get(s["idx"])
    return symbols


def describe_graphs(graphs, texts, symbols, first_no, debug):
    """Number, title and orientation of each graph."""
    for no, g in enumerate(graphs, first_no):
        g["no"] = no
        g["rot"], g["title"] = graph_rotation(g, texts, symbols)
        if g["rot"]:
            # turned graph: the axis running across the page carries the
            # data y values, the one running up/down the page the x values
            g["x"], g["y"] = g["y"], g["x"]
        if debug:
            print("[debug] graph %d title: %r rotation: %d" % (no, g["title"], g["rot"]),
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
            if bars and all(s["idx"] in bar_paths for s in marks):
                gone = {id(s) for s in marks}
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


def make_rows(pno, graphs, symbols, legend, namer, opts):
    """One output row per reported symbol."""
    rows = []
    for si, s in enumerate(symbols):
        if s["shape"] == "rectangle" and si not in legend:
            continue                      # oblong boxes count only as legend keys
        d, g = graph_for_symbol(graphs, s)
        x0, y0, x1, y1 = g["rect"]
        w, h = x1 - x0, y1 - y0
        if d > 0.5 * max(w, h) and si not in legend and clip_graph(graphs, s) is not g:
            continue                      # far from every graph (and not drawn in one)
        # markers are small, but in tiny panels (small multiples) a few
        # points of marker are still a large share of the panel
        if s["shape"] not in ("bar", "line") and \
                s["size"] > max(opts.max_frac * min(w, h), min(3.5, 0.4 * min(w, h))):
            continue
        if opts.inside_only and d > 1e-6 or opts.exclude_legend and si in legend:
            continue
        name, hexs = color_name(s["rgb"])
        if s["shape"] in LINE_SHAPES or s["shape"] in ("bar", "line"):
            sym_name = s["shape"]
        else:
            sym_name = ("filled-" if s["filled"] else "open-") + s["shape"]
        rows.append({
            "page": pno, "graph": g["no"], "graph_title": g["title"],
            "symbol": sym_name,
            "x_coord": map_value(g["x"]["map"], s["cy"] if g["rot"] else s["cx"]),
            "y_coord": map_value(g["y"]["map"], s["cx"] if g["rot"] else s["cy"]),
            "color": name, "color_hex": hexs,
            "series": namer.name(si, s, g),
            "rotation": g["rot"],
            "legend_key": 1 if si in legend else 0,
            "pdf_x": s["cx"], "pdf_y": s["cy"]})
    return rows

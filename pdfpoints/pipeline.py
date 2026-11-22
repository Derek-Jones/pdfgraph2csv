"""The extraction pipeline: for every page, draw it, read its text, find
axes and graphs, find the markers (or bars / line vertices), name their
series from the legends and map each point through its graph's axes.
"""

import collections
import math
import re
import sys

from .axes import drop_duplicate_axes, drop_scattered_tick_axes, find_axes
from .charts import find_bars, find_boxes, find_line_series, find_stems
from .context import PAGE
from .datalabels import add_data_labels
from .document import Document
from .errbars import find_error_bars
from .fragments import rebuild_fragmented_circles, rebuild_strip_discs
from .geometry import fmt_rect, median
from .colourbar import add_heat_tiles
from .grouplabels import group_categories, label_bar_groups
from .graphs import (
    add_panel_graphs, build_graphs, forget_graphs, graph_for_symbol, graph_rotation,
    set_graph_backgrounds)
from .image_marks import image_symbols
from .interpreter import Interpreter
from .labels import apply_axis_multipliers, resolve_shared_labels
from .legend import SeriesNamer, find_page_legend, legend_for_lines, patch_swatches
from .meta import graph_meta
from .nongraphs import axis_labels, drop_tables, text_boxes
from .occlusion import cover_rects, drop_hidden_glyphs
from .outlined_text import outlined_text
from .rows import legend_looks, make_rows, marker_sized, name_box_slots, reportable
from .scales import find_break_marks
from .strays import (drop_box_dashes, drop_corner_ticks, drop_foreign_crowds, drop_plot_backgrounds,
                     drop_pattern_dashes, drop_rule_joints, drop_symbols_in_prose, add_dash_markers,
                     mark_legend_frames, fill_circles_under_dots, merge_crossed_squares)
from .styles import guess_tool
from .symbols import (drop_covered_bits, drop_lone_turned, drop_hidden_dots, drop_highlight_boxes,
                      drop_marker_faces,
                      drop_outline_rings, drop_specks, find_symbols)
from .text import attach_vector_minus, merge_texts, split_numbers
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
                # graph lookups cached for the page hold on to its graphs (and
                # results cached on its subpaths): let them go
                forget_graphs()
    return rows


def page_turn(texts):
    """The angle (90, -90 or 180) by which a page's content is drawn turned,
    or 0.  Seongmin-PhD-044 (cairo, a thesis page set sideways) turns four
    ggplot figures 90 degrees anticlockwise: caption, titles, legends and
    axis titles read up the page, while each panel's value labels, turned
    in the figure's own frame as R draws them, read across it (or upside
    down) and spoil the turned-graph test of each graph (graph_rotation:
    both axes' labels turned alike).  When 60% or more of the page's
    characters (60 or more) read one turned way, three times as many as
    read any other way (Seongmin-PhD-044: 597 up the page, 110 across, 108
    upside down), the page is read in that frame."""
    count = collections.Counter()
    for t in texts:
        n = len(t["text"].strip())
        ux, uy = t["up"]
        if not n or not (ux or uy):
            continue
        a = math.degrees(math.atan2(-ux, uy))
        r = min((0, 90, -90, 180), key=lambda r: abs((a - r + 180) % 360 - 180))
        if abs((a - r + 180) % 360 - 180) <= 10:
            count[r] += n
    total = sum(count.values())
    if total < 60:
        return 0
    (r, n), rest = count.most_common(1)[0], count.most_common()[1:]
    return r if r and n >= 0.6 * total and all(n >= 3 * m for _, m in rest) else 0


def turn_matrix(page, rot):
    """(ctm drawing the page turned upright, the map from that frame back to
    PDF page points), for content turned by `rot` (geometry.to_frame)."""
    x0, y0, x1, y1 = page.mediabox
    if rot == 90:            # (x, y) -> (y, x0 + x1 - x)
        w = x0 + x1
        return (0, -1, 1, 0, 0, w), lambda p: (w - p[1], p[0])
    if rot == -90:           # (x, y) -> (y0 + y1 - y, x)
        h = y0 + y1
        return (0, 1, -1, 0, h, 0), lambda p: (p[1], h - p[0])
    w, h = x0 + x1, y0 + y1  # (x, y) -> (w - x, h - y)
    return (-1, 0, 0, -1, w, h), lambda p: (w - p[0], h - p[1])


def share_pair_titles(graphs, texts, symbols):
    """Two panels side by side under one title, centred over the pair
    (Seongmin-PhD-044: "commons-cli criterion5" over its deleted-lines and
    time panels): graphs left without a title look for one over the union
    of their box and a neighbour's of the same height (to 2 pt) a little
    way off (a gap under a tenth of their width); both take it."""
    from .titles import find_title
    for g in graphs:
        if g["title"] or g["rot"]:
            continue
        x0, y0, x1, y1 = g["rect"]
        for o in graphs:
            if o is g or o["rot"] or o["title"]:
                continue
            ox0, oy0, ox1, oy1 = o["rect"]
            gap = max(ox0 - x1, x0 - ox1)
            if abs(oy0 - y0) > 2 or abs(oy1 - y1) > 2 or not 0 <= gap < 0.1 * min(x1 - x0, ox1 - ox0):
                continue
            title = find_title((min(x0, ox0), min(y0, oy0), max(x1, ox1), max(y1, oy1)),
                               texts, symbols)
            if title:
                g["title"] = o["title"] = title
                break


def extract_page(pdf, pno, page, opts, info):
    """The pipeline for one page: draw it, read its text, find the axes and
    graphs, find the markers (or bars / line vertices), name the series from
    the legends and map every point through its graph's axes."""
    PAGE.reset()
    PAGE.number = pno
    it = Interpreter(pdf)
    it.run_page(page)
    if opts.debug and it.op_errors:
        for (op, kind), (n, msg) in sorted(it.op_errors.items()):
            print("[debug] page %d: operator %s raised %s %d time(s) (ignored): %s"
                  % (pno, op, kind, n, msg), file=sys.stderr)
    turn = page_turn(it.texts)
    if turn:
        # a page whose content is drawn turned is read turned upright
        ctm, PAGE.unturn = turn_matrix(page, turn)
        PAGE.turn = turn
        it = Interpreter(pdf)
        it.run_page(page, ctm)
    texts, text_parts, blobs = read_page_text(it)
    # boxes that may hold notes: they excuse their text from the word limit
    # of a graph and their dashed borders from being points
    boxes = text_boxes(it.paths)
    graphs = find_page_graphs(it, texts, boxes, pno, opts.debug)
    if not graphs:
        return []
    info["graphs"] += len(graphs)
    # graphs are numbered through the document: info carries the count
    first_no = info.setdefault("graph_no", 0) + 1
    info["graph_no"] += len(graphs)

    # markers, less the shapes that only look like markers once the
    # graphs are known (strays.py)
    symbols = find_page_symbols(pdf, it, text_parts)
    symbols = drop_plot_backgrounds(symbols, graphs)
    symbols = drop_corner_ticks(symbols, graphs)
    symbols = drop_symbols_in_prose(symbols, texts, graphs)
    symbols = drop_box_dashes(symbols, texts, boxes, graphs)
    symbols = drop_rule_joints(symbols, it.paths)
    symbols = drop_pattern_dashes(symbols, it.paths)
    symbols = add_dash_markers(symbols, it.paths, graphs)
    symbols = drop_foreign_crowds(symbols, graphs)
    symbols = mark_legend_frames(symbols, it.paths, graphs)
    symbols = fill_circles_under_dots(symbols, it.texts)
    symbols = merge_crossed_squares(symbols)

    # titles and turned graphs before anything that reads text around a
    # graph (legends, twin scales)
    describe_graphs(graphs, texts, symbols, first_no, opts.debug)
    share_pair_titles(graphs, texts, symbols)
    by_x = PathsByX(it.paths)
    for g in graphs:
        x0, _, x1, _ = g["rect"]
        mine = by_x.between(x0 - 0.1 * (x1 - x0), x1 + 0.1 * (x1 - x0))
        g["tool"] = graph_tool(g, mine, it.glyph_symbols) or pdf.tool
        g["tool_guess"] = guess_tool(g["rect"], mine, it.texts, it.glyph_symbols)
    line_names = add_bars_and_lines(graphs, symbols, it.paths, texts,
                                    lambda s, g, d: reportable(graphs, s, g, d, opts))
    # heat maps: a point per tile, valued by the colour bar beside it
    add_heat_tiles(graphs, symbols, it.paths, it.colour_strips, texts)
    # the resolution of each symbol's coordinates (from the path drawing
    # it) decides how many digits its values are written with
    res_of = {p["idx"]: p.get("res") for p in it.paths}
    for s in symbols:
        if s.get("res") is None:
            s["res"] = res_of.get(s["idx"])
    # (bar-legend patches, too oblong to be markers, are swatches)
    symbols += patch_swatches(it.paths, texts, graphs)
    legend = find_page_legend(symbols, texts, blobs, graphs, it.paths)
    if opts.debug and legend:
        print("[debug] legend keys: %s" % sorted(set(legend.values())), file=sys.stderr)
    # the short texts beside points ("55%"): the label column
    names = set(legend.values()) | set(line_names.values())
    add_data_labels(graphs, symbols, texts, legend, names, boxes,
                    _labellable(graphs, symbols, legend, opts))
    namer = SeriesNamer(symbols, legend, graphs, line_names)
    # with a scale on both sides, each series must be mapped by its own
    twin_axes(graphs, symbols, namer, texts, opts.debug)
    bars = find_error_bars(symbols, it.paths,
                           lambda s: graph_for_symbol(graphs, s)[1]) if opts.errbars else {}
    rows = make_rows(pno, graphs, symbols, legend, namer, opts, bars)
    name_box_slots(rows)
    renumber_graphs(graphs, rows, info)
    warn_twin_unsure(graphs, rows, pdf.warnings)
    info.setdefault("meta", []).extend(graph_meta(pno, graphs, rows))
    return rows


def renumber_graphs(graphs, rows, info):
    """Number the graphs that have rows 1, 2, 3 ... through the document,
    in the order found; a graph without points gets no number (its meta
    record shows none).  The numbers given while reading the page (and
    shown in debug output) count every graph found: in
    Statistical_Test_Coverage_for_Linux the graphs of pages 6, 8 and 11
    give no points, and the CSV's graphs were numbered 2 and 4."""
    used = {r["graph"] for r in rows}
    new = {}
    for g in graphs:
        if g["no"] in used:
            info["out_no"] = info.get("out_no", 0) + 1
            new[g["no"]] = info["out_no"]
            g["no"] = info["out_no"]
        else:
            g["no"] = ""
    for r in rows:
        r["graph"] = new[r["graph"]]


def _labellable(graphs, symbols, legend, opts):
    """Whether a symbol can carry a data label: a bar, or a marker of a
    size rows.make_rows accepts.  (Line corners are no drawn marks.)"""
    keyed = legend_looks(symbols, legend)

    keys = {id(symbols[i]) for i in legend}

    def test(s):
        if s["shape"] == "tile":
            return True                   # a heat map's cell (its printed value)
        return s["shape"] != "line" and marker_sized(
            s, graph_for_symbol(graphs, s)[1], opts, keyed if id(s) not in keys else ())
    return test

def read_page_text(it):
    """All text of the page: real text (minus glyphs painted over by later
    boxes) and text drawn as glyph outlines, read by shape.  Returns
    (texts, outline parts that are text, unreadable outlined words).
    The outline parts are returned so that the letters 'o' and full stops
    of outlined text are not taken for markers; the unreadable words still
    serve as category and legend labels (numbered #1, #2, ...)."""
    covers = cover_rects(it.paths, it.images)
    it.texts = drop_hidden_glyphs(it.texts, covers)
    # (axis-break wiggles must be known before outlined text is read: they
    # are no glyphs)
    PAGE.break_marks = find_break_marks(it.paths)
    blobs = []
    out_texts, text_parts = outlined_text(it.paths, blobs, covers)
    texts = merge_texts(it.texts) + merge_texts(out_texts)
    attach_vector_minus(texts, it.paths)
    # short texts and unreadable words: the candidates for category labels
    # (several numbers set as one string, "12.8 25.6", one label each)
    PAGE.nominal_labels = [u for t in texts if t["text"].strip()
                           and len(t["text"].strip()) <= 40 for u in split_numbers(t)] + blobs
    return texts, text_parts, blobs


def find_page_graphs(it, texts, boxes, pno, debug):
    """Axes (ticks + labels + value mapping) paired into graphs, less the
    candidates that are tables or text (nongraphs.py)."""
    axes = drop_duplicate_axes(resolve_shared_labels(drop_scattered_tick_axes(
        find_axes(it.paths, texts, debug))))
    apply_axis_multipliers(axes, texts)
    graphs = add_panel_graphs(build_graphs(axes), axes, it.paths)
    graphs = drop_tables(graphs, texts, debug, boxes, it.paths)
    if debug:
        for g in graphs:
            print("[debug] page %d graph rect %s  x:%s  y:%s" % (
                pno, fmt_rect(g["rect"]), g["x"]["map"], g["y"]["map"]), file=sys.stderr)
    if graphs:
        PAGE.graph_rects = [g["rect"] for g in graphs]
        # where each graph's x tick labels end: text just below them is its
        # axis title, not the title of a graph further down
        PAGE.xlabel_zones = [(g["rect"][0], g["rect"][2],
                              min(tx["bbox"][1] for _, tx in g["x"]["labels"]))
                             for g in graphs if g["x"].get("labels") and g["x"]["orient"] == "x"]
        # the page's typical tick-label size: a graph's title is set no
        # smaller than its labels (titles.py)
        PAGE.label_size = median((t["size"] for g in graphs for t in axis_labels(g)), 0.0)
        set_graph_backgrounds(graphs, it.paths)
    return graphs


def find_page_symbols(pdf, it, text_parts):
    """The marker symbols of the page.  Markers outside the axis ranges are
    kept, even when the plot clips them out of view (the user asked for
    them); each symbol notes the clipping box it was drawn with ('clip'),
    which tells which graph it belongs to."""
    symbols = drop_lone_turned(find_symbols(it.paths, it.glyph_symbols, text_parts))
    # markers some programs break into pieces (flattened transparency,
    # strips of a disc) are put back together before the filters below,
    # which would take the pieces for specks
    symbols = rebuild_fragmented_circles(it.paths, symbols, text_parts, pdf.warnings)
    symbols = rebuild_strip_discs(it.paths, symbols)
    # shapes that are painted over, highlight boxes and rings round a
    # marker, specks and stray bits: none of them is a point of its own
    symbols = [s for s in symbols if s["idx"] not in PAGE.hiding_paths]
    symbols = drop_hidden_dots(drop_outline_rings(drop_marker_faces(drop_highlight_boxes(symbols), it.paths)), it.paths)
    symbols = drop_specks(drop_covered_bits(symbols, it.paths))
    # markers drawn as small pictures (shadows dropped)
    symbols += image_symbols(it.image_marks, it.paths)
    clip_of = {p["idx"]: p.get("clip") for p in it.paths}
    for s in symbols:
        # (glyph markers carry their own clipping box)
        s["clip"] = clip_of[s["idx"]] if s["idx"] in clip_of else s.get("clip")
    return symbols


def describe_graphs(graphs, texts, symbols, first_no, debug):
    """Number, title, figure number and caption, and orientation of each
    graph (for the -meta file; the orientation also decides which axis
    gives x and which y)."""
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


def add_bars_and_lines(graphs, symbols, paths, texts, reportable=None):
    """Graphs without marker symbols: report their bars (bar charts,
    histograms) or, failing that, the vertices of their data lines, so that
    such graphs still give their data.  Short bars that look like squares
    are bars too.  Extends `symbols` in place; returns {id(line vertex
    symbol): series name from a line legend}.  Only shapes that could be
    reported as the graph's points count as its markers (`reportable`):
    the circles of a diagram in the other column of
    Statistical_Test_Coverage_for_Linux's pages 6 and 11, nearest to the
    page's only graph, hid its curve."""
    line_names = {}
    owner = {}
    outside = {}
    for s in symbols:
        if s["shape"] != "rectangle" or s.get("marker"):
            d, g = graph_for_symbol(graphs, s)
            if reportable is not None and not reportable(s, g, d):
                continue
            (outside if d > 0 else owner).setdefault(id(g), []).append(s)
    # markers outside a graph's box are its own unless they crowd there
    # (100 or more, over twice as many as inside): a drawing beside the
    # plot (the networks above 2204.07073-010's bars), reported, but no
    # reason to leave out the bars inside
    for gid, outs in outside.items():
        if len(outs) < 100 or len(outs) <= 2 * len(owner.get(gid, ())):
            owner.setdefault(gid, []).extend(outs)

    def bars_of(g):
        return [b for b in find_bars(g, paths) if graph_for_symbol(graphs, b)[1] is g]

    def stems_of(g, marks):
        stems, dots = find_stems(g, paths, marks)
        return [s for s in stems if graph_for_symbol(graphs, s)[1] is g], dots

    for g in graphs:
        marks = owner.get(id(g), [])
        bars = None
        # a box plot: its boxes, instead of the square/rectangle "markers"
        # their rectangles made; other markers (outliers) stay
        boxes = find_boxes(g, paths)
        if boxes:
            def in_box(s, boxes=boxes):
                return s["shape"] in ("square", "rectangle") and any(
                    r[0] - 0.5 <= s["cx"] <= r[2] + 0.5 and r[1] - 0.5 <= s["cy"] <= r[3] + 0.5
                    for r, _ in boxes)
            gone = {id(s) for s in marks if in_box(s)}
            symbols[:] = [s for s in symbols if id(s) not in gone]
            for _, pts in boxes:
                symbols += pts
            continue
        # the only marks are the dots of stems of no height (a stem plot,
        # jordan-teh-026): the stems are the data, unless there are bars
        if marks and all(s["shape"] == "circle" and s["size"] <= 1.0 for s in marks):
            stems, dots = stems_of(g, marks)
            if stems and len(dots) == len(marks) and not bars_of(g):
                symbols[:] = [s for s in symbols if id(s) not in dots]
                symbols += stems
                continue
        # (and so are the thin segments of stacked bars taken for dash
        # markers: Memory_systems_cacheDRAMdisk-051)
        if marks and all(s["shape"] in ("square", "rectangle") for s in marks):
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
            # a second row of x labels naming groups of bars; categories
            # that each stand for a set of groups
            label_bar_groups(g, bars, texts)
            group_categories(g, bars)
            continue
        stems = stems_of(g, ())[0]
        if stems:
            symbols += stems
            continue
        series = find_line_series(g, paths)
        names = legend_for_lines(series, paths, texts, g["rect"])
        for k, line in enumerate(series):
            for q in line["points"]:
                sym = {"shape": "line", "cx": q[0], "cy": q[1], "size": 0.0,
                       "filled": False, "rgb": line["rgb"], "idx": line["idx"]}
                if k in names:
                    line_names[id(sym)] = names[k]
                symbols.append(sym)
    return line_names

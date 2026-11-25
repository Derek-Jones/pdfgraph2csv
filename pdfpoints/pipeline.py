"""The extraction pipeline: for every page, draw it, read its text, find
axes and graphs, find the markers (or bars / line vertices), name their
series from the legends and map each point through its graph's axes.
"""

import collections
import math
import re
import sys

from .axes import drop_duplicate_axes, drop_scattered_tick_axes, find_axes
from .charts import find_bars, find_boxes, find_line_series, find_stacked_areas, find_stems, find_violins
from .context import PAGE
from .datalabels import add_data_labels
from .document import Document
from .errbars import find_error_bars, lone_capped_bars
from .fragments import rebuild_fragmented_circles, rebuild_strip_discs
from .geometry import fmt_rect, median
from .colourbar import add_heat_tiles, heatmap_values
from .grouplabels import group_categories, label_bar_groups
from .graphs import (
    add_panel_graphs, build_graphs, drop_same_plot_graphs, forget_graphs, graph_for_symbol, graph_rotation,
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
                      drop_outline_rings, drop_specks, find_symbols, drop_arrowheads)
from .text import (attach_vector_minus, billions_not_bytes, drop_repeated_texts, merge_texts,
                   split_numbers)
from .titles import find_figure_caption, text_lines
from .tools import PathsByX, graph_tool
from .twin import twin_axes, warn_twin_unsure


class Options:
    """What to report (from the command line)."""

    def __init__(self, inside_only=False, max_frac=0.1, debug=False, exclude_legend=False,
                 errbars=False, heatmap=False):
        self.inside_only = inside_only        # drop symbols outside the axes box
        self.max_frac = max_frac              # largest marker, as part of the plot
        self.debug = debug                    # axis details on stderr
        self.exclude_legend = exclude_legend  # drop legend-key markers
        self.errbars = errbars                # low/high ends of error bars
        self.heatmap = heatmap                # markers valued by a colour bar


def extract(pdf_path, pages=None, inside_only=False, max_frac=0.1, debug=False,
            exclude_legend=False, password=b"", info=None, errbars=False, heatmap=False):
    """Return the data point rows of a PDF file (one dict per point).
    `pages` limits the work to a set of page numbers.  If `info` is a dict
    it receives 'graphs' (number of graphs found) and 'warnings'."""
    with open(pdf_path, "rb") as f:
        pdf = Document(f.read(), password)
    opts = Options(inside_only, max_frac, debug, exclude_legend, errbars, heatmap)
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
    # round letters of unread outlined names ("o", "e") outside every plot:
    # flanked by letters of those names on both sides, close
    # (2355585.2355594-006's slanted benchmark names; a legend key has its
    # name on one side only, and markers inside a plot may crowd into
    # unread "words" of marker shapes)
    blob_boxes = [t["bbox"] for t in PAGE.nominal_labels if t.get("text") is None]
    if blob_boxes:
        symbols = [s for s in symbols if any(
            g["rect"][0] - 0.5 * s["size"] <= s["cx"] <= g["rect"][2] + 0.5 * s["size"] and
            g["rect"][1] - 0.5 * s["size"] <= s["cy"] <= g["rect"][3] + 0.5 * s["size"]
            for g in graphs) or not _flanked_by_letters(s, blob_boxes)]
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
    add_heat_tiles(graphs, symbols, it.paths, it.colour_strips, texts, it.pictures, opts.heatmap)
    # capped error bars with no marker: a group's mean (an "H" on its side)
    symbols += lone_capped_bars(graphs, symbols, it.paths,
                                lambda s: graph_for_symbol(graphs, s)[1])
    # the resolution of each symbol's coordinates (from the path drawing
    # it) decides how many digits its values are written with
    res_of = {p["idx"]: (p.get("res"), p.get("scale")) for p in it.paths}
    for s in symbols:
        r, sc = res_of.get(s["idx"], (None, None))
        if s.get("res") is None:
            s["res"] = r
        if s.get("scale") is None and not s.get("image"):
            s["scale"] = sc
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
    if opts.heatmap:
        # markers coloured along a colour bar: the value each colour stands for
        heatmap_values(graphs, symbols, it.colour_strips, texts,
                       lambda s: graph_for_symbol(graphs, s)[1])
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

def drop_clipped_texts(texts):
    """Text whose middle lies outside its clipping box or the /BBox of the
    form drawing it (by more than 0.5 pt) is not seen: a figure included
    with its edges trimmed off keeps them in the file (Sovinsky-paper-017: the Stata figure, printed to PDF
    with its first caption "Figure 4: ...", clipped to the graph in the
    paper, whose caption reads "Figure 5: ...")."""
    out = []
    for t in texts:
        x, y = t["center"] if "center" in t else t["p0"]
        if all(c is None or c[0] - 0.5 <= x <= c[2] + 0.5 and c[1] - 0.5 <= y <= c[3] + 0.5
               for c in (t.get("clip"), t.get("form_box"))):
            out.append(t)
    return out


def read_page_text(it):
    """All text of the page: real text (minus glyphs painted over by later
    boxes) and text drawn as glyph outlines, read by shape.  Returns
    (texts, outline parts that are text, unreadable outlined words).
    The outline parts are returned so that the letters 'o' and full stops
    of outlined text are not taken for markers; the unreadable words still
    serve as category and legend labels (numbered #1, #2, ...)."""
    covers = cover_rects(it.paths, it.images)
    it.texts = drop_hidden_glyphs(drop_repeated_texts(drop_clipped_texts(it.texts)), covers)
    # (axis-break wiggles must be known before outlined text is read: they
    # are no glyphs)
    PAGE.break_marks = find_break_marks(it.paths)
    blobs = []
    read_parts = set()
    out_texts, text_parts = outlined_text(it.paths, blobs, covers, read_parts)
    # (parts of unread "words": a marker drawn as filled strokes may be
    # grouped as one - 1356058.1356080-007's 'x' of four filled half-arms)
    PAGE.blob_parts = text_parts - read_parts
    texts = merge_texts(it.texts) + merge_texts(out_texts)
    billions_not_bytes(texts)
    attach_vector_minus(texts, it.paths)
    # short texts and unreadable words: the candidates for category labels
    # (several numbers set as one string, "12.8 25.6", one label each)
    PAGE.nominal_labels = [u for t in texts if t["text"].strip()
                           and len(t["text"].strip()) <= 40 for u in split_numbers(t)] + blobs
    return texts, text_parts, blobs


def _off_colour_bars(axes, strips):
    """Axes less those running along the long side of a colour bar (a
    colour strip image; within 1.5 pt, over most of its length): the bar's
    own scale, which is no graph's axis (2020.01.30.927558.full-048: the
    ticks 0 ... 40 beside its bar were the y axis of the bar chart left of
    it)."""
    boxes = []
    for st in strips or ():
        a, b, c, d, e, f = st["ctm"]
        cs = [(a * u + c * v + e, b * u + d * v + f) for u, v in ((0, 0), (1, 0), (0, 1), (1, 1))]
        boxes.append((min(p[0] for p in cs), min(p[1] for p in cs),
                      max(p[0] for p in cs), max(p[1] for p in cs)))

    def along(ax):
        for x0, y0, x1, y1 in boxes:
            if ax["orient"] == "y" and y1 - y0 > x1 - x0:
                if min(abs(ax["pos"] - x0), abs(ax["pos"] - x1)) <= 1.5 and \
                        min(ax["hi"], y1) - max(ax["lo"], y0) >= 0.8 * (y1 - y0):
                    return True
            if ax["orient"] == "x" and x1 - x0 > y1 - y0:
                if min(abs(ax["pos"] - y0), abs(ax["pos"] - y1)) <= 1.5 and \
                        min(ax["hi"], x1) - max(ax["lo"], x0) >= 0.8 * (x1 - x0):
                    return True
        return False
    return [ax for ax in axes if not along(ax)]


def find_page_graphs(it, texts, boxes, pno, debug):
    """Axes (ticks + labels + value mapping) paired into graphs, less the
    candidates that are tables or text (nongraphs.py)."""
    axes = drop_duplicate_axes(_off_colour_bars(resolve_shared_labels(drop_scattered_tick_axes(
        find_axes(it.paths, texts, debug))), it.colour_strips))
    apply_axis_multipliers(axes, texts)
    graphs = drop_same_plot_graphs(add_panel_graphs(build_graphs(axes), axes, it.paths))
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
                              min(tx["bbox"][1] for _, tx in g["x"]["labels"]), tuple(g["rect"]))
                             for g in graphs if g["x"].get("labels") and g["x"]["orient"] == "x"]
        # the page's typical tick-label size: a graph's title is set no
        # smaller than its labels (titles.py)
        PAGE.label_size = median((t["size"] for g in graphs for t in axis_labels(g)), 0.0)
        set_graph_backgrounds(graphs, it.paths)
    return graphs


def _on_bar(s, b):
    """Is shape s centred on bar b (its middle across the bar within 30%
    of the bar's width, along it between its foot and its end)?  For a
    horizontal bar, across is y (2020.01.30.927558.full-026: a short bar's
    outline, as tall as long, taken for a square)."""
    j, k = ("cy", "cx") if b.get("horizontal") else ("cx", "cy")
    end, foot = b[k], b.get("base", b[k])
    return abs(s[j] - b[j]) <= 0.3 * b["size"] and \
        min(end, foot) - 0.5 <= s[k] <= max(end, foot) + 0.5


def _flanked_by_letters(s, boxes):
    """Is marker s a letter of an unread word: grey or black like text,
    two of the word's letter boxes (`boxes`) of about its size (0.5 to 1.5
    times their height... their height 0.67 to 2 times its size) within
    0.35 of their height of it, on opposite sides of it?  (Not a yellow
    note pointer among a note's letters: ITRS_2011ExecSum-031.)"""
    if s["shape"] in ("line", "bar", "stem", "tile") or s["size"] <= 0:
        return False
    rgb = s.get("rgb") or (0.0, 0.0, 0.0)
    if max(rgb) - min(rgb) > 0.1:
        return False
    near = []
    for b in boxes:
        h = b[3] - b[1]
        if not 0.67 * s["size"] <= h <= 2.0 * s["size"]:
            continue
        gx = max(b[0] - s["cx"], s["cx"] - b[2], 0.0) - 0.5 * s["size"]
        gy = max(b[1] - s["cy"], s["cy"] - b[3], 0.0) - 0.5 * s["size"]
        if max(gx, gy) <= 0.35 * h:
            near.append(((b[0] + b[2]) / 2 - s["cx"], (b[1] + b[3]) / 2 - s["cy"]))
    return any(u[0] * v[0] + u[1] * v[1] < 0 for i, u in enumerate(near) for v in near[i + 1:])


def find_page_symbols(pdf, it, text_parts):
    """The marker symbols of the page.  Markers outside the axis ranges are
    kept, even when the plot clips them out of view (the user asked for
    them); each symbol notes the clipping box it was drawn with ('clip'),
    which tells which graph it belongs to."""
    symbols = drop_lone_turned(find_symbols(it.paths, it.glyph_symbols, text_parts,
                                            getattr(PAGE, "blob_parts", frozenset())))
    # markers some programs break into pieces (flattened transparency,
    # strips of a disc) are put back together before the filters below,
    # which would take the pieces for specks
    symbols = rebuild_fragmented_circles(it.paths, symbols, text_parts, pdf.warnings)
    # (circles rebuilt from curved pieces outside every plot box are the
    # round letters of axis labels and titles drawn as outlines, not
    # markers: PhysRevResearch.3.033169-009's blue and red tick labels -
    # coloured, so the circle rebuilder may use their pieces - and its
    # unread epsilon gave circles of the markers' size beside the axes)
    symbols = [s for s in symbols if not s.get("rebuilt") or any(
        r[0] - 0.5 * s["size"] <= s["cx"] <= r[2] + 0.5 * s["size"] and
        r[1] - 0.5 * s["size"] <= s["cy"] <= r[3] + 0.5 * s["size"] for r in PAGE.graph_rects)]
    symbols = rebuild_strip_discs(it.paths, symbols)
    # shapes that are painted over, highlight boxes and rings round a
    # marker, specks and stray bits: none of them is a point of its own
    symbols = [s for s in symbols if s["idx"] not in PAGE.hiding_paths]
    symbols = drop_hidden_dots(drop_outline_rings(drop_marker_faces(drop_highlight_boxes(symbols), it.paths)), it.paths)
    symbols = drop_specks(drop_covered_bits(symbols, it.paths))
    # heads of arrows pointing at points from their labels
    PAGE.arrows = []
    symbols = drop_arrowheads(symbols, it.paths, PAGE.arrows)
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
        # a stacked area chart: the bands' tops, whatever marks there are
        # (economies-open-intelligence-005's legend circles stay keys)
        areas = find_stacked_areas(g, paths)
        if areas:
            symbols += [a for a in areas if graph_for_symbol(graphs, a)[1] is g]
            continue
        # violin plots with inner boxes: five points each, instead of the
        # marks their strokes made
        violins = find_violins(g, paths)
        if violins:
            gone = {id(s) for s in marks if any(
                r[0] - 0.5 <= s["cx"] <= r[2] + 0.5 and r[1] - 0.5 <= s["cy"] <= r[3] + 0.5
                for r, _ in violins)}
            symbols[:] = [s for s in symbols if id(s) not in gone]
            for _, pts in violins:
                symbols += pts
            continue
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
        if marks and all(s["shape"] in ("square", "rectangle", "cross", "plus") for s in marks):
            bars = bars_of(g)
            bar_paths = {b["idx"] for b in bars}
            # (by place too: a square of a bar's fill and outline may carry
            # the outline's path - VaskeBeaman2006-Lessonslearned-003's bars
            # of 1, as tall as wide, the outline drawn right after the fill)
            # (a cross on a bar no longer than it is its error bar over the
            # bar's edge: a bar of almost nothing with its error bar,
            # 2020.01.30.927558.full-023; not plus markers on bar tops)
            short = [s for s in marks if (s["shape"] in ("square", "rectangle") and (
                s["idx"] in bar_paths or any(abs(s["idx"] - b["idx"]) == 1 and _on_bar(s, b)
                                             for b in bars))) or
                     (s["shape"] in ("cross", "plus") and any(
                         _on_bar(s, b) and abs(b["cy" if not b.get("horizontal") else "cx"] -
                                               b.get("base", 0.0)) <= s["size"] for b in bars))]
            # short bars taken for squares are bars; squares that are no
            # bars (legend keys of the bar colours) stay, if the bars are
            # most of the shapes
            if bars and (len(short) == len(marks) or len(bars) >= 3 * (len(marks) - len(short))):
                gone = {id(s) for s in short}
                symbols[:] = [s for s in symbols if id(s) not in gone]
                marks = []
        if marks:
            # bars under line-and-marker series in a graph with a scale on
            # each side (Seongmin-PhD-036: R barplot()s with points() and
            # lines() of ratios over them): three or more bars standing on
            # the baseline are reported too, and squares that are short
            # bars (by path, or the outline drawn next to the fill) are no
            # markers
            # (only in a graph with a scale on each side: elsewhere square
            # markers and background grids pass for bars)
            if "y2" in g or "x2" in g:
                bars = bars_of(g) if bars is None else bars
            if ("y2" in g or "x2" in g) and len(bars) >= 3:
                bar_paths = {b["idx"] for b in bars}
                short = {id(s) for s in marks if s["shape"] in ("square", "rectangle") and (
                    s["idx"] in bar_paths or any(
                        abs(s["idx"] - b["idx"]) == 1 and _on_bar(s, b) for b in bars))}
                symbols[:] = [s for s in symbols if id(s) not in short]
                symbols += bars
                label_bar_groups(g, bars, texts)
                group_categories(g, bars)
            continue
        bars = bars_of(g) if bars is None else bars
        symbols += bars
        if bars:
            # (rectangles that are short bars' outlines, centred on a bar
            # and as wide, go: 2020.01.30.927558.full-048)
            outl = {id(s) for s in symbols if s["shape"] == "rectangle" and not s.get("marker") and
                    any(abs(s["size"] - b["size"]) <= 0.2 * b["size"] and _on_bar(s, b) for b in bars)}
            if outl:
                symbols[:] = [s for s in symbols if id(s) not in outl]
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
                if line.get("clip"):
                    # (a vertex clipped out of view stays with its graph)
                    sym["clip"] = line["clip"]
                if k in names:
                    line_names[id(sym)] = names[k]
                symbols.append(sym)
    return line_names

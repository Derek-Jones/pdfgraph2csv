"""The extraction pipeline: for every page, draw it, read its text, find
axes and graphs, find the markers (or bars / line vertices), name their
series from the legends and map each point through its graph's axes.
"""

import collections
import math
import re
import sys
import time

from .axes import drop_duplicate_axes, drop_scattered_tick_axes, find_axes
from .charts import find_bars, find_boxes, find_line_series, find_stacked_areas, find_stems, find_violins
from .datalabels import add_data_labels
from .document import Document
from .errbars import find_error_bars, lone_capped_bars
from .fragments import rebuild_fragmented_circles
from .geometry import fmt_rect, median
from .colourbar import add_heat_tiles, heatmap_values
from .grouplabels import group_categories, label_bar_groups
from .graphs import (
    add_panel_graphs, build_graphs, drop_same_plot_graphs, forget_graphs, graph_for_symbol, graph_rotation,
    set_graph_backgrounds, share_row_scales)
from .image_marks import image_symbols
from .interpreter import Interpreter
from .labels import apply_axis_multipliers, resolve_shared_labels
from .legend import SeriesNamer, find_page_legend, legend_for_lines, patch_swatches
from .meta import graph_meta
from .model import CHECKING, check_records
from .nongraphs import axis_labels, drop_tables, text_boxes
from .page import Page
from .normalise import normalise_page
from .rows import legend_looks, make_rows, marker_sized, name_box_slots, reportable
from .rules import Context, Rule, Tracer, run_rules
from .spatial import SortedIndex
from .strays import (drop_box_dashes, drop_corner_ticks, drop_foreign_crowds, drop_plot_backgrounds,
                     drop_pattern_dashes, drop_rule_joints, drop_symbols_in_prose, add_dash_markers,
                     mark_legend_frames, fill_circles_under_dots, merge_crossed_squares)
from .styles import guess_tool
from .symbols import (drop_covered_bits, drop_lone_turned, drop_hidden_dots, drop_highlight_boxes,
                      drop_marker_faces,
                      drop_outline_rings, drop_specks, find_symbols, drop_arrowheads)
from .text import join_subscripts, split_numbers
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
            exclude_legend=False, password=b"", info=None, errbars=False, heatmap=False,
            progress=None):
    """Return the data point rows of a PDF file (one dict per point).
    `pages` limits the work to a set of page numbers.  If `info` is a dict
    it receives 'graphs' (number of graphs found) and 'warnings'.
    `progress`, if given, is called with each page number before the page
    is processed and the seconds since this call began (--progress)."""
    start = time.monotonic()
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
            if progress:
                progress(pno, time.monotonic() - start)
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


_LEVEL_DEG = 10       # text within 10 degrees of a direction reads that way
_TURN_MIN_CHARS = 60  # a page is turned with 60 characters or more read one way
_TURN_SHARE = 0.6     # 60% of them
_TURN_OVER = 3        # three times as many as any other way


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
        if abs((a - r + 180) % 360 - 180) <= _LEVEL_DEG:
            count[r] += n
    total = sum(count.values())
    if total < _TURN_MIN_CHARS:
        return 0
    (r, n), rest = count.most_common(1)[0], count.most_common()[1:]
    return r if r and n >= _TURN_SHARE * total and all(n >= _TURN_OVER * m for _, m in rest) else 0


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


_PAIR_GAP_FRAC = 0.1  # a pair of graphs side by side within a tenth of their width


def share_pair_titles(graphs, texts, symbols, *, page):
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
            if abs(oy0 - y0) > 2 or abs(oy1 - y1) > 2 or not 0 <= gap < _PAIR_GAP_FRAC * min(x1 - x0, ox1 - ox0):
                continue
            title = find_title((min(x0, ox0), min(y0, oy0), max(x1, ox1), max(y1, oy1)),
                               texts, symbols, page=page)
            if title:
                g["title"] = o["title"] = title
                break


_COLUMN_FRAC = 0.1  # a graph's paths: those within its width plus 10%


def extract_page(pdf, pno, pdf_page, opts, info):
    """The pipeline for one page: draw it, read its text, find the axes and
    graphs, find the markers (or bars / line vertices), name the series from
    the legends and map every point through its graph's axes.  The facts
    found about the page are kept in its page model (page.Page), passed to
    the steps that read or add them."""
    page = Page(pno)
    it = Interpreter(pdf, pno)
    it.run_page(pdf_page)
    if opts.debug and it.op_errors:
        for (op, kind), (n, msg) in sorted(it.op_errors.items()):
            print("[debug] page %d: operator %s raised %s %d time(s) (ignored): %s"
                  % (pno, op, kind, n, msg), file=sys.stderr)
    turn = page_turn(it.texts)
    if turn:
        # a page whose content is drawn turned is read turned upright
        ctm, page.unturn = turn_matrix(pdf_page, turn)
        page.turn = turn
        it = Interpreter(pdf, pno)
        it.run_page(pdf_page, ctm)
    page.drawn = it
    tracer = Tracer(pno, opts.debug)
    texts, text_parts, blobs = read_page_text(it, page=page, tracer=tracer)
    # boxes that may hold notes: they excuse their text from the word limit
    # of a graph and their dashed borders from being points
    boxes = text_boxes(it.paths)
    graphs = find_page_graphs(it, texts, boxes, pno, opts.debug, page=page)
    if CHECKING:
        check_records("text", texts, "page text")
        check_records("path", it.paths, "page paths")
        check_records("subpath", (sp for p in it.paths for sp in p["subpaths"]), "page paths")
    if not graphs:
        return []
    info["graphs"] += len(graphs)
    # graphs are numbered through the document: info carries the count
    first_no = info.setdefault("graph_no", 0) + 1
    info["graph_no"] += len(graphs)

    # markers, less the shapes that only look like markers once the
    # graphs are known (strays.py)
    symbols = find_page_symbols(pdf, it, text_parts, page=page, tracer=tracer)
    ctx = Context(page=page, it=it, paths=it.paths, graphs=graphs, texts=texts, boxes=boxes)
    symbols = run_rules(GRAPH_RULES, symbols, ctx, tracer)

    # titles and turned graphs before anything that reads text around a
    # graph (legends, twin scales)
    describe_graphs(graphs, texts, symbols, first_no, opts.debug, page=page)
    share_pair_titles(graphs, texts, symbols, page=page)
    by_x = page.index.get("paths by x", it.paths, lambda: PathsByX(it.paths))
    for g in graphs:
        x0, _, x1, _ = g["rect"]
        mine = by_x.between(x0 - _COLUMN_FRAC * (x1 - x0), x1 + _COLUMN_FRAC * (x1 - x0))
        g["tool"] = graph_tool(g, mine, it.glyph_symbols) or pdf.tool
        g["tool_guess"] = guess_tool(g["rect"], mine, it.texts, it.glyph_symbols)
    line_names = add_bars_and_lines(graphs, symbols, it.paths, texts,
                                    lambda s, g, d: reportable(graphs, s, g, d, opts), page=page)
    # heat maps: a point per tile, valued by the colour bar beside it
    add_heat_tiles(graphs, symbols, it.paths, it.colour_strips, texts, it.pictures, opts.heatmap)
    # capped error bars with no marker: a group's mean (an "H" on its side)
    symbols += lone_capped_bars(graphs, symbols, it.paths,
                                lambda s: graph_for_symbol(graphs, s)[1], page=page)
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
    legend = find_page_legend(symbols, texts, blobs, graphs, it.paths, page=page)
    if opts.debug and legend:
        print("[debug] legend keys: %s" % sorted(set(legend.values())), file=sys.stderr)
    # the short texts beside points ("55%"): the label column
    names = set(legend.values()) | set(line_names.values())
    add_data_labels(graphs, symbols, texts, legend, names, boxes,
                    _labellable(graphs, symbols, legend, opts), page=page)
    namer = SeriesNamer(symbols, legend, graphs, line_names)
    # with a scale on both sides, each series must be mapped by its own
    twin_axes(graphs, symbols, namer, texts, opts.debug)
    bars = find_error_bars(symbols, it.paths,
                           lambda s: graph_for_symbol(graphs, s)[1], page=page) if opts.errbars else {}
    if opts.heatmap:
        # markers coloured along a colour bar: the value each colour stands for
        heatmap_values(graphs, symbols, it.colour_strips, texts,
                       lambda s: graph_for_symbol(graphs, s)[1])
    if CHECKING:
        check_records("graph", graphs, "graphs")
        check_records("axis", (g[k] for g in graphs for k in ("x", "y", "x2", "y2") if k in g), "axes")
        check_records("symbol", symbols, "symbols")
    rows = make_rows(pno, graphs, symbols, legend, namer, opts, bars, page=page)
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



_NOMINAL_MAX_CHARS = 40  # category label candidates are at most 40 characters


def read_page_text(it, *, page, tracer=None):
    """All text of the page, as the analysis needs it: the normalisation
    stage (normalise.py) run on the drawing - text as it is seen, discs
    of strips, break marks, outlined text read by shape, words, minus signs
    - and the page's category-label candidates.  Returns (texts, outline
    parts that are text, unreadable outlined words).  The outline parts are
    returned so that the letters 'o' and full stops of outlined text are
    not taken for markers; the unreadable words still serve as category and
    legend labels (numbered #1, #2, ...)."""
    d = normalise_page(it, page, tracer)
    texts = d.words
    # short texts and unreadable words: the candidates for category labels
    # (several numbers set as one string, "12.8 25.6", one label each)
    # (subscripts joined to their words: "N2", "DT3")
    labels, page.subscripts = join_subscripts(texts)
    page.nominal_labels = [u for t in labels if t["text"].strip()
                           and len(t["text"].strip()) <= _NOMINAL_MAX_CHARS for u in split_numbers(t)] + d.blobs
    return texts, d.text_parts, d.blobs


_STRIP_AXIS_PT = 1.5  # an axis along a colour bar: within 1.5 pt
_STRIP_COVER = 0.8    # over 80% of its length


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
                if min(abs(ax["pos"] - x0), abs(ax["pos"] - x1)) <= _STRIP_AXIS_PT and \
                        min(ax["hi"], y1) - max(ax["lo"], y0) >= _STRIP_COVER * (y1 - y0):
                    return True
            if ax["orient"] == "x" and x1 - x0 > y1 - y0:
                if min(abs(ax["pos"] - y0), abs(ax["pos"] - y1)) <= _STRIP_AXIS_PT and \
                        min(ax["hi"], x1) - max(ax["lo"], x0) >= _STRIP_COVER * (x1 - x0):
                    return True
        return False
    return [ax for ax in axes if not along(ax)]


def find_page_graphs(it, texts, boxes, pno, debug, *, page):
    """Axes (ticks + labels + value mapping) paired into graphs, less the
    candidates that are tables or text (nongraphs.py)."""
    axes = drop_duplicate_axes(_off_colour_bars(resolve_shared_labels(drop_scattered_tick_axes(
        find_axes(it.paths, texts, debug, page=page))), it.colour_strips))
    apply_axis_multipliers(axes, texts)
    graphs = drop_same_plot_graphs(add_panel_graphs(build_graphs(axes, page=page), axes, it.paths, page=page))
    graphs = share_row_scales(graphs, axes, page=page)
    graphs = drop_tables(graphs, texts, debug, boxes, it.paths, page=page)
    if debug:
        for g in graphs:
            print("[debug] page %d graph rect %s  x:%s  y:%s" % (
                pno, fmt_rect(g["rect"]), g["x"]["map"], g["y"]["map"]), file=sys.stderr)
    if graphs:
        page.graph_rects = [g["rect"] for g in graphs]
        # where each graph's x tick labels end: text just below them is its
        # axis title, not the title of a graph further down
        page.xlabel_zones = [(g["rect"][0], g["rect"][2],
                              min(tx["bbox"][1] for _, tx in g["x"]["labels"]), tuple(g["rect"]))
                             for g in graphs if g["x"].get("labels") and g["x"]["orient"] == "x"]
        # the page's typical tick-label size: a graph's title is set no
        # smaller than its labels (titles.py)
        page.label_size = median((t["size"] for g in graphs for t in axis_labels(g)), 0.0)
        set_graph_backgrounds(graphs, it.paths, page=page)
    return graphs


_ON_BAR_FRAC = 0.3  # a shape on a bar: centred within 30% of its width


class _BarsAcross:
    """Bars sorted by their middle across (x for upright bars, y for
    horizontal ones), so that a shape looks only at those it may be
    centred on (_on_bar: within 30% of a bar's width) - every shape against
    every bar took ten minutes on gopinath2014mutations-004's 9 000 bars."""

    def __init__(self, bars):
        self.sides = []
        for horizontal in (False, True):
            j = "cy" if horizontal else "cx"
            mine = SortedIndex([b for b in bars if bool(b.get("horizontal")) == horizontal],
                               key=lambda b, j=j: b[j])
            if mine:
                reach = _ON_BAR_FRAC * max(b["size"] for b in mine.items)
                self.sides.append((j, mine, reach))

    def near(self, s):
        for j, mine, reach in self.sides:
            yield from mine.between(s[j] - reach, s[j] + reach)


_ON_BAR_PT = 0.5  # between its foot and end within 0.5 pt


def _on_bar(s, b):
    """Is shape s centred on bar b (its middle across the bar within 30%
    of the bar's width, along it between its foot and its end)?  For a
    horizontal bar, across is y (2020.01.30.927558.full-026: a short bar's
    outline, as tall as long, taken for a square)."""
    j, k = ("cy", "cx") if b.get("horizontal") else ("cx", "cy")
    end, foot = b[k], b.get("base", b[k])
    return abs(s[j] - b[j]) <= _ON_BAR_FRAC * b["size"] and \
        min(end, foot) - _ON_BAR_PT <= s[k] <= max(end, foot) + _ON_BAR_PT


_TEXT_GREY = 0.1            # grey or black like text: channels within 0.1
_LETTER_MIN_SIZES = 0.67    # letter boxes 0.67 to 2 times the mark's size tall
_LETTER_MAX_SIZES = 2.0     # (the tallest letter box beside a mark)
_LETTER_GAP_HEIGHTS = 0.35  # within 0.35 of their height of it


def _flanked_by_letters(s, boxes):
    """Is marker s a letter of an unread word: grey or black like text,
    two of the word's letter boxes (`boxes`) of about its size (0.5 to 1.5
    times their height... their height 0.67 to 2 times its size) within
    0.35 of their height of it, on opposite sides of it?  (Not a yellow
    note pointer among a note's letters: ITRS_2011ExecSum-031.)"""
    if s["shape"] in ("line", "bar", "stem", "tile") or s["size"] <= 0:
        return False
    rgb = s.get("rgb") or (0.0, 0.0, 0.0)
    if max(rgb) - min(rgb) > _TEXT_GREY:
        return False
    near = []
    for b in boxes:
        h = b[3] - b[1]
        if not _LETTER_MIN_SIZES * s["size"] <= h <= _LETTER_MAX_SIZES * s["size"]:
            continue
        gx = max(b[0] - s["cx"], s["cx"] - b[2], 0.0) - 0.5 * s["size"]
        gy = max(b[1] - s["cy"], s["cy"] - b[3], 0.0) - 0.5 * s["size"]
        if max(gx, gy) <= _LETTER_GAP_HEIGHTS * h:
            near.append(((b[0] + b[2]) / 2 - s["cx"], (b[1] + b[3]) / 2 - s["cy"]))
    return any(u[0] * v[0] + u[1] * v[1] < 0 for i, u in enumerate(near) for v in near[i + 1:])


def find_page_symbols(pdf, it, text_parts, *, page, tracer=None):
    """The marker symbols of the page.  Markers outside the axis ranges are
    kept, even when the plot clips them out of view (the user asked for
    them); each symbol notes the clipping box it was drawn with ('clip'),
    which tells which graph it belongs to.  The steps are the rules of
    FIND_RULES, in order."""
    page.arrows = []
    ctx = Context(page=page, it=it, paths=it.paths, text_parts=text_parts, pdf=pdf)
    symbols = run_rules(FIND_RULES, [], ctx, tracer)
    clip_of = {p["idx"]: p.get("clip") for p in it.paths}
    for s in symbols:
        # (glyph markers carry their own clipping box)
        s["clip"] = clip_of[s["idx"]] if s["idx"] in clip_of else s.get("clip")
    return symbols


_TOUCHES_SIZES = 0.5  # a symbol touches a box when its centre is within half its size of it


def _drop_rebuilt_outside(symbols, ctx):
    """Circles rebuilt from curved pieces outside every plot box are the
    round letters of axis labels and titles drawn as outlines, not
    markers: PhysRevResearch.3.033169-009's blue and red tick labels -
    coloured, so the circle rebuilder may use their pieces - and its
    unread epsilon gave circles of the markers' size beside the axes."""
    rects = ctx.page.graph_rects
    return [s for s in symbols if not s.get("rebuilt") or any(
        r[0] - _TOUCHES_SIZES * s["size"] <= s["cx"] <= r[2] + _TOUCHES_SIZES * s["size"] and
        r[1] - _TOUCHES_SIZES * s["size"] <= s["cy"] <= r[3] + _TOUCHES_SIZES * s["size"] for r in rects)]


def _drop_painted_over(symbols, ctx):
    """Shapes painted over by a later opaque box that hides text (the
    page's hiding paths, occlusion.py) are no points."""
    hidden = ctx.page.hiding_paths
    return [s for s in symbols if s["idx"] not in hidden]


def _drop_unread_name_letters(symbols, ctx):
    """Round letters of unread outlined names ("o", "e") outside every
    plot: flanked by letters of those names on both sides, close
    (2355585.2355594-006's slanted benchmark names; a legend key has its
    name on one side only, and markers inside a plot may crowd into unread
    "words" of marker shapes)."""
    blob_boxes = [t["bbox"] for t in ctx.page.nominal_labels if t.get("text") is None]
    if not blob_boxes:
        return symbols
    graphs = ctx.graphs
    return [s for s in symbols if any(
        g["rect"][0] - _TOUCHES_SIZES * s["size"] <= s["cx"] <= g["rect"][2] + _TOUCHES_SIZES * s["size"] and
        g["rect"][1] - _TOUCHES_SIZES * s["size"] <= s["cy"] <= g["rect"][3] + _TOUCHES_SIZES * s["size"]
        for g in graphs) or not _flanked_by_letters(s, blob_boxes)]


# The marker symbols of a page (find_page_symbols), before the graphs are
# described: the shapes that may be markers; markers broken into pieces
# put back together (before the filters below, which would take the
# pieces for specks); then shapes that are painted over, highlight boxes
# and rings round a marker, specks, stray bits and arrowheads, none of
# them a point of its own; and markers drawn as small pictures.
FIND_RULES = [
    Rule("find_symbols", lambda s, c: find_symbols(c.paths, c.it.glyph_symbols, c.text_parts,
                                                   c.page.blob_parts),
         "the shapes that may be markers: vector shapes, crossing strokes, Dingbats glyphs"),
    Rule("drop_lone_turned", lambda s, c: drop_lone_turned(s), drop_lone_turned.__doc__),
    Rule("rebuild_fragmented_circles",
         lambda s, c: rebuild_fragmented_circles(c.paths, s, c.text_parts, c.pdf.warnings),
         rebuild_fragmented_circles.__doc__),
    Rule("drop_rebuilt_outside", _drop_rebuilt_outside),
    Rule("drop_painted_over", _drop_painted_over),
    Rule("drop_highlight_boxes", lambda s, c: drop_highlight_boxes(s), drop_highlight_boxes.__doc__),
    Rule("drop_marker_faces", lambda s, c: drop_marker_faces(s, c.paths), drop_marker_faces.__doc__),
    Rule("drop_outline_rings", lambda s, c: drop_outline_rings(s), drop_outline_rings.__doc__),
    Rule("drop_hidden_dots", lambda s, c: drop_hidden_dots(s, c.paths), drop_hidden_dots.__doc__),
    Rule("drop_covered_bits", lambda s, c: drop_covered_bits(s, c.paths), drop_covered_bits.__doc__),
    Rule("drop_specks", lambda s, c: drop_specks(s), drop_specks.__doc__),
    Rule("drop_arrowheads", lambda s, c: drop_arrowheads(s, c.paths, c.page.arrows), drop_arrowheads.__doc__),
    Rule("add_image_symbols", lambda s, c: s + image_symbols(c.it.image_marks, c.paths),
         "markers drawn as small pictures (shadows dropped)"),
]

# The shapes that only look like markers once the graphs are known
# (strays.py), run on the page's symbols after FIND_RULES.
GRAPH_RULES = [
    Rule("drop_plot_backgrounds", lambda s, c: drop_plot_backgrounds(s, c.graphs), drop_plot_backgrounds.__doc__),
    Rule("drop_unread_name_letters", _drop_unread_name_letters),
    Rule("drop_corner_ticks", lambda s, c: drop_corner_ticks(s, c.graphs), drop_corner_ticks.__doc__),
    Rule("drop_symbols_in_prose", lambda s, c: drop_symbols_in_prose(s, c.texts, c.graphs),
         drop_symbols_in_prose.__doc__),
    Rule("drop_box_dashes", lambda s, c: drop_box_dashes(s, c.texts, c.boxes, c.graphs), drop_box_dashes.__doc__),
    Rule("drop_rule_joints", lambda s, c: drop_rule_joints(s, c.paths), drop_rule_joints.__doc__),
    Rule("drop_pattern_dashes", lambda s, c: drop_pattern_dashes(s, c.paths), drop_pattern_dashes.__doc__),
    Rule("add_dash_markers", lambda s, c: add_dash_markers(s, c.paths, c.graphs), add_dash_markers.__doc__),
    Rule("drop_foreign_crowds", lambda s, c: drop_foreign_crowds(s, c.graphs), drop_foreign_crowds.__doc__),
    Rule("mark_legend_frames", lambda s, c: mark_legend_frames(s, c.paths, c.graphs), mark_legend_frames.__doc__),
    Rule("fill_circles_under_dots", lambda s, c: fill_circles_under_dots(s, c.it.texts),
         fill_circles_under_dots.__doc__),
    Rule("merge_crossed_squares", lambda s, c: merge_crossed_squares(s), merge_crossed_squares.__doc__),
]


def describe_graphs(graphs, texts, symbols, first_no, debug, *, page):
    """Number, title, figure number and caption, and orientation of each
    graph (for the -meta file; the orientation also decides which axis
    gives x and which y)."""
    lines = None
    for no, g in enumerate(graphs, first_no):
        g["no"] = no
        g["rot"], g["title"] = graph_rotation(g, texts, symbols, page=page)
        if lines is None:
            lines = text_lines(texts)
        g["figure"], g["caption"] = find_figure_caption(g["rect"], lines, page.graph_rects)
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


_OUTSIDE_CROWD = 100  # markers outside a box are its own unless 100 or more
_IN_BOX_PT = 0.5      # a mark in a box (violin, box plot): within 0.5 pt
_BARS_OVER = 3        # bars outnumber other squares 3 to 1
_TWIN_BARS_MIN = 3    # 3 bars or more under line series
_OUTLINE_WIDTH = 0.2  # a bar's outline as wide within 20%


def add_bars_and_lines(graphs, symbols, paths, texts, reportable=None, *, page):
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
    line_sets, sym_of = [], {}     # (graph, series, names) and the symbols of each line
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
        if len(outs) < _OUTSIDE_CROWD or len(outs) <= 2 * len(owner.get(gid, ())):
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
                r[0] - _IN_BOX_PT <= s["cx"] <= r[2] + _IN_BOX_PT and r[1] - _IN_BOX_PT <= s["cy"] <= r[3] + _IN_BOX_PT
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
                    r[0] - _IN_BOX_PT <= s["cx"] <= r[2] + _IN_BOX_PT and r[1] - _IN_BOX_PT <= s["cy"] <= r[3] + _IN_BOX_PT
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
            # (bars by drawing step: 460-201's 150 000 marks against every bar)
            by_idx = {}
            for b in bars:
                by_idx.setdefault(b["idx"], []).append(b)
            across = _BarsAcross(bars)
            short = [s for s in marks if (s["shape"] in ("square", "rectangle") and (
                s["idx"] in bar_paths or any(_on_bar(s, b) for d in (-1, 1)
                                             for b in by_idx.get(s["idx"] + d, ())))) or
                     (s["shape"] in ("cross", "plus") and any(
                         _on_bar(s, b) and abs(b["cy" if not b.get("horizontal") else "cx"] -
                                               b.get("base", 0.0)) <= s["size"] for b in across.near(s)))]
            # short bars taken for squares are bars; squares that are no
            # bars (legend keys of the bar colours) stay, if the bars are
            # most of the shapes
            if bars and (len(short) == len(marks) or len(bars) >= _BARS_OVER * (len(marks) - len(short))):
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
            if ("y2" in g or "x2" in g) and len(bars) >= _TWIN_BARS_MIN:
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
            across = _BarsAcross(bars)
            outl = {id(s) for s in symbols if s["shape"] == "rectangle" and not s.get("marker") and
                    any(abs(s["size"] - b["size"]) <= _OUTLINE_WIDTH * b["size"] and _on_bar(s, b) for b in across.near(s))}
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
        names = legend_for_lines(series, paths, texts, g["rect"], page=page)
        line_sets.append((g, series, names))
        for k, line in enumerate(series):
            for q in line["points"]:
                sym = {"shape": "line", "cx": q[0], "cy": q[1], "size": 0.0,
                       "filled": False, "rgb": line["rgb"], "idx": line["idx"]}
                if line.get("clip"):
                    # (a vertex clipped out of view stays with its graph)
                    sym["clip"] = line["clip"]
                if k in names:
                    line_names[id(sym)] = names[k]
                sym_of.setdefault((id(g), k), []).append(sym)
                symbols.append(sym)
    _share_line_names(line_sets, sym_of, line_names)
    return line_names


def _share_line_names(line_sets, sym_of, line_names):
    """Panels of one lattice share a legend: a graph whose lines found no
    legend of their own takes the names that a graph it shares an axis
    with (directly or through others: the same x or y axis, borrowed)
    found for lines of the same style and colour, when each such style and
    colour has one name only (2020.01.30.927558.full-012: "True value" and
    "Slider value" beside the upper right panel name the lines of all
    four)."""
    named = [(g, ser, nm) for g, ser, nm in line_sets if nm]
    if not named:
        return
    # graphs joined by shared axes
    groups = {id(g): {id(g)} for g, _s, _n in line_sets}
    gs = [g for g, _s, _n in line_sets]
    for i, g in enumerate(gs):
        for h in gs[i + 1:]:
            if g["x"] is h["x"] or g["y"] is h["y"]:
                u = groups[id(g)] | groups[id(h)]
                for k in u:
                    groups[k] = u
    for g, series, names in line_sets:
        if names or not series:
            continue
        keys = {}
        for h, ser, nm in named:
            if id(h) not in groups[id(g)]:
                continue
            for k, n in nm.items():
                keys.setdefault((ser[k]["style"][0], ser[k]["rgb"]), set()).add(n)
        for k, line in enumerate(series):
            n = keys.get((line["style"][0], line["rgb"]))
            if n and len(n) == 1:
                for sym in sym_of.get((id(g), k), ()):
                    line_names[id(sym)] = next(iter(n))

"""Output rows: each reported symbol mapped through its graph's axes (or,
for a graph with two scales, through the one its series uses), with the
significant digits its coordinates justify and, with --errbars, the ends of
its error bars."""

import math

from .colours import color_name
from .geometry import overlap_area, rect_area
from .graphs import clip_graph, graph_for_symbol
from .scales import map_value, nominal_rank
from .charts import BOX_SHAPES
from .symbols import LINE_SHAPES
from .twin import twin_key, twin_view


def value_digits(m, v, res, least=6, most=15):
    """Significant digits to write a value with: the digits the PDF's
    coordinates resolve (one unit of their last decimal, carried through the
    axis mapping) and one more, so that rounding the output adds at most a
    tenth of that resolution; never fewer than `least`."""
    if res is None or not isinstance(v, float) or not math.isfinite(v) or v == 0:
        return least
    kind = m["kind"]
    if kind == "log":
        rv = abs(v) * math.log(10) * abs(m["a"]) * res
    elif kind in ("linear", "piecewise"):
        rv = max(abs(m["a"]), abs(m.get("a2", 0.0))) * res
    else:
        return least
    if not rv > 0:
        return least
    sig = math.floor(math.log10(abs(v))) - math.floor(math.log10(rv)) + 2
    return max(least, min(most, sig))


def legend_looks(symbols, legend):
    """(shape, colour) of the legend keys: markers that look like a key."""
    return {(symbols[i]["shape"], color_name(symbols[i]["rgb"])[1]) for i in legend}


def marker_sized(s, g, opts, keyed=frozenset()):
    """Whether a symbol is small enough to be a marker of graph g.  Markers
    are small: at most --max-symbol-frac (0.1) of the plot's shorter side,
    but in tiny panels (small multiples) a few points of marker are still
    a large share of the panel, so 3.5 pt (at most 0.4 of the side) always
    passes.  A shape with the shape and colour of a legend key is a marker
    up to a quarter of the side (charts that print an id inside each big
    marker); the keys themselves are not (ggplot draws a big white square
    behind each key).  Bars and line corners have no marker size."""
    if s["shape"] in ("bar", "line", "stem") or s["shape"] in BOX_SHAPES:
        return True
    x0, y0, x1, y1 = g["rect"]
    side = min(x1 - x0, y1 - y0)
    if s["size"] <= max(opts.max_frac * side, min(3.5, 0.4 * side)):
        return True
    return s["size"] <= 0.25 * side and (s["shape"], color_name(s["rgb"])[1]) in keyed


def reportable(graphs, s, g, d, opts, key=False, keyed=frozenset()):
    """Whether a symbol at distance d from its graph g may be one of its
    data points: not far from every graph (more than half the graph's
    larger side) nor drawn in a plot box that is not a graph found, unless
    drawn in g or a legend key; and of marker size."""
    x0, y0, x1, y1 = g["rect"]
    w, h = x1 - x0, y1 - y0
    if not key and clip_graph(graphs, s) is not g:
        if d > 0.5 * max(w, h):
            return False                  # far from every graph (and not drawn in one)
        c = s.get("clip")
        if d > 0 and c and overlap_area(g["rect"], c) < 0.1 * max(rect_area(c), 1e-9):
            return False                  # drawn in a plot box that is not a graph found
    return marker_sized(s, g, opts, keyed if not key else ())


def symbol_size(s):
    """--sizesymbol: the size of a point's marker in PDF points (1/72 inch):
    the diameter of a circle, the average edge length of a box (the mean of
    its bounding box's width and height, which other shapes use too).
    Shapes recorded without their box (crossing strokes, glyph markers,
    bars, line vertices) give their 'size': the larger side, a bar's
    width, 0."""
    w, h = s.get("w"), s.get("h")
    if w is None or h is None:
        return s["size"]
    return (w + h) / 2


def make_rows(pno, graphs, symbols, legend, namer, opts, bars=None):
    """One output row per reported symbol (with the ends of its error bars,
    `bars` from find_error_bars, when --errbars is given), graph by graph
    and, within a graph, in increasing order of x."""
    rows = []
    keys_seen = set()
    keyed = legend_looks(symbols, legend)
    for si, s in enumerate(symbols):
        # Each test below drops a shape that is no data point of a graph
        # found.  Legend keys are kept (flagged legend_key=1) unless
        # --exclude-legend: the user asked for them to be reported.
        if s["shape"] == "rectangle" and si not in legend and not s.get("marker"):
            continue                      # oblong boxes count only as legend keys (or as a set
                                          # of markers: strays.add_dash_markers)
        d, g = graph_for_symbol(graphs, s)
        if not reportable(graphs, s, g, d, opts, si in legend, keyed):
            continue
        if opts.inside_only and d > 1e-6 or opts.exclude_legend and si in legend:
            continue
        if si in legend:
            # one key drawn by several layers (ggplot2 draws each point
            # layer's glyph in the key box) is one key
            k = (s["shape"], s["filled"], s["rgb"], round(s["cx"], 1), round(s["cy"], 1))
            if k in keys_seen:
                continue
            keys_seen.add(k)
        name, hexs = color_name(s["rgb"])
        if s["shape"] in LINE_SHAPES or s["shape"] in ("bar", "line", "stem") or s["shape"] in BOX_SHAPES:
            sym_name = s["shape"]
        else:
            sym_name = ("filled-" if s["filled"] else "open-") + s["shape"]
        series = namer.name(si, s, g)
        # (a graph with a scale on each side: the view with the series' own)
        g, side = twin_view(g, twin_key(series, s)) if "twin" in g else (g, "")
        # page positions along the data axes (swapped in a turned graph)
        xc, yc = (s["cy"], s["cx"]) if g["rot"] else (s["cx"], s["cy"])
        x = map_value(g["x"]["map"], xc)
        y = map_value(g["y"]["map"], yc)
        rows.append({
            "page": pno, "graph": g["no"], "graph_title": g["title"],
            "symbol": sym_name,
            "x_coord": x, "y_coord": y,
            # significant digits the PDF's coordinates justify (at least 6)
            "x_digits": value_digits(g["x"]["map"], x, s.get("res")),
            "y_digits": value_digits(g["y"]["map"], y, s.get("res")),
            "color": name, "color_hex": hexs,
            "series": series, "axis": side, "label": s.get("label", ""),
            "rotation": g["rot"],
            "symbol_size": symbol_size(s),
            "legend_key": 1 if si in legend else 0,
            "pdf_x": s["cx"], "pdf_y": s["cy"],
            "x_order": x_order(g["x"]["map"], xc, x)})
        rows[-1].update(label_tick_ranges(g, xc, yc))
        if opts.errbars:
            rows[-1].update(error_bar_values(g, s, x, y, (bars or {}).get(si)))
    # graph by graph, in increasing x (a stable sort: rows with the same x
    # keep their drawing order)
    rows.sort(key=lambda r: (r["graph"], r["x_order"]))
    return rows


def label_tick_ranges(g, xc, yc):
    """x_coord_low ... y_coord_high: where a value read against an axis
    whose ticks are its label centres (no tick marks) may really lie - the
    page position give or take the axis's uncertainty, mapped through it;
    "" for an axis with tick marks."""
    out = {}
    for axis, c in (("x", xc), ("y", yc)):
        a = g[axis]
        unc = a.get("tick_unc")
        lo = hi = ""
        if unc is not None:
            ends = [map_value(a["map"], c - unc), map_value(a["map"], c + unc)]
            if all(isinstance(v, float) for v in ends):
                lo, hi = min(ends), max(ends)
        out[axis + "_coord_low"], out[axis + "_coord_high"] = lo, hi
    return out


def x_order(m, c, x):
    """Sort key of a row's x value: numbers in increasing order (not-a-number
    last), the categories of a category axis in their order along it."""
    if m["kind"] == "nominal":
        return (1, nominal_rank(m, c))
    if isinstance(x, float) and math.isnan(x):
        return (2, 0.0)
    return (0, x)


def error_bar_values(g, s, x, y, bar):
    """x_low, x_high, y_low, y_high of a point from its error bars (page
    coordinates) mapped through its graph's axes; "" where it has no bar
    in that direction.  A side without a bar is the point's own value.  In
    a turned graph a vertical bar on the page gives the data x range."""
    out = {"x_low": "", "x_high": "", "y_low": "", "y_high": ""}
    if not bar:
        return out
    # page direction of each data axis: "v" (along page y) or "h"
    dirs = (("x", "v"), ("y", "h")) if g["rot"] else (("x", "h"), ("y", "v"))
    for axis, k in dirs:
        ends = bar.get(k)
        m = g[axis]["map"]
        if ends is None or m["kind"] == "nominal":
            continue
        own = x if axis == "x" else y
        vals = [map_value(m, e) if e is not None else own for e in ends]
        if all(isinstance(v, float) for v in vals):
            out[axis + "_low"], out[axis + "_high"] = min(vals), max(vals)
    return out

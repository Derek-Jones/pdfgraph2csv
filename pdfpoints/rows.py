"""Output rows: each reported symbol mapped through its graph's axes (or,
for a graph with two scales, through the one its series uses), with the
significant digits its coordinates justify and, with --errbars, the ends of
its error bars."""

import math

from .colours import color_name
from .graphs import clip_graph, graph_for_symbol
from .scales import map_value
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


def make_rows(pno, graphs, symbols, legend, namer, opts, bars=None):
    """One output row per reported symbol (with the ends of its error bars,
    `bars` from find_error_bars, when --errbars is given)."""
    rows = []
    for si, s in enumerate(symbols):
        if s["shape"] == "rectangle" and si not in legend:
            continue                      # oblong boxes count only as legend keys
        d, g = graph_for_symbol(graphs, s)
        x0, y0, x1, y1 = g["rect"]
        w, h = x1 - x0, y1 - y0
        if d > 0.5 * max(w, h) and si not in legend and clip_graph(graphs, s) is not g:
            continue                      # far from every graph (and not drawn in one)
        c = s.get("clip")
        if d > 0 and c and si not in legend and clip_graph(graphs, s) is not g:
            ov = max(0.0, min(x1, c[2]) - max(x0, c[0])) * max(0.0, min(y1, c[3]) - max(y0, c[1]))
            if ov < 0.1 * max((c[2] - c[0]) * (c[3] - c[1]), 1e-9):
                continue                  # drawn in a plot box that is not a graph found
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
        series = namer.name(si, s, g)
        g, side = twin_view(g, twin_key(series, s)) if "twin" in g else (g, "")
        x = map_value(g["x"]["map"], s["cy"] if g["rot"] else s["cx"])
        y = map_value(g["y"]["map"], s["cx"] if g["rot"] else s["cy"])
        rows.append({
            "page": pno, "graph": g["no"], "graph_title": g["title"],
            "symbol": sym_name,
            "x_coord": x, "y_coord": y,
            # significant digits the PDF's coordinates justify (at least 6)
            "x_digits": value_digits(g["x"]["map"], x, s.get("res")),
            "y_digits": value_digits(g["y"]["map"], y, s.get("res")),
            "color": name, "color_hex": hexs,
            "series": series, "axis": side,
            "rotation": g["rot"],
            "legend_key": 1 if si in legend else 0,
            "pdf_x": s["cx"], "pdf_y": s["cy"]})
        if opts.errbars:
            rows[-1].update(error_bar_values(g, s, x, y, (bars or {}).get(si)))
    return rows


def error_bar_values(g, s, x, y, bar):
    """x_low, x_high, y_low, y_high of a point from its error bars (page
    coordinates) mapped through its graph's axes; "" where it has no bar
    in that direction.  A side without a bar is the point's own value.  In
    a turned graph a vertical bar on the page gives the data x range."""
    out = {"x_low": "", "x_high": "", "y_low": "", "y_high": ""}
    if not bar:
        return out
    # page direction of each data axis: "v" (along page y) or "h"
    dirs = (("x", "v", s["cy"]), ("y", "h", s["cx"])) if g["rot"] else \
        (("x", "h", s["cx"]), ("y", "v", s["cy"]))
    for axis, k, centre in dirs:
        ends = bar.get(k)
        m = g[axis]["map"]
        if ends is None or m["kind"] == "nominal":
            continue
        own = x if axis == "x" else y
        vals = [map_value(m, e) if e is not None else own for e in ends]
        if all(isinstance(v, float) for v in vals):
            out[axis + "_low"], out[axis + "_high"] = min(vals), max(vals)
    return out

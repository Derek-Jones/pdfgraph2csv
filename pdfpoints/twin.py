"""Graphs with a scale on both sides (option-free).

A graph may carry two y scales, one on the left and one on the right (or
two x scales, at the bottom and the top).  Each series belongs to one of
them; the reader is told which by
  * the legend: "SRAM (left axis)", "Pitch [right]", "CGP (RHS)", ...;
  * the axis titles: "SRAM area (µm²)" on the left, "CGP/M1 pitch (µm)" on
    the right name the series they carry;
  * colour: the labels or the title of an axis drawn in the colour of its
    series.
`assign_twin_axes` decides, per series name, which axis it uses, in that
order of evidence.  Series that none of these settles are mapped through
the left (bottom) axis, and a warning names them.
"""

import re
import sys

from .colours import color_name
from .graphs import graph_for_symbol

_SIDE_WORDS = {
    "y": ((r"\bleft\b|\blhs\b|\(l\)|\[l\]|primary", "first"),
          (r"\bright\b|\brhs\b|\(r\)|\[r\]|secondary|\baxis 2\b|\by2\b", "second")),
    "x": ((r"\bbottom\b|\blower\b|primary", "first"),
          (r"\btop\b|\bupper\b|secondary|\baxis 2\b|\bx2\b", "second")),
}


def _norm(s):
    return " ".join(re.sub(r"[^0-9a-z]+", " ", (s or "").lower()).split())


def axis_title(axis, texts, side):
    """The text set beside an axis beyond its tick labels (its title),
    joined in reading order; `side` is -1 when it lies below / left of the
    axis line, +1 above / right."""
    k = 0 if axis["orient"] == "y" else 1           # across the axis
    labels = [tx for _, tx in axis.get("labels", ()) if tx.get("bbox")]
    pos = axis["pos"]
    if labels:
        outer = min(tx["bbox"][k] for tx in labels) if side < 0 else \
            max(tx["bbox"][k + 2] for tx in labels)
    else:
        outer = pos
    band = (outer - 40, outer + 0.5) if side < 0 else (outer - 0.5, outer + 40)
    lo, hi = axis["lo"], axis["hi"]
    used = set(id(tx) for tx in labels)
    picked = []
    for t in texts:
        if id(t) in used or not t.get("text") or t["value"] is not None:
            continue
        b = t["bbox"]
        c_across = (b[k] + b[k + 2]) / 2
        c_along = (b[1 - k] + b[3 - k]) / 2
        if band[0] <= c_across <= band[1] and lo - 5 <= c_along <= hi + 5:
            picked.append(t)
    picked.sort(key=lambda t: (-t["bbox"][1], t["bbox"][0]) if k == 1 else
                (t["bbox"][1], t["bbox"][0]))
    return picked


def _axis_colours(axis, title_items):
    cols = [tx.get("rgb") for _, tx in axis.get("labels", ())] + \
        [t.get("rgb") for t in title_items]
    cols = [color_name(c)[1] for c in cols if c]
    dark = {"#000000"}
    cols = [c for c in cols if c not in dark]
    return set(cols)


def assign_twin_axes(g, texts, series_info):
    """{series name: "first" | "second"} for a graph with a second scale
    (g["y2"] or g["x2"]); series_info is {name: set of colour hex codes}.
    Also sets g["twin"] = (data axis letter, first side name, second side
    name, titles) and returns the names it could not place."""
    key = "y" if "y2" in g else "x"
    first, second = g[key], g[key + "2"]
    rect = g["rect"]
    mid = (rect[0] + rect[2]) / 2 if key == "y" else (rect[1] + rect[3]) / 2
    t1 = axis_title(first, texts, -1 if first["pos"] < mid else 1)
    t2 = axis_title(second, texts, -1 if second["pos"] < mid else 1)
    n1 = _norm(" ".join(t["text"] for t in t1))
    n2 = _norm(" ".join(t["text"] for t in t2))
    c1, c2 = _axis_colours(first, t1), _axis_colours(second, t2)
    names = ("left", "right") if key == "y" else ("bottom", "top")
    g["twin"] = {"axis": key, "sides": names, "titles": (n1, n2)}
    out, unsure = {}, []
    for name, colours in series_info.items():
        nn = "" if name.startswith("#colour ") else _norm(name)
        side = None
        for pat, which in _SIDE_WORDS[key]:
            if nn and re.search(pat, " %s " % (name or "").lower()):
                side = which
        if side is None and nn:
            in1 = re.search(r"\b%s\b" % re.escape(nn), n1) is not None
            in2 = re.search(r"\b%s\b" % re.escape(nn), n2) is not None
            if in1 != in2:
                side = "first" if in1 else "second"
        if side is None and colours:
            m1, m2 = bool(colours & c1), bool(colours & c2)
            if m1 != m2:
                side = "first" if m1 else "second"
        if side is None:
            side = "first"
            unsure.append(name)
        out[name] = side
    return out, unsure


def twin_axes(graphs, symbols, namer, texts, warnings, debug):
    """For each graph with a scale on both sides, which scale each of its
    series is read against (g["twin_map"]: series name -> "first" /
    "second")."""
    twins = [g for g in graphs if "y2" in g or "x2" in g]
    if not twins:
        return
    info = {}
    for si, s in enumerate(symbols):
        _, g = graph_for_symbol(graphs, s)
        if g is not None and ("y2" in g or "x2" in g):
            info.setdefault(g["no"], {}).setdefault(twin_key(namer.name(si, s, g), s), set()).add(
                color_name(s["rgb"])[1])
    for g in twins:
        g["twin_map"], unsure = assign_twin_axes(g, texts, info.get(g["no"], {}))
        if debug:
            print("[debug] graph %d has two scales; titles %s; series %s" % (
                g["no"], g["twin"]["titles"], g["twin_map"]), file=sys.stderr)
        g["twin_unsure"] = set(unsure)


def warn_twin_unsure(graphs, rows, warnings):
    """Warn about reported series whose scale (left or right) is unknown."""
    for g in graphs:
        names = sorted(set(r["series"] or r["color_hex"] for r in rows if r["graph"] == g["no"]
                           and twin_key(r["series"], {"rgb": None}) in g.get("twin_unsure", ())
                           or (not r["series"] and "#colour " + r["color_hex"]
                               in g.get("twin_unsure", ()))))
        if names:
            warnings.append("graph %d has a scale on both sides; not known which one "
                            "series %s use%s: read against the %s one" % (
                                g["no"], ", ".join(repr(u) for u in names),
                                "" if len(names) > 1 else "s", g["twin"]["sides"][0]))


def twin_key(series, s):
    """A series for choosing its scale: its name, or for unnamed series
    (no legend) its colour."""
    return series if series else "#colour " + color_name(s["rgb"])[1]


def twin_view(g, series):
    """The graph as seen by one series: with its own scale as the data axis
    when the graph has two, and the name of that scale's side."""
    tw = g.get("twin")
    if not tw:
        return g, ""
    k = "y" if "y2" in g else "x"
    if g.get("twin_map", {}).get(series) == "second":
        return dict(g, **{k: g[k + "2"]}), tw["sides"][1]
    return g, tw["sides"][0]

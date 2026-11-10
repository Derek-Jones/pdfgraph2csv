"""A best guess at the program that drew a graph, from its drawing style.

Plotting programs leave recognisable habits in the PDF they write: their
default colours, fonts, line caps and joins, the number of decimals of the
coordinates, the names they give to graphics states and reusable marker
drawings, and the way they draw markers.  `guess_tool` scores the evidence
found in and around one graph for each program and names the best one, or
"" when nothing points clearly to one.  It is a guess: an edited figure
(Illustrator), a converted one (Ghostscript, Distiller) or a non-default
theme can hide or mimic the signs.

Signs used (each adds to the program's score):

  R          ZapfDingbats circles as markers (R's pdf() device); strokes
             with round caps and joins and coordinates of 2-3 decimals;
             R's default palettes and rainbow()
  ggplot2    (R) the grey panel grid (#EBEBEB) and the hue palette
             (#F8766D, #00BFC4, #7CAE00, #C77CFF, ...)
  lattice    (R) the peach strip background (#FFE5CC) and #0080FF points
  matplotlib graphics states named A1, A2, ... and markers as reusable
             drawings named M0, M1, ...; the tab10 palette (#1F77B4, ...);
             DejaVu fonts
  MATLAB     axes and labels in #262626 (R2014b and later); the line
             colours #0072BD, #D95319, #EDB120, ...
  Excel      Calibri / Arial text with Office chart palettes: 2003 (#000080
             navy markers, #FF00FF), 2007-2010 (#4F81BD, #C0504D, gridlines
             #868686), 2013 and later (#5B9BD5, #4472C4, #ED7D31, gridlines
             #D9D9D9, text #595959)
  gnuplot    its default line colours (#9400D3, #009E73, #56B4E9, ...)
  Mathematica  its default colours (#5E81B5, #E19C24, #8FB032, ...)
  Stata      the s2color scheme (#1A476F, #90353B, background #EAF2F3)
"""

import re

_PALETTES = {
    "ggplot2": {"f8766d", "00bfc4", "7cae00", "c77cff", "00ba38", "619cff", "e76bf3",
                "a3a500", "00bf7d", "00b0f6", "ebebeb"},
    "lattice": {"ffe5cc", "0080ff", "ccffff"},
    # R 4's palette(), R 3's (green3, gray), rainbow(8)
    "R": {"df536b", "61d04f", "2297e6", "28e2e5", "cd0bbc", "f5c710", "00cd00", "bebebe",
          "ffbf00", "80ff00", "00ff40", "0040ff", "8000ff", "ff00bf"},
    "matplotlib": {"1f77b4", "ff7f0e", "2ca02c", "d62728", "9467bd", "8c564b", "e377c2",
                   "7f7f7f", "bcbd22", "17becf"},
    "MATLAB": {"262626", "0072bd", "d95319", "edb120", "7e2f8e", "77ac30", "4dbeee", "a2142f"},
    "Excel": {"000080", "4f81bd", "c0504d", "9bbb59", "8064a2", "4bacc6", "f79646",
              "5b9bd5", "4472c4", "ed7d31", "a5a5a5", "ffc000", "70ad47", "868686",
              "d9d9d9", "595959", "9999ff", "993366", "ffffcc"},
    "gnuplot": {"9400d3", "009e73", "56b4e9", "e69f00", "f0e442", "0072b2", "e51e10"},
    "Mathematica": {"5e81b5", "e19c24", "8fb032", "eb6235", "8778b3", "c56e1a", "5d9ec7"},
    "Stata": {"1a476f", "90353b", "55752f", "e37e00", "6e8e84", "c10534", "938dd2", "eaf2f3"},
}
# colours that on their own say little (black, white, greys, primaries)
_COMMON = {"000000", "ffffff", "ff0000", "00ff00", "0000ff", "808080", "c0c0c0"}


def _rgb(h):
    return tuple(int(h[k:k + 2], 16) for k in (0, 2, 4))


_PALETTE_RGB = {tool: [_rgb(h) for h in pal] for tool, pal in _PALETTES.items()}
_COMMON_RGB = [_rgb(h) for h in _COMMON]


def _matches(h, rgbs, tol=2):
    """Is colour h within `tol` units (per channel) of one of rgbs?  (A
    converter may shift a colour slightly: #EDB120 becomes #EDB021.)"""
    c = _rgb(h)
    return any(all(abs(a - b) <= tol for a, b in zip(c, r)) for r in rgbs)


def _hex(rgb):
    return "%02x%02x%02x" % tuple(int(round(255 * max(0.0, min(1.0, c)))) for c in rgb)


def guess_tool(rect, paths, texts, glyph_symbols):
    """The likely program ("R", "R (ggplot2)", "R (lattice)", "matplotlib",
    "MATLAB", "Excel", "gnuplot", "Mathematica", "Stata") that drew the
    graph with box `rect`, judged from the paths, texts and Dingbats markers
    in and around it; "" when no program stands out."""
    x0, y0, x1, y1 = rect
    mx, my = 0.1 * (x1 - x0), 0.15 * (y1 - y0)

    def near(x, y):
        return x0 - mx <= x <= x1 + mx and y0 - my <= y <= y1 + my

    mine = [p for p in paths if near(*p["subpaths"][0]["start"])]
    words = [t for t in texts if near(*t["p0"])]
    dingbats = sum(1 for s in glyph_symbols if near(s["cx"], s["cy"]))
    if not mine and not dingbats:
        return ""

    colours = {}
    for p in mine:
        for on, rgb in ((p["fill"], p["fill_rgb"]), (p["stroke"], p["stroke_rgb"])):
            if on and rgb:
                h = _hex(rgb)
                colours[h] = colours.get(h, 0) + 1
    fonts = {}
    for t in words:
        f = (t.get("font") or "").lower()
        fonts[f] = fonts.get(f, 0) + 1
    styles = [p.get("style") or (None,) * 6 for p in mine]
    strokes = [st for p, st in zip(mine, styles) if p["stroke"]]

    score = {}

    def add(tool, n):
        score[tool] = score.get(tool, 0.0) + n

    # palettes: each distinct characteristic colour counts, provided the
    # palette's colours make up a fair share of the graph's colours (one
    # colour of a rainbow that happens to match proves nothing)
    special = {c: n for c, n in colours.items() if not _matches(c, _COMMON_RGB, 0)}
    total = sum(special.values())
    owners = {}               # colour -> the palettes it belongs to (exact match first)
    for c in special:
        exact = [t for t, pal in _PALETTES.items() if c in pal]
        owners[c] = exact or [t for t, rgbs in _PALETTE_RGB.items() if _matches(c, rgbs)]
    for tool in _PALETTES:
        hits = [c for c in special if tool in owners[c]]
        if hits and sum(special[c] for c in hits) >= 0.2 * total:
            add(tool, min(3.0, 1.0 + len(hits)))
    # MATLAB draws axes, ticks and labels in #262626
    if any(_matches(c, [(38, 38, 38)], 1) for c in colours):
        add("MATLAB", 1.5)

    # R: ZapfDingbats circles; round caps and joins with 2-3 decimals
    if dingbats:
        add("R", 3.0)
    if strokes:
        rounded = sum(1 for st in strokes if st[1] == 1 and st[2] == 1 and
                      st[3] is not None and st[3] <= 3)
        if rounded >= 0.8 * len(strokes):
            add("R", 2.0)

    # matplotlib: graphics states A1, A2, ...; marker drawings M0, M1, ...
    gs = [st[5] for st in styles if st[5]]
    if gs and sum(1 for g in gs if re.fullmatch(r"A\d+", g)) >= 0.8 * len(gs):
        add("matplotlib", 3.0)
    if any(st[4] and re.fullmatch(r"M\d+", st[4]) for st in styles):
        add("matplotlib", 2.0)

    # fonts
    if any("dejavu" in f for f in fonts):
        add("matplotlib", 2.0)
    if any("calibri" in f for f in fonts):
        add("Excel", 2.0)
    elif any(f.startswith("arial") for f in fonts) and score.get("Excel"):
        add("Excel", 1.0)
    if any(f.startswith("helvetica") for f in fonts):
        for tool in ("R", "MATLAB"):
            if score.get(tool):
                add(tool, 0.5)

    # filled diamonds: the first default marker of Excel's charts
    if score.get("Excel") and any(p["fill"] for p in mine):
        from .symbols import as_closed, classify_subpath
        diamonds = sum(1 for p in mine[:400] if p["fill"] and
                       (classify_subpath(as_closed(p["subpaths"][0])) or {}).get("shape")
                       == "diamond")
        if diamonds >= 3:
            add("Excel", 1.0)

    if not score:
        return ""
    # the R add-on packages are R too: they need R's evidence or their own
    r_family = score.get("R", 0.0)
    for pkg in ("ggplot2", "lattice"):
        if pkg in score:
            score["R (%s)" % pkg] = r_family + score.pop(pkg)
    ranked = sorted(score.items(), key=lambda kv: -kv[1])
    best, s = ranked[0]
    second = ranked[1][1] if len(ranked) > 1 else 0.0
    if best.startswith("R (") and len(ranked) > 1 and ranked[1][0] == "R":
        second = max((v for k, v in ranked[2:]), default=0.0)
    if s < 2.5 or s - second < 1.0:
        return ""
    return best

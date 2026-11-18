"""Charts without markers: bars of bar charts / histograms, the stems of
stem plots and the vertices of data lines (solid or dashed) of line
charts.
"""

import math

from .geometry import (axis_aligned, bbox_of, inside_rect, line_intersection, median, rect_area,
                       rect_of, vertices)


def find_bars(graph, paths):
    """Bars of a bar chart: filled axis-aligned rectangles standing on the
    graph's baseline (its x axis line, or the line of value 0).  Each bar is
    one data point at the middle of its top edge (its value is its height;
    a bar going down from 0 has its value at its bottom edge)."""
    x0, y0, x1, y1 = graph["rect"]
    w, h = x1 - x0, y1 - y0
    bases = [y0]
    if graph["y"]["map"]["kind"] == "linear" and graph["y"]["map"]["a"]:
        yz = -graph["y"]["map"]["b"] / graph["y"]["map"]["a"]      # where value 0 is
        if y0 < yz < y1:
            bases.append(yz)
    tol = max(0.75, 0.005 * h)
    bars = []
    hanging = []                    # bars going down from the lowest line
    loose = []                      # rectangles off the baseline: stacked segments?
    seen = set()
    for p in paths:
        if not p["fill"]:
            continue
        for sp in p["subpaths"]:
            if any(s[0] != "l" for s in sp["segs"]) or len(sp["segs"]) not in (3, 4):
                rb = _rounded_bar_box(sp)    # a bar with rounded corners?
                if rb is None:
                    continue
                bx0, by0, bx1, by1 = rb
            else:
                pts = vertices(sp)
                bx0, by0, bx1, by1 = bbox_of(pts)
                if not all(abs(a[0] - b[0]) < 1e-3 or abs(a[1] - b[1]) < 1e-3
                           for a, b in zip(pts, pts[1:] + pts[:1])):
                    continue                 # not an axis-aligned rectangle
            bw, bh = bx1 - bx0, by1 - by0
            # (the box of a category axis ends at the outer categories'
            # centres: a bar's middle must be inside it, not the whole bar)
            if bw <= 0.3 or bw > 0.25 * w or bh <= 0 or \
                    not x0 - tol <= (bx0 + bx1) / 2 <= x1 + tol:
                continue
            for base in bases:
                # (a bar may rise above the plot box by a quarter of its
                # height: a chart without a frame ends its box at the top
                # grid line, and 3485513-020's tallest bars pass it)
                if abs(by0 - base) <= tol and by1 <= y1 + max(tol, 0.25 * h):
                    top = by1
                elif abs(by1 - base) <= tol and by0 >= y0 - tol and base != y0:
                    top = by0                # a bar going down from zero
                elif abs(by1 - base) <= tol and base == y0 and by0 >= y0 - 0.25 * h:
                    # going down from the lowest line, which is not 0 (bars of
                    # ratios from 1x): kept if as wide as the standing bars
                    hanging.append(((bx0 + bx1) / 2, by0, bw, p))
                    break
                else:
                    continue
                key = (round(bx0, 2), round(bx1, 2), round(top, 2))
                if key in seen:
                    continue                 # fill and outline of one bar
                seen.add(key)
                bars.append({"shape": "bar", "cx": (bx0 + bx1) / 2, "cy": top, "size": bw,
                             "filled": True, "rgb": p["fill_rgb"], "idx": p["idx"],
                             "base": by0 if top == by1 else by1})
                break
            else:
                if by1 <= y1 + tol:
                    loose.append((bx0, by0, bx1, by1, p))
    _stack(bars, loose, tol, seen)
    if hanging and len(bars) >= 3:
        wm = median(b["size"] for b in bars)
        for cx, top, bw, p in hanging:
            key = (round(cx - bw / 2, 2), round(cx + bw / 2, 2), round(top, 2))
            if abs(bw - wm) <= 0.05 * wm and key not in seen:
                seen.add(key)
                bars.append({"shape": "bar", "cx": cx, "cy": top, "size": bw,
                             "filled": True, "rgb": p["fill_rgb"], "idx": p["idx"]})
    return _drop_bands(bars, y0, y1, tol)


def _rounded_bar_box(sp):
    """(x0, y0, x1, y1) of a rectangle with rounded corners traced by a
    subpath, or None (3485513-020: Google Sheets bars, rounded at the top).
    Its straight segments are horizontal or vertical (the closing one too),
    its curves (one to four) quarter arcs, both ends within half the
    shorter side of one corner of its box, and every segment end lies on
    the box's edges, and straight sides make up half its outline or more (a
    circle's arcs end on its box too).  (The soft shadows drawn round such bars have corner
    points inside their box: not bars.)"""
    segs = sp["segs"]
    if not segs or len(segs) > 16 or any(s[0] not in ("l", "c") for s in segs):
        return None
    n_c = sum(1 for s in segs if s[0] == "c")
    if not 1 <= n_c <= 4:
        return None
    pts = [sp["start"]] + [s[-1] for s in segs]
    x0, y0, x1, y1 = bbox_of(pts)
    w, h = x1 - x0, y1 - y0
    if w <= 0.3 or h <= 0:
        return None
    r = 0.5 * min(w, h)
    e = 0.01

    def on_edge(q):
        return abs(q[0] - x0) <= e or abs(q[0] - x1) <= e or abs(q[1] - y0) <= e or abs(q[1] - y1) <= e

    if not all(on_edge(q) for q in pts):
        return None
    corners = ((x0, y0), (x0, y1), (x1, y0), (x1, y1))
    prev = sp["start"]
    straight = 0.0
    for s in segs + [("l", sp["start"])]:
        q = s[-1]
        if s[0] == "l":
            if abs(q[0] - prev[0]) > 1e-3 and abs(q[1] - prev[1]) > 1e-3:
                return None
            straight += abs(q[0] - prev[0]) + abs(q[1] - prev[1])
        elif not any(max(abs(prev[0] - c[0]), abs(prev[1] - c[1])) <= r + e and
                     max(abs(q[0] - c[0]), abs(q[1] - c[1])) <= r + e for c in corners) or \
                abs(q[0] - prev[0]) <= e or abs(q[1] - prev[1]) <= e:
            return None
        prev = q
    # mostly straight sides: a circle's four arcs also end on its box
    # (jordan-teh-026's dots of atoms of no mass are no bars)
    if straight < 0.5 * 2 * (w + h):
        return None
    return (x0, y0, x1, y1)


def _stack(bars, loose, tol, seen):
    """Stacked bars: a rectangle as wide as a bar, standing on its top, is
    the next segment of the stack (2204.07073-010: the share of physical
    jobs on that of cognitive ones).  It is a data point at its own top, as
    every bar is.  Adds to `bars`."""
    tops = list(bars)
    while tops and loose:
        nxt = []
        for b in tops:
            bx0, bx1 = b["cx"] - b["size"] / 2, b["cx"] + b["size"] / 2
            for r in loose:
                rx0, ry0, rx1, ry1, p = r
                if abs(rx0 - bx0) <= tol and abs(rx1 - bx1) <= tol and abs(ry0 - b["cy"]) <= tol and ry1 > b["cy"] + tol:
                    key = (round(rx0, 2), round(rx1, 2), round(ry1, 2))
                    if key in seen:
                        continue
                    seen.add(key)
                    seg = {"shape": "bar", "cx": (rx0 + rx1) / 2, "cy": ry1, "size": rx1 - rx0,
                           "filled": True, "rgb": p["fill_rgb"], "idx": p["idx"], "base": ry0}
                    bars.append(seg)
                    nxt.append(seg)
        loose = [r for r in loose if (round(r[0], 2), round(r[2], 2), round(r[3], 2)) not in seen]
        tops = nxt


def _drop_bands(bars, y0, y1, tol):
    """Bars that all run the full height of the plot box in one light
    colour are bands shading periods of the x axis (2204.07073-010: grey
    bands behind the years of some editions), not data: a bar chart's bars
    differ in height."""
    if not bars or not all(abs(b["cy"] - y1) <= tol for b in bars):
        return bars
    rgbs = {b["rgb"] for b in bars}
    if len(rgbs) == 1 and None not in rgbs and min(next(iter(rgbs))) >= 0.6:
        return []
    return bars


def _inner_frames(rect, paths):
    """Dark outlined rectangles well inside a plot box and smaller than a
    third of it: the frames of insets and legends."""
    area = rect_area(rect)
    out = []
    for p in paths:
        if not p["stroke"] or sum(p["stroke_rgb"] or (0, 0, 0)) >= 1.5:
            continue
        for sp in p["subpaths"]:
            b = rect_of(sp)
            if b and rect_area(b) < area / 3 and min(b[2] - b[0], b[3] - b[1]) >= 5 and \
                    rect[0] - 0.5 <= b[0] and b[2] <= rect[2] + 0.5 and \
                    rect[1] - 0.5 <= b[1] and b[3] <= rect[3] + 0.5:
                out.append(b)
    return out


def find_line_series(graph, paths):
    """Data lines of a line chart without markers, so that such a chart
    still gives its data.  Returns a list of series, each {"points": [(x,
    y), ...], "rgb", "style", "idx"}:
      * stroked polylines: their corners (pieces that continue each other
        are joined first);
      * dashed lines drawn as many small filled dashes (some programs
        expand the dash pattern into shapes): the dashes are chained and
        each corner is recovered where the dash direction changes.
    Axis-parallel straight lines (grid, axes, frames) are not data lines,
    nor are lines inside a framed box within the plot (an inset with axes
    of its own, as the density curves of 2204.07073-010, or a legend)."""
    rect = graph["rect"]
    tol = max(1.0, 0.01 * max(rect[2] - rect[0], rect[3] - rect[1]))
    frames = _inner_frames(rect, paths)

    def inside(q):
        return inside_rect(rect, q[0], q[1], tol) and not any(
            inside_rect(f, q[0], q[1]) for f in frames)

    series = _stroked_lines(paths, inside) + _dashed_lines(graph, paths, inside)
    out = []
    for s in series:
        pts = []
        for q in s["pts"]:
            if not pts or math.hypot(q[0] - pts[-1][0], q[1] - pts[-1][1]) > 0.05:
                pts.append(q)           # (repeated corners once)
        if len(pts) >= 3:
            out.append(dict(s, points=pts))
    return _drop_arrowheads(out, rect)


def _drop_arrowheads(series, rect):
    """Arrowheads are no data lines: a line of two strokes of one length
    (within 10%), each under 5% of the plot's diagonal, whose tip lies on
    another line (within 0.5 pt of one of its segments).  song2025rigorous-
    002's phase plot draws its yearly path with an arrowhead on every step:
    21 corners and 60 arrowhead corners."""
    diag = math.hypot(rect[2] - rect[0], rect[3] - rect[1])

    def on_line(q, pts):
        for a, b in zip(pts, pts[1:]):
            dx, dy = b[0] - a[0], b[1] - a[1]
            L2 = dx * dx + dy * dy
            t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((q[0] - a[0]) * dx + (q[1] - a[1]) * dy) / L2))
            if math.hypot(a[0] + t * dx - q[0], a[1] + t * dy - q[1]) <= 0.5:
                return True
        return False

    heads = set()
    for i, s in enumerate(series):
        pts = s["points"]
        if len(pts) != 3:
            continue
        l1 = math.hypot(pts[1][0] - pts[0][0], pts[1][1] - pts[0][1])
        l2 = math.hypot(pts[2][0] - pts[1][0], pts[2][1] - pts[1][1])
        if not (0 < l1 < 0.05 * diag and 0 < l2 < 0.05 * diag and abs(l1 - l2) <= 0.1 * max(l1, l2)):
            continue
        if any(on_line(pts[1], o["points"]) for j, o in enumerate(series) if j != i and len(o["points"]) > 3):
            heads.add(i)
    return [s for i, s in enumerate(series) if i not in heads]


def _stroked_lines(paths, inside):
    """Open stroked polylines inside the plot, not all axis-parallel,
    joined where they continue each other (same colour and width)."""
    pieces = []
    for p in paths:
        if not p["stroke"] or p["fill"]:
            continue
        for sp in p["subpaths"]:
            if sp["closed"] or not sp["segs"] or any(s[0] != "l" for s in sp["segs"]):
                continue
            pts = vertices(sp)
            if not all(inside(q) for q in pts):
                continue
            if all(axis_aligned(a, b) for a, b in zip(pts, pts[1:])):
                continue           # grid lines, ticks, axes, steps of a frame
            pieces.append({"pts": pts, "rgb": p["stroke_rgb"], "style": ("solid", round(p.get("lw", 0), 2)),
                           "idx": p["idx"]})
    # programs split long lines into pieces (R: one per few hundred points)
    series = []
    for pc in sorted(pieces, key=lambda pc: pc["idx"]):
        for s in series:
            if s["rgb"] == pc["rgb"] and s["style"] == pc["style"]:
                if math.hypot(s["pts"][-1][0] - pc["pts"][0][0], s["pts"][-1][1] - pc["pts"][0][1]) < 0.05:
                    s["pts"] += pc["pts"][1:]
                    break
                if math.hypot(pc["pts"][-1][0] - s["pts"][0][0], pc["pts"][-1][1] - s["pts"][0][1]) < 0.05:
                    s["pts"] = pc["pts"][:-1] + s["pts"]
                    break
        else:
            series.append({"pts": list(pc["pts"]), "rgb": pc["rgb"], "style": pc["style"],
                           "idx": pc["idx"]})
    return series


def _dashed_lines(graph, paths, inside):
    """Dashed lines drawn as small filled quadrilaterals: per colour, the
    dashes chained left to right, with a corner wherever the direction of
    successive dashes changes (or, on a dense labelled x axis, the line read
    at each label)."""
    x0, y0, x1, y1 = graph["rect"]
    w, h = x1 - x0, y1 - y0
    dashes = {}             # colour -> [(left end, right end, drawing step)]
    for p in paths:
        if not p["fill"] or p["stroke"]:
            continue
        for sp in p["subpaths"]:
            if len(sp["segs"]) not in (3, 4) or any(s[0] != "l" for s in sp["segs"]):
                continue
            q = vertices(sp)[:4]
            if not all(inside(v) for v in q):
                continue
            e = [math.hypot(q[(i + 1) % 4][0] - q[i][0], q[(i + 1) % 4][1] - q[i][1]) for i in range(4)]
            longs = max(e[0], e[1]), min(e[0], e[1])
            if longs[1] <= 0 or longs[0] / longs[1] < 2.5 or longs[0] > 0.1 * max(w, h):
                continue        # not slender, or too long for a dash
            # the dash's centre line runs between the middles of its short sides
            if e[0] >= e[1]:     # short sides are 1-2 and 3-0
                a = ((q[1][0] + q[2][0]) / 2, (q[1][1] + q[2][1]) / 2)
                b = ((q[3][0] + q[0][0]) / 2, (q[3][1] + q[0][1]) / 2)
            else:
                a = ((q[0][0] + q[1][0]) / 2, (q[0][1] + q[1][1]) / 2)
                b = ((q[2][0] + q[3][0]) / 2, (q[2][1] + q[3][1]) / 2)
            dashes.setdefault(p["fill_rgb"], []).append((min(a, b), max(a, b), p["idx"]))
    series = []
    for rgb, ds in dashes.items():
        if len(ds) < 6:
            continue
        ds.sort()
        # gaps between dashes are short; the chain must run left to right
        gap = median(ds[i + 1][0][0] - ds[i][1][0] for i in range(len(ds) - 1))
        if gap is None or gap > 0.05 * w:
            continue
        pts = [ds[0][0]]
        for (a1, b1, _), (a2, b2, _) in zip(ds, ds[1:]):
            d1 = (b1[0] - a1[0], b1[1] - a1[1])
            d2 = (b2[0] - a2[0], b2[1] - a2[1])
            ang = abs(math.atan2(d1[0] * d2[1] - d1[1] * d2[0], d1[0] * d2[0] + d1[1] * d2[1]))
            if ang > math.radians(2):
                v = line_intersection(a1, d1, a2, d2)
                if v and b1[0] - 0.1 <= v[0] <= a2[0] + 0.1:
                    pts.append(v)              # corner in the gap
                elif v and a1[0] <= v[0] <= b1[0]:
                    pts.append(v)              # corner inside a dash
        pts.append(ds[-1][1])
        # on a dense labelled x axis (dates, categories) every series has its
        # corners at the label positions: read the dashed line there, as
        # gentle bends between dashes are easy to miss
        xs_lab = sorted(t for t, _ in graph["x"].get("ticks", ()))
        if graph["x"]["map"]["kind"] != "log" and len(xs_lab) >= 6:
            samp = _sample_chain(ds, xs_lab)
            if len(samp) >= len(pts) - 1:
                pts = samp
        series.append({"pts": pts, "rgb": rgb, "style": ("dashed",), "idx": min(d[2] for d in ds)})
    return series


def _sample_chain(ds, xs):
    """The chained dashes `ds` read (interpolated) at each x of `xs` that
    the chain reaches, within half a label spacing of its ends (a dash
    pattern may stop short of the line's last corner)."""
    chain = []
    for a, b, _ in ds:
        chain += [a, b]
    samp = []
    reach = 0.5 * min(b - a for a, b in zip(xs, xs[1:]))
    for xv in xs:
        if not (chain[0][0] - reach <= xv <= chain[-1][0] + reach):
            continue
        for (u, v) in zip(chain, chain[1:]):
            if u[0] - 1e-9 <= xv <= v[0] + 1e-9 or (xv < chain[0][0] and u is chain[0]) \
                    or (xv > chain[-1][0] and v is chain[-1]):
                f = 0.0 if v[0] == u[0] else (xv - u[0]) / (v[0] - u[0])
                samp.append((xv, u[1] + f * (v[1] - u[1])))
                break
    return samp


def find_stems(graph, paths, marks):
    """Stems of a stem plot: thin vertical strokes standing on the graph's
    baseline (its x axis line, or the line of value 0), each one data point
    at its free end (jordan-teh-026: the atoms of a Dirichlet process
    draw, their masses on the y axis).  Returns (stems, ids of `marks` that
    are stems of no height).

    A stem is a stroked open subpath of one straight segment, vertical
    within 0.01 pt, with one end on a baseline (within 0.25 pt) and inside
    the plot's x range, not on the plot's left or right edge (frame, y
    axis) and shorter than 99% of the plot's height (grid lines).  A stroke
    of no length on the baseline is a stem of no height (an atom of
    negligible mass), and so is a filled dot no larger than 1 pt centred on
    it: Ghostscript draws a round-capped stroke of no length as a dot.
    Tick marks standing on the axis are not stems: a stroke as long as the
    axis's ticks (within 0.1 pt) at a tick position on the run of its
    labelled ticks, or four or more strokes of one length evenly spaced on
    the axis line (minor ticks).  A plot counts as a stem plot only with at least three
    stems with height whose heights differ (by more than 1 pt and more
    than the ticks' length): a row of equal strokes is ticks or a
    pattern, not data."""
    x0, y0, x1, y1 = graph["rect"]
    w, h = x1 - x0, y1 - y0
    bases = [y0]
    ym = graph["y"]["map"]
    if ym["kind"] == "linear" and ym["a"]:
        yz = -ym["b"] / ym["a"]                  # where value 0 is
        if y0 + 0.25 < yz < y1:
            bases.append(yz)
    tol = 0.25
    edge = max(0.3, 0.003 * w)
    xa = graph["x"]
    tick_len = xa.get("tick_len") or 0.0
    labelled = sorted(p for p, _ in xa.get("ticks", ()))
    step = median([b - a for a, b in zip(labelled, labelled[1:])]) if len(labelled) >= 2 else None

    def on_tick_run(x):
        if not step or step <= 0:
            return False
        k = round((x - labelled[0]) / step)
        return abs(labelled[0] + k * step - x) <= 0.1

    found = {}                                     # (x, base, top) -> stem
    for p in paths:
        if not p["stroke"] or p["fill"]:
            continue
        for sp in p["subpaths"]:
            if sp["closed"] or len(sp["segs"]) != 1 or sp["segs"][0][0] != "l":
                continue
            a, b = sp["start"], sp["segs"][0][-1]
            if abs(a[0] - b[0]) > 0.01:
                continue
            x = (a[0] + b[0]) / 2
            if not (x0 + edge < x < x1 - edge):
                continue
            for base in bases:
                if abs(a[1] - base) <= tol:
                    top = b[1]
                elif abs(b[1] - base) <= tol:
                    top = a[1]
                else:
                    continue
                if not (y0 - tol <= top <= y1 + tol) or abs(top - base) >= 0.99 * h:
                    break
                if (tick_len and base == y0 and abs(abs(top - base) - tick_len) <= 0.1
                        and on_tick_run(x)):
                    break                          # a tick mark of the x axis
                key = (round(x, 2), round(base, 2), round(top, 2))
                found.setdefault(key, {"shape": "stem", "cx": x, "cy": top, "size": 0.0,
                                       "filled": False, "rgb": p["stroke_rgb"],
                                       "idx": p["idx"], "base": base})
                break
    stems = list(found.values())
    # rows of equal, evenly spaced strokes on the axis line: (minor) tick
    # marks.  (Not on a line of value 0 inside the plot, where no ticks
    # stand: three stems of S1383762124002030's autocorrelations two lags
    # apart are all 0.5 pt long.)
    by_len = {}
    for s in stems:
        n = abs(s["cy"] - s["base"])
        if n > tol and s["base"] == y0:
            by_len.setdefault(round(n, 2), []).append(s)
    ticks = set()
    for group in by_len.values():
        xs = sorted(s["cx"] for s in group)
        gaps = [b - a for a, b in zip(xs, xs[1:])]
        if len(xs) >= 4 and max(gaps) - min(gaps) <= 0.05:
            ticks.update(id(s) for s in group)
    stems = [s for s in stems if id(s) not in ticks]
    heights = sorted(abs(s["cy"] - s["base"]) for s in stems if abs(s["cy"] - s["base"]) > tol)
    if len(heights) < 3 or heights[-1] - heights[0] <= max(1.0, tick_len):
        return [], set()
    dots = set()
    for m in marks:
        if (m["shape"] == "circle" and m.get("filled") and m["size"] <= 1.0
                and x0 + edge < m["cx"] < x1 - edge
                and any(abs(m["cy"] - base) <= tol for base in bases)):
            base = min(bases, key=lambda bb: abs(m["cy"] - bb))
            dots.add(id(m))
            stems.append({"shape": "stem", "cx": m["cx"], "cy": base, "size": 0.0,
                          "filled": False, "rgb": m["rgb"], "idx": m["idx"], "base": base})
    stems.sort(key=lambda s: (s["idx"], s["cx"]))
    return stems, dots


BOX_SHAPES = ("box-min", "box-q1", "box-median", "box-q3", "box-max")


def _box_rect(sp):
    """(x0, y0, x1, y1) of an axis-aligned rectangle traced by a subpath of
    straight segments (closed, or ending where it began), allowing one of
    no height (a box whose quartiles coincide), or None."""
    if not sp["segs"] or any(seg[0] != "l" for seg in sp["segs"]):
        return None
    pts = vertices(sp)
    if len(pts) == 5 and math.hypot(pts[4][0] - pts[0][0], pts[4][1] - pts[0][1]) <= 0.01:
        pts = pts[:4]
    if len(pts) != 4:
        return None
    for p, q in zip(pts, pts[1:] + pts[:1]):
        if abs(p[0] - q[0]) > 0.01 and abs(p[1] - q[1]) > 0.01:
            return None
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    if max(xs) - min(xs) < 0.5:
        return None
    return (min(xs), min(ys), max(xs), max(ys))


def find_boxes(graph, paths):
    """Box plots: [(box, [five points])], each point a symbol dict of shape
    box-min, box-q1, box-median, box-q3 or box-max at the box's centre
    line (sarroRE15-008: R's boxplot()).  Vertical boxes first; failing
    those, horizontal ones (Statistical_Test_Coverage_for_Linux page 8:
    estimates with their 95% intervals as grey boxes, each with a line at
    the estimate, no whiskers), whose points stand on the box's middle
    across, their values along x.

    A box is an axis-aligned rectangle inside the plot (filled or outlined;
    a fill and an outline of one rectangle are one box), narrower across
    than a third of the plot, with a median: a single stroke across it
    spanning its width (within 10%) between its ends.  Whiskers are single
    strokes on its centre line (within 0.3 pt) running outward from its
    ends (within 0.3 pt); a whisker's far end is the minimum or maximum
    (caps, the short strokes across those ends, are not needed).  A side
    with no whisker ends at the quartile.

    Bars with error bars look alike, so a graph is a box plot only with
    two or more boxes whose median lies strictly inside the box (more than
    0.3 pt from both ends) and that have a whisker - or, with no whiskers
    at all, three or more boxes with a median strictly inside (a bar has
    no stroke across its middle); then boxes with a median but no whiskers
    (all values within the quartiles) and boxes of no length (quartiles
    equal: just a median line), as wide as the others (within 10%), are
    boxes too."""
    x0, y0, x1, y1 = graph["rect"]
    tol = 0.3
    rects = {}
    hs, vs = [], []
    for p in paths:
        for sp in p["subpaths"]:
            r = _box_rect(sp) if (p["fill"] or p["stroke"]) else None
            if r is None and (p["fill"] or p["stroke"]):
                r = _box_rect_flat(sp)
            if r is not None:
                if x0 - tol <= r[0] and r[2] <= x1 + tol and y0 - tol <= r[1] and r[3] <= y1 + tol:
                    # a fill and an outline of one box (within 0.2 pt, not by
                    # rounding: S1383762124002030's differ across a rounding edge)
                    key = (round(r[0]), round(r[1]))
                    same = None
                    for kk in ((key[0] + i, key[1] + j) for i in (-1, 0, 1) for j in (-1, 0, 1)):
                        for n, (q, _) in enumerate(rects.get(kk, ())):
                            if all(abs(u - v) <= 0.2 for u, v in zip(q, r)):
                                same = (kk, n)
                    if same is None:
                        rects.setdefault(key, []).append((r, p))
                    elif p["fill"]:
                        rects[same[0]][same[1]] = (r, p)
                continue
            if not p["stroke"] or len(sp["segs"]) != 1 or sp["segs"][0][0] != "l":
                continue
            a, b = sp["start"], sp["segs"][0][-1]
            if abs(a[1] - b[1]) <= 0.01 and abs(a[0] - b[0]) > 0.01:
                hs.append((min(a[0], b[0]), max(a[0], b[0]), a[1]))
            elif abs(a[0] - b[0]) <= 0.01 and abs(a[1] - b[1]) > 0.01:
                vs.append(((a[0] + b[0]) / 2, min(a[1], b[1]), max(a[1], b[1])))
    allr = [rp for lst in rects.values() for rp in lst]
    out = _boxes_upright(allr, hs, vs, x1 - x0, tol)
    if out:
        return out
    # horizontal boxes: the same in the frame with x and y swapped
    sw = [((r[1], r[0], r[3], r[2]), p) for r, p in allr]
    hs_t = [(lo, hi, x) for x, lo, hi in vs]
    vs_t = [(y, lo, hi) for lo, hi, y in hs]
    out = _boxes_upright(sw, hs_t, vs_t, y1 - y0, tol)
    back = []
    for r, pts in out:
        for q in pts:
            q["cx"], q["cy"] = q["cy"], q["cx"]
        back.append(((r[1], r[0], r[3], r[2]), pts))
    return back


def _box_rect_flat(sp):
    """A box of no length drawn as a closed outline of two coinciding
    lines (a rectangle of no height or width), or None."""
    if not sp["segs"] or any(seg[0] != "l" for seg in sp["segs"]) or len(sp["segs"]) > 4:
        return None
    pts = vertices(sp)
    xs = [q[0] for q in pts]
    ys = [q[1] for q in pts]
    w, h = max(xs) - min(xs), max(ys) - min(ys)
    if (w <= 0.01) == (h <= 0.01):
        return None
    if not sp.get("closed") and math.hypot(pts[-1][0] - pts[0][0], pts[-1][1] - pts[0][1]) > 0.01:
        return None
    return (min(xs), min(ys), max(xs), max(ys))


def _boxes_upright(rects, hs, vs, span, tol):
    """The upright boxes among rects [(rect, path)] with the horizontal
    strokes hs [(lo, hi, y)] and vertical ones vs [(x, lo, hi)]; span is
    the plot's width (boxes are narrower than a third of it)."""
    found = []
    for r, p in rects:
        bx0, by0, bx1, by1 = r
        bw, cx = bx1 - bx0, (bx0 + bx1) / 2
        # (at least 1.5 pt thick: logpaper5Rediscoveries-007's data markers,
        # 0.8 pt dashes with a piece of error bar across, are no boxes)
        if bw >= span / 3 or bw < 1.5:
            continue
        meds = [y for lo, hi, y in hs
                if abs(lo - bx0) <= 0.1 * bw and abs(hi - bx1) <= 0.1 * bw and by0 - tol <= y <= by1 + tol]
        if not meds:
            continue
        med = min(meds, key=lambda y: abs(y - (by0 + by1) / 2))
        low = [lo for x, lo, hi in vs if abs(x - cx) <= tol and abs(hi - by0) <= tol and lo < by0 - tol]
        high = [hi for x, lo, hi in vs if abs(x - cx) <= tol and abs(lo - by1) <= tol and hi > by1 + tol]
        found.append({"rect": r, "cx": cx, "w": bw, "med": med,
                      "min": min(low) if low else by0, "max": max(high) if high else by1,
                      "whisker": bool(low or high),
                      "inside": by0 + tol < med < by1 - tol,
                      "rgb": p["fill_rgb"] if p["fill"] else p["stroke_rgb"], "idx": p["idx"],
                      "clip": p.get("clip")})
    sure = [b for b in found if b["whisker"] and b["inside"]]
    if len(sure) < 2:
        inside = [b for b in found if b["inside"]]
        if any(b["whisker"] for b in found) or len(inside) < 3:
            return []
        sure = inside
    bw = median([b["w"] for b in sure])
    boxes = [b for b in found if any(b is s for s in sure) or abs(b["w"] - bw) <= 0.1 * bw]
    out = []
    for b in sorted(boxes, key=lambda b: b["cx"]):
        ys = (b["min"], b["rect"][1], b["med"], b["rect"][3], b["max"])
        # (the clipping box ties a whisker end beyond the plot to its graph,
        # as for clipped outliers: MSR23_Anisha-003's 2012 box)
        pts = [{"shape": name, "cx": b["cx"], "cy": y, "size": b["w"], "filled": True,
                "rgb": b["rgb"], "idx": b["idx"], "clip": b["clip"]} for name, y in zip(BOX_SHAPES, ys)]
        out.append((b["rect"], pts))
    return out

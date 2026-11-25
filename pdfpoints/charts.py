"""Charts without markers: bars of bar charts / histograms, the stems of
stem plots and the vertices of data lines (solid or dashed) of line
charts.
"""

import collections
import bisect
import math

from .geometry import (axis_aligned, bbox_of, flatten_subpath, inside_rect, line_intersection, median, polygon_area, rect_area, rect_of, subpath_bbox, vertices)


def find_bars(graph, paths):
    """Bars of a bar chart: filled axis-aligned rectangles standing on the
    graph's baseline (its x axis line, or the line of value 0).  Each bar is
    one data point at the middle of its top edge (its value is its height;
    a bar going down from 0 has its value at its bottom edge)."""
    if graph["y"]["map"]["kind"] == "nominal" and graph["x"]["map"]["kind"] == "linear":
        return _find_hbars(graph, paths)
    x0, y0, x1, y1 = graph["rect"]
    w, h = x1 - x0, y1 - y0
    bases = [y0]
    if graph["y"]["map"]["kind"] == "linear" and graph["y"]["map"]["a"]:
        yz = -graph["y"]["map"]["b"] / graph["y"]["map"]["a"]      # where value 0 is
        if y0 < yz < y1:
            bases.append(yz)
    tol = max(0.75, 0.005 * h)
    # (on a category axis a bar may be as wide as 90% of the categories'
    # spacing: 2020.01.30.927558.full-030's panel A, three bars 17 pt wide
    # in a plot 64 pt wide)
    cat_w = 0.0
    mx = graph["x"]["map"]
    if mx.get("kind") == "nominal" and len(mx.get("ticks") or ()) >= 2:
        cs = sorted(c for c, _ in mx["ticks"])
        cat_w = 0.9 * min(b - a for a, b in zip(cs, cs[1:]))
    bars = []
    hanging = []                    # bars going down from the lowest line
    loose = []                      # rectangles off the baseline: stacked segments?
    seen = set()
    for p in paths:
        thick = _thick_upright_strokes(p)
        if not p["fill"] and not thick:
            continue
        for sp in (thick if thick else p["subpaths"]):
            if isinstance(sp, tuple):
                bx0, by0, bx1, by1 = sp
            elif any(s[0] != "l" for s in sp["segs"]) or len(sp["segs"]) not in (3, 4):
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
            if bw <= 0.3 or bw > max(0.25 * w, cat_w) or bh <= 0 or \
                    not x0 - tol <= (bx0 + bx1) / 2 <= x1 + tol:
                continue
            for base in (() if thick else bases):
                # (a bar may rise above the plot box by a quarter of its
                # height: a chart without a frame ends its box at the top
                # grid line, and 3485513-020's tallest bars pass it)
                clip = p.get("clip")
                if abs(by0 - base) <= tol and by1 <= y1 + max(tol, 0.25 * h):
                    top = by1
                elif base == y0 and by0 < y0 - tol and y0 + tol < by1 <= y1 + max(tol, 0.25 * h) and \
                        clip and abs(clip[1] - y0) <= max(tol, 1.0):
                    # (on a log axis a bar's foot, at 0, lies far below:
                    # clipped at the plot's bottom, it stands there -
                    # 2305.15675v1-015's histogram reaches y = -13 826)
                    top = by1
                    by0 = y0
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
                             "filled": True, "rgb": _paint(p, thick), "idx": p["idx"],
                             "base": by0 if top == by1 else by1})
                break
            else:
                if by1 <= y1 + tol:
                    loose.append((bx0, by0, bx1, by1, p, _paint(p, thick)))
    _stack(bars, loose, tol, seen)
    if hanging and len(bars) >= 3:
        wm = median(b["size"] for b in bars)
        for cx, top, bw, p in hanging:
            key = (round(cx - bw / 2, 2), round(cx + bw / 2, 2), round(top, 2))
            if abs(bw - wm) <= 0.05 * wm and key not in seen:
                seen.add(key)
                bars.append({"shape": "bar", "cx": cx, "cy": top, "size": bw,
                             "filled": True, "rgb": p["fill_rgb"], "idx": p["idx"]})
    return _drop_bands(bars, y1, tol)


def _find_hbars(graph, paths):
    """Horizontal bars: in a graph with categories up its y axis and a
    number scale along x (2020.01.30.927558.full-026: model names, bars of
    delta AIC to the right), filled axis-aligned rectangles at most a
    quarter of the plot's height thick, centred within it, one end on the
    plot's left side or on the line of value 0.  Each bar is one point at
    the middle of its far end."""
    x0, y0, x1, y1 = graph["rect"]
    w, h = x1 - x0, y1 - y0
    m = graph["x"]["map"]
    bases = [x0]
    if m.get("a"):
        xz = -m["b"] / m["a"]
        if x0 < xz < x1:
            bases.append(xz)
    tol = max(0.75, 0.005 * w)
    bars, seen, loose = [], set(), []
    for p in paths:
        if not p["fill"]:
            continue
        for sp in p["subpaths"]:
            if any(sg[0] != "l" for sg in sp["segs"]) or len(sp["segs"]) not in (3, 4):
                continue
            pts = vertices(sp)
            bx0, by0, bx1, by1 = bbox_of(pts)
            if not all(abs(a[0] - b[0]) < 1e-3 or abs(a[1] - b[1]) < 1e-3
                       for a, b in zip(pts, pts[1:] + pts[:1])):
                continue
            bh = by1 - by0
            if bh <= 0.3 or bh > 0.25 * h or bx1 - bx0 <= 0 or \
                    not y0 - tol <= (by0 + by1) / 2 <= y1 + tol:
                continue
            for base in bases:
                if abs(bx0 - base) <= tol and bx1 <= x1 + max(tol, 0.25 * w):
                    end, foot = bx1, bx0
                elif abs(bx1 - base) <= tol and base != x0 and bx0 >= x0 - tol:
                    end, foot = bx0, bx1          # a bar going left from zero
                else:
                    continue
                key = (round(by0, 2), round(by1, 2), round(end, 2))
                if key not in seen:
                    seen.add(key)
                    bars.append({"shape": "bar", "cx": end, "cy": (by0 + by1) / 2, "size": bh,
                                 "filled": True, "rgb": p["fill_rgb"], "idx": p["idx"],
                                 "base": foot, "horizontal": True})
                break
            else:
                loose.append((bx0, by0, bx1, by1, p))
    # stacked: a rectangle as thick as a bar starting at its end is the
    # next segment, a point at its own end (2305.15675v1 page 7: shares of
    # four classes in each bar)
    ends = [b for b in bars if b["cx"] > b["base"]]
    while ends and loose:
        nxt = []
        for b in ends:
            b0, b1 = b["cy"] - b["size"] / 2, b["cy"] + b["size"] / 2
            for r in loose:
                rx0, ry0, rx1, ry1, p = r
                if abs(ry0 - b0) <= tol and abs(ry1 - b1) <= tol and abs(rx0 - b["cx"]) <= tol and \
                        rx1 > b["cx"] + 0.1:
                    key = (round(ry0, 2), round(ry1, 2), round(rx1, 2))
                    if key in seen:
                        continue
                    seen.add(key)
                    seg = {"shape": "bar", "cx": rx1, "cy": (ry0 + ry1) / 2, "size": ry1 - ry0,
                           "filled": True, "rgb": p["fill_rgb"], "idx": p["idx"], "base": rx0,
                           "horizontal": True}
                    bars.append(seg)
                    nxt.append(seg)
        loose = [r for r in loose if (round(r[1], 2), round(r[3], 2), round(r[2], 2)) not in seen]
        ends = nxt
    return bars


def _thick_upright_strokes(p):
    """A bar drawn as a vertical line stroked as wide as the bar
    (Memory_systems_cacheDRAMdisk-051: the black "CPU + DRAM" segment of
    each stacked bar is a line 2.3 pt wide down the bar's centre): the
    rectangle it paints, [(x0, y0, x1, y1)] for each such subpath.  Only
    strokes of butt caps (the default) at least 0.5 pt wide, and only as a
    segment of a stack on a filled bar (w21074-042's Excel line chart has
    thick vertical strokes standing on its axis: no bars)."""
    if not p["stroke"] or p["fill"]:
        return []
    style = p.get("style") or ()
    lw = style[0] if style and isinstance(style[0], (int, float)) else 0.0
    cap = style[1] if len(style) > 1 else None
    if lw < 0.5 or cap not in (None, 0):
        return []
    out = []
    for sp in p["subpaths"]:
        if len(sp["segs"]) != 1 or sp["segs"][0][0] != "l":
            continue
        a, b = sp["start"], sp["segs"][0][-1]
        if abs(a[0] - b[0]) <= 0.01 and abs(a[1] - b[1]) > 0.05:
            x = (a[0] + b[0]) / 2
            out.append((x - lw / 2, min(a[1], b[1]), x + lw / 2, max(a[1], b[1])))
    return out


def _paint(p, thick):
    return p["stroke_rgb"] if thick else p["fill_rgb"]


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
    for s in [*segs, ("l", sp["start"])]:
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
                rx0, ry0, rx1, ry1, p, rgb = r
                # (a segment may be thin: Memory_systems_cacheDRAMdisk-051's
                # 0.17 pt grey layers between the black and white ones)
                if abs(rx0 - bx0) <= tol and abs(rx1 - bx1) <= tol and abs(ry0 - b["cy"]) <= tol and \
                        ry1 > b["cy"] + 0.1:
                    key = (round(rx0, 2), round(rx1, 2), round(ry1, 2))
                    if key in seen:
                        continue
                    seen.add(key)
                    seg = {"shape": "bar", "cx": (rx0 + rx1) / 2, "cy": ry1, "size": rx1 - rx0,
                           "filled": True, "rgb": rgb, "idx": p["idx"], "base": ry0}
                    bars.append(seg)
                    nxt.append(seg)
        loose = [r for r in loose if (round(r[0], 2), round(r[2], 2), round(r[3], 2)) not in seen]
        tops = nxt


def _drop_bands(bars, y1, tol):
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
        each corner is recovered where the dash direction changes;
      * lines converted to outlines (one long thin filled shape): their
        centre line traced and simplified (_outlined_lines).
    Axis-parallel straight lines (grid, axes, frames) are not data lines,
    nor are lines inside a framed box within the plot (an inset with axes
    of its own, as the density curves of 2204.07073-010, or a legend)."""
    rect = graph["rect"]
    tol = max(1.0, 0.01 * max(rect[2] - rect[0], rect[3] - rect[1]))
    frames = _inner_frames(rect, paths)

    def inside(q):
        return inside_rect(rect, q[0], q[1], tol) and not any(
            inside_rect(f, q[0], q[1]) for f in frames)

    series = _regrid(_stroked_lines(paths, inside, rect, tol)) + _dashed_lines(graph, paths, inside) + \
        _outlined_lines(graph, paths, inside)
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


def _straight_segs(sp):
    """Are all the subpath's segments straight?  A curve whose control
    points lie on its chord (within 0.02 pt) is a straight segment written
    as a curve (ArianeWuerbach-Phd-219: about 400 of each trace plot's 5 254
    segments)."""
    q = sp["start"]
    for s in sp["segs"]:
        if s[0] == "c":
            a, b = q, s[-1]
            dx, dy = b[0] - a[0], b[1] - a[1]
            L = math.hypot(dx, dy)
            for c in s[1:3]:
                d = abs(dx * (c[1] - a[1]) - dy * (c[0] - a[0])) / L if L else math.dist(c, a)
                if d > 0.02:
                    return False
        elif s[0] != "l":
            return False
        q = s[-1]
    return True


def _clipped_to(p, rect, tol):
    """Was the path drawn clipped to the plot box (within tol)?"""
    c = p.get("clip")
    return bool(c) and all(abs(a - b) <= tol for a, b in zip(c, rect))


def _chain_stroked_dashes(pieces, rect):
    """Dashed lines whose dashes are stroked one by one (Sovinsky-paper-017:
    PDF-XChange prints Stata's dashed line as one two-point stroke per dash,
    a dash bent at a corner as two strokes that touch).  The pieces of one
    colour and width, in drawing order, are one dashed line when five or
    more breaks between them are gaps of one length (0.5 to 1.3 times their
    median, which is at most 3% of the plot's larger side: a gap across a
    corner is shorter) and every other break touches (within 0.05 pt).  A corner inside a gap is where the two dashes
    either side, extended, meet (when they turn by more than 2 degrees and
    the meeting point lies in the gap).  The chain is one piece, style
    ("dashed",); the dash ends stay vertices, to be dropped by _regrid."""
    if rect is None:
        return pieces
    big = max(rect[2] - rect[0], rect[3] - rect[1])
    groups = {}
    for pc in pieces:
        groups.setdefault((pc["rgb"], pc["style"]), []).append(pc)
    out = []
    for key, ps in groups.items():
        breaks = [math.dist(a["pts"][-1], b["pts"][0]) for a, b in zip(ps, ps[1:])]
        gaps = [d for d in breaks if d >= 0.05]
        med = median(gaps) if gaps else None
        if len(ps) < 6 or len(gaps) < 5 or med > 0.03 * big or \
                any(not 0.5 * med <= d <= 1.3 * med for d in gaps):
            out += ps
            continue
        pts = list(ps[0]["pts"])
        for pc in ps[1:]:
            q = pc["pts"]
            if math.dist(pts[-1], q[0]) >= 0.05 and len(pts) >= 2:
                a1, a2 = pts[-2], pts[-1]
                d1 = (a2[0] - a1[0], a2[1] - a1[1])
                d2 = (q[1][0] - q[0][0], q[1][1] - q[0][1])
                ang = abs(math.atan2(d1[0] * d2[1] - d1[1] * d2[0], d1[0] * d2[0] + d1[1] * d2[1]))
                if ang > math.radians(2):
                    v = line_intersection(a2, d1, q[0], d2)
                    if v and min(a2[0], q[0][0]) - 0.1 <= v[0] <= max(a2[0], q[0][0]) + 0.1 and \
                            math.dist(v, a2) + math.dist(v, q[0]) <= 2 * math.dist(a2, q[0]):
                        pts.append(v)    # (a peak lies above both dash ends)
                pts += q
            else:
                pts += q[1:]
        out.append(dict(ps[0], pts=pts, style=("dashed",), idx=ps[0]["idx"],
                        pieces=len(pts) - 1,        # (every dash and gap a segment of its own)
                        flat=all(axis_aligned(a, b) for a, b in zip(pts, pts[1:]))))
    return out


def _rightward(xs):
    """Do the x positions run left to right (a corner put in a dash gap
    may lie a hair, 0.1 pt, before the dash end it follows)?"""
    return all(b > a - 0.1 for a, b in zip(xs, xs[1:])) and xs[-1] > xs[0]


def _grid_of(pts, tol=0.35):
    """The evenly spaced x positions (first x, step) on which a polyline
    running left to right has a vertex at every one: the finest such grid
    from its first to its last vertex, of four steps or more and steps of
    1 pt or more.  None if there is none."""
    xs = [q[0] for q in pts]
    if len(xs) < 5 or not _rightward(xs):
        return None
    a, b = xs[0], xs[-1]
    for m in range(len(xs) - 1, 3, -1):
        d = (b - a) / m
        if d < 1.0:
            continue
        j = 0
        for k in range(m + 1):
            x = a + k * d
            while j < len(xs) and xs[j] < x - tol:
                j += 1
            if j == len(xs) or abs(xs[j] - x) > tol:
                break
        else:
            return a, d
    return None


def _at(pts, x):
    """The polyline's y at x (the end value just past either end)."""
    if x <= pts[0][0]:
        return pts[0][1]
    for u, v in zip(pts, pts[1:]):
        if u[0] <= x <= v[0]:
            return u[1] if v[0] == u[0] else u[1] + (x - u[0]) / (v[0] - u[0]) * (v[1] - u[1])
    return pts[-1][1]


def _regrid(series, tol=0.35, near=0.4):
    """Lines printed with extra vertices (Sovinsky-paper-017: PDF-XChange
    splits Stata's lines into pieces of at most about 12 pt, adds a vertex
    just before most corners and rounds every vertex to about 0.2 pt; its
    dashed line has a vertex at every dash end).  When one of the graph's
    stroked lines has a vertex at every point of an evenly spaced x grid
    (_grid_of) - a time series' quarters - each stroked line running left
    to right is read at the grid's points within its x range, provided
    that it starts and ends on a grid point and every one of its vertices
    lies within `near` of the line so read (no corner is lost).  A line
    whose vertices are all on the grid is unchanged."""
    def read(s, a, d):
        pts = s["pts"]
        xs = [q[0] for q in pts]
        k0, k1 = math.ceil((xs[0] - a - tol) / d), math.floor((xs[-1] - a + tol) / d)
        if not (_rightward(xs) and k1 - k0 >= 3 and
                abs(a + k0 * d - xs[0]) <= tol and abs(a + k1 * d - xs[-1]) <= tol):
            return None
        samp = [(a + k * d, _at(pts, a + k * d)) for k in range(k0, k1 + 1)]
        samp[0], samp[-1] = pts[0], pts[-1]
        if len(samp) < len(pts) and all(
                min(math.dist(q, _seg_near(q, u, v)) for u, v in zip(samp, samp[1:])) <= near for q in pts):
            return samp
        return None

    # only lines printed piece by piece (a path for each segment or dash,
    # nearly: a polyline drawn as one path has no printer's vertices, and
    # a dense curve has a vertex near every point of many grids)
    def printed(s):
        return s.get("pieces", 1) >= 0.8 * (len(s["pts"]) - 1)
    # the grid that reads the most lines (a coarser one on a tie: a dense
    # dashed chain may have a vertex at every point of a fine grid too)
    best = None
    for g in {g for s in series if printed(s) and (g := _grid_of(s["pts"], tol))}:
        reads = [read(s, *g) if printed(s) else None for s in series]
        n = sum(r is not None for r in reads)
        if n and (best is None or (n, g[1]) > (best[0], best[1])):
            best = (n, g[1], reads)
    if best is None:
        return series
    return [dict(s, pts=r) if r is not None else s for s, r in zip(series, best[2])]


def _stroked_lines(paths, inside, rect=None, tol=1.0):
    """Open stroked polylines inside the plot, not all axis-parallel,
    joined where they continue each other (same colour and width).

    A polyline drawn clipped to the plot box may run outside it: R draws
    every vertex of lines() and lets the clip hide those beyond the axis
    limits (ESEUR-intro page 7: the lower regions' sales fall below the y
    range set by the world total; page 10: Wang's counts start in 1985,
    left of xlim, and E-Commerce rises far above ylim).  Such a line is
    kept when two or more of its vertices are inside, and all its
    vertices are reported, as markers clipped out of view are.  A clipped
    piece wholly out of view is kept when a line of its colour and width
    is in view: R breaks a line at each missing value, and the lower
    regions' first ten months (1976, before two missing months) lie below
    the plot.  Where a line leaves the device altogether R cuts it there
    and starts a new polyline where it comes back: the two cut ends,
    outside the clip box at one x or one y (within 0.01 pt), are no data;
    the pieces are joined without them (E-Commerce's last piece runs from
    the cut to its 2003 count, both above the plot)."""
    pieces = []
    for p in paths:
        if not p["stroke"] or p["fill"]:
            continue
        clipped = rect is not None and _clipped_to(p, rect, tol)
        for sp in p["subpaths"]:
            if sp["closed"] or not sp["segs"] or not _straight_segs(sp):
                continue
            pts = vertices(sp)
            n_in = sum(1 for q in pts if inside(q))
            if n_in < len(pts) and not clipped:
                continue
            # (axis-parallel pieces - grid lines, ticks, axes, steps of a
            # frame - are no lines alone, but may be the level stretches of
            # a line printed piece by piece: Sovinsky-paper-017's flat runs
            # and level dashes)
            flat = all(axis_aligned(a, b) for a, b in zip(pts, pts[1:]))
            pieces.append({"pts": pts, "rgb": p["stroke_rgb"], "style": ("solid", round(p.get("lw", 0), 2)),
                           "idx": p["idx"], "clip": p.get("clip") if clipped else None,
                           "seen": n_in >= 2, "flat": flat, "pieces": 1})

    pieces = _chain_stroked_dashes(pieces, rect)

    def out_of_clip(pc, q):
        c = pc["clip"]
        return c is not None and not inside_rect(c, q[0], q[1], 0.01)

    def cut_pair(a, b):
        return out_of_clip(a, a["pts"][-1]) and out_of_clip(b, b["pts"][0]) and (
            abs(a["pts"][-1][0] - b["pts"][0][0]) <= 0.01 or abs(a["pts"][-1][1] - b["pts"][0][1]) <= 0.01)

    # programs split long lines into pieces (R: one per few hundred points);
    # an axis-parallel piece joins only pieces drawn next to it (within two
    # drawing steps), so a grid line or frame is no part of a line
    series = []
    for pc in sorted(pieces, key=lambda pc: pc["idx"]):
        for s in series:
            if s["rgb"] == pc["rgb"] and s["style"] == pc["style"] and (
                    not (pc["flat"] or s["flat"]) or abs(pc["idx"] - s["last"]) <= 2):
                if math.hypot(s["pts"][-1][0] - pc["pts"][0][0], s["pts"][-1][1] - pc["pts"][0][1]) < 0.05:
                    s["pts"] += pc["pts"][1:]
                elif math.hypot(pc["pts"][-1][0] - s["pts"][0][0], pc["pts"][-1][1] - s["pts"][0][1]) < 0.05:
                    s["pts"] = pc["pts"][:-1] + s["pts"]
                elif cut_pair(s, pc):
                    s["pts"] = s["pts"][:-1] + pc["pts"][1:]
                else:
                    continue
                s["seen"] = s["seen"] or pc["seen"]
                s["flat"] = s["flat"] and pc["flat"]
                s["pieces"] += pc["pieces"]
                s["last"] = pc["idx"]
                break
        else:
            series.append({"pts": list(pc["pts"]), "rgb": pc["rgb"], "style": pc["style"],
                           "idx": pc["idx"], "clip": pc["clip"], "seen": pc["seen"],
                           "flat": pc["flat"], "last": pc["idx"], "pieces": pc["pieces"]})
    series = [s for s in series if not s["flat"]]
    shown = {(s["rgb"], s["style"]) for s in series if s["seen"]}
    return [s for s in series if s["seen"] or (s["rgb"], s["style"]) in shown]


def _simplify(pts, tol):
    """Douglas-Peucker: the corners of polyline `pts` to within `tol`."""
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        i, j = stack.pop()
        a, b = pts[i], pts[j]
        dx, dy = b[0] - a[0], b[1] - a[1]
        L = math.hypot(dx, dy)
        far, k = -1.0, None
        for m in range(i + 1, j):
            q = pts[m]
            d = abs(dx * (q[1] - a[1]) - dy * (q[0] - a[0])) / L if L else math.dist(q, a)
            if d > far:
                far, k = d, m
        if k is not None and far > tol:
            keep[k] = True
            stack += [(i, k), (k, j)]
    return [q for q, kp in zip(pts, keep) if kp]


def _smooth(pts, reach):
    """Polyline `pts` averaged over the points within `reach` along it of
    each (its ends kept)."""
    arc = [0.0]
    for a, b in zip(pts, pts[1:]):
        arc.append(arc[-1] + math.dist(a, b))
    out, lo, hi, sx, sy = [], 0, 0, 0.0, 0.0
    for k in range(len(pts)):
        while hi < len(pts) and arc[hi] <= arc[k] + reach:
            sx += pts[hi][0]; sy += pts[hi][1]; hi += 1
        while arc[lo] < arc[k] - reach:
            sx -= pts[lo][0]; sy -= pts[lo][1]; lo += 1
        out.append((sx / (hi - lo), sy / (hi - lo)))
    out[0], out[-1] = pts[0], pts[-1]
    return out


def _seg_near(q, a, b):
    """The point of segment ab nearest q."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    L2 = dx * dx + dy * dy
    t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((q[0] - a[0]) * dx + (q[1] - a[1]) * dy) / L2))
    return (a[0] + t * dx, a[1] + t * dy)


def _outlined_lines(graph, paths, inside):
    """Lines converted to outlines (978-3-031-36060-2_2-006: each d3 curve
    of Figure 2.3 is one filled shape of 1 600 - 2 300 edges, a staircase of
    0.42 pt steps where the short square-capped strokes overlapped): a
    filled, unstroked single closed contour of 40 edges or more inside the
    plot, spanning a fifth of its width or height, not all axis-parallel,
    long and thin - its width, area over half its perimeter, at most 3 pt
    and 2% of the plot's diagonal, its half perimeter 15 widths or more.
    The centre line is the middle of each slice across the shape: up and
    down every half width, and across (for steep parts), slices 6 widths
    long or less; the middles are chained from the end farthest from the
    shape's centre, averaged along the chain over a width either way, and
    simplified to within half the width (the original vertices cannot be
    told from the steps of the outline: each loop of its contour, one
    short stroke, touches both sides)."""
    x0, y0, x1, y1 = graph["rect"]
    diag = math.hypot(x1 - x0, y1 - y0)
    out = []
    for p in paths:
        if not p["fill"] or p["stroke"] or len(p["subpaths"]) != 1:
            continue
        sp = p["subpaths"][0]
        if len(sp["segs"]) < 40:
            continue
        pts = flatten_subpath(sp)
        if len(pts) > 2 and math.dist(pts[0], pts[-1]) < 0.01:
            pts = pts[:-1]
        if not all(inside(q) for q in pts):
            continue
        bx0, by0, bx1, by1 = bbox_of(pts)
        if bx1 - bx0 < 0.2 * (x1 - x0) and by1 - by0 < 0.2 * (y1 - y0):
            continue
        n = len(pts)
        half = sum(math.dist(pts[k], pts[(k + 1) % n]) for k in range(n)) / 2
        width = abs(polygon_area(pts)) / half if half else 0.0
        if not 0 < width <= min(3.0, 0.02 * diag) or half < 15 * width:
            continue
        if all(axis_aligned(pts[k], pts[(k + 1) % n]) for k in range(n)) and \
                (bx1 - bx0 < 3 * width or by1 - by0 < 3 * width):
            continue                        # an outlined axis or grid line
        # the centre line: the middle of each slice across the shape - up
        # and down every half width where it is shallow, across where it is
        # steep (slices of 6 widths or less) - chained from one end, across
        # gaps of up to 12 widths (a steep run of steps, too wide both ways)
        edges = [(pts[k], pts[(k + 1) % n]) for k in range(n)]
        step = 0.5 * width
        mids = []
        for k in (0, 1):                    # 0: vertical slices at x; 1: level ones at y
            lo_b, hi_b = (bx0, bx1) if k == 0 else (by0, by1)
            v = lo_b + step / 2
            while v < hi_b:
                cuts = []
                for a, b in edges:
                    if (a[k] - v) * (b[k] - v) < 0:
                        f = (v - a[k]) / (b[k] - a[k])
                        cuts.append(a[1 - k] + f * (b[1 - k] - a[1 - k]))
                if cuts and max(cuts) - min(cuts) <= 6 * width:
                    c = (min(cuts) + max(cuts)) / 2
                    mids.append((v, c) if k == 0 else (c, v))
                v += step
        if len(mids) < 3:
            continue
        cx, cy = (bx0 + bx1) / 2, (by0 + by1) / 2
        cur = max(mids, key=lambda q: math.hypot(q[0] - cx, q[1] - cy))
        left = set(range(len(mids)))
        left.discard(mids.index(cur))
        centre = [cur]
        while left:
            m = min(left, key=lambda k: math.dist(mids[k], cur))
            if math.dist(mids[m], cur) > 12 * width:
                break                       # (a stray slice off the line)
            left.discard(m)
            cur = mids[m]
            centre.append(cur)
        if len(centre) < 0.8 * len(mids) or len(centre) < 3:
            continue
        # the slices' middles wobble where the outline steps: averaged along
        # the trace over a width either way, the ends kept; then wiggles
        # within half a width are hidden in the line
        line = _simplify(_smooth(centre, width), max(0.05, 0.5 * width))
        out.append({"pts": line, "rgb": p["fill_rgb"], "style": ("solid", round(width, 2)),
                    "idx": p["idx"]})
    return out


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
    # (0.5 pt across in one direction at least: a horizontal box may be
    # shorter along x - 2305.15675v1-015's are 0.42 pt long, 9 pt thick;
    # the thickness across is tested with the boxes)
    if max(xs) - min(xs) < 0.5 and max(ys) - min(ys) < 0.5:
        return None
    return (min(xs), min(ys), max(xs), max(ys))


def find_violins(graph, paths):
    """Violin plots with an inner box (2355585.2355594-006: matplotlib
    violins of 31 benchmarks in four stacked panels, every stroke written
    as a filled outline): [(outline box, [points])] like find_boxes, the
    points box-min, box-q1, box-median, box-q3 and box-max on the violin's
    centre line.  At one x (within 0.3 pt), thin upright strokes (filled
    outlines at most 1.5 pt wide, or stroked lines) of which some are 1.6
    times as thick as the thinnest: the thick ones span the quartiles, all
    of them the minimum to the maximum; a short level stroke centred on
    that x (1.5 to 6 times the thick one's width, within 0.3 pt) between
    the quartiles is the median.  The thick ones are 1.6 times as wide as
    the commonest width (slivers where pieces overlap are no measure).
    Pieces may be of any height from 0.02 pt (a flat violin's whisker and
    box are specks: the IPC panel's), but not wider than tall when 0.8 pt
    wide or more (the dots of dotted grid lines); a group keeps the pieces
    of its widest piece's colour (within 0.3 per channel: not the slivers
    of a red reference line crossing the violins).  A
    violin stands round them: a closed outline of 20 edges or more, curved,
    centred on that x (within 2 pt), holding the minimum to the maximum
    (within 1 pt; the density runs on past them); groups round one outline
    are one.  A violin with no thick piece (the quartiles coincide) but a
    median line gives the minimum, median and maximum.  Level marks at one
    height (within 0.5 pt) in 80% of the violins marked or more are a reference
    line's marks, not medians: then no medians are reported.  Three
    violins or more in the graph, or none."""
    x0, y0, x1, y1 = graph["rect"]
    ups, levels, outlines = [], [], []
    for p in paths:
        for sp in p["subpaths"]:
            if not sp["segs"]:
                continue
            b = subpath_bbox(sp)
            w, h = b[2] - b[0], b[3] - b[1]
            cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
            if not (x0 <= cx <= x1 and y0 - 1 <= cy <= y1 + 1):
                continue
            # (tick marks start on the plot's edge: no part of a violin)
            on_edge = b[1] <= y0 + 0.3 or b[3] >= y1 - 0.3
            # (a flat violin may be under 2 pt tall: the bottom panel's #26)
            if p["fill"] and len(sp["segs"]) >= 20 and w > 2 and h > 0.5 and \
                    any(s[0] == "c" for s in sp["segs"]):
                outlines.append(b)
            if p["fill"] and not p["stroke"]:
                # (pieces of any height: a flat violin's whisker and box are
                # specks - not the dots of a dotted grid line, wider than tall)
                if w <= 1.5 and h >= 0.02 and not on_edge and not (w >= 0.8 and h < w):
                    ups.append((cx, b[1], b[3], w, p))
                elif h <= 1.5 and w >= 1.5 * h and w <= 12:
                    levels.append((cx, cy, w, h, p))
            elif p["stroke"] and not p["fill"] and len(sp["segs"]) == 1 and \
                    sp["segs"][0][0] == "l":
                lw = (p.get("style") or (1.0,))[0] or 0.1
                if w <= 0.05 and h > 0.5 and not on_edge:
                    ups.append((cx, b[1], b[3], lw, p))
                elif h <= 0.05 and 1.5 * lw <= w <= 12:
                    levels.append((cx, cy, w, lw, p))
    if len(ups) < 6 or not outlines:
        return []
    ups.sort(key=lambda u: u[0])
    groups, cur = [], [ups[0]]
    for u in ups[1:]:
        if u[0] - cur[-1][0] <= 0.3:
            cur.append(u)
        else:
            groups.append(cur)
            cur = [u]
    groups.append(cur)
    # (groups round one violin outline are one: an off-centre sliver may
    # break a chain of pieces - the IPC panel's #16)
    by_box = {}

    def colour(u):
        p = u[4]
        return (p.get("fill_rgb") if p["fill"] else p.get("stroke_rgb")) or (0.0, 0.0, 0.0)
    for grp in groups:
        # (one colour family, the widest piece's: slivers of a reference
        # line laid over the violins - dark red where it crosses them - are
        # no part of them)
        ref = colour(max(grp, key=lambda u: u[3]))
        grp = [u for u in grp if max(abs(a - b) for a, b in zip(colour(u), ref)) <= 0.3]
        if not grp or max(u[2] - u[1] for u in grp) < 0.5:
            continue            # (specks alone - slivers - make no violin)
        gx = sum(u[0] for u in grp) / len(grp)
        glo, ghi = min(u[1] for u in grp), max(u[2] for u in grp)
        # (the largest: a violin's black outline holds its white body)
        box = max((ob for ob in outlines if abs((ob[0] + ob[2]) / 2 - gx) <= 2.0 and
                   ob[1] <= glo + 1.0 and ob[3] >= ghi - 1.0),
                  key=lambda ob: (ob[2] - ob[0]) * (ob[3] - ob[1]), default=None)
        if box is not None:
            by_box.setdefault(box, []).extend(grp)
    out = []
    for box, grp in by_box.items():
        ref = colour(max(grp, key=lambda u: u[3]))
        grp = [u for u in grp if max(abs(a - b) for a, b in zip(colour(u), ref)) <= 0.3]
        # (the commonest width is the whisker's: slivers 0.2 pt wide, where
        # pieces overlap, are no measure)
        widths = collections.Counter(round(u[3], 2) for u in grp)
        thin = min(w for w, n in widths.items() if n == max(widths.values()))
        thick = [u for u in grp if u[3] >= 1.6 * thin]
        if len(thick) == len(grp):
            continue
        x = sum(u[0] for u in grp) / len(grp)
        lo, hi = min(u[1] for u in grp), max(u[2] for u in grp)
        if thick:
            q1, q3 = min(u[1] for u in thick), max(u[2] for u in thick)
            tw = max(u[3] for u in thick)
        else:
            # (no box: the quartiles coincide - a median line and the
            # whisker only, reported without them)
            q1, q3, tw = lo, hi, 2 * thin
        meds = [lv for lv in levels if abs(lv[0] - x) <= 0.3 and q1 - 0.5 <= lv[1] <= q3 + 0.5
                and 1.5 * tw <= lv[2] <= 6 * tw]
        ys = [lo, q1 if thick else None, None, q3 if thick else None, hi]
        if meds:
            # (the darkest, drawn first: a reference line laid over it is
            # another colour)
            m = min(meds, key=lambda lv: (sum(lv[4].get("fill_rgb") or lv[4].get("stroke_rgb")
                                              or (0, 0, 0)), lv[4]["idx"]))
            ys[2] = m[1]
        elif not thick:
            continue                    # a bare line in an outline: no violin known
        if not thick:
            ys[1] = ys[3] = None
        p0 = (thick or grp)[0][4]
        rgb = p0.get("fill_rgb") if p0["fill"] else p0.get("stroke_rgb")
        pts = [{"shape": name, "cx": x, "cy": y, "size": tw, "filled": True, "rgb": rgb,
                "idx": p0["idx"], "clip": p0.get("clip")}
               for name, y in zip(BOX_SHAPES, ys) if y is not None]
        out.append((box, pts))
    # level marks at one height in most violins are a reference, not their
    # medians (2355585.2355594-006: every violin marked at 10^0, the value
    # each benchmark is normalised to, the mark below some violins' first
    # quartile): no medians
    meds = [p["cy"] for _, pts in out for p in pts if p["shape"] == "box-median"]
    if len(meds) >= 3:
        common = max(sum(1 for m in meds if abs(m - c) <= 0.5) for c in meds)
        if common >= 0.8 * len(meds):
            out = [(box, [p for p in pts if p["shape"] != "box-median"]) for box, pts in out]
    return out if len(out) >= 3 else []


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
    # a box's values are read along its length: never along a category
    # axis (Memory_systems_cacheDRAMdisk-051: the segments of stacked bars
    # over category ticks, with hidden strokes across them, were taken for
    # horizontal boxes)
    def numeric(orient):
        m = (graph.get(orient) or {}).get("map")
        return m is None or m.get("kind") != "nominal"
    out = _boxes_upright(allr, hs, vs, x1 - x0, tol) if numeric("y") else []
    # (boxes that all end on the line of value 0 are bars hanging from (or
    # standing on) zero with error bars: the cap inside a bar looked like a
    # median, the bar beyond its end like a whisker -
    # 2020.01.30.927558.full-023)
    m = graph["y"]["map"]
    if out and m.get("kind") == "linear" and m.get("a"):
        yz = -m["b"] / m["a"]
        if all(min(abs(r[1] - yz), abs(r[3] - yz)) <= max(0.75, 0.005 * (y1 - y0)) for r, _ in out):
            return []
    if out or not numeric("x"):
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
        # a stroke along the centre line from end to end inside the box
        # crosses the median: a square marker with a plus in it (R's pch
        # 12: wp_21_1036-019), no box (whiskers lie outside a box)
        # (within a tenth of the box's length of its ends: a whisker stub
        # beside a box 0.25 pt long is no such stroke, 2305.15675v1-015)
        end_tol = min(tol, 0.1 * (by1 - by0))
        if any(abs(x - cx) <= tol and lo >= by0 - end_tol and hi <= by1 + end_tol and
               hi - lo >= 0.9 * (by1 - by0) for x, lo, hi in vs):
            continue
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


def _band_chains(p, rect, tol):
    """A filled path that is one band of a stacked area chart: a closed
    polygon of straight segments running left to right along one edge and
    back along the other at the same x positions (plotly / matplotlib
    stackplot and fill_between); where the band is of no thickness (a
    series not yet started, economies-open-intelligence-005) the two edges
    share a vertex.  Returns (xs, top ys, bottom ys) left to right, or
    None."""
    if not p["fill"] or len(p["subpaths"]) != 1:
        return None
    sp = p["subpaths"][0]
    if len(sp["segs"]) < 20 or any(s[0] != "l" for s in sp["segs"]):
        return None
    pts = vertices(sp)
    if len(pts) > 2 and math.dist(pts[0], pts[-1]) < 0.01:
        pts = pts[:-1]
    # x positions (within 0.01 pt), and the outline's walk over them: up
    # to the right end, then back down to the left
    xs = []
    for x in sorted(q[0] for q in pts):
        if not xs or x - xs[-1] > 0.01:
            xs.append(x)
    if len(xs) < 10:
        return None
    at = [bisect.bisect_left(xs, q[0] - 0.01) for q in pts]
    k0 = at.index(0)
    walk = at[k0:] + at[:k0]
    turn = 0
    while turn + 1 < len(walk) and walk[turn + 1] >= walk[turn]:
        turn += 1
    if walk[turn] != len(xs) - 1 or any(walk[k + 1] > walk[k] for k in range(turn, len(walk) - 1)):
        return None
    ys = [[] for _ in xs]
    for q, a in zip(pts, at):
        ys[a].append(q[1])
    if any(not 1 <= len(v) <= 2 for v in ys):
        return None
    x0, y0, x1, y1 = rect
    if xs[-1] - xs[0] < 0.5 * (x1 - x0) or not all(
            inside_rect(rect, q[0], q[1], tol) for q in pts):
        return None
    return xs, [max(v) for v in ys], [min(v) for v in ys]


def find_stacked_areas(graph, paths):
    """The bands of a stacked area chart (economies-open-intelligence-005:
    shares of downloads by developer and by country, one translucent band
    per series): two or more bands of the shape _band_chains reads, inside
    the plot, each sharing a boundary with another (one's bottom the
    other's top, within 0.05 pt at the same x positions) - a lone
    fill_between (a confidence band) is no stack.  Each vertex of a band's
    top is a point ("area") at the band's top, with the band's bottom in
    "base_y": the series' own share is the difference."""
    rect = graph["rect"]
    tol = max(1.0, 0.01 * max(rect[2] - rect[0], rect[3] - rect[1]))
    bands = []
    for p in paths:
        ch = _band_chains(p, rect, tol)
        if ch:
            bands.append((p, ch))

    def same(u, v):
        return len(u) == len(v) and all(abs(s - t) <= 0.05 for s, t in zip(u, v))
    stacked = [(p, (xs, top, bot)) for p, (xs, top, bot) in bands if any(
        q is not p and same(xs, xs2) and (same(top, bot2) or same(bot, top2))
        for q, (xs2, top2, bot2) in bands)]
    out = []
    for p, (xs, top, bot) in stacked:
        for x, t, b in zip(xs, top, bot):
            out.append({"shape": "area", "cx": x, "cy": t, "size": 0.0, "filled": True,
                        "rgb": p["fill_rgb"], "idx": p["idx"], "base_y": b})
    return out

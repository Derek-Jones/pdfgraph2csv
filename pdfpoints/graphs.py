"""Graphs: pairing x and y axes into plot boxes, panels of lattice plots,
inset graphs, assigning symbols to graphs and recognising graphs turned by
90 degrees.
"""

import math
from .geometry import (
    axis_aligned, bbox_of, frame_rect, merge_collinear, rect_distance,
    straight_segments, to_frame)
from .context import PAGE
from .titles import find_title


def borrows_axis(shared, other):
    """May a graph whose axis `other` lies away from the labelled axis
    `shared` (stacked graphs with the x labels under the bottom one only,
    or side-by-side graphs with the y labels left of the first only) use
    `shared`'s scale?  Only if it has an axis line of its own at one end of
    `other`, spanning the same stretch as `shared`, with its ticks (if it
    has any) at the same places as `shared`'s."""
    if not shared["has_line"]:
        return False
    k = shared["orient"]
    span = shared["hi"] - shared["lo"]
    # as far from the end of `other` as a corner may be (some programs
    # leave a gap between the axes)
    tol = 0.08 * max(span, other["hi"] - other["lo"])
    lines = PAGE.dark_lines[0 if k == "x" else 1]
    want = sorted(shared.get("tick_pos") or [])
    edges = (other["lo"], other["hi"])
    # its own ticks decide (rows of two are the frame's side lines)
    bare = [b for b in PAGE.bare_axes if b["orient"] == k and len(b["tick_pos"]) >= 3
            and any(abs(b["pos"] - e) <= tol for e in edges)
            and b["lo"] < shared["hi"] and shared["lo"] < b["hi"]]
    if bare:
        ttol = max(0.5, 0.005 * span)
        return any(len(b["tick_pos"]) == len(want) and all(
            abs(u - v) <= ttol for u, v in zip(sorted(b["tick_pos"]), want)) for b in bare)
    # no ticks: a plain axis line spanning the same stretch
    etol = max(1.0, 0.01 * span)
    return any(abs(pp - e) <= tol and lo <= shared["lo"] + etol and hi >= shared["hi"] - etol
               for lo, hi, pp in lines for e in edges)


def build_graphs(axes):
    """Pair x and y axes whose lines meet at a corner into graphs:
    {'x': axis, 'y': axis, 'rect': plot box}.  Axes with an axis line are
    preferred to those without.  An axis may also serve a graph further
    along it that shares its scale (borrows_axis)."""
    xs = [a for a in axes if a["orient"] == "x"]
    ys = [a for a in axes if a["orient"] == "y"]
    if any(a["has_line"] for a in xs) and any(a["has_line"] for a in ys):
        xs = [a for a in xs if a["has_line"]]
        ys = [a for a in ys if a["has_line"]]

    def corner(xa, ya):
        """How far the two axis lines are from meeting at a corner:
        (dx, dy) = gap along x between the y axis and the ends of the x
        axis, and gap along y between the x axis and the ends of the y axis.
        An x axis without a line (ticks only) only has to span the y axis."""
        dy = min(abs(xa["pos"] - ya["lo"]), abs(xa["pos"] - ya["hi"]))
        dx = min(abs(ya["pos"] - xa["lo"]), abs(ya["pos"] - xa["hi"]))
        if not xa["has_line"] and xa["lo"] - 1 <= ya["pos"] <= xa["hi"] + 1:
            dx = 0.0
        return dx, dy

    def tol(xa, ya):
        return 0.08 * max(xa["hi"] - xa["lo"], ya["hi"] - ya["lo"])

    # every x axis takes the y axis that comes closest to forming a corner
    # with it, and every y axis the closest x axis; each choice is a graph
    # (an axis shared by side-by-side panels takes part in several).  The
    # second gap may be loose (a y axis set off from the end of the x axis),
    # but one more than half the axis long is another graph's axis, used
    # only if it shares this graph's scale (borrows_axis)
    pairs = set()
    for i, xa in enumerate(xs):
        cands = [(corner(xa, ya), j) for j, ya in enumerate(ys)]
        cands = [c for c in cands if c[0][1] <= tol(xa, ys[c[1]]) and (
            c[0][0] <= 0.5 * (xa["hi"] - xa["lo"]) or borrows_axis(ys[c[1]], xa))]
        if cands:
            pairs.add((i, min(cands)[1]))
    for j, ya in enumerate(ys):
        cands = [(corner(xa, ya)[::-1], i) for i, xa in enumerate(xs)]
        cands = [c for c in cands if c[0][1] <= tol(xs[c[1]], ya) and (
            c[0][0] <= 0.5 * (ya["hi"] - ya["lo"]) or borrows_axis(xs[c[1]], ya))]
        if cands:
            pairs.add((min(cands)[1], j))
    graphs = []
    for i, j in pairs:
        xa, ya = xs[i], ys[j]
        graphs.append({"x": xa, "y": ya,
                       "rect": (xa["lo"], ya["lo"], xa["hi"], ya["hi"])})
    return order_graphs(merge_twin_axes(graphs))


def merge_twin_axes(graphs):
    """A graph with a scale on both sides (a left and a right y axis over
    one x axis, or a bottom and a top x axis beside one y axis) is found as
    two graphs with the same plot box.  Merge them: the axis at the left
    (bottom) stays the graph's "y" ("x"), the other becomes "y2" ("x2"),
    and each series is later mapped through the one it belongs to
    (twin.assign_twin_axes)."""
    out = list(graphs)
    for shared, other in (("x", "y"), ("y", "x")):
        i = 0
        while i < len(out):
            g = out[i]
            j = i + 1
            while j < len(out):
                h = out[j]
                a, b = g[other], h[other]
                span = g[shared]["hi"] - g[shared]["lo"]
                tol = max(1.0, 0.02 * span)
                ends = (g[shared]["lo"], g[shared]["hi"])
                if h[shared] is g[shared] and a is not b and \
                        abs(a["lo"] - b["lo"]) <= tol and abs(a["hi"] - b["hi"]) <= tol and \
                        abs(a["pos"] - b["pos"]) > 0.8 * span and \
                        all(min(abs(ax["pos"] - e) for e in ends) <= tol for ax in (a, b)) and \
                        other + "2" not in g and other + "2" not in h:
                    first, second = (a, b) if a["pos"] < b["pos"] else (b, a)
                    g[other], g[other + "2"] = first, second
                    lo = min(first["lo"], second["lo"])
                    hi = max(first["hi"], second["hi"])
                    r = g["rect"]
                    g["rect"] = (r[0], lo, r[2], hi) if other == "y" else (lo, r[1], hi, r[3])
                    del out[j]
                    continue
                j += 1
            i += 1
    return out


def dark_frame_lines(paths):
    """Merged dark horizontal and vertical stroked lines (frames, borders)."""
    hs, vs = [], []
    for p in paths:
        if not p["stroke"] or sum(p["stroke_rgb"] or (0, 0, 0)) >= 1.5:
            continue
        for sp in p["subpaths"]:
            for a, b in straight_segments({"subpaths": [sp]}):
                aa = axis_aligned(a, b)
                if aa:
                    (hs if aa[0] == "h" else vs).append(aa[1:])
    return merge_collinear(hs), merge_collinear(vs)


def add_panel_graphs(graphs, axes, paths):
    """Small multiples (lattice / facet plots): only the outer panels carry
    labelled axes; every panel shares the x scale of its column and the y
    scale of its row.  Each framed rectangle spanned by a column's x axis
    and a row's y axis is a graph."""
    xs = [a for a in axes if a["orient"] == "x" and a["has_line"]]
    ys = [a for a in axes if a["orient"] == "y" and a["has_line"]]
    if len(xs) * len(ys) < 4:
        return graphs
    hl, vl = dark_frame_lines(paths)

    def covered(lines, pos, lo, hi, tol=0.6):
        """Is there a frame line at `pos` running at least from lo to hi?"""
        return any(abs(pp - pos) <= tol and l0 <= lo + tol and l1 >= hi - tol
                   for l0, l1, pp in lines)

    have = [g["rect"] for g in graphs]
    out = list(graphs)
    for xa in xs:
        for ya in ys:
            r = (xa["lo"], ya["lo"], xa["hi"], ya["hi"])
            if any(all(abs(u - v) < 1.0 for u, v in zip(r, h)) for h in have):
                continue                      # already a graph
            if r[2] - r[0] <= 0 or r[3] - r[1] <= 0:
                continue
            # a panel is a rectangle framed on all four sides by dark lines
            if (covered(hl, r[1], r[0], r[2]) and covered(hl, r[3], r[0], r[2]) and
                    covered(vl, r[0], r[1], r[3]) and covered(vl, r[2], r[1], r[3])):
                out.append({"x": xa, "y": ya, "rect": r})
                have.append(r)
    return order_graphs(out) if len(out) > len(graphs) else graphs


def order_graphs(graphs):
    """Reading order: rows from top to bottom (graphs whose vertical extents
    mostly overlap share a row), left to right within a row."""
    rest = sorted(graphs, key=lambda g: -g["rect"][3])
    out = []
    while rest:
        top = rest[0]
        h0 = top["rect"][3] - top["rect"][1]
        row = []
        for g in rest:
            h = g["rect"][3] - g["rect"][1]
            ov = min(top["rect"][3], g["rect"][3]) - max(top["rect"][1], g["rect"][1])
            if ov > 0.5 * min(h0, h):
                row.append(g)
        rest = [g for g in rest if not any(g is r for r in row)]
        out += sorted(row, key=lambda g: g["rect"][0])
    return out


def frame_texts(texts, rot):
    """Copies of the text items expressed in a turned graph's frame."""
    if not rot:
        return texts
    out = []
    for t in texts:
        u = dict(t)
        x0, y0, x1, y1 = t["bbox"]
        pts = [to_frame(p, rot) for p in ((x0, y0), (x1, y1))]
        u["bbox"] = (min(p[0] for p in pts), min(p[1] for p in pts),
                     max(p[0] for p in pts), max(p[1] for p in pts))
        u["center"] = ((u["bbox"][0] + u["bbox"][2]) / 2, (u["bbox"][1] + u["bbox"][3]) / 2)
        u["p0"], u["p1"] = to_frame(t["p0"], rot), to_frame(t["p1"], rot)
        up = to_frame(t["up"], rot)
        u["up"] = up
        ang = (t.get("angle", 0.0) - rot + 180) % 360 - 180
        u["angle"] = ang
        u["rotated"] = not (abs(ang) < 10 or abs(abs(ang) - 180) < 10)
        out.append(u)
    return out


def frame_symbols(symbols, rot):
    """Symbols seen from a frame turned by `rot` (for legends of turned
    graphs)."""
    if not rot:
        return symbols
    out = []
    for s in symbols:
        u = dict(s)
        u["cx"], u["cy"] = to_frame((s["cx"], s["cy"]), rot)
        out.append(u)
    return out


def graph_rotation(g, texts, symbols):
    """0, or the angle by which the whole graph is turned.  A graph is turned
    when the tick labels of both axes read in the same non-horizontal
    direction and the title found in the turned frame is at least as large
    as any title found in the page frame (a turned graph's former y-axis
    title reads horizontally, so a horizontal heading alone proves nothing)."""
    ax, ay = g["x"].get("label_angle"), g["y"].get("label_angle")
    if ax is None or ax != ay or ax == 0:
        return 0, find_title(g["rect"], texts, symbols)
    rot = ax
    t_rot = find_title(frame_rect(g["rect"], rot), frame_texts(texts, rot),
                       frame_symbols(symbols, rot), with_size=True)
    t_0 = find_title(g["rect"], texts, symbols, with_size=True)
    if t_0[0] and (not t_rot[0] or t_0[1] > t_rot[1] * 1.05):
        return 0, t_0[0]
    return rot, t_rot[0]


def set_graph_backgrounds(graphs, paths):
    """Drawing step at which each graph's own opaque background box was
    painted (an inset is painted over its parent graph), or -1."""
    boxes = []                       # (box, drawing step) of filled single shapes
    for p in paths:
        if not p["fill"] or len(p["subpaths"]) != 1:
            continue
        sp = p["subpaths"][0]
        if len(sp["segs"]) < 3:
            continue
        boxes.append((bbox_of([sp["start"]] + [s[-1] for s in sp["segs"]]), p["idx"]))
    for g in graphs:
        g["bg"] = -1
        x0, y0, x1, y1 = g["rect"]
        tol = max(1.5, 0.01 * max(x1 - x0, y1 - y0))
        for b, idx in boxes:
            if abs(b[0] - x0) <= tol and abs(b[1] - y0) <= tol and \
                    abs(b[2] - x1) <= tol and abs(b[3] - y1) <= tol and idx > g["bg"]:
                g["bg"] = idx


_CACHE = {"graphs": None, "n": 0}


def _cache_for(graphs):
    """Answers worked out for the page's list of graphs (which graph a
    clipping box belongs to, the grid of graph boxes):
    kept while the same list is asked about, dropped when another list (or
    the same one grown) comes."""
    if _CACHE["graphs"] is not graphs or _CACHE["n"] != len(graphs):
        _CACHE.clear()
        _CACHE.update(graphs=graphs, n=len(graphs), clip={}, at=None)
    return _CACHE


def forget_graphs():
    """Drop the cached answers about the last list of graphs."""
    _CACHE.clear()
    _CACHE.update(graphs=None, n=0)


def clip_graph(graphs, s):
    """The graph whose plot box the symbol was clipped to when drawn (the
    clipping box is about the graph's box), or None.  Worked out once per
    clipping box (thousands of markers share one) and list of graphs."""
    c = s.get("clip")
    if not c:
        return None
    memo = _cache_for(graphs)["clip"]
    key = tuple(c)
    if key not in memo:
        memo[key] = _clip_graph(graphs, c)
    return memo[key]


def _clip_graph(graphs, c):
    best = None
    for g in graphs:
        x0, y0, x1, y1 = g["rect"]
        area = max((x1 - x0) * (y1 - y0), 1e-9)
        ov = max(0.0, min(x1, c[2]) - max(x0, c[0])) * max(0.0, min(y1, c[3]) - max(y0, c[1]))
        carea = max(0.0, c[2] - c[0]) * max(0.0, c[3] - c[1])
        if ov >= 0.9 * area and carea <= 1.5 * area and (best is None or carea < best[0]):
            best = (carea, g)
    return best[1] if best else None


def _graphs_at(graphs, x, y):
    """The graphs whose box contains (x, y) (edges included), in list
    order.  The boxes are filed in a grid once per list of graphs (pages of
    small multiples have hundreds of panels and thousands of points)."""
    cache = _cache_for(graphs)
    if cache["at"] is None:
        sizes = sorted(max(g["rect"][2] - g["rect"][0], g["rect"][3] - g["rect"][1])
                       for g in graphs) or [1.0]
        cell = max(sizes[len(sizes) // 2], 1.0)
        grid = {}
        for k, g in enumerate(graphs):
            x0, y0, x1, y1 = g["rect"]
            for gx in range(int(math.floor(x0 / cell)), int(math.floor(x1 / cell)) + 1):
                for gy in range(int(math.floor(y0 / cell)), int(math.floor(y1 / cell)) + 1):
                    grid.setdefault((gx, gy), []).append(k)
        cache["at"] = (cell, grid)
    cell, grid = cache["at"]
    ks = grid.get((int(math.floor(x / cell)), int(math.floor(y / cell))), ())
    return [graphs[k] for k in ks if rect_distance(graphs[k]["rect"], x, y) == 0]


def graph_for_symbol(graphs, s):
    """The graph a symbol belongs to: the graph it was clipped to; else,
    among the graphs whose box contains it, the innermost one painted before
    the symbol; otherwise the nearest graph.  Returns (distance, graph)."""
    g = clip_graph(graphs, s)
    if g is not None:
        return rect_distance(g["rect"], s["cx"], s["cy"]), g
    inside = _graphs_at(graphs, s["cx"], s["cy"])
    if inside:
        before = [g for g in inside if g.get("bg", -1) < s["idx"]] or inside
        g = max(before, key=lambda g: (g.get("bg", -1),
                                       -(g["rect"][2] - g["rect"][0]) * (g["rect"][3] - g["rect"][1])))
        return 0.0, g
    return min(((rect_distance(g["rect"], s["cx"], s["cy"]), g) for g in graphs),
               key=lambda dg: dg[0])

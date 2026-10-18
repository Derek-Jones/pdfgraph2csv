"""Graphs: pairing x and y axes into plot boxes, panels of lattice plots,
inset graphs, assigning symbols to graphs and recognising graphs turned by
90 degrees.
"""

from .geometry import (
    axis_aligned, bbox_of, frame_rect, merge_collinear, rect_distance,
    straight_segments, to_frame)
from .titles import find_title


def build_graphs(axes):
    """Pair x and y axes whose lines meet at a corner into graphs:
    {'x': axis, 'y': axis, 'rect': plot box}.  Axes with an axis line are
    preferred to those without."""
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
    # (an axis shared by side-by-side panels takes part in several)
    pairs = set()
    for i, xa in enumerate(xs):
        cands = [(corner(xa, ya), j) for j, ya in enumerate(ys)]
        cands = [c for c in cands if c[0][1] <= tol(xa, ys[c[1]])]
        if cands:
            pairs.add((i, min(cands)[1]))
    for j, ya in enumerate(ys):
        cands = [(corner(xa, ya)[::-1], i) for i, xa in enumerate(xs)]
        cands = [c for c in cands if c[0][1] <= tol(xs[c[1]], ya)]
        if cands:
            pairs.add((min(cands)[1], j))
    graphs = []
    for i, j in pairs:
        xa, ya = xs[i], ys[j]
        graphs.append({"x": xa, "y": ya,
                       "rect": (xa["lo"], ya["lo"], xa["hi"], ya["hi"])})
    return order_graphs(graphs)


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
    for g in graphs:
        g["bg"] = -1
        x0, y0, x1, y1 = g["rect"]
        tol = max(1.5, 0.01 * max(x1 - x0, y1 - y0))
        for p in paths:
            if not p["fill"] or len(p["subpaths"]) != 1:
                continue
            sp = p["subpaths"][0]
            pts = [sp["start"]] + [s[-1] for s in sp["segs"]]
            if len(pts) < 4:
                continue
            b = bbox_of(pts)
            if all(abs(u - v) <= tol for u, v in zip(b, g["rect"])):
                g["bg"] = max(g["bg"], p["idx"])


def clip_graph(graphs, s):
    """The graph whose plot box the symbol was clipped to when drawn (the
    clipping box is about the graph's box), or None."""
    c = s.get("clip")
    if not c:
        return None
    best = None
    for g in graphs:
        x0, y0, x1, y1 = g["rect"]
        area = max((x1 - x0) * (y1 - y0), 1e-9)
        ov = max(0.0, min(x1, c[2]) - max(x0, c[0])) * max(0.0, min(y1, c[3]) - max(y0, c[1]))
        carea = max(0.0, c[2] - c[0]) * max(0.0, c[3] - c[1])
        if ov >= 0.9 * area and carea <= 1.5 * area and (best is None or carea < best[0]):
            best = (carea, g)
    return best[1] if best else None


def graph_for_symbol(graphs, s):
    """The graph a symbol belongs to: the graph it was clipped to; else,
    among the graphs whose box contains it, the innermost one painted before
    the symbol; otherwise the nearest graph.  Returns (distance, graph)."""
    g = clip_graph(graphs, s)
    if g is not None:
        return rect_distance(g["rect"], s["cx"], s["cy"]), g
    inside = [g for g in graphs if rect_distance(g["rect"], s["cx"], s["cy"]) == 0]
    if inside:
        before = [g for g in inside if g.get("bg", -1) < s["idx"]] or inside
        g = max(before, key=lambda g: (g.get("bg", -1),
                                       -(g["rect"][2] - g["rect"][0]) * (g["rect"][3] - g["rect"][1])))
        return 0.0, g
    return min(((rect_distance(g["rect"], s["cx"], s["cy"]), g) for g in graphs),
               key=lambda dg: dg[0])

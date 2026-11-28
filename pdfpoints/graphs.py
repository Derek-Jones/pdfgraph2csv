"""Graphs: pairing x and y axes into plot boxes, panels of lattice plots,
inset graphs, assigning symbols to graphs and recognising graphs turned by
90 degrees.
"""

import math

from .geometry import (
    axis_aligned, bbox_of, frame_rect, median, merge_collinear, overlap_area, rect_area,
    rect_distance, rects_gap, straight_segments, to_frame, vertices)
from .scales import map_value
from .titles import find_title


_BORROW_TOL_FRAC = 0.08  # a borrowed axis lines up within 8% of the longer span
_BARE_MIN_TICKS = 3      # a bare axis has 3 ticks or more
_TICK_TOL_PT = 0.5       # ticks agree within 0.5 pt
_TICK_TOL_FRAC = 0.005   # or 0.5% of the span
_END_TOL_FRAC = 0.01     # ends agree within 1% of the span


def borrows_axis(shared, other, *, page):
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
    tol = _BORROW_TOL_FRAC * max(span, other["hi"] - other["lo"])
    lines = page.dark_lines[0 if k == "x" else 1]
    want = sorted(shared.get("tick_pos") or [])
    # its own axis line is at the end facing the labelled axis (a left axis
    # serves the plots to its right through their left sides)
    if shared["pos"] < other["lo"]:
        edges = (other["lo"],)
    elif shared["pos"] > other["hi"]:
        edges = (other["hi"],)
    else:
        edges = (other["lo"], other["hi"])
    # its own ticks decide (rows of two are the frame's side lines)
    bare = [b for b in page.bare_axes if b["orient"] == k and len(b["tick_pos"]) >= _BARE_MIN_TICKS
            and any(abs(b["pos"] - e) <= tol for e in edges)
            and b["lo"] < shared["hi"] and shared["lo"] < b["hi"]]
    if bare:
        ttol = max(_TICK_TOL_PT, _TICK_TOL_FRAC * span)
        return any(len(b["tick_pos"]) == len(want) and all(
            abs(u - v) <= ttol for u, v in zip(sorted(b["tick_pos"]), want)) for b in bare)
    # no ticks: a plain axis line spanning the same stretch (dark; or, when
    # the labelled axis has no ticks either - ggplot2 facets without ticks,
    # grey panel borders - a line of any shade)
    etol = max(1.0, _END_TOL_FRAC * span)
    if not shared.get("tick_len") or shared.get("label_ticks"):
        lines = list(lines) + list(page.all_lines[0 if k == "x" else 1])
    return any(abs(pp - e) <= tol and lo <= shared["lo"] + etol and hi >= shared["hi"] - etol
               for lo, hi, pp in lines for e in edges)


_ROW_STEP = 2      # the panels of a row step at most twice the axis's length
_ROW_CORNER_PT = 2.0  # a bare axis at the end of an x axis: within 2 pt


def share_row_scales(graphs, axes, *, page):
    """Small multiples in a row with the y scale written beside the first
    only, each panel with an axis line and ticks (or grid lines) of its own
    but no labels: an x axis left without a graph whose low end meets a bare
    y axis (page.bare_axes: ticks with no labels; within 2 pt), whose ticks
    lie where the ticks of a graph's labelled y axis lie (as many, within
    0.5 pt or 0.5% of the span) and which spans the same stretch (within
    1%), the panels stepping along the row from that axis (each at most
    twice the axis's length on from the one before), makes a graph with
    that y axis's scale (2411.16433v1-066: twelve bar charts with grid lines
    at 0 ... 3, labelled left of the first only; their x axes are their
    zero lines, above the plots' feet, so the corners do not meet).
    Returns the graphs with the new ones added (their y axes marked
    "shared")."""
    used = {id(g["x"]) for g in graphs}
    orphans = [a for a in axes if a["orient"] == "x" and id(a) not in used and a["has_line"]]
    if not orphans:
        return graphs
    out = list(graphs)
    for g in graphs:
        a = g["y"]
        if not a["has_line"] or a["map"]["kind"] == "nominal" or a.get("shared"):
            continue
        span = a["hi"] - a["lo"]
        ttol = max(_TICK_TOL_PT, _TICK_TOL_FRAC * span)
        etol = max(1.0, _END_TOL_FRAC * span)
        want = sorted(a.get("tick_pos") or [])
        if len(want) < _BARE_MIN_TICKS:
            continue
        same = [b for b in page.bare_axes if b["orient"] == "y" and b["pos"] > a["pos"] and
                abs(b["lo"] - a["lo"]) <= etol and abs(b["hi"] - a["hi"]) <= etol and
                len(b["tick_pos"]) == len(want) and
                all(abs(u - v) <= ttol for u, v in zip(sorted(b["tick_pos"]), want))]
        last = a["pos"]
        for b in sorted(same, key=lambda b: b["pos"]):
            if b["pos"] - last > _ROW_STEP * span:
                break
            last = b["pos"]
            xa = next((x for x in orphans if abs(x["lo"] - b["pos"]) <= _ROW_CORNER_PT and
                       a["lo"] <= x["pos"] <= a["hi"]), None)
            if xa is None:
                continue
            orphans.remove(xa)
            ya = dict(a, pos=b["pos"], labels=[], shared=True)
            out.append({"x": xa, "y": ya, "rect": (b["pos"], a["lo"], xa["hi"], a["hi"])})
    return order_graphs(out) if len(out) > len(graphs) else graphs


_LINED_PT = 3.0          # an axis on a drawn line: within 3 pt
_PAIR_GAP_FRAC = 0.08    # a pair of axes meets within 8% of the longer
_PAIR_SLACK_FRAC = 0.02  # axes overlap by 2% of their span
_PAIR_ALONG = 0.5        # a far axis within half its span
_PAIR_ASPECT_LO = 0.3    # a graph's sides 0.3 to 3 times each other
_PAIR_ASPECT_HI = 3      # (the most elongated)
_INSET_LO = 0.05         # an inset lies from 5%
_INSET_HI = 0.95         # to 95% of its host


def build_graphs(axes, *, page):
    """Pair x and y axes whose lines meet at a corner into graphs:
    {'x': axis, 'y': axis, 'rect': plot box}.  Axes with an axis line are
    preferred to those without.  An axis may also serve a graph further
    along it that shares its scale (borrows_axis)."""
    xs = [a for a in axes if a["orient"] == "x"]
    ys = [a for a in axes if a["orient"] == "y"]
    if any(a["has_line"] for a in xs) and any(a["has_line"] for a in ys):
        lined = [a for a in xs if a["has_line"]]
        # (an x axis of ticks only that no lined x axis covers stays: the
        # heat map of 2020.01.30.927558.full-048, its ticks hanging from the
        # frame, beside lined axes elsewhere on the page)
        xs = lined + [a for a in xs if not a["has_line"] and not any(
            abs(b["pos"] - a["pos"]) <= _LINED_PT and b["lo"] < a["hi"] and a["lo"] < b["hi"] for b in lined)]
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
        if _foot_of(xa, ya):
            dx = dy = 0.0
        return dx, dy

    def tol(xa, ya):
        return _PAIR_GAP_FRAC * max(xa["hi"] - xa["lo"], ya["hi"] - ya["lo"])

    def wrong_side(a, b):
        """Is axis `a` beyond an end of axis `b` with its labels in the gap
        between them?  Such an axis is the left (lower) axis of a plot on the
        far side, not the right (upper) axis of b's plot."""
        labs = a.get("labels") or ()
        if not labs:
            return False
        k = 0 if a["orient"] == "y" else 1
        mid = sum((tx["bbox"][k] + tx["bbox"][k + 2]) / 2 for _, tx in labs) / len(labs)
        gap = _PAIR_SLACK_FRAC * (b["hi"] - b["lo"])
        if a["pos"] > b["hi"] + gap:
            return b["hi"] < mid < a["pos"]
        if a["pos"] < b["lo"] - gap:
            return a["pos"] < mid < b["lo"]
        return False

    def partner(a, others, gaps):
        """The index of the axis among `others` closest to forming a corner
        with `a`, or None.  gaps(a, b) = (gap along a, gap along b)."""
        cands = []
        for k, b in enumerate(others):
            along_a, along_b = gaps(a, b)
            if along_b <= tol(a, b) and not wrong_side(b, a) and (
                    along_a <= _PAIR_ALONG * (a["hi"] - a["lo"]) or borrows_axis(b, a, page=page)):
                cands.append(((along_a, along_b), k))
        return min(cands)[1] if cands else None

    # every x axis takes the y axis that comes closest to forming a corner
    # with it, and every y axis the closest x axis; each choice is a graph
    # (an axis shared by side-by-side panels takes part in several).  The
    # gap along the axis may be loose (a y axis set off from the end of the
    # x axis), but one more than half the axis long is another graph's
    # axis, used only if it shares this graph's scale (borrows_axis)
    pairs = set()
    for i, xa in enumerate(xs):
        j = partner(xa, ys, corner)
        if j is not None:
            pairs.add((i, j))
    for j, ya in enumerate(ys):
        i = partner(ya, xs, lambda a, b: corner(b, a)[::-1])
        if i is not None:
            pairs.add((i, j))
    stack_on_shared_x(xs, ys, pairs, page=page)
    row_on_shared_y(xs, ys, pairs)
    # axes that cross inside the plot (Excel's log axes crossing at 1, axes
    # through the origin): each line runs across the other one, well inside
    # its ends, with the crossing point inside both; only for axes that
    # found no corner
    used_x = {i for i, _ in pairs}
    used_y = {j for _, j in pairs}
    for i, xa in enumerate(xs):
        if i in used_x or not xa["has_line"]:
            continue
        best = None
        for j, ya in enumerate(ys):
            if j in used_y or not ya["has_line"]:
                continue
            wx, wy = xa["hi"] - xa["lo"], ya["hi"] - ya["lo"]
            if not (_PAIR_ASPECT_LO * wx <= wy <= _PAIR_ASPECT_HI * wx):
                continue
            ix = (ya["pos"] - xa["lo"]) / wx
            iy = (xa["pos"] - ya["lo"]) / wy
            if _INSET_LO < ix < _INSET_HI and _INSET_LO < iy < _INSET_HI:
                d = abs(ix - 0.5) + abs(iy - 0.5)
                if best is None or d < best[0]:
                    best = (d, j)
        if best:
            pairs.add((i, best[1]))
            used_y.add(best[1])
    graphs = []
    for i, j in pairs:
        xa, ya = xs[i], ys[j]
        x0 = ya["pos"] if _foot_of(xa, ya) else xa["lo"]
        graphs.append({"x": xa, "y": ya,
                       "rect": (x0, ya["lo"], xa["hi"], ya["hi"])})
    return order_graphs(merge_twin_axes(graphs))


_FOOT_FRAC = 0.5  # a y axis standing at the foot within half the x axis's length


def _foot_of(xa, ya):
    """An x axis of ticks only (no line) at the foot of a y axis (within
    2 pt), the y axis left of its first tick by at most half its length:
    ticks hanging from a frame whose bottom edge the axis builder did not
    take (2020.01.30.927558.full-048's heat map, ticked only at the
    experiments' borders, 100 ... 408).  The y axis has its line (the
    frame's edge): 978-3-031-36060-2_2-006's lineless right-hand y axes
    stand left of the next chart's x axis."""
    return not xa["has_line"] and ya["has_line"] and abs(xa["pos"] - ya["lo"]) <= 2.0 and \
        ya["pos"] < xa["lo"] and xa["lo"] - ya["pos"] <= _FOOT_FRAC * (xa["hi"] - xa["lo"])


_SAME_PLOT = 0.85  # graphs overlapping by 85% are one plot


def drop_same_plot_graphs(graphs):
    """Two graphs whose plot boxes overlap by 85% or more of each are one
    plot found twice (ArianeWuerbach-Phd-219: a trace plot's own axis, and
    the scale of the plot at the foot of its column borrowed along the
    shared iteration axis): the one whose axes carry more labels stays (on
    a tie, the first)."""
    def labels(g):
        return sum(g[k]["map"].get("n", 0) for k in ("x", "y"))
    out = []
    for g in sorted(graphs, key=lambda g: -labels(g)):
        a = rect_area(g["rect"])
        if a > 0 and any(overlap_area(g["rect"], o["rect"]) >= _SAME_PLOT * max(a, rect_area(o["rect"]))
                         for o in out):
            continue
        out.append(g)
    keep = {id(g) for g in out}
    return [g for g in graphs if id(g) in keep]


_ROW_GAP_FRAC = 0.25  # panels of a row within a quarter of the span


def row_on_shared_y(xs, ys, pairs):
    """A panel's x axis left without a graph, on the line of a graph's x
    axis (within 1 pt) and continuing it (beginning within 2 pt of where
    that one ends), takes that graph's y axis: a row of panels with the y
    scale drawn at the left only (2020.01.30.927558.full-023).  Repeated
    along the row.  Adds the pairs to `pairs`."""
    changed = True
    while changed:
        changed = False
        used_x = {i for i, _ in pairs}
        for i, xa in enumerate(xs):
            if i in used_x or not xa["has_line"]:
                continue
            for k, j in list(pairs):
                xb = xs[k]
                # (or beginning after a gap of at most a quarter of its own
                # length, the y axis of category rows: the "Average" bars of
                # 2020.01.30.927558.full-048 beside its heat map's rows)
                gap = xa["lo"] - xb["hi"]
                if abs(xb["pos"] - xa["pos"]) <= 1.0 and (abs(gap) <= 2.0 or (
                        ys[j]["map"]["kind"] == "nominal" and 0 < gap <= _ROW_GAP_FRAC * (xa["hi"] - xa["lo"]))):
                    pairs.add((i, j))
                    changed = True
                    break


_SHARED_X_TOL_FRAC = 0.01  # a shared x axis lines up within 1%
_STACK_GAP_FRAC = 0.5      # panels stacked within half the span


def stack_on_shared_x(xs, ys, pairs, *, page):
    """Stacked panels each with a labelled y axis line of its own but one x
    axis, under the bottom panel only, and no x axis line in the others
    (plot d of song2025rigorous-002): a y axis left without a graph, on
    the line of a graph's y axis (the same x) and just above or below it
    (a gap under half its length), takes that graph's x axis, if the x
    axis reaches the y axis and the panel has no x axis line or frame of
    its own (_own_x_line).  Adds the pairs to `pairs`."""
    used_y = {j for _, j in pairs}
    for j, ya in enumerate(ys):
        if j in used_y or not ya["has_line"] or not ya.get("labels"):
            continue
        span = ya["hi"] - ya["lo"]
        best = None
        for i, k in pairs:
            yb, xa = ys[k], xs[i]
            if abs(yb["pos"] - ya["pos"]) > max(1.0, _SHARED_X_TOL_FRAC * span) or \
                    not xa["lo"] - 1 <= ya["pos"] <= xa["hi"] + 1:
                continue
            gap = max(yb["lo"] - ya["hi"], ya["lo"] - yb["hi"])
            if 0 <= gap <= _STACK_GAP_FRAC * span and (best is None or gap < best[0]):
                best = (gap, i)
        if best and not _own_x_line(xs[best[1]], ya, page=page):
            pairs.add((best[1], j))


_OWN_LINE_FRAC = 0.05  # a graph's own x line within 5% of its height
_OWN_LINE_COVER = 0.5  # covering half its length


def _own_x_line(xa, ya, *, page):
    """Does a horizontal line (of any shade) lie at an end of y axis `ya`,
    over half as long as x axis `xa` and across from it?  Then the panel
    has an x axis (or frame) of its own and borrows no other - unless the
    line is a copy of the shared axis's, its ends those of the line the
    shared x axis lies on (within 2 pt) (2020.01.30.927558.full-012: each
    upper panel has the bottom panel's x axis line again, unlabelled; a
    panel whose y axis already has a graph borrows nothing anyway)."""
    tol = _OWN_LINE_FRAC * (ya["hi"] - ya["lo"])
    need = _OWN_LINE_COVER * (xa["hi"] - xa["lo"])
    for lo, hi, pp in list(page.dark_lines[0]) + list(page.all_lines[0]):
        if min(hi, xa["hi"]) - max(lo, xa["lo"]) >= need and \
                min(abs(pp - ya["lo"]), abs(pp - ya["hi"])) <= tol and not _copy_of_axis_line(lo, hi, pp, xa, page=page):
            return True
    return False


_COPY_MIN_TICKS = 3  # a copied axis line has a row of 3 ticks or more
_COPY_AGREE = 0.8    # 80% of them agreeing


def _copy_of_axis_line(lo, hi, pp, xa, *, page):
    """Is the horizontal line lo...hi at height pp a copy of the line under
    x axis xa - the same ends (within 2 pt) as a line at xa's own place,
    and either no tick row (of three or more) on it or one ticked at xa's
    ticks (80% of its ticks within 1 pt of them, three or more: -012's
    0.7 pt ticks)?  Then it
    is the shared axis drawn again for the upper panel, unlabelled.  A
    line ticked elsewhere is a scale of its own (mpl-shared-axes: a panel
    with other unlabelled ticks takes no scale)."""
    ticks = list(xa.get("tick_pos") or ())
    # (rows of three ticks or more: the frame's two corners are no row)
    rows = [b.get("tick_pos") or () for b in page.bare_axes
            if b["orient"] == "x" and abs(b["pos"] - pp) <= 1.0 and len(b.get("tick_pos") or ()) >= _COPY_MIN_TICKS]

    def agrees(row):
        n = sum(1 for t in row if any(abs(t - u) <= 1.0 for u in ticks))
        return n >= _COPY_MIN_TICKS and n >= _COPY_AGREE * len(row)
    if rows and not any(agrees(r) for r in rows):
        return False
    return any(abs(l2 - lo) <= 2.0 and abs(h2 - hi) <= 2.0 and abs(p2 - xa["pos"]) <= 2.0
               for l2, h2, p2 in list(page.dark_lines[0]) + list(page.all_lines[0]))


_TWIN_TOL_FRAC = 0.02  # twin axes line up within 2% of the span
_TWIN_APART = 0.8      # on opposite sides: 80% of the span apart


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
                tol = max(1.0, _TWIN_TOL_FRAC * span)
                ends = (g[shared]["lo"], g[shared]["hi"])
                # (the far ends may differ when both axes start on the shared
                # axis line: R draws each axis() only as far as its last
                # tick - Seongmin-PhD-036's 0 ... 2000 left, 0 ... 25000
                # right, 22 pt higher)
                base = g[shared]["pos"]
                if h[shared] is g[shared] and a is not b and \
                        abs(a["lo"] - b["lo"]) <= tol and (
                            abs(a["hi"] - b["hi"]) <= tol or
                            abs(a["lo"] - base) <= tol and abs(b["lo"] - base) <= tol) and \
                        abs(a["pos"] - b["pos"]) > _TWIN_APART * span and \
                        all(min(abs(ax["pos"] - e) for e in ends) <= tol for ax in (a, b)) and \
                        other + "2" not in g and other + "2" not in h:
                    first, second = (a, b) if a["pos"] < b["pos"] else (b, a)
                    if _mirrored(first, second):
                        # the same scale drawn on both sides: one graph
                        if g[other] is second:
                            g[other] = first
                        del out[j]
                        continue
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


_AGREE_FRAC = 1e-3  # values agree within 0.1%


def _agree(ma, mb, p, tol):
    """Do two value mappings agree at position p, to within what tol points
    of position mean there?  (w21074-042's right labels stand 0.2 pt above
    the left ones.)"""
    va, vb = map_value(ma, p), map_value(mb, p)
    if va is None or vb is None:
        return False
    vt = map_value(ma, p + tol)
    slack = abs(vt - va) if vt is not None else 0.0
    return abs(va - vb) <= max(slack, _AGREE_FRAC * max(abs(va), abs(vb), 1e-12))


def _same_values(a, b, tol=0.5):
    """Do two numeric scales give the same values at the labelled ticks of
    each (two or more labels on each side)?"""
    ma, mb = a.get("map"), b.get("map")
    if not ma or not mb or "nominal" in (ma["kind"], mb["kind"]):
        return False
    pts = list(a.get("ticks", ())) + list(b.get("ticks", ()))
    if len(a.get("ticks", ())) < 2 or len(b.get("ticks", ())) < 2:
        return False
    return all(_agree(ma, mb, p, tol) for p, _ in pts)


_MIRROR_MIN = 3           # a mirrored axis has 3 ticks or more
_MIRROR_TOL_PT = 0.5      # mirrored ticks agree within 0.5 pt
_MIRROR_TOL_FRAC = 0.005  # or 0.5% of the span
_MIRROR_FRAC = 0.9        # 90% of them


def _mirrored(a, b):
    """Whether axis b, opposite axis a, repeats a's scale: the same series of
    tick marks (one set within the other, as one side may lack the minor
    ticks), and labels that do not say otherwise.  The user asked for such
    ticks to be treated as one scale unless the labels differ: labels that
    give other values at those ticks make b a second scale; labels that are
    words opposite numbers (body text beside the plot) do not.

    A side with fewer than three tick marks (w21074-042, Excel: the right
    side has none, only the frame's corners, labelled 0% and 100%, its
    other labels beside the left side's gridlines) repeats the scale when
    two or more numeric labels give the same values as the other side at
    the same places."""
    ta, tb = a.get("tick_pos") or [], b.get("tick_pos") or []
    small, big = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    if len(small) < _MIRROR_MIN:
        return _same_values(a, b)
    tol = max(_MIRROR_TOL_PT, _MIRROR_TOL_FRAC * (max(big) - min(big) if big else 0))
    # (a tick at an end of the axis may be lost in the frame's corner)
    big = [*list(big), a["lo"], a["hi"], b["lo"], b["hi"]]
    if sum(1 for p in small if any(abs(p - q) <= tol for q in big)) < _MIRROR_FRAC * len(small):
        return False
    ma, mb = a.get("map"), b.get("map")
    if not ma or not mb:
        return True
    if (ma["kind"] == "nominal") != (mb["kind"] == "nominal"):
        return True                      # words opposite numbers: not a scale
    if mb["kind"] == "nominal":
        return [v for _, v in ma["ticks"]] == [v for _, v in mb["ticks"]]
    # (other values: a second scale)
    return all(_agree(ma, mb, p, tol) for p, _ in b.get("ticks", ()))


_DARK_SUM = 1.5  # a dark line: channels sum under 1.5


def dark_frame_lines(paths):
    """Merged dark horizontal and vertical stroked lines (frames, borders)."""
    hs, vs = [], []
    for p in paths:
        if not p["stroke"] or sum(p["stroke_rgb"] or (0, 0, 0)) >= _DARK_SUM:
            continue
        for a, b in straight_segments(p):
            aa = axis_aligned(a, b)
            if aa:
                (hs if aa[0] == "h" else vs).append(aa[1:])
    return merge_collinear(hs), merge_collinear(vs)


_PANELS_MIN = 4        # a lattice has 4 panels or more
_PANEL_COVER_PT = 0.6  # a panel side covered by a line within 0.6 pt
_PANEL_OVERLAP = 0.5   # a panel over half covered by a graph is no new graph


def add_panel_graphs(graphs, axes, paths, *, page):
    """Small multiples (lattice / facet plots): only the outer panels carry
    labelled axes; every panel shares the x scale of its column and the y
    scale of its row.  Each framed rectangle spanned by a column's x axis
    and a row's y axis is a graph."""
    xs = [a for a in axes if a["orient"] == "x" and a["has_line"]]
    ys = [a for a in axes if a["orient"] == "y" and a["has_line"]]
    if len(xs) * len(ys) < _PANELS_MIN:
        return graphs
    hl, vl = dark_frame_lines(paths)

    def covered(lines, pos, lo, hi, tol=_PANEL_COVER_PT):
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
                    covered(vl, r[0], r[1], r[3]) and covered(vl, r[2], r[1], r[3])) or \
                    (_open_panel(r, ya, hl, vl, page=page) and not any(
                        overlap_area(r, h) > _PANEL_OVERLAP * min(rect_area(r), rect_area(h)) for h in have)):
                out.append({"x": xa, "y": ya, "rect": r})
                have.append(r)
    return order_graphs(out) if len(out) > len(graphs) else graphs


def _open_panel(r, ya, hl, vl, *, page):
    """A panel of open axes in a lattice: a line along its foot and one up
    its left side (within 2 pt of the column's and row's ends), the left
    one ticked at two or more of the row's y ticks (an unlabelled tick row
    there, within 1 pt) - 2020.01.30.927558.full-012's upper right panel,
    its x scale that of the panel below, its y scale that of the panel to
    its left, both axes drawn again without labels.  (The caller refuses a
    rectangle over half covered by a graph: a twin-scale plot's right axis
    paired with its own x axis, PhysRevResearch.3.033169-009.)"""
    x0, y0, x1, y1 = r
    foot = any(abs(pp - y0) <= 2.0 and l0 <= x0 + 2.0 and l1 >= x1 - 2.0 for l0, l1, pp in hl)
    side = [pp for l0, l1, pp in vl if abs(pp - x0) <= 2.0 and l0 <= y0 + 2.0 and l1 >= y1 - 2.0]
    if not foot or not side:
        return False
    ticks = list(ya.get("tick_pos") or ())
    return any(b["orient"] == "y" and any(abs(b["pos"] - pp) <= 1.0 for pp in side) and
               sum(1 for t in b.get("tick_pos") or () if any(abs(t - u) <= 1.0 for u in ticks)) >= 2
               for b in page.bare_axes)


_ORDER_OVERLAP = 0.5  # graphs of one row overlap by half their height


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
            if ov > _ORDER_OVERLAP * min(h0, h):
                row.append(g)
        rest = [g for g in rest if not any(g is r for r in row)]
        out += sorted(row, key=lambda g: g["rect"][0])
    return out


_UPRIGHT_DEG = 10  # text within 10 degrees of level is not rotated


def frame_texts(texts, rot):
    """Copies of the text items expressed in a turned graph's frame."""
    if not rot:
        return texts
    out = []
    for t in texts:
        u = dict(t)
        u["bbox"] = frame_rect(t["bbox"], rot)
        u["center"] = ((u["bbox"][0] + u["bbox"][2]) / 2, (u["bbox"][1] + u["bbox"][3]) / 2)
        u["p0"], u["p1"] = to_frame(t["p0"], rot), to_frame(t["p1"], rot)
        u["up"] = to_frame(t["up"], rot)
        ang = (t.get("angle", 0.0) - rot + 180) % 360 - 180
        u["angle"] = ang
        u["rotated"] = not (abs(ang) < _UPRIGHT_DEG or abs(abs(ang) - 180) < _UPRIGHT_DEG)
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


_ROTATION_MARGIN = 1.05  # turned labels must outnumber upright ones by 5%


def graph_rotation(g, texts, symbols, *, page):
    """0, or the angle by which the whole graph is turned.  A graph is turned
    when the tick labels of both axes read in the same non-horizontal
    direction (or the page-y axis's at r and the page-x axis's, not
    horizontal, at r + 90: labels along a turned y axis) and the title found in the turned frame is at least as large
    as any title found in the page frame (a turned graph's former y-axis
    title reads horizontally, so a horizontal heading alone proves nothing)."""
    ax, ay = g["x"].get("label_angle"), g["y"].get("label_angle")
    if ax is not None and ay is not None and ax == ay and ax != 0:
        rot = ax
    elif ax is not None and ay is not None and ax != 0 and ay != 0 and (ax - ay) % 360 == 90:
        # R's default labels (las = 0) turned with the graph: the x labels
        # read across the turned frame, the y labels along their axis, a
        # quarter turn further (ArianeWuerbach-Phd-219's trace plots, turned
        # 90 degrees on the page: iteration labels at 90, the values at 180)
        rot = ay
    else:
        return 0, find_title(g["rect"], texts, symbols, page=page)
    t_rot = find_title(frame_rect(g["rect"], rot), frame_texts(texts, rot),
                       frame_symbols(symbols, rot), with_size=True, page=page)
    t_0 = find_title(g["rect"], texts, symbols, with_size=True, page=page)
    if t_0[0] and (not t_rot[0] or t_0[1] > t_rot[1] * _ROTATION_MARGIN):
        return 0, t_0[0]
    return rot, t_rot[0]


_BG_MAX_SEGS = 5      # a background box has at most 5 segments
_BG_CORNER_PT = 0.1   # its corners within 0.1 pt of its box
_BG_OUTSIDE_PT = 0.5  # it holds the plot within 0.5 pt
_BG_MAX_AREA = 4      # and is at most 4 times its area
_PAPER_WIDTH = 1.6    # paper at most 1.6 times the plot's width
_BG_TOL_PT = 1.5      # a plot background matches its box within 1.5 pt
_BG_TOL_FRAC = 0.01   # or 1% of its size


def set_graph_backgrounds(graphs, paths, *, page):
    """Drawing step at which each graph's own opaque background box was
    painted (an inset is painted over its parent graph), or -1."""
    boxes = []                       # (box, drawing step) of filled single shapes
    rects = []                       # boxes of single rectangles, filled or stroked
    papers = []                      # boxes of opaque filled single rectangles
    for p in paths:
        if len(p["subpaths"]) != 1:
            continue
        sp = p["subpaths"][0]
        if len(sp["segs"]) < 3:
            continue
        pts = vertices(sp)
        b = bbox_of(pts)
        if p["fill"]:
            boxes.append((b, p["idx"]))
        if all(s[0] == "l" for s in sp["segs"]) and len(sp["segs"]) <= _BG_MAX_SEGS and all(
                min(abs(x - b[0]), abs(x - b[2])) < _BG_CORNER_PT and min(abs(y - b[1]), abs(y - b[3])) < _BG_CORNER_PT
                for x, y in pts):
            rects.append(b)
            if p["fill"] and p.get("opaque", True):
                papers.append(b)
    # the paper a chart is drawn on (plotly: an opaque rectangle round the
    # plot, its labels and its legend): the smallest such rectangle holding
    # the plot box (within 0.5 pt), no other graph's plot, and no more
    # than four times the plot's area.  Legend keys outside every plot go
    # to the graph whose paper they are on (economies-open-intelligence-
    # 005: the developer legend under the upper chart is nearer the lower
    # plot, on the upper chart's paper)
    for g in graphs:
        x0, y0, x1, y1 = g["rect"]
        best = None
        for b in papers:
            if min(x0 - b[0], y0 - b[1], b[2] - x1, b[3] - y1) >= -_BG_OUTSIDE_PT and \
                    rect_area(b) <= _BG_MAX_AREA * rect_area(g["rect"]) and not any(
                        o is not g and b[0] <= (o["rect"][0] + o["rect"][2]) / 2 <= b[2] and
                        b[1] <= (o["rect"][1] + o["rect"][3]) / 2 <= b[3] for o in graphs) and (
                    best is None or rect_area(b) < rect_area(best)):
                best = b
        g["paper"] = best
    # the box round a whole chart (Excel's chart area): the smallest
    # rectangle holding the plot box with room for its labels, not much
    # bigger; text outside it is not the chart's title
    for g in graphs:
        x0, y0, x1, y1 = g["rect"]
        w, h = x1 - x0, y1 - y0
        best = None
        for b in rects:
            m = min(x0 - b[0], y0 - b[1], b[2] - x1, b[3] - y1)
            if m >= 2.0 and b[2] - b[0] <= _PAPER_WIDTH * w and b[3] - b[1] <= 2.0 * h and (
                    best is None or rect_area(b) < rect_area(best)):
                best = b
        if best:
            page.chart_frames[tuple(g["rect"])] = best
    for g in graphs:
        g["bg"] = -1
        x0, y0, x1, y1 = g["rect"]
        tol = max(_BG_TOL_PT, _BG_TOL_FRAC * max(x1 - x0, y1 - y0))
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


_CLIP_COVER = 0.9  # a clip holding a graph covers 90% of it
_CLIP_MAX = 1.5    # and is at most 1.5 times its area


def _clip_graph(graphs, c):
    """The graph whose box lies (at least 90%) inside clipping box c, c
    being at most 1.5 times its area (the smallest such c's graph), or
    None: plots clip their markers to the plot box or a little beyond it."""
    best = None
    carea = max(0.0, c[2] - c[0]) * max(0.0, c[3] - c[1])
    for g in graphs:
        area = max(rect_area(g["rect"]), 1e-9)
        ov = overlap_area(g["rect"], c)
        if ov >= _CLIP_COVER * area and carea <= _CLIP_MAX * area and (best is None or carea < best[0]):
            best = (carea, g)
    return best[1] if best else None


def _graphs_at(graphs, x, y):
    """The graphs whose box contains (x, y) (edges included), in list
    order.  The boxes are filed in a grid once per list of graphs (pages of
    small multiples have hundreds of panels and thousands of points)."""
    cache = _cache_for(graphs)
    if cache["at"] is None:
        cell = max(median((max(g["rect"][2] - g["rect"][0], g["rect"][3] - g["rect"][1])
                           for g in graphs), 1.0), 1.0)
        grid = {}
        for k, g in enumerate(graphs):
            x0, y0, x1, y1 = g["rect"]
            for gx in range(math.floor(x0 / cell), math.floor(x1 / cell) + 1):
                for gy in range(math.floor(y0 / cell), math.floor(y1 / cell) + 1):
                    grid.setdefault((gx, gy), []).append(k)
        cache["at"] = (cell, grid)
    cell, grid = cache["at"]
    ks = grid.get((math.floor(x / cell), math.floor(y / cell)), ())
    return [graphs[k] for k in ks if rect_distance(graphs[k]["rect"], x, y) == 0]


def nearest_to_frame(graphs, frame):
    """The graph nearest a legend frame (as a whole)."""
    return min(graphs, key=lambda g: rects_gap(g["rect"], frame))


def graph_for_symbol(graphs, s):
    """The graph a symbol belongs to: the graph it was clipped to; else,
    among the graphs whose box contains it, the innermost one painted before
    the symbol; else, for a key in a legend frame outside all graphs, the
    graph nearest the frame (see strays.mark_legend_frames); otherwise the
    nearest graph.  Returns (distance, graph)."""
    g = clip_graph(graphs, s)
    if g is not None:
        return rect_distance(g["rect"], s["cx"], s["cy"]), g
    inside = _graphs_at(graphs, s["cx"], s["cy"])
    if inside:
        before = [g for g in inside if g.get("bg", -1) < s["idx"]] or inside
        g = max(before, key=lambda g: (g.get("bg", -1), -rect_area(g["rect"])))
        return 0.0, g
    if s.get("frame"):
        g = nearest_to_frame(graphs, s["frame"])
        return rect_distance(g["rect"], s["cx"], s["cy"]), g
    # (on one chart's paper: that chart's - set_graph_backgrounds)
    on = [g for g in graphs if g.get("paper") and g["paper"][0] <= s["cx"] <= g["paper"][2] and
          g["paper"][1] <= s["cy"] <= g["paper"][3]]
    if len(on) == 1:
        return rect_distance(on[0]["rect"], s["cx"], s["cy"]), on[0]
    return min(((rect_distance(g["rect"], s["cx"], s["cy"]), g) for g in graphs),
               key=lambda dg: dg[0])

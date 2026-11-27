"""Error bars (option --errbars).

An error bar is a straight line through a marker's centre, along one of the
page axes, reaching beyond the marker; programs draw it as one segment from
the low to the high end (matplotlib), or as two halves that start at the
marker's centre (Excel), usually with a short cap across each end (the caps
are not needed).  Vertical bars give the y range of a point, horizontal ones
the x range (in a graph turned by 90 degrees the other way round).

For each marker the straight (nearly) axis-aligned segments of open stroked paths
(and strokes converted to thin filled rectangles) that lie on its centre
line are gathered; pieces that continue each other end to end are chained
(the two halves of a bar), but overlapping ones are not (they are the bars
of different points at the same x).  The chain that touches the marker is
its bar.  Chains that span nearly the whole plot (grid lines, axes, frame)
and pieces wholly outside the plot box (tick marks) are not bars; neither is
a chain that does not reach beyond the marker (the stroke of a '+').  When
several markers touch one chain, it belongs to the marker at which a piece
of it starts or ends (Excel's halves), else to the one nearest its middle.

A bar (symbol 'bar') is measured as a marker of 1 pt at the middle of its
end, its error bar along it only.

The vertices of lines without markers (symbol 'line') have no size to
measure a bar against, so their vertical bars must be capped: a short
horizontal stroke centred on each end (_vertex_bars).
"""

import bisect
import math

from .geometry import thin_rect_line

_BUCKET = 0.5                     # pt: bucket size of the segment index


def _nearly_aligned(a, b):
    """('h' | 'v', lo, hi, pos) for a segment within 0.3 pt (or a tenth of its
    length) of horizontal or vertical, else None.  Excel rounds coordinates
    to a grid, so its bars lean slightly: (433.14, 303.6) - (433.38, 306.96)."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    if abs(dx) <= max(0.3, 0.1 * abs(dy)) and abs(dy) > abs(dx):
        return "v", min(a[1], b[1]), max(a[1], b[1]), (a[0] + b[0]) / 2
    if abs(dy) <= max(0.3, 0.1 * abs(dx)) and abs(dx) > abs(dy):
        return "h", min(a[0], b[0]), max(a[0], b[0]), (a[1] + b[1]) / 2
    return None


def _segments(paths):
    """Axis-aligned straight segments that may be error bars:
    {"h": [(lo, hi, pos)], "v": [...]} (pos = the y of a horizontal segment,
    the x of a vertical one)."""
    out = {"h": [], "v": []}
    for p in paths:
        if p["stroke"]:
            for sp in p["subpaths"]:
                if sp["closed"]:
                    continue                      # marker outlines, boxes
                a = sp["start"]
                for seg in sp["segs"]:
                    b = seg[-1]
                    if seg[0] == "l":
                        aa = _nearly_aligned(a, b)
                        if aa:
                            out[aa[0]].append(aa[1:])
                    a = b
        elif p["fill"] and len(p["subpaths"]) == 1:
            ln = thin_rect_line(p["subpaths"][0])     # a stroke converted to an outline
            if ln is not None:
                aa = _nearly_aligned(*ln)
                if aa:
                    out[aa[0]].append(aa[1:])
    return out


def _index(segs):
    """Segments filed by their position across (buckets of _BUCKET pt): a
    page may hold tens of thousands of strokes and markers."""
    idx = {}
    for lo, hi, pos in segs:
        idx.setdefault(math.floor(pos / _BUCKET), []).append((lo, hi, pos))
    return idx


def _chains(pieces, join):
    """Chain pieces (lo, hi) that continue each other end to end (within
    `join`); overlapping pieces start a separate chain.  Returns
    [(lo, hi, knots)] where knots are the pieces' end points."""
    chains = []
    for lo, hi in sorted(pieces):
        for c in chains:
            if abs(lo - c[1]) <= join and hi > c[1]:
                c[1] = hi
                c[2].extend((lo, hi))
                break
            if abs(hi - c[0]) <= join and lo < c[0]:
                c[0] = lo
                c[2].extend((lo, hi))
                break
            if abs(lo - c[0]) <= join and abs(hi - c[1]) <= join:
                break                             # the same piece drawn twice
        else:
            chains.append([lo, hi, [lo, hi]])
    return [tuple(c) for c in chains]


# a lone bar's caps may be long: a strip chart of two groups is narrow
# (BehavioralNetworkScience-121's caps are 15% of the plot's width)
_LONE_CAP_FRAC = 0.3


def lone_capped_bars(graphs, symbols, paths, graph_of):
    """Capped error bars standing alone, with no marker on them: a group's
    mean and its error bar drawn as a capped vertical bar - an "H" on its
    side - among the jittered points of an R strip chart
    (BehavioralNetworkScience-121: the mean +/- standard error of each
    group).  A vertical stroke inside a graph, 0.5 pt long or more and
    shorter than 90% of the plot, with a cap (a horizontal stroke 0.5 pt
    to 30% of the plot's width long) centred on each end, the two caps no
    more than twice each other's length; no marker, line vertex or bar top
    (a quarter of the caps' length or bigger, or of any size at its middle
    when alone on it) lies on it (those bars are their points',
    find_error_bars); the stroke is not also filled (2401.16279-023's
    arrows); and the
    graph has no box plot (a whisker meeting a box's edge looks alike).
    Each is a point at its middle, symbol "errorbar", in the stroke's
    colour, its ends kept for --errbars.  Returns the new symbols."""
    segs = _segments(paths)
    index = _index(segs["h"])
    hidx = {"h": index}
    boxed = {id(graph_of(s)) for s in symbols if s["shape"].startswith("box-")}
    # (the symbols sorted across, so that a stroke looks only at those that
    # may stand on it: every stroke against every symbol took minutes on
    # ESEUR-slowpages' plots of thousands of points)
    marks = sorted(((s["cx"], k, s) for k, s in enumerate(symbols) if not s["shape"].startswith("box-")),
                   key=lambda m: (m[0], m[1]))
    xs = [m[0] for m in marks]
    reach = max([0.3] + [0.15 * m[2]["size"] for m in marks])
    out, seen = [], set()
    for p in paths:
        if not p["stroke"] or p["fill"]:
            continue                      # (filled and stroked: 2401.16279-023's arrows)
        for sp in p["subpaths"]:
            if sp["closed"] or len(sp["segs"]) != 1 or sp["segs"][0][0] != "l":
                continue
            aa = _nearly_aligned(sp["start"], sp["segs"][0][-1])
            if not aa or aa[0] != "v":
                continue
            _, lo, hi, x = aa
            key = (round(x, 2), round(lo, 2), round(hi, 2))
            if key in seen:
                continue
            seen.add(key)
            probe = {"cx": x, "cy": (lo + hi) / 2, "size": 0.0, "shape": "errorbar", "idx": p["idx"]}
            g = graph_of(probe)
            if g is None or id(g) in boxed:
                continue
            gx0, gy0, gx1, gy1 = g["rect"]
            if not (gx0 <= x <= gx1) or hi - lo < 0.5 or hi - lo >= 0.9 * (gy1 - gy0):
                continue
            c_lo, c_hi = (_cap(hidx, x, e, gx1 - gx0, _LONE_CAP_FRAC) for e in (lo, hi))
            if c_lo is None or c_hi is None or max(c_lo, c_hi) > 2 * min(c_lo, c_hi):
                continue
            # (a marker owning the bar is not much smaller than its caps, or
            # sits at its middle: 120875-008's 2.5 pt dots with 10.2 pt caps;
            # jittered dots, a seventh of the caps' length, fall on it by
            # chance and off its middle)
            cap, mid = max(c_lo, c_hi), (lo + hi) / 2
            near = marks[bisect.bisect_left(xs, x - reach):bisect.bisect_right(xs, x + reach)]
            on = [s for _, _, s in near if abs(s["cx"] - x) <= max(0.3, 0.15 * s["size"]) and
                  lo - 0.5 * s["size"] <= s["cy"] <= hi + 0.5 * s["size"]]
            if any(s["size"] >= 0.25 * cap or s["shape"] in ("line", "bar", "stem") or
                   (len(on) == 1 and abs(s["cy"] - mid) <= max(0.3, 0.15 * s["size"]))
                   for s in on):
                continue                          # a marker's (or vertex's, bar's) error bar
            out.append({"shape": "errorbar", "cx": x, "cy": (lo + hi) / 2,
                        "size": max(c_lo, c_hi), "filled": False,
                        "rgb": p.get("stroke_rgb") or (0.0, 0.0, 0.0), "idx": p["idx"],
                        "clip": p.get("clip"), "vbar": (lo, hi)})
    return out


def find_error_bars(symbols, paths, graph_of):
    """{symbol index: {"v": (low, high) | None, "h": (low, high) | None}} in
    page coordinates, for the markers that have error bars.  `graph_of(s)`
    gives a symbol's graph.  A side without a bar ends at the marker's
    centre."""
    segs = _segments(paths)
    index = {k: _index(v) for k, v in segs.items()}
    claims = {}                    # (direction, chain) -> [(score, symbol index, ends)]
    out = {}
    for si, s in enumerate(symbols):
        if s["shape"] == "errorbar":
            out[si] = {"v": s["vbar"], "h": None}     # a lone capped bar: its own ends
            continue
        if s["shape"] in ("line", "stem") or s["shape"].startswith("box-"):
            continue
        g = graph_of(s)
        if g is None:
            continue
        x0, y0, x1, y1 = g["rect"]
        # (a bar's error bar crosses the middle of its end, along the bar:
        # 2020.01.30.927558.full-023's bars hanging from 0, -026's
        # horizontal bars; measured as a marker of 1 pt there)
        is_bar = s["shape"] == "bar"
        size = 1.0 if is_bar else max(s["size"], 0.5)
        tol = max(0.15 * size, 0.3)
        dirs = (("v", s["cx"], s["cy"], y1 - y0), ("h", s["cy"], s["cx"], x1 - x0))
        if is_bar:
            dirs = dirs[1:] if s.get("horizontal") else dirs[:1]
        # k: the bar's direction; centre: the marker's position across the
        # bar, along: its position along it; span: the plot's extent that way
        for k, centre, along, span in dirs:
            pieces = []
            for b in range(math.floor((centre - tol) / _BUCKET),
                           math.floor((centre + tol) / _BUCKET) + 1):
                for lo, hi, pos in index[k].get(b, ()):
                    if abs(pos - centre) > tol:
                        continue
                    # wholly outside the plot box: a tick mark, not a bar
                    if k == "v" and (hi < y0 - 0.5 or lo > y1 + 0.5):
                        continue
                    if k == "h" and (hi < x0 - 0.5 or lo > x1 + 0.5):
                        continue
                    pieces.append((lo, hi))
            if not pieces:
                continue
            for lo, hi, knots in _chains(pieces, join=max(0.3, 0.1 * size)):
                if hi - lo >= 0.9 * span:
                    continue                      # grid line, axis, frame
                if lo > along + 0.6 * size or hi < along - 0.6 * size:
                    continue                      # does not touch the marker
                reach = 0.55 * size
                low = lo if lo < along - reach else None
                high = hi if hi > along + reach else None
                if low is None and high is None:
                    continue                      # inside the marker ('+' stroke)
                # who owns the chain: a piece starting or ending at the
                # marker's centre (Excel's halves), else the marker nearest
                # its middle (a bar drawn in one piece)
                score = min(*(abs(q - along) for q in knots[1:-1] or [math.inf]), abs((lo + hi) / 2 - along))
                key = (k, round(centre / tol), round(lo, 2), round(hi, 2))
                claims.setdefault(key, []).append((score, si, (low, high)))
    taken = set()                  # (x, low, high) of the markers' vertical bars
    for (k, *_), cands in claims.items():
        score, si, ends = min(cands)
        bars = out.setdefault(si, {"v": None, "h": None})
        if bars[k] is None:
            bars[k] = ends
            if k == "v":
                taken.add((symbols[si]["cx"], *ends))
    for si, ends in _vertex_bars(symbols, graph_of, index, taken).items():
        out.setdefault(si, {"v": None, "h": None})["v"] = ends
    return out


# a cap is at most this fraction of the plot's width long
_CAP_FRAC = 0.06
_TOL = 0.3                         # pt


def _cap(index, x, y, width, frac=_CAP_FRAC):
    """Length of the short horizontal stroke centred on (x, y) - an error
    bar's cap, at most `frac` of the plot's `width` - or None."""
    # (each bucket's strokes sorted by their middles, made on first use, so
    # that only those that may be centred on x are tried: a bucket holds
    # thousands of strokes on ESEUR-slowpages' dense plots)
    mids = index.get("h_mid")
    if mids is None:
        mids = index["h_mid"] = {}
        for b, segs in index["h"].items():
            segs = sorted(segs, key=lambda q: (q[0] + q[1]) / 2)
            mids[b] = ([(lo + hi) / 2 for lo, hi, _ in segs], segs)
    reach = max(_TOL, 0.1 * frac * width)
    best = None
    for b in range(math.floor((y - _TOL) / _BUCKET), math.floor((y + _TOL) / _BUCKET) + 1):
        ms, segs = mids.get(b, ((), ()))
        for lo, hi, pos in segs[bisect.bisect_left(ms, x - reach - 1e-9):bisect.bisect_right(ms, x + reach + 1e-9)]:
            n = hi - lo
            if (abs(pos - y) <= _TOL and abs((lo + hi) / 2 - x) <= max(_TOL, 0.1 * n)
                    and 0.5 <= n <= frac * width):
                best = n if best is None else max(best, n)
    return best


def _capped_runs(pieces, cx, cy, index, width, height):
    """(lo, hi) of the capped error bars through a vertex at (cx, cy) made
    of `pieces` (vertical (lo, hi) at its x).  Pieces that continue each
    other end to end are chained as for markers, but a bar is any run of
    consecutive pieces of a chain with a cap at both ends, the longest
    first: a drop line from the axis that ends where a bar's lower cap is
    continues the bar end to end (mpl-line-errorbars), and the chain as a
    whole has no cap at its foot."""
    pieces = sorted(set(pieces))
    chains = []                            # [[(lo, hi), ...]] end to end
    for p in pieces:
        for c in chains:
            if abs(p[0] - c[-1][1]) <= _TOL and p[1] > c[-1][1]:
                c.append(p)
                break
        else:
            chains.append([p])
    out = []
    for c in chains:
        runs = sorted(((c[i][0], c[j][1]) for i in range(len(c)) for j in range(i, len(c))),
                      key=lambda r: r[0] - r[1])
        for lo, hi in runs:
            if not (lo - _TOL <= cy <= hi + _TOL) or hi - lo < 0.5 or hi - lo >= 0.9 * height:
                continue
            c_lo, c_hi = _cap(index, cx, lo, width), _cap(index, cx, hi, width)
            if c_lo is None or c_hi is None or max(c_lo, c_hi) > 2 * min(c_lo, c_hi):
                continue
            out.append((lo, hi))
            break
    return out


def _vertex_bars(symbols, graph_of, index, taken):
    """{symbol index: (low, high)}: vertical error bars at the vertices of
    line charts, which have no marker to measure a bar against.  The bars
    of 2204.07073-010's polarisation lines (graphs 2 and 3) are a vertical
    stroke through each vertex with a short horizontal cap centred on each
    end.  Without a marker, a vertical stroke at a vertex could also be a
    step of a step chart or a drop line, so the caps are required: a run
    of vertical pieces end to end (_capped_runs) within 0.3 pt of the
    vertex's x, reaching it and longer than 0.5 pt, shorter than 90% of the
    plot's height, with a horizontal stroke centred on each end, 0.5 pt to
    6% of the plot's width long, the two caps no more than twice each
    other's length.  A bar already given to a marker at that x is not
    taken again; of several vertices on one bar (lines crossing at an x)
    it goes to the one nearest its middle.  A side that ends at the vertex
    has no bar on that side."""
    claims = {}                    # chain -> [(distance to middle, symbol index, ends)]
    for si, s in enumerate(symbols):
        if s["shape"] != "line":
            continue
        g = graph_of(s)
        if g is None:
            continue
        x0, y0, x1, y1 = g["rect"]
        cx, cy = s["cx"], s["cy"]
        pieces = []
        for b in range(math.floor((cx - _TOL) / _BUCKET), math.floor((cx + _TOL) / _BUCKET) + 1):
            for lo, hi, pos in index["v"].get(b, ()):
                if abs(pos - cx) <= _TOL and hi >= y0 - 0.5 and lo <= y1 + 0.5:
                    pieces.append((lo, hi))
        for lo, hi in _capped_runs(pieces, cx, cy, index, x1 - x0, y1 - y0):
            if any(abs(tx - cx) <= _TOL and abs((tl if tl is not None else cy) - lo) <= _TOL
                   and abs((th if th is not None else cy) - hi) <= _TOL for tx, tl, th in taken):
                continue                          # a marker's bar
            ends = (lo if lo < cy - _TOL else None, hi if hi > cy + _TOL else None)
            if ends == (None, None):
                continue
            key = (round(cx / _TOL), round(lo, 2), round(hi, 2))
            claims.setdefault(key, []).append((abs((lo + hi) / 2 - cy), si, ends))
    out = {}
    for cands in claims.values():
        _, si, ends = min(cands)
        out.setdefault(si, ends)
    return out

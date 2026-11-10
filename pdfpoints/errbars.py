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
"""

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
    idx = {}
    for lo, hi, pos in segs:
        idx.setdefault(int(math.floor(pos / _BUCKET)), []).append((lo, hi, pos))
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


def find_error_bars(symbols, graphs, paths, graph_of):
    """{symbol index: {"v": (low, high) | None, "h": (low, high) | None}} in
    page coordinates, for the markers that have error bars.  `graph_of(s)`
    gives a symbol's graph.  A side without a bar ends at the marker's
    centre."""
    segs = _segments(paths)
    index = {k: _index(v) for k, v in segs.items()}
    claims = {}                    # (direction, chain) -> [(score, symbol index, ends)]
    for si, s in enumerate(symbols):
        if s["shape"] in ("bar", "line"):
            continue
        g = graph_of(s)
        if g is None:
            continue
        x0, y0, x1, y1 = g["rect"]
        size = max(s["size"], 0.5)
        tol = max(0.15 * size, 0.3)
        for k, centre, along, span, (lo_lim, hi_lim) in (
                ("v", s["cx"], s["cy"], y1 - y0, (x0, x1)),
                ("h", s["cy"], s["cx"], x1 - x0, (y0, y1))):
            pieces = []
            for b in range(int(math.floor((centre - tol) / _BUCKET)),
                           int(math.floor((centre + tol) / _BUCKET)) + 1):
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
                score = min(min(abs(q - along) for q in knots[1:-1] or [math.inf]),
                            abs((lo + hi) / 2 - along))
                key = (k, round(centre / tol), round(lo, 2), round(hi, 2))
                claims.setdefault(key, []).append((score, si, (low, high)))
    out = {}
    for (k, *_), cands in claims.items():
        score, si, ends = min(cands)
        bars = out.setdefault(si, {"v": None, "h": None})
        if bars[k] is None:
            bars[k] = ends
    return out

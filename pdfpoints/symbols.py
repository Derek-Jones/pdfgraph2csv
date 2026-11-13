"""Marker symbols drawn as vector paths: classification of subpaths into
circles, squares, triangles, diamonds, polygons, crosses and plus signs,
and the removal of things that are not markers (letters, dashes, doubled
outlines, highlight boxes).
"""

import collections
import math

from .colours import color_name
from .geometry import axis_aligned, bbox_of, flatten_subpath, memoized
from .grouping import BoxGrid, DisjointSets


def drop_hidden_dots(symbols, paths):
    """Dots hardly wider than a line of their colour drawn through them
    (at most 1.3 times its width: points at the vertices of a model curve,
    the curve drawn about as thick as they are) cannot be told from the
    line: they are not data points."""
    cell = 5.0
    segs = {}                            # (colour, cell) -> [(p, q, half width)]
    for p in paths:
        lw = (p.get("style") or (None,))[0]
        if not p["stroke"] or not lw or lw < 0.5 or p["stroke_rgb"] is None:
            continue
        for sp in p["subpaths"]:
            pts = flatten_subpath(sp)
            for a, b in zip(pts, pts[1:]):
                for gx in range(int(min(a[0], b[0]) // cell), int(max(a[0], b[0]) // cell) + 1):
                    for gy in range(int(min(a[1], b[1]) // cell), int(max(a[1], b[1]) // cell) + 1):
                        segs.setdefault((p["stroke_rgb"], gx, gy), []).append((a, b, lw))
    if not segs:
        return symbols

    def hidden(s):
        if not s["filled"] or s["shape"] != "circle":
            return False
        for a, b, lw in segs.get((s["rgb"], int(s["cx"] // cell), int(s["cy"] // cell)), ()):
            if s["size"] > 1.3 * lw + 0.05:
                continue
            dx, dy = b[0] - a[0], b[1] - a[1]
            L2 = dx * dx + dy * dy
            t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((s["cx"] - a[0]) * dx + (s["cy"] - a[1]) * dy) / L2))
            if math.hypot(a[0] + t * dx - s["cx"], a[1] + t * dy - s["cy"]) <= 0.25 * lw:
                return True
        return False
    return [s for s in symbols if not hidden(s)]


def drop_covered_bits(symbols, paths):
    """Small shapes painted before an opaque filled marker that covers them
    entirely (pieces of error bars traced from a bitmap, under the points
    drawn over them) are not seen and are no data points.  Only shapes at
    most 0.4 times the covering marker's size count: a duplicate point
    under an equal marker is still reported."""
    opaque = {p["idx"] for p in paths if p.get("opaque", True)}
    covers = [s for s in symbols if s["filled"] and s.get("idx") in opaque and 0 < s["size"] <= 20]
    if not covers:
        return symbols
    biggest = max(c["size"] for c in covers)
    if not any(s["size"] <= 0.4 * biggest for s in symbols):
        return symbols
    # of a stack of identical covers only the last painted one matters
    last = {}
    for c in covers:
        k = (c["shape"], round(c["cx"], 2), round(c["cy"], 2), round(c["size"], 2))
        if k not in last or c["idx"] > last[k]["idx"]:
            last[k] = c
    covers = list(last.values())
    sizes = sorted(c["size"] for c in covers)
    grid = BoxGrid(max(sizes[len(sizes) // 2], 0.5))
    for c in covers:
        r = c["size"] / 2
        grid.add(id(c), (c["cx"] - r, c["cy"] - r, c["cx"] + r, c["cy"] + r))
    by_id = {id(c): c for c in covers}

    def covered(s):
        if s["size"] > 0.4 * biggest:
            return False
        r = s["size"] / 2
        for k in grid.near((s["cx"] - r, s["cy"] - r, s["cx"] + r, s["cy"] + r)):
            c = by_id[k]
            if c is s or c["idx"] <= s.get("idx", -1) or s["size"] > 0.4 * c["size"]:
                continue
            R = c["size"] / 2 if c["shape"] == "circle" else c["size"] / 2 * 0.95
            if math.hypot(s["cx"] - c["cx"], s["cy"] - c["cy"]) + r <= R:
                return True
        return False
    return [s for s in symbols if not covered(s)]


def drop_specks(symbols):
    """On a page of many markers, a few tiny one-off shapes - each far
    smaller than the markers and of a shape and colour seen only a few
    times on the page (at most twice, or 0.5% of the markers: specks of a
    figure traced from a bitmap) - are no data points.  A
    series of small dots repeats its look and is kept."""
    if len(symbols) < 100:
        return symbols
    sizes = sorted(s["size"] for s in symbols)
    small = [s for s in symbols if s["size"] < 0.35 * sizes[len(sizes) // 2]]
    if not small:
        return symbols
    looks = collections.Counter((s["shape"], s["filled"], s["rgb"]) for s in symbols)
    rare = max(2, 0.005 * len(symbols))
    specks = {id(s) for s in small if looks[(s["shape"], s["filled"], s["rgb"])] <= rare}
    if len(specks) > 0.02 * len(symbols):
        return symbols
    return [s for s in symbols if id(s) not in specks]


def drop_outline_rings(symbols):
    """A marker's outline drawn as a filled ring right after its filled
    body (a stroke converted to an outline: ggplot2 points through some
    converters) is found as an open circle round a filled one: the same
    colour, the same centre, a little bigger, painted next.  Drop the ring.
    A ring of another colour painted directly after a body that nearly
    fills it is the border of a filled point (ggplot2's shape 21: coloured
    inside, black border) and is dropped too.  So is a filled marker of the
    same shape but another look painted directly over a filled marker,
    a little bigger (up to 1.25 times) and on the same centre: it
    highlights that point (a blue dot under a white circle with a blue
    outline), which keeps its own series."""
    filled, filled_any = {}, {}
    for s in symbols:
        if s["filled"] and s.get("idx") is not None:
            filled_any.setdefault(s["idx"], []).append(s)
            if s["shape"] == "circle":
                filled.setdefault(s["idx"], []).append(s)
    out = []
    for s in symbols:
        if not s["filled"] and s["shape"] == "circle" and s.get("idx") is not None:
            body = [f for d in (1, 2) for f in filled.get(s["idx"] - d, ())
                    if (f["rgb"] == s["rgb"] and 0.5 * s["size"] <= f["size"] <= s["size"] or
                        d == 1 and s.get("ring") and 0.75 * s["size"] <= f["size"] <= s["size"])
                    and math.hypot(f["cx"] - s["cx"], f["cy"] - s["cy"]) < 0.15 * s["size"]]
            if body:
                continue
        if s["filled"] and s.get("idx") is not None and any(
                f["shape"] == s["shape"] and (f["rgb"], f.get("outline_rgb")) != (s["rgb"], s.get("outline_rgb"))
                and 0.8 * s["size"] <= f["size"] < s["size"]
                and math.hypot(f["cx"] - s["cx"], f["cy"] - s["cy"]) < 0.15 * s["size"]
                for f in filled_any.get(s["idx"] - 1, ())):
            continue
        out.append(s)
    return out


def drop_highlight_boxes(symbols):
    """An open square or circle drawn round a smaller marker of another
    colour highlights that point; it is not a data point itself."""
    # grid cell -> colour -> symbols: only markers of another colour count,
    # so thousands of stacked markers of one colour are never compared
    grid = {}
    for t in symbols:
        if t["size"] > 0:
            cell = grid.setdefault((int(t["cx"] // 4), int(t["cy"] // 4)), {})
            cell.setdefault(t["rgb"], []).append(t)
    def highlights(s):
        gx, gy = int(s["cx"] // 4), int(s["cy"] // 4)
        r = int(0.25 * s["size"] // 4) + 1
        own, lim, cut = s["rgb"], 0.8 * s["size"], 0.25 * s["size"]
        for dx in range(-r, r + 1):
            for dy in range(-r, r + 1):
                cell = grid.get((gx + dx, gy + dy))
                if not cell or (len(cell) == 1 and own in cell):
                    continue                  # empty, or only its own colour
                for rgb, ts in cell.items():
                    if rgb == own:
                        continue
                    for t in ts:
                        if t["size"] < lim and \
                                math.hypot(t["cx"] - s["cx"], t["cy"] - s["cy"]) < cut:
                            return True
        return False

    # highlight boxes are a style of their own, each around a point; open
    # markers of a series that only sometimes surround another marker
    # (means drawn over the per-generator markers at the same value) stay
    cand = [s for s in symbols
            if not s.get("filled") and s["shape"] in ("square", "circle") and s["size"] > 0]
    style = lambda s: (s["shape"], s["rgb"], round(s["size"], 1))
    total, hits = {}, {}
    hl = set()
    for s in cand:
        total[style(s)] = total.get(style(s), 0) + 1
        if highlights(s):
            hl.add(id(s))
            hits[style(s)] = hits.get(style(s), 0) + 1
    return [s for s in symbols
            if not (id(s) in hl and hits[style(s)] == total[style(s)])]


def _rotationally_symmetric(verts, size):
    """Regular polygons, stars and filled plus signs map onto themselves
    when turned by 360/k degrees about their centre (k = 2..8); letters
    drawn as outlines ('v', 'A', 'k', ...) do not."""
    cx = sum(v[0] for v in verts) / len(verts)
    cy = sum(v[1] for v in verts) / len(verts)
    tol = 0.08 * size
    for k in (2, 3, 4, 5, 6, 8):
        a = 2 * math.pi / k
        ca, sa = math.cos(a), math.sin(a)
        ok = True
        for x, y in verts:
            rx = cx + (x - cx) * ca - (y - cy) * sa
            ry = cy + (x - cx) * sa + (y - cy) * ca
            if min(math.hypot(rx - u, ry - w) for u, w in verts) > tol:
                ok = False
                break
        if ok:
            return True
    return False


def elongation(poly):
    """sqrt(largest / smallest principal second moment of area) of a polygon:
    1 for discs, squares and regular shapes; large for thin strokes."""
    A = cx = cy = 0.0
    for (x0, y0), (x1, y1) in zip(poly, poly[1:] + poly[:1]):
        c = x0 * y1 - x1 * y0
        A += c
        cx += (x0 + x1) * c
        cy += (y0 + y1) * c
    if abs(A) < 1e-12:
        return float("inf")
    A /= 2.0
    cx /= 6.0 * A
    cy /= 6.0 * A
    sxx = syy = sxy = 0.0
    for (x0, y0), (x1, y1) in zip(poly, poly[1:] + poly[:1]):
        x0 -= cx; x1 -= cx; y0 -= cy; y1 -= cy
        c = x0 * y1 - x1 * y0
        sxx += (y0 * y0 + y0 * y1 + y1 * y1) * c
        syy += (x0 * x0 + x0 * x1 + x1 * x1) * c
        sxy += (x0 * y1 + 2 * x0 * y0 + 2 * x1 * y1 + x1 * y0) * c
    sxx, syy, sxy = abs(sxx) / 12.0, abs(syy) / 12.0, abs(sxy) / 24.0
    tr, det = sxx + syy, sxx * syy - sxy * sxy
    disc = math.sqrt(max(tr * tr / 4 - det, 0.0))
    lo, hi = tr / 2 - disc, tr / 2 + disc
    return math.sqrt(hi / lo) if lo > 1e-15 else float("inf")


def classify_subpath(sp):
    """Classify one closed subpath as a marker shape.  Returns None or a
    dict with 'shape' (circle, square, rectangle, triangle, diamond or
    polygon), centre 'cx', 'cy', 'size' (larger side of its box) and
    'ring' when it is the outline ring of an open circle.  (Crosses and
    plus signs are open strokes: see match_crossing_strokes.)"""
    c = memoized("cls", sp, _classify_subpath)
    return dict(c) if c is not None else None      # (callers add to it)


def as_closed(sp):
    """A filled subpath is closed implicitly: the subpath marked closed (the
    subpath itself when it is, so that its cached results serve; else a
    copy)."""
    if sp["closed"]:
        return sp
    # (results cached on the subpath, under "_..." keys, are not the copy's)
    out = {k: v for k, v in sp.items() if not k.startswith("_")}
    out["closed"] = True
    return out


def _classify_subpath(sp):
    pts = [sp["start"]]
    curves = lines = 0
    for seg in sp["segs"]:
        pts.extend(seg[1:])
        if seg[0] == "c":
            curves += 1
        else:
            lines += 1
    end = pts[-1]
    x0, y0, x1, y1 = bbox_of(pts)
    w, h = x1 - x0, y1 - y0
    size = max(w, h)
    if size <= 1e-9:
        return None
    closed = sp["closed"] or math.hypot(end[0] - pts[0][0], end[1] - pts[0][1]) < 0.02 * size
    if not closed or min(w, h) <= 1e-9:
        return None
    aspect = min(w, h) / max(w, h)
    shape = None
    ring = False
    centre = ((x0 + x1) / 2, (y0 + y1) / 2)      # the middle of the box
    if curves == 2 and lines <= 1:
        # a circle of two half-circle arcs (GraphPad Prism): their control
        # points stand 4/3 of the radius off the diameter, so the box and
        # the roundness are measured on the curve itself
        flat = flatten_subpath(sp, steps=12)
        fx0, fy0, fx1, fy1 = bbox_of(flat)
        fw, fh = fx1 - fx0, fy1 - fy0
        if min(fw, fh) > 0.85 * max(fw, fh) > 1e-9:
            cx0, cy0, r = (fx0 + fx1) / 2, (fy0 + fy1) / 2, max(fw, fh) / 2
            if all(abs(math.hypot(q[0] - cx0, q[1] - cy0) - r) < 0.06 * r for q in flat):
                shape, centre, size = "circle", (cx0, cy0), max(fw, fh)
    elif curves >= 3 and lines <= 1:        # a circle: 4, 8, ... Bezier arcs
        shape = "circle" if aspect > 0.85 else None
    elif curves >= 6 and lines <= 3 and aspect > 0.85:
        # an outline ring drawn as one contour: outer circle, a short line
        # inwards, inner circle back (an open circle with its stroke
        # converted to a filled shape)
        cx0, cy0 = (x0 + x1) / 2, (y0 + y1) / 2
        r_out = size / 2
        rs = [math.hypot(q[0] - cx0, q[1] - cy0) for s in sp["segs"] if s[0] == "c" for q in (s[3],)]
        inner = [r for r in rs if r < 0.9 * r_out]
        outer = [r for r in rs if r >= 0.9 * r_out]
        if inner and outer and max(inner) - min(inner) < 0.1 * r_out and \
                min(outer) > 0.95 * r_out and min(inner) > 0.3 * r_out:
            shape, ring = "circle", True
    elif curves == 0:                       # a polygon: count its corners
        verts = [sp["start"]] + [s[1] for s in sp["segs"]]
        uniq = []
        for v in verts:
            if not uniq or math.hypot(v[0] - uniq[-1][0], v[1] - uniq[-1][1]) > 0.01 * size:
                uniq.append(v)
        if len(uniq) > 1 and math.hypot(uniq[-1][0] - uniq[0][0], uniq[-1][1] - uniq[0][1]) <= 0.01 * size:
            uniq.pop()
        n = len(uniq)
        if n == 3:
            shape = "triangle"
            # an equilateral triangle (box aspect sqrt(3)/2) is centred on its
            # centroid, as R draws it (pch 2, 6, 17, 24, 25: apex r above
            # the point, base r/2 below); a triangle filling a square box,
            # as matplotlib draws it, on the middle of the box
            if 0.8 < aspect < 0.93:
                centre = (sum(v[0] for v in uniq) / 3, sum(v[1] for v in uniq) / 3)
        elif n == 4:
            edges = [axis_aligned(uniq[k], uniq[(k + 1) % 4]) for k in range(4)]
            if all(edges):
                # oblong boxes are only ever used as legend keys (colour swatches)
                shape = "square" if aspect > 0.85 else ("rectangle" if aspect >= 0.5 else None)
            elif aspect >= 0.5:
                # a diamond has one corner at the middle of each side of its
                # bounding box: left, right (at mid height), top, bottom (mid
                # width); one in a box of aspect 0.5-0.85 is a thin diamond
                # (matplotlib's 'd').  The corners may be off the middle by
                # up to 12% of the box: some programs (seen with Excel via
                # Distiller) put them on a grid of about a fifth of the
                # marker's size
                xm, ym = (x0 + x1) / 2, (y0 + y1) / 2
                tx, ty = 0.12 * (x1 - x0), 0.12 * (y1 - y0)
                sides = set()
                for v in uniq:
                    if abs(v[1] - ym) < ty and abs(v[0] - x0) < tx:
                        sides.add("l")
                    elif abs(v[1] - ym) < ty and abs(v[0] - x1) < tx:
                        sides.add("r")
                    elif abs(v[0] - xm) < tx and abs(v[1] - y0) < ty:
                        sides.add("b")
                    elif abs(v[0] - xm) < tx and abs(v[1] - y1) < ty:
                        sides.add("t")
                if sides == {"l", "r", "t", "b"}:
                    shape = "diamond" if aspect > 0.85 else "thin-diamond"
        elif 5 <= n <= 12 and aspect > 0.7 and _rotationally_symmetric(uniq, size):
            shape = "polygon"
            # the centre of symmetry (for a pentagon or a star it is not the
            # middle of the box)
            centre = (sum(v[0] for v in uniq) / n, sum(v[1] for v in uniq) / n)
    if shape is None:
        return None
    # markers are compact; a short diagonal stroke (e.g. the dash of a dashed
    # line converted to an outline) has a square-ish bounding box but is long
    # and thin
    if shape in ("polygon", "triangle", "diamond") and elongation(flatten_subpath(sp)) > 1.8 or \
            shape == "thin-diamond" and elongation(flatten_subpath(sp)) > 2.2:
        return None
    out = {"shape": shape, "cx": centre[0], "cy": centre[1], "size": size}
    if ring:
        out["ring"] = True
    return out


def doubled_outlines(paths, text_parts=frozenset(), cls_of=None):
    """Some converters (seen with Acrobat Distiller) write every marker
    outline twice in a row.  Identical marker outlines that follow each
    other directly form runs; when the runs on a page are (almost) all of
    even length, the page is doubled and a run of L outlines is L/2 markers
    (a run of 4 is two data points at the same place).  Runs are followed
    across painting operations, since a doubled pair can be split between
    two of them.  Returns the (path idx, subpath no) entries to skip.
    `cls_of` holds the classify_subpath results of each path's subpaths
    (path idx -> list), where already known."""
    def geom(p, sp):
        return (p["fill"], p["stroke"], p["fill_rgb"], p["stroke_rgb"],
                tuple(round(v, 3) for v in sp["start"]),
                tuple(tuple(round(v, 3) for q in s[1:] for v in q) for s in sp["segs"]))

    seq = []
    for p in paths:
        cls = cls_of.get(p["idx"]) if cls_of else None
        for k, sp in enumerate(p["subpaths"]):
            if (p["idx"], k) in text_parts:
                continue
            c = cls[k] if cls is not None and (sp["closed"] or not p["fill"]) else classify_subpath(sp)
            if c is None:
                continue
            seq.append(((p["idx"], k), p, sp))
    runs = []                       # [geometry, keys, (path, subpath) of the run]
    for key, p, sp in seq:
        here = None
        if runs:
            q, sq = runs[-1][2]
            # outlines whose start points differ cannot be equal: skip the
            # full comparison (the common case)
            if abs(sq["start"][0] - sp["start"][0]) < 0.001 and \
                    abs(sq["start"][1] - sp["start"][1]) < 0.001:
                if sp["start"] == sq["start"] and sp["segs"] == sq["segs"] and \
                        (p["fill"], p["stroke"], p["fill_rgb"], p["stroke_rgb"]) == \
                        (q["fill"], q["stroke"], q["fill_rgb"], q["stroke_rgb"]):
                    runs[-1][1].append(key)     # the very same numbers: equal
                    continue
                if runs[-1][0] is None:
                    runs[-1][0] = geom(q, sq)
                here = geom(p, sp)
                if runs[-1][0] == here:
                    runs[-1][1].append(key)
                    continue
        runs.append([here, [key], (p, sp)])     # (its geometry, if worked out)
    if len(seq) < 4:
        return set()
    in_even = sum(len(r[1]) for r in runs if len(r[1]) % 2 == 0)
    if in_even < 0.9 * len(seq):
        return set()                        # not a doubled page
    skip = set()
    for r in runs:
        skip.update(r[1][1::2])             # keep every other outline
    return skip


def _containers(boxes):
    """(k, m) for each box k lying inside a larger box m (the first such m
    in order).  A box containing box k covers k's centre, so only the boxes
    covering that point are tested (grid index; boxes spanning very many
    cells are tested directly)."""
    sizes = sorted(max(b[2] - b[0], b[3] - b[1]) for b in boxes)
    cell = max(sizes[len(sizes) // 2], 1e-3)
    grid, big = {}, []
    for m, o in enumerate(boxes):
        gx0, gy0, gx1, gy1 = int(o[0] // cell), int(o[1] // cell), int(o[2] // cell), int(o[3] // cell)
        if (gx1 - gx0 + 1) * (gy1 - gy0 + 1) > 400:
            big.append(m)
            continue
        for gx in range(gx0, gx1 + 1):
            for gy in range(gy0, gy1 + 1):
                grid.setdefault((gx, gy), []).append(m)
    out = []
    for k, b in enumerate(boxes):
        area = (b[2] - b[0]) * (b[3] - b[1])
        cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
        for m in sorted(grid.get((int(cx // cell), int(cy // cell)), []) + big):
            o = boxes[m]
            if m != k and (o[2] - o[0]) * (o[3] - o[1]) > area and \
                    o[0] <= b[0] and o[1] <= b[1] and b[2] <= o[2] and b[3] <= o[3]:
                out.append((k, m))
                break
    return out


def find_symbols(paths, glyph_symbols=(), text_parts=frozenset()):
    """All marker symbols of the page: vector shapes (filled, outlined or
    both), crossing strokes (+, x) and ZapfDingbats glyphs.  Outline parts
    that belong to text (`text_parts`) are ignored."""
    syms = [dict(g) for g in glyph_symbols]
    open_lines = []
    marker_edges = set()    # the edges of polygon markers
    # filling closes every outline implicitly
    cls_of = {p["idx"]: [classify_subpath(as_closed(sp) if p["fill"] else sp)
                         for sp in p["subpaths"]] for p in paths}
    doubled = doubled_outlines(paths, text_parts, cls_of)
    for p in paths:
        holes = set()
        hole_of = {}        # outer contour -> its holes
        if p["fill"] and len(p["subpaths"]) > 1:
            # a contour inside another contour of the same path is a hole
            boxes = [bbox_of([sp["start"]] + [q for s in sp["segs"] for q in s[1:]])
                     for sp in p["subpaths"]]
            for k, m in _containers(boxes):
                holes.add(k)
                hole_of.setdefault(m, []).append(k)
        cls = cls_of[p["idx"]]
        if p["fill"]:
            outer = [k for k in range(len(cls)) if k not in holes]
            if len(outer) >= 3 and sum(1 for k in outer if cls[k]) < 0.5 * len(outer):
                continue            # a word of outlined letters, not markers
        for k, sp in enumerate(p["subpaths"]):
            if (p["idx"], k) in text_parts or k in holes or (p["idx"], k) in doubled:
                continue
            c = cls[k]
            if c and k in hole_of:
                # a marker's hole repeats its shape around the same centre
                # (an open marker drawn as an outline); any other hole means
                # a letter such as 'A', 'e' or 'o'
                for h in hole_of[k]:
                    ch = cls[h]
                    if not ch or ch["shape"] != c["shape"] or \
                            math.hypot(ch["cx"] - c["cx"], ch["cy"] - c["cy"]) > 0.15 * c["size"]:
                        c = None
                        break
            if c:
                filled = p["fill"]
                if filled and c["shape"] == "circle" and any(
                        h != k and abs(classify_subpath(p["subpaths"][h])["cx"] - c["cx"]) < 0.1 * c["size"]
                        for h in holes if classify_subpath(p["subpaths"][h])):
                    filled = False      # a ring: an open circle drawn as outline
                if c.get("ring"):
                    filled = False          # only the outline is painted
                    c["rgb"] = p["fill_rgb"] if p["fill"] else p["stroke_rgb"]
                else:
                    c["rgb"] = p["fill_rgb"] if filled else p["stroke_rgb"]
                c["filled"] = filled
                c["idx"] = p["idx"]
                if filled and p["stroke"] and p["stroke_rgb"] is not None:
                    c["outline_rgb"] = p["stroke_rgb"]      # (filled and stroked at once)
                syms.append(c)
                if all(seg[0] == "l" for seg in sp["segs"]):
                    verts = [sp["start"]] + [seg[1] for seg in sp["segs"]]
                    for a, b in zip(verts, verts[1:] + verts[:1]):
                        marker_edges.add(_edge_key(a, b))
            elif (p["stroke"] and not sp["closed"] and len(sp["segs"]) == 1
                  and sp["segs"][0][0] == "l"):
                open_lines.append((p["idx"], sp["start"], sp["segs"][0][1], p["stroke_rgb"]))
    # a marker's outline stroked as separate edges (seen with Excel via
    # Distiller: each filled diamond, then its four edges) is no '+' or 'x':
    # crossing edges of overlapping diamonds would read as such
    if marker_edges:
        open_lines = [ln for ln in open_lines if _edge_key(ln[1], ln[2]) not in marker_edges]
    syms.extend(match_crossing_strokes(open_lines))
    syms.sort(key=lambda s: s["idx"])
    return merge_fill_outline(syms)


def _edge_key(a, b):
    """A straight edge whichever way it is drawn (to 0.01 pt)."""
    a, b = (round(a[0], 2), round(a[1], 2)), (round(b[0], 2), round(b[1], 2))
    return (a, b) if a <= b else (b, a)


def match_crossing_strokes(lines):
    """Plus signs, crosses and asterisks drawn as separate straight strokes.

    The strokes of one symbol need not be drawn together: R, for example,
    draws all vertical bars of all '+' markers first and then all horizontal
    bars.  So strokes are matched globally: strokes of the same colour and
    similar length whose midpoints coincide form a group; inside a group the
    strokes are sorted by direction and the symbols are formed from one
    stroke of each direction.  Two directions (perpendicular) make a plus
    (axis aligned) or a cross (diagonal); three or more make an asterisk.
    Coincident symbols (duplicate data points) give several strokes per
    direction and are all reported.  Unmatched strokes (tick marks, legend
    lines, ...) are ignored."""
    segs = []
    for idx, a, b, rgb in lines:
        L = math.hypot(b[0] - a[0], b[1] - a[1])
        if L <= 1e-9:
            continue
        mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
        ang = math.degrees(math.atan2(b[1] - a[1], b[0] - a[0])) % 180.0
        segs.append({"idx": idx, "a": a, "b": b, "rgb": rgb, "L": L, "mid": mid, "ang": ang})
    if not segs:
        return []
    sets = DisjointSets(len(segs))
    # strokes drawn on top of each other (duplicate points: stacks of 30 in
    # the corpus) join each other; only one of each needs comparing
    first = {}
    reps = []
    for i, s in enumerate(segs):
        key = (s["mid"], s["L"], s["rgb"])
        j = first.get(key)
        if j is None:
            first[key] = i
            reps.append(i)
        else:
            sets.union(j, i)
    # strokes join only when their lengths are within 20% of each other and
    # their midpoints closer than 0.15 of the shorter one: file the
    # midpoints by length class (factors of 1.2), each class in a grid of
    # cells 0.15 times its longest stroke, and look only in the neighbouring
    # classes - a few cells per stroke, whatever the mix of lengths (curves
    # drawn as thousands of 0.01 pt strokes beside 300 pt axes once made a
    # single grid scan 10^8 cells per long stroke)
    step = math.log(1.2)
    klass = {i: int(math.floor(math.log(max(segs[i]["L"], 1e-9)) / step)) for i in reps}
    grids = {}
    for i in reps:
        k = klass[i]
        cell = 0.15 * 1.2 ** (k + 1)
        m = segs[i]["mid"]
        grids.setdefault(k, (cell, {}))[1].setdefault(
            (int(m[0] // cell), int(m[1] // cell)), []).append(i)
    for i in reps:
        s = segs[i]
        mx, my = s["mid"]
        r = 0.15 * s["L"]                       # >= the reach of any pair with s
        for k in range(klass[i] - 2, klass[i] + 3):
            got = grids.get(k)
            if got is None:
                continue
            cell, grid = got
            for gx in range(int((mx - r) // cell), int((mx + r) // cell) + 1):
                for gy in range(int((my - r) // cell), int((my + r) // cell) + 1):
                    for j in grid.get((gx, gy), ()):
                        if j <= i:
                            continue
                        t = segs[j]
                        if (t["rgb"] == s["rgb"] and abs(t["L"] / s["L"] - 1) < 0.2 and
                                math.hypot(t["mid"][0] - mx, t["mid"][1] - my)
                                < 0.15 * min(s["L"], t["L"])):
                            sets.union(i, j)
    out = []
    for g in ([segs[i] for i in members] for members in sets.groups()):
        if len(g) < 2:
            continue
        # bucket by direction (within 10 degrees, wrapping at 180)
        buckets = []
        for s in sorted(g, key=lambda s: s["idx"]):
            for bk in buckets:
                d = abs(bk[0]["ang"] - s["ang"])
                if min(d, 180 - d) < 10:
                    bk.append(s)
                    break
            else:
                buckets.append([s])
        if len(buckets) < 2:
            continue
        if len(buckets) == 2:
            d = abs(buckets[0][0]["ang"] - buckets[1][0]["ang"])
            if min(d, 180 - d) < 25:
                continue
            aligned = all(axis_aligned(bk[0]["a"], bk[0]["b"]) for bk in buckets)
            shape = "plus" if aligned else "cross"
        else:
            shape = "asterisk"
        for k in range(min(len(bk) for bk in buckets)):
            parts = [bk[k] for bk in buckets]
            pts = [p for s in parts for p in (s["a"], s["b"])]
            x0, y0, x1, y1 = bbox_of(pts)
            out.append({"shape": shape, "cx": (x0 + x1) / 2, "cy": (y0 + y1) / 2,
                        "size": max(x1 - x0, y1 - y0), "filled": False,
                        "rgb": parts[0]["rgb"], "idx": min(s["idx"] for s in parts),
                        "last": max(s["idx"] for s in parts)})
    return _join_asterisks(out)


def _join_asterisks(syms):
    """An asterisk whose diagonal rays are longer than its straight ones
    (or the other way round) comes out of the stroke matching as a plus and
    a cross: the strokes' lengths differ too much to be grouped.  A plus and
    a cross of one colour around the same centre, drawn one right after the
    other, are one asterisk."""
    by_spot = {}
    for k, s in enumerate(syms):
        if s["shape"] in ("plus", "cross"):
            key = (s["rgb"], round(s["cx"], 1), round(s["cy"], 1))
            by_spot.setdefault(key, []).append(k)
    gone = set()
    for k, s in enumerate(syms):
        if k in gone or s["shape"] not in ("plus", "cross"):
            continue
        other = "cross" if s["shape"] == "plus" else "plus"
        cands = [j for dx in (-0.1, 0.0, 0.1) for dy in (-0.1, 0.0, 0.1)
                 for j in by_spot.get((s["rgb"], round(s["cx"] + dx, 1), round(s["cy"] + dy, 1)), ())]
        for j in sorted(set(cands)):
            o = syms[j]
            if j in gone or j == k or o["shape"] != other:
                continue
            tol = 0.05 * min(s["size"], o["size"])
            near = abs(o["cx"] - s["cx"]) <= tol and abs(o["cy"] - s["cy"]) <= tol
            # drawn one right after the other (in one path, or in
            # consecutive painting operations)
            together = o["idx"] <= s["last"] + 2 and s["idx"] <= o["last"] + 2
            if near and together and 0.5 < o["size"] / s["size"] < 2:
                s.update(shape="asterisk", size=max(s["size"], o["size"]),
                         idx=min(s["idx"], o["idx"]), last=max(s["last"], o["last"]))
                gone.add(j)
                break
    return [s for k, s in enumerate(syms) if k not in gone]


def merge_fill_outline(syms):
    """Many programs (e.g. Excel) draw one marker as a filled shape followed
    immediately by a separate stroke of the same outline, or vice versa.
    Such a pair is one data point: report it once, as a filled symbol.
    Only directly consecutive fill/stroke pairs are merged, so genuinely
    repeated data points (two fills or two outlines) are all kept."""
    out = []
    i = 0
    while i < len(syms):
        a = syms[i]
        if i + 1 < len(syms):
            b = syms[i + 1]
            tol = 0.02 * max(a["size"], b["size"], 1e-9)
            if (a["shape"] == b["shape"] and a["filled"] != b["filled"] and
                    b["idx"] - a["idx"] <= 2 and
                    abs(a["cx"] - b["cx"]) <= tol and abs(a["cy"] - b["cy"]) <= tol and
                    abs(a["size"] - b["size"]) <= 0.1 * max(a["size"], b["size"])):
                fill = a if a["filled"] else b
                m = dict(fill)
                m["idx"] = min(a["idx"], b["idx"])
                m["outline_rgb"] = (b if a["filled"] else a)["rgb"]
                out.append(m)
                i += 2
                continue
        out.append(a)
        i += 1
    return out


LINE_SHAPES = ("plus", "cross", "asterisk")


def symbol_signature(s):
    """What makes markers of one series alike: shape, filled, colour."""
    return (s["shape"], s["shape"] in LINE_SHAPES or s["filled"], color_name(s["rgb"])[1])

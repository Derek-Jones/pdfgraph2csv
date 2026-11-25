"""Marker symbols drawn as vector paths.

find_symbols classifies each closed subpath (classify_subpath: circle,
square, triangle, diamond, polygon) and pairs straight strokes into plus
signs, crosses and asterisks (match_crossing_strokes).  Programs draw
markers in many ways - four or eight Bezier arcs, two half circles, a
20-gon, a fan of triangles, a filled body plus a stroked outline, every
outline written twice - so each way has its own rule here.

The drop_* functions remove shapes that have a marker's form but are not
data points, judged from the shapes alone: dots hidden in a line of their
own colour, bits covered by a later marker, one-off specks, outline rings
and highlight circles drawn round a point, and boxes round a point.  (The
filters that need the page's graphs are in strays.py.)
"""

import bisect
import collections
import math

from .colours import color_name
from .geometry import (
    axis_aligned, bbox_of, encloses, flatten_subpath, median, memoized, rect_area, subpath_bbox,
    vertices)
from .grouping import BoxGrid, DisjointSets


def drop_hidden_dots(symbols, paths):
    """Dots hardly wider than a line of their colour drawn through them
    (at most 1.3 times its width: points at the vertices of a model curve,
    the curve drawn about as thick as they are) cannot be told from the
    line: they are not data points.  Only when they are at least half the
    filled circles of their colour and size: those are the curve's
    vertices.  A few of a scatter's dots that happen to lie under the
    smooth drawn through it are data (monotonicity-025: 194 of 9 928 Stata
    dots under the lowess curves, 17 of graph 1's 1 638)."""
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
    gone = [s for s in symbols if hidden(s)]
    if not gone:
        return symbols
    kind = lambda s: (s["rgb"], round(s["size"], 2))
    total = collections.Counter(kind(s) for s in symbols if s["filled"] and s["shape"] == "circle")
    under = collections.Counter(kind(s) for s in gone)
    drop = {id(s) for s in gone if under[kind(s)] >= 0.5 * total[kind(s)]}
    return [s for s in symbols if id(s) not in drop]


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
    grid = BoxGrid(max(median(c["size"] for c in covers), 0.5))
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
    typical = median(s["size"] for s in symbols)
    small = [s for s in symbols if s["size"] < 0.35 * typical]
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
                    if ((f["rgb"] == s["rgb"] and 0.5 * s["size"] <= f["size"] <= s["size"]) or
                        (d == 1 and s.get("ring") and 0.75 * s["size"] <= f["size"] <= s["size"]))
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


def _tint_of(light, base, tol=0.08):
    """Is colour `light` the colour `base` mixed with white (each channel
    the same fraction of the way to white, at least 0.3 of it: a face is
    plainly lighter - small dots of one colour beside bigger ones are a
    stippled drawing's, song2025rigorous-002)?"""
    if light is None or base is None:
        return False
    ts = []
    for a, b in zip(light, base):
        if a < b - 0.02:
            return False
        if 1.0 - b > 0.05:
            ts.append((a - b) / (1.0 - b))
    return bool(ts) and min(ts) >= 0.3 and max(ts) - min(ts) <= tol


def drop_marker_faces(symbols, paths=()):
    """A marker drawn in layers, each layer for all markers in turn
    (cheyette2024limited-011, strokes converted to outlines: a coloured
    disc, its ring, then a pale disc and annulus inside it): a smaller
    circle (at most 0.8 times the size), painted later on the centre of a
    circle, filled or open (within 0.2 of its size), in a pale tint of its
    colour (or white), is that marker's face, not another point; so is a
    sliver of a face (at most 0.3 times the size, within one size of the
    centre), cut where two markers overlap.  It is dropped; the marker
    keeps its own colour.  Copies of one size (stacked points) are never
    faces.

    Translucent markers flattened into pieces (panel (b): open rings cut
    by the lines crossing them and by each other into pieces of blended
    colours) may keep no whole ring, but their opaque faces, painted last,
    stay whole.  When three or more faces of one colour and size lie on
    whole rings, every other face like them stands for a marker of its
    own: a circle of the rings' usual size and kind, coloured by the fill
    that covers most of the pieces painted before it within the ring.  The
    small pieces (at most 0.45 of the ring's size) within 0.75 of a ring's
    size of a face (lenses where two rings overlap),
    and the circles painted before a face, centred within its ring and no
    bigger (pieces of the disc and ring under it), are no points.  A marker
    with a white face is an open marker."""
    cell = 4.0
    grid = {}
    for s in symbols:
        # (the base may be a ring too: an open marker whose inside is
        # painted later, as cheyette2024limited-011's panel (b) does in white)
        if s["shape"] == "circle" and s.get("idx") is not None and s["size"] > 0:
            grid.setdefault((int(s["cx"] // cell), int(s["cy"] // cell)), []).append(s)
    if not grid:
        return symbols
    # (largest first in each cell: a face looks only at bigger circles, so
    # thousands of stacked markers of one size are never compared -
    # 2001.10488v4-56's 200 000)
    for lst in grid.values():
        lst.sort(key=lambda b: -b["size"])

    def base_of(s):
        # (a filled disc rather than its ring, when the face lies on both)
        found = None
        gx, gy = int(s["cx"] // cell), int(s["cy"] // cell)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for b in grid.get((gx + dx, gy + dy), ()):
                    if s["size"] > 0.8 * b["size"]:
                        break
                    d = math.hypot(b["cx"] - s["cx"], b["cy"] - s["cy"])
                    if b is not s and b["idx"] < s["idx"] and \
                            (d <= 0.2 * b["size"] or (s["size"] <= 0.3 * b["size"] and d <= b["size"])) and \
                            _tint_of(_paint(s), b["rgb"]):
                        if b["filled"]:
                            return b
                        found = found or b
        return found
    faces = {}                        # id(face) -> its base
    for s in symbols:
        if s["shape"] == "circle" and s.get("idx") is not None:
            b = base_of(s)
            if b is not None:
                faces[id(s)] = b
    # faces whose ring was flattened into pieces
    kinds = {}
    for s in symbols:
        b = faces.get(id(s))
        if b is not None and s["size"] > 0.3 * b["size"]:
            kinds.setdefault((_paint(s), round(s["size"], 1)), []).append(b)
    made = []
    for s in symbols:
        if id(s) in faces or s["shape"] != "circle" or s.get("idx") is None:
            continue
        bases = kinds.get((_paint(s), round(s["size"], 1)))
        if not bases or len(bases) < 3:
            continue
        # (a face of two parts - a disc and an annulus round it, painted
        # one after the other - stands for one marker)
        twin = next((m for m in made if abs(m["idx"] - s["idx"]) <= 2 and
                     math.hypot(m["cx"] - s["cx"], m["cy"] - s["cy"]) <= 0.2 * m["size"]), None)
        if twin is not None:
            faces[id(s)] = {"size": twin["size"]}
            continue
        size = median(b["size"] for b in bases)
        filled = sum(1 for b in bases if b["filled"]) * 2 > len(bases) and \
            not (_paint(s) and min(_paint(s)) >= 0.97)       # (white face: open)
        rgb = _ring_colour(s, size, paths)
        if rgb is None:
            continue
        m = dict(s, size=size, filled=filled, rgb=rgb, w=size, h=size, face_of=True)
        m.pop("outline_rgb", None)
        made.append(m)
        faces[id(s)] = m
    # pieces within the ring of a face
    centres = {}
    for s in symbols:
        b = faces.get(id(s))
        # (whole faces only: a sliver of a face lies off its marker's centre)
        if b is not None and s["size"] > 0.3 * b["size"]:
            centres.setdefault((int(s["cx"] // cell), int(s["cy"] // cell)), []).append((s, b["size"]))

    # (the bases of whole faces: a sliver of white may lie on any piece)
    base_ids = {id(faces[id(s)]) for s in symbols
                if id(s) in faces and s["size"] > 0.3 * faces[id(s)]["size"]}
    # a marker whose face is white is an open marker (panel (b)'s rings
    # with white insides), whether its base is the ring or a disc under it
    white_faced = {id(faces[id(s)]) for s in symbols
                   if id(s) in faces and _paint(s) and min(_paint(s)) >= 0.97 and
                   s["size"] > 0.3 * faces[id(s)]["size"]}

    def piece(s):
        # a small piece near a face, or (painted before the face, on its
        # ring, no bigger than it) a piece of the ring or disc under it
        gx, gy = int(s["cx"] // cell), int(s["cy"] // cell)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for f, z in centres.get((gx + dx, gy + dy), ()):
                    if f is s:
                        continue
                    d = math.hypot(f["cx"] - s["cx"], f["cy"] - s["cy"])
                    if (s["size"] <= 0.45 * z and d <= 0.75 * z) or \
                            (s["idx"] < f["idx"] and s["size"] <= 1.1 * z and d <= 0.5 * z):
                        return True
        return False
    out = []
    for s in symbols:
        if id(s) in faces:
            b = faces[id(s)]
            if b.get("face_of"):
                out.append(b)          # the face stands for its marker
            continue
        if s["shape"] == "circle" and centres and id(s) not in base_ids and piece(s):
            continue
        if id(s) in white_faced and s["filled"]:
            s = dict(s, filled=False)
            s.pop("outline_rgb", None)
        out.append(s)
    return out


def _paint(s):
    """The colour a symbol is painted in (a ring filled in one colour may
    carry a leftover stroke colour as its own)."""
    return s.get("paint_rgb") or s["rgb"]


def _ring_colour(face, size, paths):
    """The fill covering most of the pieces painted before `face` within a
    ring of `size` around it (by the area of their boxes); None if none.
    Not the face's own colour (other faces nearby), nor a darker shade of
    another colour found there (pieces where a translucent line or another
    marker lies over the ring)."""
    r = 0.5 * size
    area = {}
    for p in paths:
        if p["idx"] >= face["idx"] or not p["fill"] or p.get("fill_rgb") is None:
            continue
        for sp in p["subpaths"]:
            if not sp["segs"]:
                continue
            x0, y0, x1, y1 = subpath_bbox(sp)
            if x1 - x0 > 1.2 * size or y1 - y0 > 1.2 * size:
                continue
            if math.hypot((x0 + x1) / 2 - face["cx"], (y0 + y1) / 2 - face["cy"]) > r:
                continue
            if p["fill_rgb"] != _paint(face):
                area[p["fill_rgb"]] = area.get(p["fill_rgb"], 0.0) + (x1 - x0) * (y1 - y0)
    pure = [c for c in area
            if not any(d != c and all(a <= b + 0.005 for a, b in zip(c, d)) for d in area)]
    # (the grey lines joining the points cross the rings: a grey is the
    # ring's colour only when nothing coloured is there)
    coloured = [c for c in pure if max(c) - min(c) > 0.05]
    pure = coloured or pure
    if not pure:
        return None
    return max(pure, key=area.get)


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
    def style(s):
        return (s["shape"], s["rgb"], round(s["size"], 1))
    total, hits = collections.Counter(), collections.Counter()
    hl = set()
    for s in cand:
        total[style(s)] += 1
        if highlights(s):
            hl.add(id(s))
            hits[style(s)] += 1
    return [s for s in symbols
            if not (id(s) in hl and hits[style(s)] == total[style(s)])]


def _turned_square(v):
    """Are the four corners v those of a square at any angle: four equal
    sides and equal diagonals (within 8%)?"""
    sides = [math.hypot(v[k][0] - v[k - 1][0], v[k][1] - v[k - 1][1]) for k in range(4)]
    d1 = math.hypot(v[2][0] - v[0][0], v[2][1] - v[0][1])
    d2 = math.hypot(v[3][0] - v[1][0], v[3][1] - v[1][1])
    return min(sides) > 0.92 * max(sides) and min(d1, d2) > 0.92 * max(d1, d2)


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
    for (ax, ay), (bx, by) in zip(poly, poly[1:] + poly[:1]):
        x0, x1, y0, y1 = ax - cx, bx - cx, ay - cy, by - cy
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
    turned = None
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
        # (squashed up to 0.7: a figure placed with unequal x and y scales
        # turns its circles into ellipses)
        shape = "circle" if aspect > 0.7 else None
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
        verts = vertices(sp)
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
                elif _turned_square(uniq):
                    # a square turned by some other angle (the nodes of
                    # 2204.07073-010's network drawings, each network
                    # turned its own way): its edge is its size
                    shape = "square"
                    side = sum(math.hypot(uniq[k][0] - uniq[k - 1][0], uniq[k][1] - uniq[k - 1][1])
                               for k in range(4)) / 4
                    turned = side
        elif n >= 13 and aspect > 0.85:
            # a circle drawn as a polygon of many short sides (a 20-gon)
            cx0, cy0 = (x0 + x1) / 2, (y0 + y1) / 2
            rs = [math.hypot(v[0] - cx0, v[1] - cy0) for v in uniq]
            r = sum(rs) / n
            if r > 0 and all(abs(q - r) <= 0.12 * r for q in rs):
                shape = "circle"
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
    if (shape in ("polygon", "triangle", "diamond") and elongation(flatten_subpath(sp)) > 1.8) or \
            (shape == "thin-diamond" and elongation(flatten_subpath(sp)) > 2.2):
        return None
    out = {"shape": shape, "cx": centre[0], "cy": centre[1], "size": size, "w": w, "h": h}
    if turned is not None:
        out["w"] = out["h"] = turned
        out["turned"] = True
    if shape == "circle" and size != max(w, h):      # measured on the curve
        out["w"] = out["h"] = size
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
    cell = max(median(max(b[2] - b[0], b[3] - b[1]) for b in boxes), 1e-3)
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
        area = rect_area(b)
        cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
        for m in sorted(grid.get((int(cx // cell), int(cy // cell)), []) + big):
            o = boxes[m]
            if m != k and rect_area(o) > area and encloses(o, b, 0.0):
                out.append((k, m))
                break
    return out


def find_symbols(paths, glyph_symbols=(), text_parts=frozenset(), blob_parts=frozenset()):
    """All marker symbols of the page: vector shapes (filled, outlined or
    both), crossing strokes (+, x) and ZapfDingbats glyphs.  Outline parts
    that belong to text (`text_parts`) are ignored - except that a part of
    an unread "word" (`blob_parts`) that is a stroke drawn as its filled
    outline may still be an arm of a '+' or 'x' (1356058.1356080-007)."""
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
            boxes = [subpath_bbox(sp) for sp in p["subpaths"]]
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
                if (p["idx"], k) in blob_parts and p["fill"] and not p["stroke"] and \
                        len(p["subpaths"]) == 1:
                    ln = _outlined_stroke(sp)
                    if ln:
                        open_lines.append((p["idx"], ln[0], ln[1], p["fill_rgb"]))
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
                    # (the colour it is painted in, for telling a marker's
                    # face: cheyette2024limited-011's pale annuli)
                    c["paint_rgb"] = p["fill_rgb"]
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
                    verts = vertices(sp)
                    for a, b in zip(verts, verts[1:] + verts[:1]):
                        marker_edges.add(_edge_key(a, b))
            elif (p["stroke"] and not sp["closed"] and len(sp["segs"]) == 1
                  and sp["segs"][0][0] == "l"):
                open_lines.append((p["idx"], sp["start"], sp["segs"][0][1], p["stroke_rgb"]))
            elif p["fill"] and not p["stroke"] and len(p["subpaths"]) == 1:
                ln = _outlined_stroke(sp)
                if ln:
                    open_lines.append((p["idx"], ln[0], ln[1], p["fill_rgb"]))
    # a marker's outline stroked as separate edges (seen with Excel via
    # Distiller: each filled diamond, then its four edges) is no '+' or 'x':
    # crossing edges of overlapping diamonds would read as such
    if marker_edges:
        open_lines = [ln for ln in open_lines if _edge_key(ln[1], ln[2]) not in marker_edges]
    syms.extend(match_crossing_strokes(open_lines))
    syms.sort(key=lambda s: s["idx"])
    return merge_fill_outline(syms)


def drop_arrowheads(symbols, paths, arrows=None):
    """Triangles that are the heads of arrows pointing at points
    (1356058.1356080-007: arrows from the labels "-O1" ... "-Os" to the '+'
    markers, each a 6 pt shaft and an open triangle) are no points: a
    triangle with a separate straight stroked shaft, drawn within two paths
    of it, one end of the shaft within 0.7 of its size of the triangle's
    centre, the shaft at least as long as the triangle is big, pointing
    through it to its farthest corner (within 25 degrees), and no symbol at
    the shaft's other end (a line joining markers leads to another one).
    Each arrow (tip, unit direction, free end, head size) is added to
    `arrows`, for labelling the point it points at."""
    by_idx = {p["idx"]: p for p in paths}
    tri = [s for s in symbols if s["shape"] == "triangle"]
    if not tri:
        return symbols
    near = BoxGrid(5.0)
    for i, s in enumerate(symbols):
        near.add(i, (s["cx"], s["cy"], s["cx"], s["cy"]))
    gone = set()
    for s in tri:
        size = s["size"]
        for d in (-2, -1, 1, 2):
            p = by_idx.get(s["idx"] + d)
            if p is None or not p["stroke"] or p["fill"] or len(p["subpaths"]) != 1:
                continue
            sp = p["subpaths"][0]
            if sp["closed"] or len(sp["segs"]) != 1 or sp["segs"][0][0] != "l":
                continue
            a, b = sp["start"], sp["segs"][0][1]
            if math.dist(a, b) < size:
                continue
            if math.dist(b, (s["cx"], s["cy"])) < math.dist(a, (s["cx"], s["cy"])):
                a, b = b, a                          # a: the end at the head
            if math.dist(a, (s["cx"], s["cy"])) > 0.7 * size:
                continue
            p_head = by_idx.get(s["idx"])
            corners = vertices(p_head["subpaths"][0]) if p_head else []
            tip = a
            if corners:
                tip = max(corners, key=lambda q: math.dist(q, b))
                v1 = (a[0] - b[0], a[1] - b[1])
                v2 = (tip[0] - b[0], tip[1] - b[1])
                n1, n2 = math.hypot(*v1), math.hypot(*v2)
                if n1 == 0 or n2 == 0 or \
                        (v1[0] * v2[0] + v1[1] * v2[1]) / (n1 * n2) < math.cos(math.radians(25)):
                    continue
            if any(symbols[i] is not s and
                   math.dist((symbols[i]["cx"], symbols[i]["cy"]), b) <= max(1.0, 0.7 * symbols[i]["size"])
                   for i in near.near((b[0] - 5, b[1] - 5, b[0] + 5, b[1] + 5))):
                continue
            gone.add(id(s))
            if arrows is not None:
                L = math.dist(b, tip) or 1.0
                arrows.append((tip, ((tip[0] - b[0]) / L, (tip[1] - b[1]) / L), b, size))
            break
    return [s for s in symbols if id(s) not in gone]


def _outlined_stroke(sp):
    """The centre line (two ends) of a short stroke drawn as its filled
    outline - one closed contour of 4 to 8 straight edges, its length
    (along the line through its two farthest corners) at least 3 times its
    width and at most 30 pt - or None (1356058.1356080-007: Excel's 'x'
    marker drawn as four filled half-arms, thin hexagons 2.8 pt long)."""
    if not all(s[0] == "l" for s in sp["segs"]):
        return None
    pts = vertices(sp)
    if len(pts) > 2 and math.dist(pts[0], pts[-1]) < 1e-6:
        pts = pts[:-1]
    if not 4 <= len(pts) <= 8:
        return None
    a, b = max(((p, q) for i, p in enumerate(pts) for q in pts[i + 1:]),
               key=lambda pq: math.dist(*pq))
    L = math.dist(a, b)
    if L <= 1e-6 or L > 30:
        return None
    ux, uy = (b[0] - a[0]) / L, (b[1] - a[1]) / L
    cx = sum(p[0] for p in pts) / len(pts)
    cy = sum(p[1] for p in pts) / len(pts)
    along = [(p[0] - cx) * ux + (p[1] - cy) * uy for p in pts]
    across = [(p[0] - cx) * -uy + (p[1] - cy) * ux for p in pts]
    width = max(across) - min(across)
    length = max(along) - min(along)
    if width <= 0 or length < 3 * width:
        return None
    # (the ends: half a width in from the farthest corners, the caps)
    lo, hi = min(along) + 0.5 * width, max(along) - 0.5 * width
    if hi <= lo:
        return None
    return ((cx + lo * ux, cy + lo * uy), (cx + hi * ux, cy + hi * uy))


def _edge_key(a, b):
    """A straight edge whichever way it is drawn (to 0.01 pt)."""
    a, b = (round(a[0], 2), round(a[1], 2)), (round(b[0], 2), round(b[1], 2))
    return (a, b) if a <= b else (b, a)


def _join_stroke_halves(lines):
    """Consecutive collinear halves of one stroke joined (match_crossing_strokes)."""
    out = []
    lines = sorted(lines, key=lambda ln: ln[0])
    k = 0
    while k < len(lines):
        idx, a, b, rgb = lines[k]
        if k + 1 < len(lines):
            idx2, c, d, rgb2 = lines[k + 1]
            L1, L2 = math.dist(a, b), math.dist(c, d)
            if idx2 - idx == 1 and rgb2 == rgb and L1 > 1e-9 and L2 > 1e-9 and \
                    abs(L1 / L2 - 1) < 0.2:
                ux, uy = (b[0] - a[0]) / L1, (b[1] - a[1]) / L1
                cross = lambda q: abs((q[0] - a[0]) * uy - (q[1] - a[1]) * ux)
                vx, vy = (d[0] - c[0]) / L2, (d[1] - c[1]) / L2
                if abs(ux * vy - uy * vx) < math.sin(math.radians(2)) and \
                        cross(c) < 0.05 and cross(d) < 0.05:
                    t = sorted([0.0, L1, (c[0] - a[0]) * ux + (c[1] - a[1]) * uy,
                                (d[0] - a[0]) * ux + (d[1] - a[1]) * uy])
                    s1 = (0.0, L1)
                    s2 = tuple(sorted(((c[0] - a[0]) * ux + (c[1] - a[1]) * uy,
                                       (d[0] - a[0]) * ux + (d[1] - a[1]) * uy)))
                    gap = max(s1[0], s2[0]) - min(s1[1], s2[1])   # < 0: overlap
                    # (halves extend each other; a stroke drawn again on
                    # itself - a duplicate point - covers the same span)
                    if gap <= 0.05 * min(L1, L2) and t[-1] - t[0] >= 1.5 * max(L1, L2):
                        lo, hi = t[0], t[-1]
                        out.append((idx, (a[0] + lo * ux, a[1] + lo * uy),
                                    (a[0] + hi * ux, a[1] + hi * uy), rgb))
                        k += 2
                        continue
        out.append(lines[k])
        k += 1
    return out


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
    lines, ...) are ignored.

    A stroke may be drawn in two halves (1356058.1356080-007: Excel's '+'
    drawn as four 2.8 pt arms, each pair of halves overlapping at the
    centre): two consecutive strokes (drawing order) of one colour, in line
    with each other (within 2 degrees and 0.05 pt), of lengths within 20%,
    that overlap or touch end to end, together reaching 1.5 times the
    longer or more (a stroke drawn twice over is a duplicate point), are
    one stroke first.  Dashes of a dashed line leave gaps and are not
    joined."""
    lines = _join_stroke_halves(lines)
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
    klass = {i: math.floor(math.log(max(segs[i]["L"], 1e-9)) / step) for i in reps}
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
    other, are one asterisk.

    Partners are looked up by drawing order, not by place: thousands of
    markers stacked on one spot (ThomasBockPhD-073) made a search by place
    quadratic."""
    marks = sorted((s["idx"], k) for k, s in enumerate(syms) if s["shape"] in ("plus", "cross"))
    if not marks:
        return syms
    order = [i for i, _ in marks]
    span = max(syms[k]["last"] - syms[k]["idx"] for _, k in marks) + 2
    gone = set()
    for k, s in enumerate(syms):
        if k in gone or s["shape"] not in ("plus", "cross"):
            continue
        other = "cross" if s["shape"] == "plus" else "plus"
        spot = {(round(s["cx"] + dx, 1), round(s["cy"] + dy, 1))
                for dx in (-0.1, 0.0, 0.1) for dy in (-0.1, 0.0, 0.1)}
        # drawn together: o.idx <= s.last + 2 and o.last >= s.idx - 2
        lo = bisect.bisect_left(order, s["idx"] - span)
        hi = bisect.bisect_right(order, s["last"] + 2)
        cands = [j for _, j in marks[lo:hi]
                 if syms[j]["rgb"] == s["rgb"] and
                 (round(syms[j]["cx"], 1), round(syms[j]["cy"], 1)) in spot]
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


def _same_place(a, b):
    tol = 0.02 * max(a["size"], b["size"], 1e-9)
    return (a["shape"] == b["shape"] and abs(a["idx"] - b["idx"]) <= 2 and
            abs(a["cx"] - b["cx"]) <= tol and abs(a["cy"] - b["cy"]) <= tol and
            abs(a["size"] - b["size"]) <= 0.1 * max(a["size"], b["size"]))


def _drop_pattern_overlays(syms):
    gone = set()
    for i, a in enumerate(syms):
        if a["rgb"] is None and a["filled"] and (
                (i > 0 and syms[i - 1]["rgb"] is not None and _same_place(a, syms[i - 1])) or
                (i + 1 < len(syms) and syms[i + 1]["rgb"] is not None and _same_place(a, syms[i + 1]))):
            gone.add(i)
    return [s for i, s in enumerate(syms) if i not in gone] if gone else syms


def merge_fill_outline(syms):
    """Many programs (e.g. Excel) draw one marker as a filled shape followed
    immediately by a separate stroke of the same outline, or vice versa.
    Such a pair is one data point: report it once, as a filled symbol.
    Only directly consecutive fill/stroke pairs are merged, so genuinely
    repeated data points (two fills or two outlines) are all kept.
    A fill in a pattern (whose colour is unknown) of the outline drawn just
    before or after it is a texture laid over that marker, not another
    point: it is dropped first (white fill, pattern fill, black outline is
    one marker).  The two sizes may differ by 15% (the fill reaching the
    outer edge of the stroke)."""
    syms = _drop_pattern_overlays(syms)
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
                    abs(a["size"] - b["size"]) <= 0.15 * max(a["size"], b["size"])):
                # (sizes within 15%: 1356058.1356080-007's 2.21 pt dots carry
                # a 1.97 pt outline, their centre line, 11% smaller)
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


def drop_lone_turned(symbols):
    """Squares turned by an odd angle are markers only in numbers: 20 or
    more of one colour and size (the nodes of a network drawing).  A few
    are the dashes of a line or bits of a drawing (month-axis)."""
    turned = [s for s in symbols if s.get("turned")]
    if not turned:
        return symbols
    groups = collections.Counter((s["rgb"], round(s["w"], 2)) for s in turned)
    lone = {id(s) for s in turned if groups[(s["rgb"], round(s["w"], 2))] < 20}
    return [s for s in symbols if id(s) not in lone] if lone else symbols

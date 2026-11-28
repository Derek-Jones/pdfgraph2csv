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
from .spatial import BoxGrid, DisjointSets, PointGrid


_HIDDEN_CELL_PT = 5.0          # line segments filed in cells of 5 pt
_HIDDEN_MIN_LINE_PT = 0.5      # only lines 0.5 pt wide or more hide dots
_HIDDEN_DOT_WIDTHS = 1.3       # a hidden dot is at most 1.3 line widths across
_HIDDEN_DOT_PT = 0.05          # plus 0.05 pt
_HIDDEN_ON_LINE_WIDTHS = 0.25  # its centre within a quarter of a width of the line
_HIDDEN_KIND_FRAC = 0.5        # dropped when half the dots of their kind are so hidden


def drop_hidden_dots(symbols, paths):
    """Dots hardly wider than a line of their colour drawn through them
    (at most 1.3 times its width: points at the vertices of a model curve,
    the curve drawn about as thick as they are) cannot be told from the
    line: they are not data points.  Only when they are at least half the
    filled circles of their colour and size: those are the curve's
    vertices.  A few of a scatter's dots that happen to lie under the
    smooth drawn through it are data (monotonicity-025: 194 of 9 928 Stata
    dots under the lowess curves, 17 of graph 1's 1 638)."""
    cell = _HIDDEN_CELL_PT
    segs = {}                            # (colour, cell) -> [(p, q, half width)]
    for p in paths:
        lw = (p.get("style") or (None,))[0]
        if not p["stroke"] or not lw or lw < _HIDDEN_MIN_LINE_PT or p["stroke_rgb"] is None:
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
            if s["size"] > _HIDDEN_DOT_WIDTHS * lw + _HIDDEN_DOT_PT:
                continue
            dx, dy = b[0] - a[0], b[1] - a[1]
            L2 = dx * dx + dy * dy
            t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((s["cx"] - a[0]) * dx + (s["cy"] - a[1]) * dy) / L2))
            if math.hypot(a[0] + t * dx - s["cx"], a[1] + t * dy - s["cy"]) <= _HIDDEN_ON_LINE_WIDTHS * lw:
                return True
        return False
    gone = [s for s in symbols if hidden(s)]
    if not gone:
        return symbols
    kind = lambda s: (s["rgb"], round(s["size"], 2))
    total = collections.Counter(kind(s) for s in symbols if s["filled"] and s["shape"] == "circle")
    under = collections.Counter(kind(s) for s in gone)
    drop = {id(s) for s in gone if under[kind(s)] >= _HIDDEN_KIND_FRAC * total[kind(s)]}
    return [s for s in symbols if id(s) not in drop]


_COVER_MAX_PT = 20        # an opaque marker that covers bits is at most 20 pt
_BIT_MAX_FRAC = 0.4       # a covered bit is at most 0.4 times the biggest (and its cover's) size
_COVER_CELL_MIN_PT = 0.5  # covers filed in cells of their median size, at least 0.5 pt
_SQUARE_INSCRIBED = 0.95  # a square cover's inner radius: 0.95 of its half side


def drop_covered_bits(symbols, paths):
    """Small shapes painted before an opaque filled marker that covers them
    entirely (pieces of error bars traced from a bitmap, under the points
    drawn over them) are not seen and are no data points.  Only shapes at
    most 0.4 times the covering marker's size count: a duplicate point
    under an equal marker is still reported."""
    opaque = {p["idx"] for p in paths if p.get("opaque", True)}
    covers = [s for s in symbols if s["filled"] and s.get("idx") in opaque and 0 < s["size"] <= _COVER_MAX_PT]
    if not covers:
        return symbols
    biggest = max(c["size"] for c in covers)
    if not any(s["size"] <= _BIT_MAX_FRAC * biggest for s in symbols):
        return symbols
    # of a stack of identical covers only the last painted one matters
    last = {}
    for c in covers:
        k = (c["shape"], round(c["cx"], 2), round(c["cy"], 2), round(c["size"], 2))
        if k not in last or c["idx"] > last[k]["idx"]:
            last[k] = c
    covers = list(last.values())
    grid = BoxGrid(max(median(c["size"] for c in covers), _COVER_CELL_MIN_PT))
    for c in covers:
        r = c["size"] / 2
        grid.add(id(c), (c["cx"] - r, c["cy"] - r, c["cx"] + r, c["cy"] + r))
    by_id = {id(c): c for c in covers}

    def covered(s):
        if s["size"] > _BIT_MAX_FRAC * biggest:
            return False
        r = s["size"] / 2
        for k in grid.near((s["cx"] - r, s["cy"] - r, s["cx"] + r, s["cy"] + r)):
            c = by_id[k]
            if c is s or c["idx"] <= s.get("idx", -1) or s["size"] > _BIT_MAX_FRAC * c["size"]:
                continue
            R = c["size"] / 2 if c["shape"] == "circle" else c["size"] / 2 * _SQUARE_INSCRIBED
            if math.hypot(s["cx"] - c["cx"], s["cy"] - c["cy"]) + r <= R:
                return True
        return False
    return [s for s in symbols if not covered(s)]


_SPECK_PAGE_MIN = 100     # only on pages of 100 markers or more
_SPECK_MAX_FRAC = 0.35    # a speck is under 0.35 of the median size
_SPECK_RARE_MIN = 2       # of a look seen at most twice
_SPECK_RARE_FRAC = 0.005  # or on 0.5% of the markers
_SPECKS_MAX_FRAC = 0.02   # more than 2% such shapes are a series, not specks


def drop_specks(symbols):
    """On a page of many markers, a few tiny one-off shapes - each far
    smaller than the markers and of a shape and colour seen only a few
    times on the page (at most twice, or 0.5% of the markers: specks of a
    figure traced from a bitmap) - are no data points.  A
    series of small dots repeats its look and is kept."""
    if len(symbols) < _SPECK_PAGE_MIN:
        return symbols
    typical = median(s["size"] for s in symbols)
    small = [s for s in symbols if s["size"] < _SPECK_MAX_FRAC * typical]
    if not small:
        return symbols
    looks = collections.Counter((s["shape"], s["filled"], s["rgb"]) for s in symbols)
    rare = max(_SPECK_RARE_MIN, _SPECK_RARE_FRAC * len(symbols))
    specks = {id(s) for s in small if looks[(s["shape"], s["filled"], s["rgb"])] <= rare}
    if len(specks) > _SPECKS_MAX_FRAC * len(symbols):
        return symbols
    return [s for s in symbols if id(s) not in specks]


_RING_CENTRE_SIZES = 0.15    # a ring and its body share a centre within 0.15 of the ring's size
_BODY_MIN_SIZES = 0.5        # the body is 0.5 to 1.2 times the ring's size
_BODY_MAX_SIZES = 1.2        # (the biggest body, in ring sizes)
_RING_BODY_MIN_SIZES = 0.75  # (a ring right after its body: 0.75 of its size or more)
_RING_INNER_MIN_SIZES = 0.8  # an inner disc of the ring's colour is 0.8 of its size or more
_HIGHLIGHT_BIGGER = 1.02     # a highlight over a marker: 2% bigger or more


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
    outline), which keeps its own series.  (A marker as big as the one
    under it - within 2% - is a point of its own, close to the other:
    2411.16433v1-066's triangles of two series, 0.3 pt apart.)"""
    filled, filled_any, rings = {}, {}, {}
    for s in symbols:
        if not s["filled"] and s["shape"] == "circle" and s.get("idx") is not None:
            rings.setdefault(s["idx"], []).append(s)
        if s["filled"] and s.get("idx") is not None:
            filled_any.setdefault(s["idx"], []).append(s)
            if s["shape"] == "circle":
                filled.setdefault(s["idx"], []).append(s)
    out = []
    for s in symbols:
        if not s["filled"] and s["shape"] == "circle" and s.get("idx") is not None:
            # (three steps back when the step before is a ring on the same
            # centre, and the ring's inner edge a little inside the body:
            # 2020.01.30.927558.full-012 fills a disc, strokes it, fills its
            # outline as a ring and strokes that too, leaving two circles,
            # 0.9 and 1.1 times the disc; an open circle three steps after a
            # filled one with no ring between is a point of its own,
            # horowitz2014-004)
            chain = any(math.hypot(o["cx"] - s["cx"], o["cy"] - s["cy"]) < _RING_CENTRE_SIZES * s["size"]
                        for o in rings.get(s["idx"] - 1, ()))
            body = [f for d in ((1, 2, 3) if chain else (1, 2)) for f in filled.get(s["idx"] - d, ())
                    if ((f["rgb"] == s["rgb"] and _BODY_MIN_SIZES * s["size"] <= f["size"] <= _BODY_MAX_SIZES * s["size"]) or
                        (d == 1 and s.get("ring") and _RING_BODY_MIN_SIZES * s["size"] <= f["size"] <= s["size"]))
                    and math.hypot(f["cx"] - s["cx"], f["cy"] - s["cy"]) < _RING_CENTRE_SIZES * s["size"]]
            if body:
                continue
        if s["filled"] and s.get("idx") is not None and any(
                f["shape"] == s["shape"] and (f["rgb"], f.get("outline_rgb")) != (s["rgb"], s.get("outline_rgb"))
                and _RING_INNER_MIN_SIZES * s["size"] <= f["size"] <= s["size"] / _HIGHLIGHT_BIGGER
                and math.hypot(f["cx"] - s["cx"], f["cy"] - s["cy"]) < _RING_CENTRE_SIZES * s["size"]
                for f in filled_any.get(s["idx"] - 1, ())):
            continue
        out.append(s)
    return out


_TINT_MIX_TOL = 0.08   # a pale tint: its whiteness-mix ratios agree within 0.08
_TINT_DARKER = 0.02    # a tint no darker than its base, by 0.02 in any channel
_TINT_COLOURED = 0.05  # a base colour at least 0.05 from white
_TINT_MIN_MIX = 0.3    # a tint mixes in 30% white or more


def _tint_of(light, base, tol=_TINT_MIX_TOL):
    """Is colour `light` the colour `base` mixed with white (each channel
    the same fraction of the way to white, at least 0.3 of it: a face is
    plainly lighter - small dots of one colour beside bigger ones are a
    stippled drawing's, song2025rigorous-002)?"""
    if light is None or base is None:
        return False
    ts = []
    for a, b in zip(light, base):
        if a < b - _TINT_DARKER:
            return False
        if 1.0 - b > _TINT_COLOURED:
            ts.append((a - b) / (1.0 - b))
    return bool(ts) and min(ts) >= _TINT_MIN_MIX and max(ts) - min(ts) <= tol


_FACE_CELL_PT = 4.0       # marker centres filed in cells of 4 pt
_FACE_MAX_SIZES = 0.8     # a face is at most 0.8 times its marker's size
_FACE_CENTRE_SIZES = 0.2  # centred on it within 0.2 of its size
_SLIVER_MAX_SIZES = 0.3   # a sliver of a face is at most 0.3 times the size
_FACES_MIN = 3            # faces of one colour and size on whole rings: 3 or more stand for markers
_WHITE_LEVEL = 0.97       # a face this light in every channel is white (an open marker)
_LENS_MAX_SIZES = 0.45    # pieces within a ring: lenses at most 0.45 of its size
_LENS_REACH_SIZES = 0.75  # within 0.75 of its size of the face
_UNDER_MAX_SIZES = 1.1    # pieces painted before a face: at most 1.1 times its size
_UNDER_REACH_SIZES = 0.5  # within half its size of it


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
    cell = _FACE_CELL_PT
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
                    if s["size"] > _FACE_MAX_SIZES * b["size"]:
                        break
                    d = math.hypot(b["cx"] - s["cx"], b["cy"] - s["cy"])
                    if b is not s and b["idx"] < s["idx"] and \
                            (d <= _FACE_CENTRE_SIZES * b["size"] or (s["size"] <= _SLIVER_MAX_SIZES * b["size"] and d <= b["size"])) and \
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
        if b is not None and s["size"] > _SLIVER_MAX_SIZES * b["size"]:
            kinds.setdefault((_paint(s), round(s["size"], 1)), []).append(b)
    made = []
    for s in symbols:
        if id(s) in faces or s["shape"] != "circle" or s.get("idx") is None:
            continue
        bases = kinds.get((_paint(s), round(s["size"], 1)))
        if not bases or len(bases) < _FACES_MIN:
            continue
        # (a face of two parts - a disc and an annulus round it, painted
        # one after the other - stands for one marker)
        twin = next((m for m in made if abs(m["idx"] - s["idx"]) <= 2 and
                     math.hypot(m["cx"] - s["cx"], m["cy"] - s["cy"]) <= _FACE_CENTRE_SIZES * m["size"]), None)
        if twin is not None:
            faces[id(s)] = {"size": twin["size"]}
            continue
        size = median(b["size"] for b in bases)
        filled = sum(1 for b in bases if b["filled"]) * 2 > len(bases) and \
            not (_paint(s) and min(_paint(s)) >= _WHITE_LEVEL)       # (white face: open)
        rgb = _ring_colour(s, size, paths)
        if rgb is None:
            continue
        m = dict(s, size=size, filled=filled, rgb=rgb, w=size, h=size, face_of=True)
        m.pop("outline_rgb", None)
        made.append(m)
        faces[id(s)] = m
    # pieces within the ring of a face
    centres = PointGrid(cell)
    for s in symbols:
        b = faces.get(id(s))
        # (whole faces only: a sliver of a face lies off its marker's centre)
        if b is not None and s["size"] > _SLIVER_MAX_SIZES * b["size"]:
            centres.add((s, b["size"]), s["cx"], s["cy"])

    # (the bases of whole faces: a sliver of white may lie on any piece)
    base_ids = {id(faces[id(s)]) for s in symbols
                if id(s) in faces and s["size"] > _SLIVER_MAX_SIZES * faces[id(s)]["size"]}
    # a marker whose face is white is an open marker (panel (b)'s rings
    # with white insides), whether its base is the ring or a disc under it
    white_faced = {id(faces[id(s)]) for s in symbols
                   if id(s) in faces and _paint(s) and min(_paint(s)) >= _WHITE_LEVEL and
                   s["size"] > _SLIVER_MAX_SIZES * faces[id(s)]["size"]}

    def piece(s):
        # a small piece near a face, or (painted before the face, on its
        # ring, no bigger than it) a piece of the ring or disc under it
        for f, z in centres.near(s["cx"], s["cy"]):
            if f is s:
                continue
            d = math.hypot(f["cx"] - s["cx"], f["cy"] - s["cy"])
            if (s["size"] <= _LENS_MAX_SIZES * z and d <= _LENS_REACH_SIZES * z) or \
                    (s["idx"] < f["idx"] and s["size"] <= _UNDER_MAX_SIZES * z and d <= _UNDER_REACH_SIZES * z):
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


_RING_PIECE_MAX_SIZES = 1.2  # pieces of a ring lie within 1.2 of its size
_TINT_TOL = 0.005            # a colour no lighter than another, channel by channel, within 0.005
_GREY_SPREAD = 0.05          # a colour whose channels differ by more than 0.05 is no grey


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
            if x1 - x0 > _RING_PIECE_MAX_SIZES * size or y1 - y0 > _RING_PIECE_MAX_SIZES * size:
                continue
            if math.hypot((x0 + x1) / 2 - face["cx"], (y0 + y1) / 2 - face["cy"]) > r:
                continue
            if p["fill_rgb"] != _paint(face):
                area[p["fill_rgb"]] = area.get(p["fill_rgb"], 0.0) + (x1 - x0) * (y1 - y0)
    pure = [c for c in area
            if not any(d != c and all(a <= b + _TINT_TOL for a, b in zip(c, d)) for d in area)]
    # (the grey lines joining the points cross the rings: a grey is the
    # ring's colour only when nothing coloured is there)
    coloured = [c for c in pure if max(c) - min(c) > _GREY_SPREAD]
    pure = coloured or pure
    if not pure:
        return None
    return max(pure, key=area.get)


_HIGHLIGHT_CELL_PT = 4            # markers filed in cells of 4 pt
_HIGHLIGHT_INNER_MAX_SIZES = 0.8  # the highlighted marker is under 0.8 of the box's size
_HIGHLIGHT_CENTRE_SIZES = 0.25    # centred within a quarter of its size


def drop_highlight_boxes(symbols):
    """An open square or circle drawn round a smaller marker of another
    colour highlights that point; it is not a data point itself."""
    # grid cell -> colour -> symbols: only markers of another colour count,
    # so thousands of stacked markers of one colour are never compared
    grid = {}
    for t in symbols:
        if t["size"] > 0:
            cell = grid.setdefault((int(t["cx"] // _HIGHLIGHT_CELL_PT), int(t["cy"] // _HIGHLIGHT_CELL_PT)), {})
            cell.setdefault(t["rgb"], []).append(t)
    def highlights(s):
        gx, gy = int(s["cx"] // _HIGHLIGHT_CELL_PT), int(s["cy"] // _HIGHLIGHT_CELL_PT)
        r = int(_HIGHLIGHT_CENTRE_SIZES * s["size"] // _HIGHLIGHT_CELL_PT) + 1
        own, lim, cut = s["rgb"], _HIGHLIGHT_INNER_MAX_SIZES * s["size"], _HIGHLIGHT_CENTRE_SIZES * s["size"]
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


_TURNED_EQUAL = 0.92  # a turned square: sides and diagonals equal within 8%


def _turned_square(v):
    """Are the four corners v those of a square at any angle: four equal
    sides and equal diagonals (within 8%)?"""
    sides = [math.hypot(v[k][0] - v[k - 1][0], v[k][1] - v[k - 1][1]) for k in range(4)]
    d1 = math.hypot(v[2][0] - v[0][0], v[2][1] - v[0][1])
    d2 = math.hypot(v[3][0] - v[1][0], v[3][1] - v[1][1])
    return min(sides) > _TURNED_EQUAL * max(sides) and min(d1, d2) > _TURNED_EQUAL * max(d1, d2)


_SYMMETRY_TOL = 0.08  # rotational symmetry: corners within 0.08 of the size


def _rotationally_symmetric(verts, size):
    """Regular polygons, stars and filled plus signs map onto themselves
    when turned by 360/k degrees about their centre (k = 2..8); letters
    drawn as outlines ('v', 'A', 'k', ...) do not."""
    cx = sum(v[0] for v in verts) / len(verts)
    cy = sum(v[1] for v in verts) / len(verts)
    tol = _SYMMETRY_TOL * size
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


_CLOSED_FRAC = 0.02       # a subpath ending within 2% of its size of its start is closed
_FLAT_STEPS = 12          # Bezier curves flattened in 12 steps
_SQUARE_ASPECT = 0.85     # square (or round) shapes: aspect over 0.85
_CIRCLE_ARCS = 3          # a circle: 3 Bezier arcs or more, at most 1 line
_SQUASHED_ASPECT = 0.7    # a circle squashed up to 0.7 (unequal x and y scales)
_ROUND_RECT_ARCS = 6      # a rounded shape: 6 arcs or more
_ROUND_RECT_LINES = 3     # and at most 3 lines
_CIRCLE_FIT = 0.06        # points on a circle within 6% of its radius
_RING_INNER_FRAC = 0.9    # a ring's inner radii are under 0.9 of the outer
_RING_EVEN = 0.1          # inner radii alike within 10% of the outer
_RING_OUTER = 0.95        # outer radii over 95% of the largest
_RING_MIN_INNER = 0.3     # the inner over 30% of it
_VERTEX_SAME_FRAC = 0.01  # vertices within 1% of the size are one
_EQUILATERAL_LO = 0.8     # an equilateral triangle: box aspect 0.8 to 0.93
_EQUILATERAL_HI = 0.93    # (sqrt(3)/2 is 0.866)
_RECT_ASPECT = 0.5        # a rectangle (or diamond) has aspect 0.5 or more
_DIAMOND_TIP_FRAC = 0.12  # a diamond's tips within 12% of the box's middle lines
_ROUND_POLYGON = 13       # a polygon of 13 corners or more, about round, is a circle
_SYMMETRIC_MIN = 5        # a symmetric polygon (star, hexagon): 5 to 12 corners
_SYMMETRIC_MAX = 12       # (the most corners)
_ELONGATED = 1.8          # polygons more elongated than 1.8 are no markers
_THIN_ELONGATED = 2.2     # thin diamonds than 2.2


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
    closed = sp["closed"] or math.hypot(end[0] - pts[0][0], end[1] - pts[0][1]) < _CLOSED_FRAC * size
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
        flat = flatten_subpath(sp, steps=_FLAT_STEPS)
        fx0, fy0, fx1, fy1 = bbox_of(flat)
        fw, fh = fx1 - fx0, fy1 - fy0
        if min(fw, fh) > _SQUARE_ASPECT * max(fw, fh) > 1e-9:
            cx0, cy0, r = (fx0 + fx1) / 2, (fy0 + fy1) / 2, max(fw, fh) / 2
            if all(abs(math.hypot(q[0] - cx0, q[1] - cy0) - r) < _CIRCLE_FIT * r for q in flat):
                shape, centre, size = "circle", (cx0, cy0), max(fw, fh)
    elif curves >= _CIRCLE_ARCS and lines <= 1:        # a circle: 4, 8, ... Bezier arcs
        # (squashed up to 0.7: a figure placed with unequal x and y scales
        # turns its circles into ellipses)
        shape = "circle" if aspect > _SQUASHED_ASPECT else None
    elif curves >= _ROUND_RECT_ARCS and lines <= _ROUND_RECT_LINES and aspect > _SQUARE_ASPECT:
        # an outline ring drawn as one contour: outer circle, a short line
        # inwards, inner circle back (an open circle with its stroke
        # converted to a filled shape)
        cx0, cy0 = (x0 + x1) / 2, (y0 + y1) / 2
        r_out = size / 2
        rs = [math.hypot(q[0] - cx0, q[1] - cy0) for s in sp["segs"] if s[0] == "c" for q in (s[3],)]
        inner = [r for r in rs if r < _RING_INNER_FRAC * r_out]
        outer = [r for r in rs if r >= _RING_INNER_FRAC * r_out]
        if inner and outer and max(inner) - min(inner) < _RING_EVEN * r_out and \
                min(outer) > _RING_OUTER * r_out and min(inner) > _RING_MIN_INNER * r_out:
            shape, ring = "circle", True
    elif curves == 0:                       # a polygon: count its corners
        verts = vertices(sp)
        uniq = []
        for v in verts:
            if not uniq or math.hypot(v[0] - uniq[-1][0], v[1] - uniq[-1][1]) > _VERTEX_SAME_FRAC * size:
                uniq.append(v)
        if len(uniq) > 1 and math.hypot(uniq[-1][0] - uniq[0][0], uniq[-1][1] - uniq[0][1]) <= _VERTEX_SAME_FRAC * size:
            uniq.pop()
        n = len(uniq)
        if n == 3:
            shape = "triangle"
            # an equilateral triangle (box aspect sqrt(3)/2) is centred on its
            # centroid, as R draws it (pch 2, 6, 17, 24, 25: apex r above
            # the point, base r/2 below); a triangle filling a square box,
            # as matplotlib draws it, on the middle of the box
            if _EQUILATERAL_LO < aspect < _EQUILATERAL_HI:
                centre = (sum(v[0] for v in uniq) / 3, sum(v[1] for v in uniq) / 3)
        elif n == 4:
            edges = [axis_aligned(uniq[k], uniq[(k + 1) % 4]) for k in range(4)]
            if all(edges):
                # oblong boxes are only ever used as legend keys (colour swatches)
                shape = "square" if aspect > _SQUARE_ASPECT else ("rectangle" if aspect >= _RECT_ASPECT else None)
            elif aspect >= _RECT_ASPECT:
                # a diamond has one corner at the middle of each side of its
                # bounding box: left, right (at mid height), top, bottom (mid
                # width); one in a box of aspect 0.5-0.85 is a thin diamond
                # (matplotlib's 'd').  The corners may be off the middle by
                # up to 12% of the box: some programs (seen with Excel via
                # Distiller) put them on a grid of about a fifth of the
                # marker's size
                xm, ym = (x0 + x1) / 2, (y0 + y1) / 2
                tx, ty = _DIAMOND_TIP_FRAC * (x1 - x0), _DIAMOND_TIP_FRAC * (y1 - y0)
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
                    shape = "diamond" if aspect > _SQUARE_ASPECT else "thin-diamond"
                elif _turned_square(uniq):
                    # a square turned by some other angle (the nodes of
                    # 2204.07073-010's network drawings, each network
                    # turned its own way): its edge is its size
                    shape = "square"
                    side = sum(math.hypot(uniq[k][0] - uniq[k - 1][0], uniq[k][1] - uniq[k - 1][1])
                               for k in range(4)) / 4
                    turned = side
        elif n >= _ROUND_POLYGON and aspect > _SQUARE_ASPECT:
            # a circle drawn as a polygon of many short sides (a 20-gon)
            cx0, cy0 = (x0 + x1) / 2, (y0 + y1) / 2
            rs = [math.hypot(v[0] - cx0, v[1] - cy0) for v in uniq]
            r = sum(rs) / n
            if r > 0 and all(abs(q - r) <= _DIAMOND_TIP_FRAC * r for q in rs):
                shape = "circle"
        elif _SYMMETRIC_MIN <= n <= _SYMMETRIC_MAX and aspect > _SQUASHED_ASPECT and _rotationally_symmetric(uniq, size):
            shape = "polygon"
            # the centre of symmetry (for a pentagon or a star it is not the
            # middle of the box)
            centre = (sum(v[0] for v in uniq) / n, sum(v[1] for v in uniq) / n)
    if shape is None:
        return None
    # markers are compact; a short diagonal stroke (e.g. the dash of a dashed
    # line converted to an outline) has a square-ish bounding box but is long
    # and thin
    if (shape in ("polygon", "triangle", "diamond") and elongation(flatten_subpath(sp)) > _ELONGATED) or \
            (shape == "thin-diamond" and elongation(flatten_subpath(sp)) > _THIN_ELONGATED):
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


_BIG_CELLS = 400  # boxes spanning over 400 cells are tested directly


def _containers(boxes):
    """(k, m) for each box k lying inside a larger box m (the first such m
    in order).  A box containing box k covers k's centre, so only the boxes
    covering that point are tested (grid index; boxes spanning very many
    cells are tested directly)."""
    cell = max(median(max(b[2] - b[0], b[3] - b[1]) for b in boxes), 1e-3)
    grid, big = {}, []
    for m, o in enumerate(boxes):
        gx0, gy0, gx1, gy1 = int(o[0] // cell), int(o[1] // cell), int(o[2] // cell), int(o[3] // cell)
        if (gx1 - gx0 + 1) * (gy1 - gy0 + 1) > _BIG_CELLS:
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


_WORD_OUTLINES = 3   # a path of 3 outlines or more
_WORD_FRAC = 0.5     # fewer than half of them marker shapes: a word of outlined letters
_HOLE_CENTRE = 0.15  # a marker's hole is centred within 0.15 of its size
_RING_HOLE = 0.1     # a ring's hole within 0.1 of its size


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
            if len(outer) >= _WORD_OUTLINES and sum(1 for k in outer if cls[k]) < _WORD_FRAC * len(outer):
                continue            # a word of outlined letters, not markers
        for k, sp in enumerate(p["subpaths"]):
            if (p["idx"], k) in text_parts or k in holes:
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
                            math.hypot(ch["cx"] - c["cx"], ch["cy"] - c["cy"]) > _HOLE_CENTRE * c["size"]:
                        c = None
                        break
            if c:
                filled = p["fill"]
                if filled and c["shape"] == "circle" and any(
                        h != k and abs(classify_subpath(p["subpaths"][h])["cx"] - c["cx"]) < _RING_HOLE * c["size"]
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


_ARROW_CELL_PT = 5.0      # symbols filed in cells of 5 pt
_SHAFT_REACH_SIZES = 0.7  # a shaft starts within 0.7 of the triangle's size of its centre
_SHAFT_ANGLE_DEG = 25     # and points through its farthest corner within 25 degrees
_SHAFT_END_MIN_PT = 1.0   # no symbol at the shaft's other end: within 1 pt
_SHAFT_END_SIZES = 0.7    # or 0.7 of that symbol's size
_SHAFT_END_PT = 5         # (symbols looked for within 5 pt of the end)


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
    near = BoxGrid(_ARROW_CELL_PT)
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
            if math.dist(a, (s["cx"], s["cy"])) > _SHAFT_REACH_SIZES * size:
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
                        (v1[0] * v2[0] + v1[1] * v2[1]) / (n1 * n2) < math.cos(math.radians(_SHAFT_ANGLE_DEG)):
                    continue
            if any(symbols[i] is not s and
                   math.dist((symbols[i]["cx"], symbols[i]["cy"]), b) <= max(_SHAFT_END_MIN_PT, _SHAFT_END_SIZES * symbols[i]["size"])
                   for i in near.near((b[0] - _SHAFT_END_PT, b[1] - _SHAFT_END_PT, b[0] + _SHAFT_END_PT, b[1] + _SHAFT_END_PT))):
                continue
            gone.add(id(s))
            if arrows is not None:
                L = math.dist(b, tip) or 1.0
                arrows.append((tip, ((tip[0] - b[0]) / L, (tip[1] - b[1]) / L), b, size))
            break
    return [s for s in symbols if id(s) not in gone]


_OUTLINED_MIN_CORNERS = 4  # a stroke drawn as its outline: 4 to 8 corners
_OUTLINED_MAX_CORNERS = 8  # (the most corners)
_OUTLINED_MAX_PT = 30      # at most 30 pt long
_OUTLINED_MIN_WIDTHS = 3   # and 3 widths or more


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
    if not _OUTLINED_MIN_CORNERS <= len(pts) <= _OUTLINED_MAX_CORNERS:
        return None
    a, b = max(((p, q) for i, p in enumerate(pts) for q in pts[i + 1:]),
               key=lambda pq: math.dist(*pq))
    L = math.dist(a, b)
    if L <= 1e-6 or L > _OUTLINED_MAX_PT:
        return None
    ux, uy = (b[0] - a[0]) / L, (b[1] - a[1]) / L
    cx = sum(p[0] for p in pts) / len(pts)
    cy = sum(p[1] for p in pts) / len(pts)
    along = [(p[0] - cx) * ux + (p[1] - cy) * uy for p in pts]
    across = [(p[0] - cx) * -uy + (p[1] - cy) * ux for p in pts]
    width = max(across) - min(across)
    length = max(along) - min(along)
    if width <= 0 or length < _OUTLINED_MIN_WIDTHS * width:
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


_HALF_LENGTH = 0.2   # stroke halves: lengths within 20%
_HALF_INLINE = 0.05  # in line within 0.05 (pt across, of the shorter as a gap)
_HALF_REACH = 1.5    # together 1.5 times the longer or more


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
                    abs(L1 / L2 - 1) < _HALF_LENGTH:
                ux, uy = (b[0] - a[0]) / L1, (b[1] - a[1]) / L1
                cross = lambda q: abs((q[0] - a[0]) * uy - (q[1] - a[1]) * ux)
                vx, vy = (d[0] - c[0]) / L2, (d[1] - c[1]) / L2
                if abs(ux * vy - uy * vx) < math.sin(math.radians(2)) and \
                        cross(c) < _HALF_INLINE and cross(d) < _HALF_INLINE:
                    t = sorted([0.0, L1, (c[0] - a[0]) * ux + (c[1] - a[1]) * uy,
                                (d[0] - a[0]) * ux + (d[1] - a[1]) * uy])
                    s1 = (0.0, L1)
                    s2 = tuple(sorted(((c[0] - a[0]) * ux + (c[1] - a[1]) * uy,
                                       (d[0] - a[0]) * ux + (d[1] - a[1]) * uy)))
                    gap = max(s1[0], s2[0]) - min(s1[1], s2[1])   # < 0: overlap
                    # (halves extend each other; a stroke drawn again on
                    # itself - a duplicate point - covers the same span)
                    if gap <= _HALF_INLINE * min(L1, L2) and t[-1] - t[0] >= _HALF_REACH * max(L1, L2):
                        lo, hi = t[0], t[-1]
                        out.append((idx, (a[0] + lo * ux, a[1] + lo * uy),
                                    (a[0] + hi * ux, a[1] + hi * uy), rgb))
                        k += 2
                        continue
        out.append(lines[k])
        k += 1
    return out


_CROSS_CLASS = 1.2       # strokes filed in length classes 1.2 times apart
_CROSS_MID = 0.15        # crossing strokes' middles within 0.15 of the shorter
_CROSS_CLASSES = 3       # lengths compared over neighbouring classes
_CROSS_LENGTH = 0.2      # crossing strokes' lengths within 20%
_DIRECTION_DEG = 10      # strokes of one direction: within 10 degrees
_PERPENDICULAR_DEG = 25  # a plus or cross: arms within 25 degrees of square


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
    step = math.log(_CROSS_CLASS)
    klass = {i: math.floor(math.log(max(segs[i]["L"], 1e-9)) / step) for i in reps}
    grids = {}
    for i in reps:
        k = klass[i]
        cell = _CROSS_MID * _CROSS_CLASS ** (k + 1)
        m = segs[i]["mid"]
        grids.setdefault(k, (cell, {}))[1].setdefault(
            (int(m[0] // cell), int(m[1] // cell)), []).append(i)
    for i in reps:
        s = segs[i]
        mx, my = s["mid"]
        r = _CROSS_MID * s["L"]                       # >= the reach of any pair with s
        for k in range(klass[i] - 2, klass[i] + _CROSS_CLASSES):
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
                        if (t["rgb"] == s["rgb"] and abs(t["L"] / s["L"] - 1) < _CROSS_LENGTH and
                                math.hypot(t["mid"][0] - mx, t["mid"][1] - my)
                                < _CROSS_MID * min(s["L"], t["L"])):
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
                if min(d, 180 - d) < _DIRECTION_DEG:
                    bk.append(s)
                    break
            else:
                buckets.append([s])
        if len(buckets) < 2:
            continue
        if len(buckets) == 2:
            d = abs(buckets[0][0]["ang"] - buckets[1][0]["ang"])
            if min(d, 180 - d) < _PERPENDICULAR_DEG:
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


_ASTERISK_CELL = 0.1     # asterisk parts filed by centre to 0.1 pt
_ASTERISK_CENTRE = 0.05  # a plus and a cross centred within 5% of the smaller
_ASTERISK_SIZES = 0.5    # of sizes within a factor 2


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
                for dx in (-_ASTERISK_CELL, 0.0, _ASTERISK_CELL) for dy in (-_ASTERISK_CELL, 0.0, _ASTERISK_CELL)}
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
            tol = _ASTERISK_CENTRE * min(s["size"], o["size"])
            near = abs(o["cx"] - s["cx"]) <= tol and abs(o["cy"] - s["cy"]) <= tol
            # drawn one right after the other (in one path, or in
            # consecutive painting operations)
            together = o["idx"] <= s["last"] + 2 and s["idx"] <= o["last"] + 2
            if near and together and _ASTERISK_SIZES < o["size"] / s["size"] < 2:
                s.update(shape="asterisk", size=max(s["size"], o["size"]),
                         idx=min(s["idx"], o["idx"]), last=max(s["last"], o["last"]))
                gone.add(j)
                break
    return [s for k, s in enumerate(syms) if k not in gone]


_SAME_PLACE = 0.02  # markers at one place: within 2% of the bigger
_SAME_SIZE = 0.1    # of one size within 10%


def _same_place(a, b):
    tol = _SAME_PLACE * max(a["size"], b["size"], 1e-9)
    return (a["shape"] == b["shape"] and abs(a["idx"] - b["idx"]) <= 2 and
            abs(a["cx"] - b["cx"]) <= tol and abs(a["cy"] - b["cy"]) <= tol and
            abs(a["size"] - b["size"]) <= _SAME_SIZE * max(a["size"], b["size"]))


def _drop_pattern_overlays(syms):
    gone = set()
    for i, a in enumerate(syms):
        if a["rgb"] is None and a["filled"] and (
                (i > 0 and syms[i - 1]["rgb"] is not None and _same_place(a, syms[i - 1])) or
                (i + 1 < len(syms) and syms[i + 1]["rgb"] is not None and _same_place(a, syms[i + 1]))):
            gone.add(i)
    return [s for i, s in enumerate(syms) if i not in gone] if gone else syms


_FILL_OUTLINE_SIZE = 0.15  # a fill and its outline: sizes within 15%


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
            tol = _SAME_PLACE * max(a["size"], b["size"], 1e-9)
            if (a["shape"] == b["shape"] and a["filled"] != b["filled"] and
                    b["idx"] - a["idx"] <= 2 and
                    abs(a["cx"] - b["cx"]) <= tol and abs(a["cy"] - b["cy"]) <= tol and
                    abs(a["size"] - b["size"]) <= _FILL_OUTLINE_SIZE * max(a["size"], b["size"])):
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


_TURNED_MIN = 20  # squares turned by an odd angle are markers in groups of 20 or more


def drop_lone_turned(symbols):
    """Squares turned by an odd angle are markers only in numbers: 20 or
    more of one colour and size (the nodes of a network drawing).  A few
    are the dashes of a line or bits of a drawing (month-axis)."""
    turned = [s for s in symbols if s.get("turned")]
    if not turned:
        return symbols
    groups = collections.Counter((s["rgb"], round(s["w"], 2)) for s in turned)
    lone = {id(s) for s in turned if groups[(s["rgb"], round(s["w"], 2))] < _TURNED_MIN}
    return [s for s in symbols if id(s) not in lone] if lone else symbols

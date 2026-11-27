"""Markers that a converter flattened into many clipped fragments: the
circles are rebuilt by fitting circles to the fragments' arcs, and points
drawn on top of each other are counted from the colour of overlapping
semi-transparent layers.
"""

import collections
import colorsys
import math

from .geometry import (
    bbox_of, bezier_point, circumcircle, flatten_subpath, is_polygon, point_in_polys,
    polygon_area, subpath_bbox, union_box, vertices)
from .grouping import PointGrid


def _cluster_centres(arcs, rr):
    """Merge circle centres closer than 8% of the radius `rr` (the arcs of
    one circle give nearly the same centre); returns [[x, y, count]]."""
    cent, grid = [], PointGrid(max(0.2 * rr, 0.05))
    for c in arcs:
        hit = None
        for k in grid.near(c[0], c[1]):
            if math.hypot(k[0] - c[0], k[1] - c[1]) < 0.08 * rr:
                hit = k                           # (the last one found)
        if hit:
            hit[2] += 1
        else:
            k = [c[0], c[1], 1]
            cent.append(k)
            grid.add(k, c[0], c[1])
    return cent


def _hue_family(c):
    """Colours of one series blended into darker shades share a hue: the
    hue in 24 steps, or 'grey' for colours without one."""
    if max(c) - min(c) < 0.08:
        return "grey"
    return round(colorsys.rgb_to_hls(*c)[0] * 24) % 24


def _stack_shade(c, base, deepest):
    """Is colour `c` what n layers of the semi-transparent marker colour
    `base` give (one layer of alpha a over white: 1 - a (1 - m); n layers:
    1 - (1 - m)(1 - (1 - a)^n)), with `deepest` taken as the marker colour m
    itself (the saturated stack)?  Other shades in the hue are other things
    over a marker: an error bar's own transparency."""
    if c in (base, deepest):
        return True
    k = max(range(3), key=lambda i: 1 - deepest[i])
    span = 1 - deepest[k]
    if span < 0.05:
        return True
    a = (1 - base[k]) / span
    if not 0 < a < 1:
        return True
    for n in range(2, 40):
        f = 1 - (1 - a) ** n
        if all(abs((1 - (1 - deepest[i]) * f) - c[i]) <= 0.012 for i in range(3)):
            return True
    return False


def rebuild_fragmented_circles(paths, symbols, text_parts, warnings):
    """Return the symbol list with flattened-marker fragments replaced by
    rebuilt circles (one entry per marker, stacked markers repeated).

    Each rebuilt circle carries "confidence", 0 to 1, that it is a data
    point (the user asked for such a measure for reconstructed symbols):
    the fraction of its outline found among the fragments' arcs (in 5
    degree steps: a marker in plain view about 1, one mostly hidden under
    others less); a further marker stacked at the same place, known only
    from the blended colour, also divides by the number of markers whose
    circles overlap where its colour was sampled (1 when the sample saw it
    alone; its count otherwise inferred by subtracting its neighbours').
    """
    # 0. fragments are filled curved shapes that are not markers themselves;
    #    without (enough of) them there is nothing to rebuild
    marker_paths = {s["idx"] for s in symbols}
    pieces = sum(1 for p in paths if p["fill"] and p["idx"] not in marker_paths and
                 any(seg[0] == "c" for sp in p["subpaths"] for seg in sp["segs"]))
    if pieces < 20:
        return symbols
    # 1. every Bezier segment that is a good circular arc gives a centre
    #    and radius
    arcs = []            # (cx, cy, r, path idx, colour, (start angle, sweep) in degrees)
    for p in paths:
        if not p["fill"] or p["fill_rgb"] is None:
            continue
        rgb = p["fill_rgb"]
        chromatic = max(rgb) - min(rgb) > 0.15
        for k, sp in enumerate(p["subpaths"]):
            # outlined letters are black or grey; coloured pieces the text
            # reader claimed may still be marker fragments
            if (p["idx"], k) in text_parts and not chromatic:
                continue
            cur = sp["start"]
            # (round joins of a thick line drawn as an outline are arcs too;
            # their subpath runs far beyond the circle)
            sb = subpath_bbox(sp)
            extent = max(sb[2] - sb[0], sb[3] - sb[1])
            if extent > 40:
                continue                     # (no arc of radius under 8 qualifies)
            for s in sp["segs"]:
                if s[0] == "c":
                    p0, p1, p2, p3 = cur, s[1], s[2], s[3]
                    chord = math.hypot(p3[0] - p0[0], p3[1] - p0[1])
                    if chord > 0.05:
                        c = circumcircle(p0, bezier_point(p0, p1, p2, p3, .5), p3)
                        if c and 0.2 < c[2] < 8 and extent <= 5 * c[2]:
                            q1, q3 = bezier_point(p0, p1, p2, p3, .25), bezier_point(p0, p1, p2, p3, .75)
                            e = max(abs(math.hypot(q[0] - c[0], q[1] - c[1]) - c[2]) for q in (q1, q3))
                            if e < 0.01 * c[2] + 0.002 and chord > 0.3 * c[2]:
                                arcs.append((c[0], c[1], c[2], p["idx"], p["fill_rgb"],
                                             _arc_span(c, p0, bezier_point(p0, p1, p2, p3, .5), p3)))
                cur = s[-1]
    if len(arcs) < 40:
        return symbols
    # 2. the marker radius is the most common one; other common radii whose
    #    circles share its centres (inner edges of rings) belong to it too
    radii = collections.Counter(round(a[2], 2) for a in arcs)
    r1, n1 = radii.most_common(1)[0]
    if n1 < 40 or n1 < 0.15 * len(arcs):
        return symbols
    fam = [r1]
    base = _cluster_centres([a for a in arcs if abs(a[2] - r1) < 0.03 * r1], r1)
    base_cells = _centre_cells(base)
    for r2, n2 in radii.most_common(6)[1:]:
        if n2 < 0.2 * n1 or min(abs(r2 - f) for f in fam) < 0.05 * r1:
            continue
        cc = _cluster_centres([a for a in arcs if abs(a[2] - r2) < 0.03 * r2], r2)
        hit = sum(1 for k in cc if _near_centre(base_cells, k))
        if cc and hit >= 0.7 * len(cc):
            fam.append(r2)                       # concentric: same markers
    sel = [a for a in arcs if any(abs(a[2] - f) < 0.03 * f for f in fam)]
    cols = collections.Counter(a[4] for a in sel)
    if len({a[3] for a in sel}) < 20:
        return symbols                           # arcs from a few shapes only
    # 3. the marker centres
    r_out = max(fam)
    cents = []
    # (centres filed in cells of 0.12 pt: 460-201's 150 000 open circles
    # made the check against every centre so far take two minutes)
    cells = _centre_cells(())
    for f in fam:
        for k in _cluster_centres([a for a in sel if abs(a[2] - f) < 0.03 * f], f):
            if not _near_centre(cells, k):
                cents.append(k)
                cells.add(k, k[0], k[1])
    if len(cents) < 5:
        return symbols
    # markers that are intact need no rebuilding
    whole = [s for s in symbols if s["shape"] == "circle"]
    wgrid = PointGrid(r_out)
    for s in whole:
        wgrid.add(s, s["cx"], s["cy"])
    # whole markers of a graph that was not flattened (a page may have
    # both) stay as they are
    # (arcs filed in cells as big as the reach, 0.15 of the radius: cells
    # of a whole radius held hundreds of arcs each in 460-201's clouds)
    agrid = PointGrid(0.15 * r_out)
    for a in sel:
        agrid.add(a, a[0], a[1])
    intact, opaque = [], []
    keep_idx = set()                     # paths of opaque whole markers
    for k in cents:
        hits = [s for s in wgrid.near(k[0], k[1])
                if math.hypot(s["cx"] - k[0], s["cy"] - k[1]) < 0.15 * r_out]
        intact.append(bool(hits))
        # all the arcs there drawn by those circles themselves: whole
        # markers, not the top of a stack of fragments
        own = {s["idx"] for s in hits}
        arc_paths = {a[3] for a in agrid.near(k[0], k[1])
                     if math.hypot(a[0] - k[0], a[1] - k[1]) < 0.15 * r_out}
        op = bool(hits) and arc_paths <= own
        opaque.append(op)
        if op:
            keep_idx.update(own)
    if sum(intact) >= 0.6 * len(cents):
        return symbols
    cents = [k for k, op in zip(cents, opaque) if not op]
    if len(cents) < 5:
        return symbols
    # 4. how many markers are stacked at each centre: semi-transparent
    #    markers blend into darker colours where they overlap, so the colour
    #    seen at a point tells how many markers cover it.
    #    Fragments in the marker colours, indexed for point queries:
    fam_cols = set(cols)
    frags, grid = [], {}
    for p in paths:
        if p["fill"] and p["fill_rgb"] in fam_cols:
            polys = [flatten_subpath(sp) for sp in p["subpaths"] if sp["segs"]]
            pts = [q for poly in polys for q in poly]
            if pts:
                b = bbox_of(pts)
                i = len(frags)
                frags.append((b, polys, p["idx"], p["fill_rgb"]))
                if (int(b[2]) - int(b[0]) + 1) * (int(b[3]) - int(b[1]) + 1) > 10000:
                    continue                  # far larger than a marker fragment
                for gx in range(int(b[0]), int(b[2]) + 1):
                    for gy in range(int(b[1]), int(b[3]) + 1):
                        grid.setdefault((gx, gy), []).append(i)

    def colour_at(x, y):
        """Colour of the topmost fragment at (x, y)."""
        best = None
        for i in grid.get((int(x), int(y)), ()):
            b, polys, idx, col = frags[i]
            if b[0] <= x <= b[2] and b[1] <= y <= b[3] and point_in_polys(polys, x, y):
                if best is None or idx > best[0]:
                    best = (idx, col)
        return best[1] if best else None

    # layer ladder: lightest colour = 1 marker, next = 2 stacked, ...; one
    # ladder per hue (several series in different colours)
    ladders = {}
    for c in fam_cols:
        ladders.setdefault(_hue_family(c), []).append(c)
    layer, lightest = {}, {}
    for cs in ladders.values():
        cs.sort(key=lambda c: -sum(c))
        # one marker alone: the colour with the most arcs, the darkest
        # aside (an opaque line or a saturated stack); lighter colours are
        # other things (an error bar's own colour where it meets a marker)
        base = max(cs[:-1] or cs, key=lambda c: cols[c])
        cs[:] = [c for c in cs[cs.index(base):] if _stack_shade(c, base, cs[-1])]
        for i, c in enumerate(cs):
            layer[c] = i + 1
            lightest[c] = cs[0]
    ladder_len = {c: len(ladders[_hue_family(c)]) for c in layer}
    cgrid = PointGrid(r_out)
    for j, k in enumerate(cents):
        cgrid.add(j, k[0], k[1])

    def covering(x, y):
        """Indexes of the marker centres whose circle covers (x, y)."""
        return [j for j in cgrid.near(x, y) if math.hypot(cents[j][0] - x, cents[j][1] - y) < r_out - 0.02]

    # sample each marker where it overlaps as few others as possible
    samples = []         # (overlap key, covering markers, layers seen, colour) or None
    for i, k in enumerate(cents):
        best = None
        for rr in (0, 0.3 * r_out, 0.55 * r_out, 0.8 * r_out):
            for ang in range(0, 360, 30 if rr else 360):
                x = k[0] + rr * math.cos(math.radians(ang))
                y = k[1] + rr * math.sin(math.radians(ang))
                cov = covering(x, y)
                col = colour_at(x, y)
                if i not in cov or col not in layer:
                    continue
                key = (len(cov), rr)
                if best is None or key < best[0]:
                    best = (key, cov, layer[col], col)
        samples.append(best)
    # solve for the count at each centre: the layers seen at a sample are the
    # counts of all markers covering it (iterate until stable)
    m = [1] * len(cents)
    for _ in range(60):
        changed = False
        for i, s in enumerate(samples):
            if s is None:
                continue
            v = max(1, s[2] - sum(m[j] for j in s[1] if j != i))
            if v != m[i]:
                m[i] = v
                changed = True
        if not changed:
            break
    sat = [s for s in samples if s and ladder_len[s[3]] >= 3 and s[2] == ladder_len[s[3]]]
    if sat:
        warnings.append("%d marker positions are stacked so deep that the blended colour "
                        "saturates (%d+ layers): their counts are lower bounds" % (
                            len(sat), min(ladder_len[s[3]] for s in sat)))
    # drop the fragment pieces that find_symbols took for symbols
    frag_paths = {f[2] for f in frags} - keep_idx
    # (only those at a rebuilt marker: whole markers elsewhere on the page,
    # in a graph that was not flattened, stay)
    def at_rebuilt(s):
        return any(math.hypot(cents[j][0] - s["cx"], cents[j][1] - s["cy"]) < 2 * r_out
                   for j in cgrid.near(s["cx"], s["cy"], 2))
    out = [s for s in symbols if s["idx"] not in frag_paths or not at_rebuilt(s)]
    default = max(fam_cols, key=sum)
    rebuilt_idx = min(frags[0][2], 0) - 1      # drawn "before" everything
    outline = _outline_found(cents, sel, r_out)
    for i, k in enumerate(cents):
        # the colour of one marker of its series alone
        single = lightest[samples[i][3]] if samples[i] else default
        # confidence (see the docstring): the outline found; a further
        # marker stacked there also by its count's evidence
        overlap = len(samples[i][1]) if samples[i] else 2
        for n in range(m[i]):
            conf = outline[i] if n == 0 else outline[i] / overlap
            out.append({"shape": "circle", "cx": k[0], "cy": k[1], "size": 2 * r_out,
                        "filled": True, "rgb": single, "idx": rebuilt_idx, "rebuilt": True,
                        "confidence": round(conf, 2)})
    # (no warning: each rebuilt point carries its confidence instead - the
    # user asked for the warning to go)
    return out


def _arc_span(c, p0, pm, p3):
    """(start, sweep) in degrees of the arc from p0 through pm to p3 about
    centre c."""
    a0, am, a3 = (math.degrees(math.atan2(q[1] - c[1], q[0] - c[0])) for q in (p0, pm, p3))
    d, dm = (a3 - a0) % 360, (am - a0) % 360
    return (a0 % 360, d) if dm <= d else (a3 % 360, 360 - d)


def _outline_found(cents, arcs, r):
    """For each centre, the fraction of its circle's outline covered by the
    arcs fitted there (centres within 0.12 pt; 72 steps of 5 degrees)."""
    grid = PointGrid(r)
    for a in arcs:
        grid.add(a, a[0], a[1])
    out = []
    for k in cents:
        bins = set()
        for a in grid.near(k[0], k[1]):
            if math.hypot(a[0] - k[0], a[1] - k[1]) < 0.12:
                start, sweep = a[5]
                bins.update(b for b in range(72) if (b * 5 + 2.5 - start) % 360 <= sweep)
        out.append(len(bins) / 72.0)
    return out


def _centre_cells(cents):
    """Centres filed in cells of 0.12 pt, for _near_centre."""
    cells = PointGrid(0.12)
    for k in cents:
        cells.add(k, k[0], k[1])
    return cells


def _near_centre(cells, k):
    """Is a filed centre within 0.12 pt of k?  (A scan of every centre
    took minutes on 460-201's 150 000 open circles.)"""
    return any(math.hypot(k[0] - j[0], k[1] - j[1]) < 0.12 for j in cells.near(k[0], k[1]))


def rebuild_strip_discs(paths, symbols):
    """Discs filled as a fan of thin triangles (a 20-gon cut into vertical
    strips, seen in a probability textbook's plots): a run of small filled
    triangles of one colour, painted one after another and touching, whose
    box is about square and whose area is about that of the disc in it
    (pi/4 of the box; a square of two triangles fills its box) is one filled
    circle.  The pieces give no other symbols."""
    runs, cur, box = [], [], None      # (box: the run's union so far)
    for p in paths:
        piece = None
        if p["fill"] and not p["stroke"] and len(p["subpaths"]) == 1:
            sp = p["subpaths"][0]
            if is_polygon(sp):
                v = vertices(sp)
                b = bbox_of(v)
                if 3 <= len(v) <= 5 and max(b[2] - b[0], b[3] - b[1]) <= 8:
                    piece = (p, v, b)
        if piece and cur and cur[-1][0]["idx"] == piece[0]["idx"] - 1 and \
                cur[-1][0]["fill_rgb"] == piece[0]["fill_rgb"] and _touch(box, piece[2]):
            cur.append(piece)
            pb = piece[2]
            box = (min(box[0], pb[0]), min(box[1], pb[1]), max(box[2], pb[2]), max(box[3], pb[3]))
            continue
        if len(cur) >= 6:
            runs.append(cur)
        cur = [piece] if piece else []
        box = piece[2] if piece else None
    if len(cur) >= 6:
        runs.append(cur)
    discs, used = [], set()
    for run in runs:
        x0, y0, x1, y1 = union_box(b for _, _, b in run)
        w, h = x1 - x0, y1 - y0
        if min(w, h) <= 0 or min(w, h) < 0.85 * max(w, h):
            continue
        area = sum(abs(polygon_area(v)) for _, v, _ in run)
        if not 0.6 * w * h <= area <= 0.92 * w * h:
            continue
        first = run[0][0]
        discs.append({"shape": "circle", "cx": (x0 + x1) / 2, "cy": (y0 + y1) / 2,
                      "size": max(w, h), "filled": True, "rgb": first["fill_rgb"],
                      "idx": first["idx"]})
        used.update(p["idx"] for p, _, _ in run)
    if not discs:
        return symbols
    out = [s for s in symbols if s.get("idx") not in used] + discs
    out.sort(key=lambda s: s["idx"])
    return out


def _touch(a, b, tol=0.05):
    return a[0] - tol <= b[2] and b[0] - tol <= a[2] and a[1] - tol <= b[3] and b[1] - tol <= a[3]


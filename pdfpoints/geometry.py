"""Small geometry helpers shared by all analysis steps: 2-D affine
matrices, bounding boxes, flattening of Bezier subpaths, recognising
axis-aligned segments and rectangles, distances and frame rotations.
"""

import math


def mmul(m, n):
    """Product of two PDF matrices [a b c d e f] (m1 applied first)."""
    return [m[0] * n[0] + m[1] * n[2], m[0] * n[1] + m[1] * n[3],
            m[2] * n[0] + m[3] * n[2], m[2] * n[1] + m[3] * n[3],
            m[4] * n[0] + m[5] * n[2] + n[4], m[4] * n[1] + m[5] * n[3] + n[5]]


def mapply(m, x, y):
    return (m[0] * x + m[2] * y + m[4], m[1] * x + m[3] * y + m[5])


def rect_of(sp):
    """Axis-aligned rectangle (x0, y0, x1, y1) traced by a subpath, or None."""
    pts = [sp["start"]] + [seg[-1] for seg in sp["segs"]]
    if any(seg[0] != "l" for seg in sp["segs"]) or not 4 <= len(pts) <= 5:
        return None
    if len(pts) == 5 and math.hypot(pts[4][0] - pts[0][0], pts[4][1] - pts[0][1]) > 0.01:
        return None
    pts = pts[:4]
    xs = sorted(set(round(p[0], 2) for p in pts))
    ys = sorted(set(round(p[1], 2) for p in pts))
    if len(xs) != 2 or len(ys) != 2:
        return None
    for p, q in zip(pts, pts[1:] + pts[:1]):
        if abs(p[0] - q[0]) > 0.01 and abs(p[1] - q[1]) > 0.01:
            return None
    return (xs[0], ys[0], xs[1], ys[1])


def straight_segments(paint, open_only=False):
    """The straight segments (p, q) of a painted path, including the
    closing segment of closed subpaths."""
    for sp in paint["subpaths"]:
        if open_only and sp["closed"]:
            continue
        start = cur = sp["start"]
        for seg in sp["segs"]:
            if seg[0] == "l":
                yield cur, seg[1]
                cur = seg[1]
            else:
                cur = seg[-1]
        if sp["closed"] and cur != start:
            yield cur, start


def axis_aligned(p, q):
    """Return ('h', lo, hi, y) / ('v', lo, hi, x) or None."""
    dx, dy = q[0] - p[0], q[1] - p[1]
    L = math.hypot(dx, dy)
    if L <= 1e-9:
        return None
    tol = 0.02 * L + 0.01
    if abs(dy) <= tol and abs(dx) > tol:
        return ("h", min(p[0], q[0]), max(p[0], q[0]), (p[1] + q[1]) / 2)
    if abs(dx) <= tol and abs(dy) > tol:
        return ("v", min(p[1], q[1]), max(p[1], q[1]), (p[0] + q[0]) / 2)
    return None


def merge_collinear(segs):
    """segs: list of (lo, hi, pos). Merge pieces of the same line."""
    out = []
    for lo, hi, pos in sorted(segs, key=lambda s: (round(s[2], 1), s[0])):
        if out and abs(out[-1][2] - pos) <= 0.05 and lo <= out[-1][1] + 0.05:
            o = out[-1]
            out[-1] = (o[0], max(o[1], hi), o[2])
        else:
            out.append((lo, hi, pos))
    return out


def bbox_of(pts):
    """(x0, y0, x1, y1) of a list of points."""
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def circumcircle(a, b, c):
    """Centre and radius of the circle through three points (None if they
    are collinear)."""
    ax, ay = a
    bx, by = b
    cx, cy = c
    d = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(d) < 1e-12:
        return None
    a2, b2, c2 = ax * ax + ay * ay, bx * bx + by * by, cx * cx + cy * cy
    ux = (a2 * (by - cy) + b2 * (cy - ay) + c2 * (ay - by)) / d
    uy = (a2 * (cx - bx) + b2 * (ax - cx) + c2 * (bx - ax)) / d
    return ux, uy, math.hypot(ax - ux, ay - uy)


def bezier_point(p0, p1, p2, p3, t):
    """Point at parameter t of a cubic Bezier curve."""
    mt = 1 - t
    return (mt ** 3 * p0[0] + 3 * mt * mt * t * p1[0] + 3 * mt * t * t * p2[0] + t ** 3 * p3[0],
            mt ** 3 * p0[1] + 3 * mt * mt * t * p1[1] + 3 * mt * t * t * p2[1] + t ** 3 * p3[1])


def point_in_polys(polys, x, y):
    """Even-odd rule: is (x, y) inside the polygons?"""
    n = 0
    for poly in polys:
        for (x0, y0), (x1, y1) in zip(poly, poly[1:] + poly[:1]):
            if (y0 > y) != (y1 > y) and x < x0 + (y - y0) * (x1 - x0) / (y1 - y0):
                n += 1
    return n % 2 == 1


def flatten_subpath(sp, steps=6):
    """Subpath -> polygon (list of points), Beziers flattened."""
    pts = [sp["start"]]
    cur = sp["start"]
    for seg in sp["segs"]:
        if seg[0] == "l":
            pts.append(seg[1])
            cur = seg[1]
        else:
            p1, p2, p3 = seg[1], seg[2], seg[3]
            for k in range(1, steps + 1):
                t = k / float(steps)
                mt = 1 - t
                pts.append((mt ** 3 * cur[0] + 3 * mt * mt * t * p1[0] + 3 * mt * t * t * p2[0] + t ** 3 * p3[0],
                            mt ** 3 * cur[1] + 3 * mt * mt * t * p1[1] + 3 * mt * t * t * p2[1] + t ** 3 * p3[1]))
            cur = p3
    return pts


def thin_rect_line(sp):
    """A thin axis-aligned filled shape - a straight stroke converted to an
    outline, with butt ends (a rectangle) or round/square caps - -> its
    centre line ((x0, y0), (x1, y1)), else None."""
    if not sp["segs"]:
        return None
    pts = [sp["start"]] + [q for s in sp["segs"] for q in s[1:]]
    x0, y0, x1, y1 = bbox_of(pts)
    w, h = x1 - x0, y1 - y0
    t, L = min(w, h), max(w, h)
    if L <= 0 or t > 2.0 or t > 0.4 * L:
        return None
    # the long sides must be straight, and the shape must fill its bounding
    # box like a stroke does (a capsule fills > 85 %; a digit '1' ~40 %)
    straight = sum(1 for s in sp["segs"] if s[0] == "l")
    if straight < 2:
        return None
    poly = flatten_subpath(sp)
    area = abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(poly, poly[1:] + poly[:1]))) / 2
    if area < 0.8 * w * h:
        return None
    if w >= h:
        ym = (y0 + y1) / 2
        return ((x0, ym), (x1, ym))
    xm = (x0 + x1) / 2
    return ((xm, y0), (xm, y1))


def to_frame(pt, rot):
    """Page point -> the graph's own frame, for a graph turned by `rot`
    degrees (the reading direction of its labels): -90 = turned clockwise,
    90 = counter-clockwise, 180 = upside down."""
    x, y = pt
    if rot == -90:
        return (-y, x)
    if rot == 90:
        return (y, -x)
    if rot == 180:
        return (-x, -y)
    return (x, y)


def frame_rect(rect, rot):
    """A rectangle seen from a frame turned by `rot` degrees."""
    x0, y0, x1, y1 = rect
    a, b = to_frame((x0, y0), rot), to_frame((x1, y1), rot)
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1]))


def line_intersection(p1, d1, p2, d2):
    """Intersection of the lines p1 + t*d1 and p2 + s*d2 (None if parallel)."""
    den = d1[0] * d2[1] - d1[1] * d2[0]
    if abs(den) < 1e-12:
        return None
    t = ((p2[0] - p1[0]) * d2[1] - (p2[1] - p1[1]) * d2[0]) / den
    return (p1[0] + t * d1[0], p1[1] + t * d1[1])


def rect_distance(rect, x, y):
    """Distance from (x, y) to a rectangle (0 inside it)."""
    x0, y0, x1, y1 = rect
    dx = max(x0 - x, 0, x - x1)
    dy = max(y0 - y, 0, y - y1)
    return math.hypot(dx, dy)

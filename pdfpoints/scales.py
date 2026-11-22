"""Axis value mappings: fitting label values against tick positions
(linear or logarithmic), category (nominal) axes, and broken axes that are
mapped piecewise on either side of a wiggle line.
"""

import bisect
import math

from .context import PAGE
from .geometry import bbox_of, control_points, median


def fit_axis(pairs, rescue=False):
    """See _fit_axis; when no scale fits, labels whose unit's SI prefix
    steps up along the axis are tried (_prefix_steps)."""
    m = _fit_axis(pairs, rescue)
    if m is None:
        stepped = _prefix_steps(pairs)
        if stepped is not None:
            m = _fit_axis(stepped, False)
            if m is not None and m["kind"] == "log" and m["n"] == len(stepped):
                m["prefix_steps"] = True
                return m
            return None
    return m


def _prefix_steps(pairs):
    """Labels such as 10, 20, 50, ... 500 MHz, 1, 2, 5 GHz whose units
    could not be read (drawn as outlines): along the axis the values grow
    and then fall back where the unit's SI prefix steps up, a factor of
    1000.  Returns the pairs with the values after each fall multiplied by
    1000 (in the unit of the lowest labels), or None if the labels do not
    fall, or fall by other than about 1000 times what the steps before
    them lead to expect."""
    ps = sorted(pairs)
    if len(ps) < 4 or any(v <= 0 for _, v in ps):
        return None
    ups = sum(1 for a, b in zip(ps, ps[1:]) if b[1] > a[1])
    if ups < len(ps) - 1 - ups:
        ps = ps[::-1]                    # (values grow along the list, mostly)
    out, scale, falls = [ps[0]], 1.0, 0
    for (_c0, v0), (c1, v1) in zip(ps, ps[1:]):
        if v1 < v0:
            # the value expected next, from the ratio of the step before
            prev = out[-2][1] / scale if len(out) >= 2 else None
            ratio = v0 / prev if prev else 2.0
            expect = v0 * ratio
            if not 300 <= expect / v1 <= 3000:
                return None
            scale *= 1000.0
            falls += 1
        out.append((c1, v1 * scale))
    return out if falls else None


def _fit_axis(pairs, rescue=False):
    """Fit tick positions to label values: [(coord, value)] -> mapping dict
    (see map_value) or None.

    A straight line value = a*coord + b is fitted by least squares, or
    log10(value) = a*coord + b when the labels are successive powers of ten
    or fit a log scale ten times better.  A fit is accepted when every label
    lies within 2% of the value range of the line.  Otherwise the worst
    label (probably a misread or misassigned one) is dropped and the fit
    repeated, as long as more than half of the labels remain.

    With `rescue` (axes that have an axis line), if that fails, dropping
    the one label whose removal leaves an acceptable fit is tried: a wrong
    label pulls the line towards itself, so the label farthest from it can
    be a right one ("0.5 0.0 0.5 1.0", where the first should read -0.5,
    loses the 0.0).  Not for axes without a line: short strokes of '+'
    markers pass for their ticks, and some subset of stray numbers nearby
    nearly always fits."""
    pairs = list(pairs)
    original = list(pairs)

    def lsq(pp, logv=False):
        """(a, b, relative residual of each pair) or None."""
        xs = [c for c, _ in pp]
        ys = [math.log10(v) if logv else v for _, v in pp]
        n = len(xs)
        mx, my = sum(xs) / n, sum(ys) / n
        sxx = sum((x - mx) ** 2 for x in xs)
        if sxx <= 0:
            return None
        a = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
        b = my - a * mx
        rng = max(ys) - min(ys)
        if rng <= 0:
            return None
        res = [abs(a * x + b - y) / rng for x, y in zip(xs, ys)]
        return a, b, res

    n0 = len(pairs)
    rounded = _rounded_log_steps(pairs, lsq)
    if rounded is not None:
        return rounded
    while len(pairs) >= max(2, n0 // 2 + 1):
        if len({v for _, v in pairs}) < 2:
            return None
        lin = lsq(pairs)
        if lin is None:
            return None
        best = ("linear", lin)
        vals = sorted(v for _, v in pairs)
        decades = all(v > 0 and abs(math.log10(v) - round(math.log10(v))) < 1e-9 for v in vals)
        if decades and len(set(vals)) == len(vals) and \
                all(abs(b / a - 10) < 1e-6 for a, b in zip(vals, vals[1:])):
            lg = lsq(pairs, True)   # 1, 10, 100, ... : a log10 axis
            if lg is not None:
                best = ("log", lg)
        elif all(v > 0 for _, v in pairs) and max(lin[2]) > 0.01:
            lg = lsq(pairs, True)
            if lg is not None and max(lg[2]) < max(lin[2]) / 10:
                best = ("log", lg)
        kind, (a, b, res) = best
        if max(res) <= 0.02 or (len(pairs) == 2 and n0 == 2):
            vals = [v for _, v in pairs]
            return {"kind": kind, "a": a, "b": b, "n": len(pairs), "resid": max(res),
                    "range": max(vals) - min(vals)}
        worst = max(range(len(pairs)), key=lambda i: res[i])
        pairs.pop(worst)  # drop a mismatched label and refit
    if rescue and len(original) >= 4:
        # a misread label lies far off the line through the others, which
        # fit almost exactly; labels that only roughly follow a scale (a
        # category axis of sizes 250, 180, 130, 100, 70) are no misreading
        best = None
        for i in range(len(original)):
            rest = original[:i] + original[i + 1:]
            m = fit_axis(rest) if len(rest) >= 3 else None
            if m is None or m["n"] != len(rest) or m["resid"] > 0.002:
                continue
            c, v = original[i]
            pred = map_value(m, c)
            off = abs(pred - v) / m["range"] if m["kind"] != "log" else \
                abs(math.log10(max(pred, 1e-300)) - math.log10(v)) / max(
                    math.log10(max(x for _, x in rest) / min(x for _, x in rest)), 1e-12) \
                if v > 0 else float("inf")
            if off >= 0.1 and (best is None or m["resid"] < best["resid"]):
                best = m
        return best
    return None


def _rounded_log_steps(pairs, lsq):
    """A log axis whose ticks step evenly (a constant ratio) but whose
    labels between the decades are rounded names: 1x, 2x, 5x, 10x at equal
    spacing are 1, 2.15, 4.64, 10.  With 2+ labels that are exact powers of
    ten, ticks evenly spaced (within 2%) and the other labels within 10% of
    the values the decades give them, the mapping is fitted to the decades
    alone.  None otherwise."""
    if len(pairs) < 4 or any(v <= 0 for _, v in pairs):
        return None
    ps = sorted(pairs)
    gaps = [b[0] - a[0] for a, b in zip(ps, ps[1:])]
    med = sorted(gaps)[len(gaps) // 2]
    if med <= 0 or any(abs(g - med) > 0.02 * med for g in gaps):
        return None
    dec = [(c, v) for c, v in ps if abs(math.log10(v) - round(math.log10(v))) < 1e-9]
    if len(dec) < 2 or len(dec) == len(ps) or len({v for _, v in dec}) < 2:
        return None
    fit = lsq(dec, True)
    if fit is None or max(fit[2]) > 1e-3:
        return None
    a, b, _ = fit
    if any(abs(10 ** (a * c + b) - v) > 0.1 * v for c, v in ps):
        return None
    vals = [v for _, v in ps]
    return {"kind": "log", "a": a, "b": b, "n": len(ps), "resid": max(fit[2]),
            "range": max(vals) - min(vals)}


def map_value(m, c):
    """Page coordinate -> data value through an axis mapping.  Values
    closer to zero than the fit's own error are reported as 0."""
    if m["kind"] == "nominal":
        return _nearest_tick(m, c)
    if m["kind"] == "piecewise" and c > m["cut"]:
        return m["a2"] * c + m["b2"]
    v = m["a"] * c + m["b"]
    if m["kind"] == "log":
        try:
            return 10 ** v
        except OverflowError:             # far beyond the axis (a stray mark)
            return math.inf
    # values closer to zero than the axis fit's own residual are fitting noise
    eps = min(max(2 * m.get("resid", 0.0), 1e-9), 2e-6) * m["range"]
    return 0.0 if abs(v) < eps else v


# id(mapping) -> (mapping, positions, ticks): every point of a category axis
# is looked up, and graphs may hold 100 000 points.  The mapping is kept in
# the entry so that a reused id (a mapping freed and another made) is noticed.
_NOMINAL = {}


def _nearest_tick(m, c):
    """The label of the tick nearest c (the first such tick on a tie), by
    binary search over the distinct tick positions."""
    ticks, best = _nearest(m, c)
    return ticks[best][1]


def nominal_rank(m, c):
    """Where the category nearest c comes along a category axis (0 for the
    first position), for putting categories in axis order."""
    return _nearest(m, c)[1]


def _nearest(m, c):
    """(distinct ticks in position order, index of the one nearest c)."""
    entry = _NOMINAL.get(id(m))
    if entry is None or entry[0] is not m:
        first = {}
        for k, (pos, label) in enumerate(m["ticks"]):
            first.setdefault(pos, (k, label))
        pos = sorted(first)
        entry = _NOMINAL[id(m)] = (m, pos, [first[q] for q in pos])
    _, pos, ticks = entry
    i = bisect.bisect_left(pos, c)
    cands = [j for j in (i - 1, i) if 0 <= j < len(pos)]
    best = min(cands, key=lambda j: (abs(pos[j] - c), ticks[j][0]))
    return ticks, best


def nominal_map(labelled):
    """Mapping of a category axis: [((position, label), text item)]."""
    return {"kind": "nominal", "ticks": [tv for tv, _ in labelled], "a": 0.0, "b": 0.0,
            "n": len(labelled), "resid": 0.0, "range": 1.0}


def find_break_marks(paths):
    """Boxes of short open curved strokes (pieces of the wiggle lines
    that mark broken axes).  They decide where a piecewise axis is cut, and
    keep the wiggles from being read as outlined glyphs."""
    out = []
    for p in paths:
        if not p["stroke"] or p["fill"]:
            continue
        for sp in p["subpaths"]:
            if sp["closed"] or not sp["segs"] or any(seg[0] != "c" for seg in sp["segs"]):
                continue
            pts = control_points(sp)
            b = bbox_of(pts)
            ends = math.hypot(pts[-1][0] - pts[0][0], pts[-1][1] - pts[0][1])
            # an open stroke whose ends are well apart (not a circle)
            if b[2] - b[0] < 20 and b[3] - b[1] < 20 and \
                    ends > 0.6 * max(b[2] - b[0], b[3] - b[1]):
                out.append(b)
    return out


def piecewise_axis(pairs, orient, apos):
    """An axis broken by a wiggle line: the labels form two linear runs with
    the same scale and a jump in value where the wiggle crosses the axis.
    Returns a 'piecewise' mapping (cut at the wiggle) or None."""
    pp = sorted(pairs)
    n = len(pp)
    if n < 4:
        return None
    k = 0 if orient == "x" else 1
    found = None
    for i in range(2, n):
        lo, hi = pp[:i], pp[i:]
        if max(len(lo), len(hi)) < 3:
            continue
        m1 = fit_axis(lo)
        if len(hi) == 1 and m1:
            # one label beyond the break: the same scale continues there
            c, v = hi[0]
            m2 = dict(m1, b=v - m1["a"] * c, n=1)
        else:
            m2 = fit_axis(hi)
        if not m1 or not m2 or m1["kind"] != "linear" or m2["kind"] != "linear" or \
                m1["n"] < len(lo) or m2["n"] < len(hi) or m1["a"] * m2["a"] <= 0:
            continue
        if not 0.85 < m1["a"] / m2["a"] < 1.18:
            continue
        c0, c1 = lo[-1][0], hi[0][0]
        # the second run continues beyond where the first run would be
        gap = (m2["a"] * c1 + m2["b"]) - (m1["a"] * c1 + m1["b"])
        if gap * m1["a"] <= 0 or abs(gap) < 0.5 * abs(m1["a"]) * (c1 - c0):
            continue
        # a wiggle crossing the axis line between the two runs
        marks = [b for b in PAGE.break_marks
                 if c0 < (b[k] + b[k + 2]) / 2 < c1
                 and b[1 - k] - 2 <= apos <= b[3 - k] + 2]
        if not marks:
            continue
        if found is not None:
            return None                      # ambiguous
        found = (median((b[k] + b[k + 2]) / 2 for b in marks), m1, m2)
    if found is None:
        return None
    cut, m1, m2 = found
    vals = [v for _, v in pp]
    return {"kind": "piecewise", "a": m1["a"], "b": m1["b"], "a2": m2["a"], "b2": m2["b"],
            "cut": cut, "n": n, "resid": max(m1["resid"], m2["resid"]),
            "range": max(vals) - min(vals)}

"""Tick labels: pairing ticks with the label texts beyond them, splitting
strings that hold several labels, month/year and '95-style year axes,
category labels, labels shared by neighbouring axes and axis multipliers
such as "x10^-9".
"""

import re
import sys

from .context import PAGE
from .scales import fit_axis, nominal_map
from .text import SHORT_YEAR_RE, parse_number


def compose_month_axis(pairs, numeric, orient, apos):
    """Month names on an axis read as 0..11.  When year numbers are written
    beyond the month labels (one per run of months), each tick becomes
    year + month/12; months of runs without a year continue the count."""
    items = getattr(pairs, "items", None)
    if not items or not all(tx.get("month") is not None for tx in items):
        return pairs
    k = 0 if orient == "x" else 1
    ticks = [t for t, _ in pairs]
    months = [int(v) for _, v in pairs]
    # runs: a new run starts where the month number goes down
    runs, cur = [], [0]
    for i in range(1, len(months)):
        if months[i] <= months[i - 1]:
            runs.append(cur)
            cur = []
        cur.append(i)
    runs.append(cur)
    if len(runs) == 1 and not any(1000 <= t["value"] <= 2999 for t in numeric
                                  if t.get("month") is None and t["value"] is not None):
        return pairs                                  # plain months 0..11
    far = max(abs((tx["bbox"][1 - k] + tx["bbox"][3 - k]) / 2 - apos) for tx in items)
    years = [t for t in numeric if t.get("month") is None and t["value"] is not None
             and float(t["value"]).is_integer() and 1000 <= t["value"] <= 2999
             and abs(t["center"][1 - k] - apos) > far * 0.8]
    run_year = []
    for run in runs:
        lo = min(ticks[i] for i in run) - 0.6 * (ticks[1] - ticks[0] if len(ticks) > 1 else 10)
        hi = max(ticks[i] for i in run) + 0.6 * (ticks[1] - ticks[0] if len(ticks) > 1 else 10)
        ys = [t for t in years if lo <= t["center"][k] <= hi]
        run_year.append(int(min(ys, key=lambda t: abs(t["center"][1 - k] - apos))["value"]) if ys else None)
    if not any(y is not None for y in run_year):
        out = []
        for r, run in enumerate(runs):
            for i in run:
                out.append((ticks[i], float(months[i] + 12 * r)))
        return LabelPairs(out, pairs.angles, items)
    base = next((y - r for r, y in enumerate(run_year) if y is not None))
    out = []
    for r, run in enumerate(runs):
        y = run_year[r] if run_year[r] is not None else base + r
        for i in run:
            out.append((ticks[i], y + months[i] / 12.0))
    return LabelPairs(out, pairs.angles, items)


def fix_short_year_centuries(pairs):
    """Short years ('95) next to full years on one axis: give each the
    century that keeps the labels in axis order."""
    items = getattr(pairs, "items", None)
    if not items:
        return pairs
    short = [k for k, tx in enumerate(items) if SHORT_YEAR_RE.fullmatch(tx["text"].strip())]
    full = [k for k, tx in enumerate(items) if k not in short and 1000 <= pairs[k][1] <= 2999]
    if not short or not full:
        return pairs
    out = list(pairs)
    for k in short:
        c, v = out[k]
        yy = int(v) % 100
        best = None
        for cent in (1800, 1900, 2000, 2100):
            cand = cent + yy
            # count full-year labels on the wrong side of this candidate
            bad = sum(1 for f in full if (out[f][0] - c) * (out[f][1] - cand) < 0)
            near = min(abs(out[f][1] - cand) for f in full)
            if best is None or (bad, near) < best[0]:
                best = ((bad, near), cand)
        out[k] = (c, float(best[1]))
    return LabelPairs(out, pairs.angles, items)


def _label_anchor(tx, orient, axis_pos):
    """Coordinate along the axis that a (possibly slanted) label points at:
    the end of the text nearest to the axis line."""
    i = 0 if orient == "x" else 1
    if tx.get("centres"):                  # outlined word: nearest glyph
        c = min(tx["centres"], key=lambda c: abs(c[1 - i] - axis_pos))
        return c[i]
    ang = abs(tx.get("angle", 0.0)) % 180
    if orient == "x" and tx["rotated"] or orient == "y" and abs(ang - 90) < 75 and tx["rotated"]:
        p0, p1 = tx["p0"], tx["p1"]
        end = p0 if abs(p0[1 - i] - axis_pos) < abs(p1[1 - i] - axis_pos) else p1
        return end[i]
    return tx["center"][i]


def nominal_axis(g, orient, line, debug):
    """Ticks labelled with words (category names): the axis maps a position
    to the label of the nearest category.  Categories sit at the ticks or,
    as in Excel, midway between ticks that separate them.  Labels that
    cannot be read (text drawn as outlines) are numbered #1, #2, ... in
    axis order."""
    if line is None or len(g["pos"]) < 2:
        return None
    alo, ahi, apos = line
    ticks = g["pos"]

    def gap_of(tx):
        """Distance of a label from the axis line."""
        b = tx["bbox"]
        lo, hi = (b[1], b[3]) if orient == "x" else (b[0], b[2])
        return max(lo - apos, apos - hi)

    def match(places):
        """Pair category positions with label candidates beside the axis:
        [(position, text item, off-centre distance)]."""
        if len(places) < 2:
            return []
        spacing = min(b - a for a, b in zip(places, places[1:]))
        cands = []
        for j, tx in enumerate(PAGE.nominal_labels):
            b = tx["bbox"]
            s = tx["size"] or 1.0
            lo, hi = (b[1], b[3]) if orient == "x" else (b[0], b[2])
            gp = gap_of(tx)
            if lo <= apos <= hi or not (-0.3 * s <= gp <= 4 * s):
                continue
            # where along the axis the label points (for unreadable outlined
            # words any of its glyphs or ends may be the anchor)
            ancs = [_label_anchor(tx, orient, apos)]
            if tx.get("centres") and not tx.get("glyph"):     # short outlined word
                k = 0 if orient == "x" else 1
                ancs += [c[k] for c in tx["centres"]] + [b[k], b[k + 2]]
            for i, t in enumerate(places):
                d = min(abs(a - t) for a in ancs)
                if d <= max(0.3 * spacing, 0.3 * s) + 1e-9:
                    cands.append((d, i, j, gp, s))
        if not cands:
            return []
        # category labels form one row at one distance from the axis: the
        # nearest candidate of each place defines the row (captions, titles
        # and the inner letters of slanted labels lie further away)
        nearest = {}
        for d, i, j, gp, s in cands:
            nearest[i] = min(nearest.get(i, gp), gp)
        gaps = sorted(nearest.values())
        mg = gaps[len(gaps) // 2]
        sizes = sorted(s for d, i, j, gp, s in cands if abs(gp - nearest[i]) < 1e-9)
        ms = sizes[len(sizes) // 2]
        cands = [c for c in cands if abs(c[3] - mg) <= 0.6 * ms and abs(c[4] - ms) <= 0.25 * ms]
        cands.sort()
        used_t, used_l, pairs = set(), set(), []
        for d, i, j, gp, s in cands:
            if i in used_t or j in used_l:
                continue
            used_t.add(i)
            used_l.add(j)
            pairs.append((places[i], PAGE.nominal_labels[j], d))
        return pairs

    # labels at the ticks, or (Excel) midway between ticks: keep the layout
    # that labels the larger share of its places, then the better centred
    on_ticks = match(ticks)
    between = match([(a + b) / 2 for a, b in zip(ticks, ticks[1:])])
    best = None
    for pairs, n_places in ((on_ticks, len(ticks)), (between, len(ticks) - 1)):
        if len(pairs) < max(2, 0.6 * n_places):
            continue
        side = [1 if tx["bbox"][1 if orient == "x" else 0] > apos else -1 for _, tx, _ in pairs]
        if abs(sum(side)) < 0.8 * len(side):
            continue                          # labels on both sides: not a label row
        key = (len(pairs) / n_places, -sum(d for _, _, d in pairs) / len(pairs))
        if best is None or key > best[0]:
            best = (key, pairs)
    if best is None:
        return None
    pairs = sorted(best[1], key=lambda p: p[0])
    if len(pairs) < 3:            # two stray words are no category axis
        return None
    # categories are spread along a real axis, not crowded into specks
    if ahi - alo < 30 or min(b[0] - a[0] for a, b in zip(pairs, pairs[1:])) < 3:
        return None
    out = []
    # names drawn as outlines cannot be read reliably: number them instead
    readable = all(tx.get("text") and not tx.get("outlined") for _, tx, _ in pairs)
    for k, (t, tx, _) in enumerate(pairs, 1):
        out.append(((t, tx["text"].strip() if readable else "#%d" % k), tx))
    if debug:
        print("[debug] nominal %s-axis: %s" % (orient, [(round(t, 1), v) for (t, v), _ in out]),
              file=sys.stderr)
    return out


def split_labels_at_ticks(ticks, orient, numeric):
    """Labels of neighbouring ticks may be written as one string ('510 20'
    for 5, 10 and 20).  A numeric text covering two or more ticks is cut
    into digit groups, each centred on one tick."""
    if len(ticks) < 2:
        return numeric
    spacing = min(b - a for a, b in zip(ticks, ticks[1:]))
    k = 0 if orient == "x" else 1
    out = []
    for tx in numeric:
        gl = [g for g in tx.get("glyphs", ()) if not g[0].isspace()]
        if tx["rotated"] or len(gl) < 2:
            out.append(tx)
            continue
        lo, hi = tx["bbox"][k], tx["bbox"][k + 2]
        inside = [t for t in ticks if lo - 0.3 * spacing <= t <= hi + 0.3 * spacing]
        if len(inside) < 2:
            out.append(tx)
            continue
        n = len(gl)
        centre = lambda i, j: (gl[i][1][k] + gl[j - 1][2][k]) / 2
        # dynamic programme: best[i][m] = (cost, number of groups, previous
        # state) for glyphs[:i] cut into groups, the last one centred on
        # tick m-1 (ticks may stay unlabelled)
        INF = float("inf")
        best = [[(INF, 0, None)] * (len(inside) + 1) for _ in range(n + 1)]
        best[0][0] = (0.0, 0, None)
        for i in range(n):
            for m in range(len(inside) + 1):
                c0, k0, _ = best[i][m]
                if c0 == INF:
                    continue
                for j in range(i + 1, n + 1):
                    cj = centre(i, j)
                    for m2 in range(m, len(inside)):
                        d = abs(cj - inside[m2])
                        if d > 0.12 * spacing:      # labels are centred on ticks
                            continue
                        # every label found earns a bonus: prefer the cut
                        # into the most labels, then the best centred one
                        cost = c0 + d - spacing
                        if cost < best[j][m2 + 1][0]:
                            best[j][m2 + 1] = (cost, k0 + 1, (i, m))
        ends = [(best[n][m][0], m) for m in range(1, len(inside) + 1)
                if best[n][m][0] < INF and best[n][m][1] >= 2]
        if not ends:
            out.append(tx)
            continue
        _, m = min(ends)
        groups, j = [], n
        while m:
            i, pm = best[j][m][2]
            groups.append((i, j))
            j, m = i, pm
        groups.reverse()
        parts = []
        for i, j in groups:
            txt = "".join(g[0] for g in gl[i:j])
            v = parse_number(txt)
            if v is None:
                break
            p0, p1 = gl[i][1], gl[j - 1][2]
            part = dict(tx, text=txt, value=v, p0=p0, p1=p1, glyphs=gl[i:j])
            b = tx["bbox"]
            nb = list(b)
            nb[k], nb[k + 2] = min(p0[k], p1[k]), max(p0[k], p1[k])
            part["bbox"] = tuple(nb)
            c = list(tx["center"])
            c[k] = (nb[k] + nb[k + 2]) / 2
            part["center"] = tuple(c)
            parts.append(part)
        out.extend(parts if len(parts) == len(groups) else [tx])
    return out


def assign_labels(ticks, orient, outer, sign, numeric):
    """Pair each tick with the numeric label just beyond it (on the `sign`
    side of `outer`, centred on the tick).  Each label and each tick is used
    once, best matches first.  Returns a LabelPairs list of (tick, value)."""
    spacing = min((b - a for a, b in zip(ticks, ticks[1:])), default=0) or 1e9
    cands = []
    for i, t in enumerate(ticks):
        for j, tx in enumerate(numeric):
            size = tx["size"] or 1.0
            x0, y0, x1, y1 = tx["bbox"]
            cx, cy = tx["center"]
            # ref: the label's position along the axis; gap: its distance
            # beyond the tick ends; ptol: how far off-centre it may be
            if orient == "y":       # tick is horizontal, labels left/right
                ref = cy
                gap = (outer - x1) if sign < 0 else (x0 - outer)
                ptol = 0.8 * size
            else:                   # tick is vertical, labels below/above
                ang = abs(tx.get("angle", 0.0)) % 180
                if tx["rotated"] and abs(ang - 90) > 15:
                    # oblique labels point at their tick with the end
                    # nearest to the axis
                    p0, p1 = tx["p0"], tx["p1"]
                    anc = p1 if abs(p1[1] - outer) < abs(p0[1] - outer) else p0
                    ref = anc[0]
                    ptol = 1.5 * size
                else:
                    ref = cx
                    ptol = 0.8 * size
                gap = (outer - y1) if sign < 0 else (y0 - outer)
            dperp = abs(ref - t)
            if dperp > min(ptol, 0.5 * spacing + 1e-9):
                continue                      # not centred on this tick
            if gap < -0.5 * size or gap > 5 * size:
                continue                      # on the wrong side, or too far
            cands.append((dperp + 0.2 * max(gap, 0), i, j))
    # greedy matching: the best centred, closest pairs first
    cands.sort()
    used_t, used_x, trip = set(), set(), []
    for _, i, j in cands:
        if i in used_t or j in used_x:
            continue
        used_t.add(i)
        used_x.add(j)
        trip.append((ticks[i], numeric[j]["value"], numeric[j]))
    trip.sort(key=lambda t: t[0])
    return LabelPairs([(t, v) for t, v, _ in trip], [tx.get("angle", 0.0) for _, _, tx in trip],
                      [tx for _, _, tx in trip])


class LabelPairs(list):
    """List of (tick position, label value) that also remembers the reading
    direction (degrees) and the text items of the labels used."""
    def __init__(self, pairs, angles, items=()):
        list.__init__(self, pairs)
        self.angles = angles
        self.items = list(items)


def snapped_angle(angles):
    """Common reading direction of labels: 0, 90, -90 or 180 (None if mixed
    or oblique)."""
    if not angles:
        return None
    snaps = []
    for a in angles:
        s = min((0, 90, -90, 180, -180), key=lambda r: abs(a - r))
        if abs(a - s) > 15:
            return None
        snaps.append(180 if s == -180 else s)
    return snaps[0] if all(s == snaps[0] for s in snaps) else None


def resolve_shared_labels(axes):
    """A tick label belongs to one axis only.  Mirrored tick rows (ticks on
    all four sides of a box) and neighbouring panels can reach the same
    labels; each label goes to the axis line nearest to it, and axes left
    with too few labels are dropped."""
    def dist(a, tx):
        b = tx["bbox"]
        lo, hi = (b[0], b[2]) if a["orient"] == "y" else (b[1], b[3])
        d = max(lo - a["pos"], a["pos"] - hi, 0.0)
        # a label never lies inside the box of the axis it belongs to
        if a.get("inside") and ((lo + hi) / 2 - a["pos"]) * a["inside"] > 0:
            d += 1000.0
        return d
    owner = {}
    for ai, a in enumerate(axes):
        for _, tx in a.get("labels", ()):
            d = dist(a, tx)
            k = id(tx)
            if k not in owner or d < owner[k][0] - 1e-6:
                owner[k] = (d, ai)
    out = []
    for ai, a in enumerate(axes):
        labels = a.get("labels")
        if not labels:
            out.append(a)
            continue
        kept = [(tv, tx) for tv, tx in labels if owner[id(tx)][1] == ai]
        if len(kept) == len(labels):
            out.append(a)
            continue
        pairs = LabelPairs([tv for tv, _ in kept], [tx.get("angle", 0.0) for _, tx in kept],
                           [tx for _, tx in kept])
        if a["map"]["kind"] == "nominal":
            m = nominal_map(kept) if len(kept) >= 3 else None
        else:
            m = fit_axis(pairs)
        if m is None:
            continue
        b = dict(a, map=m, ticks=pairs, labels=kept,
                 label_angle=snapped_angle(pairs.angles))
        out.append(b)
    return out


_MULT_RE = re.compile(r"^(?:[x\u00d7*]\s*)?10\^([+-]?\d+)$")


def apply_axis_multipliers(axes, texts):
    """Scale factors written once at the end of an axis, e.g. 'x10^-9' above
    the top of a y axis or at the right end of an x axis.  (The 'x' itself
    is often a symbol glyph or a drawing, so only '10^n' may remain.)"""
    used = set()
    for a in axes:
        for _, tx in a.get("labels", ()):
            used.add(id(tx))
    for a in axes:
        labels = a.get("labels") or []
        if a["map"]["kind"] == "nominal":
            continue
        if not labels or a["map"]["kind"] == "log" and all(
                _MULT_RE.match(tx["text"].strip()) for _, tx in labels):
            continue
        if any(_MULT_RE.match(tx["text"].strip()) for _, tx in labels):
            continue                 # labels are powers of ten themselves
        best = None
        for t in texts:
            m = _MULT_RE.match(t["text"].strip())
            if not m or id(t) in used or t["rotated"]:
                continue
            s = t["size"] or 1.0
            b = t["bbox"]
            if a["orient"] == "y":
                ok = (a["hi"] - 0.5 * s <= b[1] <= a["hi"] + 3 * s and
                      a["pos"] - 6 * s <= b[0] <= a["pos"] + 2 * s)
                d = abs(b[1] - a["hi"])
            else:
                lab_c = sum(tx["center"][1] for _, tx in labels) / len(labels)
                ok = (a["hi"] - 3 * s <= b[0] <= a["hi"] + 3 * s and
                      abs(t["center"][1] - lab_c) <= 2.5 * s)
                d = abs(b[0] - a["hi"])
            if ok and (best is None or d < best[0]):
                best = (d, int(m.group(1)), t)
        if best:
            e = best[1]
            mp = dict(a["map"])
            if mp["kind"] == "log":
                mp["b"] += e
            else:
                mp["a"] *= 10.0 ** e
                mp["b"] *= 10.0 ** e
                if mp["kind"] == "piecewise":
                    mp["a2"] *= 10.0 ** e
                    mp["b2"] *= 10.0 ** e
                mp["range"] = mp.get("range", 1.0) * 10.0 ** e
            a["map"] = mp
            a["multiplier"] = e
            used.add(id(best[2]))
    return axes

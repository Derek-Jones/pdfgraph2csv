"""Tick labels: pairing ticks with the label texts beyond them, splitting
strings that hold several labels, month/year and '95-style year axes,
category labels, labels shared by neighbouring axes and axis multipliers
such as "x10^-9".
"""

import math
import bisect
import re
import sys

from .geometry import median
from .scales import fit_axis, nominal_map
from .text import SHORT_YEAR_RE, duration_parts, parse_number


def duration_axis(pairs):
    """Labels that are all durations ('1 min', '1 hour', '1 day') are read
    in the smallest unit among them (the user's rule: an axis labelled in
    minutes, hours and days gives values in minutes; one labelled 1 s ...
    64 h gives seconds).  Returns (the pairs in that unit, the same counted
    in working time - a day of 8 hours, a week of 40 - or None when no label
    is in days or longer); None if the labels are not all durations.

    Charts of the length of tasks place '1 day' at 8 hours and '1 week' at
    40 on a log axis; the caller keeps the reading that fits the ticks."""
    items = getattr(pairs, "items", None)
    if not items or len(items) != len(pairs):
        return None
    parts = [duration_parts(tx["text"]) for tx in items]
    if any(p is None for p in parts):
        return None
    unit = min(u for _, u, _ in parts)
    calendar = LabelPairs([(c, n * u / unit) for (c, _), (n, u, _) in zip(pairs, parts)],
                          pairs.angles, items)
    if all(u == w for _, u, w in parts):
        return calendar, None
    work = LabelPairs([(c, n * w / unit) for (c, _), (n, _, w) in zip(pairs, parts)],
                      pairs.angles, items)
    return calendar, work


_YEAR_MIN = 1000        # a four-digit year: 1000 to 2999
_YEAR_MAX = 2999        # (the latest year)
_MONTH_ROW_FAR = 0.8    # a month row farther than 0.8 of the year row
_MONTH_RUN_STEPS = 0.6  # a year's months span its run of ticks plus 0.6 of a step


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
    if len(runs) == 1 and not any(_YEAR_MIN <= t["value"] <= _YEAR_MAX for t in numeric
                                  if t.get("month") is None and t["value"] is not None):
        return pairs                                  # plain months 0..11
    far = max(abs((tx["bbox"][1 - k] + tx["bbox"][3 - k]) / 2 - apos) for tx in items)
    years = [t for t in numeric if t.get("month") is None and t["value"] is not None
             and float(t["value"]).is_integer() and _YEAR_MIN <= t["value"] <= _YEAR_MAX
             and abs(t["center"][1 - k] - apos) > far * _MONTH_ROW_FAR]
    # a year is written under its run of months (centred on it, or under
    # its first month), a little beyond the month names
    step = ticks[1] - ticks[0] if len(ticks) > 1 else 10
    run_year = []
    for run in runs:
        lo = min(ticks[i] for i in run) - _MONTH_RUN_STEPS * step
        hi = max(ticks[i] for i in run) + _MONTH_RUN_STEPS * step
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
    full = [k for k, tx in enumerate(items) if k not in short and _YEAR_MIN <= pairs[k][1] <= _YEAR_MAX]
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


_SLANT_DEG = 15     # turned labels within 15 degrees of upright
_SIDEWAYS_DEG = 75  # sideways labels: within 75 degrees of vertical
_ANCHOR_UP = 0.35   # a turned label's anchor: 0.35 of its size up from its end


def _label_anchor(tx, orient, axis_pos):
    """Coordinate along the axis that a (possibly slanted) label points at:
    the end of the text nearest to the axis line."""
    i = 0 if orient == "x" else 1
    if tx.get("centres"):                  # outlined word: nearest glyph
        c = min(tx["centres"], key=lambda c: abs(c[1 - i] - axis_pos))
        return c[i]
    ang = abs(tx.get("angle", 0.0)) % 180
    if orient == "x" and tx["rotated"] and abs(ang - 90) <= _SLANT_DEG:
        return tx["center"][i]             # upright text: centred on its tick
    if (orient == "x" and tx["rotated"]) or (orient == "y" and abs(ang - 90) < _SIDEWAYS_DEG and tx["rotated"]):
        p0, p1 = tx["p0"], tx["p1"]
        end = p0 if abs(p0[1 - i] - axis_pos) < abs(p1[1 - i] - axis_pos) else p1
        # the middle of the text's end, not its baseline end: 0.35 em up
        # (3485513-020's labels slanted 60 degrees point 0.9 pt nearer
        # their columns of points)
        up = tx.get("up")
        if up and (up[0] or up[1]):
            n = math.hypot(up[0], up[1])
            return end[i] + up[i] / n * _ANCHOR_UP * (tx.get("size") or 0.0)
        return end[i]
    return tx["center"][i]


_FLUSH_MIN = 3        # a flush column has 3 labels or more
_FLUSH_GAP_EMS = 25   # within 25 font sizes of its axis
_FLUSH_ON_TICK = 0.3  # its labels on ticks within 0.3 of the spacing
_FLUSH_NEAR_EMS = 4   # one of them within 4 font sizes
_FLUSH_RAGGED = 0.6   # right ends ragged by over 0.6 of a font size


def _flush_column(apos, places, *, page):
    """(left edge, least gap) of y category labels set flush left beside a
    y axis line at `apos` with ticks at `places`, or None: three or more
    labels left of the line, each level with a tick (within 0.3 of the
    ticks' spacing), within 25 text sizes of the line, whose left edges
    agree within 2 pt (" IIAB, ε=|Δ|" starts 1.7 pt in), one of them within 4 text sizes of the line, their
    distances from it differing by more than 0.6 of a size
    (2020.01.30.927558.full-048: the model names beside the heat map's 12
    ticks, "IIAB, ε=|Δ|" ending 35 pt short of them)."""
    if len(places) < _FLUSH_MIN:
        return None
    ps = sorted(places)
    spacing = min(b - a for a, b in zip(ps, ps[1:]))
    cands = []
    for tx in page.nominal_labels:
        b = tx["bbox"]
        sz = tx["size"] or 1.0
        gap = apos - b[2]
        if not -1.0 <= gap <= _FLUSH_GAP_EMS * sz:
            continue
        c = 0.5 * (b[1] + b[3])
        if min(abs(c - p) for p in ps) <= _FLUSH_ON_TICK * spacing:
            cands.append((b[0], gap, sz))
    best = None
    for x0, _, _ in cands:
        col = [r for r in cands if abs(r[0] - x0) <= 2.0]
        # (their distances from the line differing by more than 0.6 of a
        # size: the one row at one distance would not take them)
        if len(col) >= _FLUSH_MIN and any(r[1] <= _FLUSH_NEAR_EMS * r[2] for r in col) and \
                max(r[1] for r in col) - min(r[1] for r in col) > _FLUSH_RAGGED * median(r[2] for r in col):
            if best is None or len(col) > len(best):
                best = col
    if not best:
        return None
    return (median(r[0] for r in best), min(r[1] for r in best))


_NOM_REACH_LO = 0.3      # category labels from 0.3 of a font size inside
_NOM_REACH_EMS = 4       # to 4 font sizes outside the axis
_NOM_ON_TICK = 0.3       # a label on a tick within 0.3 of the spacing or font size
_NOM_ROW_SIZE = 0.25     # labels of a row: sizes within 25%
_NOM_ROW_GAP = 0.6       # rows within 0.6 of the median size
_END_TICK_PT = 0.5       # a tick at an axis end: within 0.5 pt
_NOM_MIN_PLACES = 0.6    # labels on 60% of the places
_NOM_SIDE = 0.8          # labels mostly on one side: 80%
_NOM_FRACTION_STEP = 20  # coverage compared in steps of 1/20
_NOM_COVERED = 0.85      # candidate rows both covering 85% of places
_NOM_SPREAD = 0.5        # gaps within half of each other
_NOM_MIN = 3             # a category axis has 3 labels or more
_NOM_MIN_LENGTH_PT = 30  # and is 30 pt long or more
_NOM_MIN_GAP_PT = 3.0    # labels 3 pt apart or more
_NOM_INNER = 0.8         # labels for 80% of the inner ticks


def nominal_axis(g, orient, line, debug, *, page):
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
        """Distance of a label from the axis line (for grid lines standing
        in for ticks: from the nearer end of the grid, the label wholly
        beyond it - the labels may be at the end with no axis line)."""
        b = tx["bbox"]
        lo, hi = (b[1], b[3]) if orient == "x" else (b[0], b[2])
        # (labels set flush left in a column: the column's gap -
        # 2020.01.30.927558.full-026's model names)
        fl = g.get("flush_left")
        if fl and orient == "y" and abs(b[0] - fl[0]) <= 2.0 and hi <= apos + 1.0:
            return fl[1]
        if g.get("grid"):
            if hi <= g["lo"]:
                return g["lo"] - hi
            if lo >= g["hi"]:
                return lo - g["hi"]
            return -1e9                       # across the grid: no label of it
        return max(lo - apos, apos - hi)

    if orient == "y" and not g.get("flush_left"):
        fl = _flush_column(apos, ticks, page=page)
        if fl:
            g = dict(g, flush_left=fl)

    def match(places):
        """Pair category positions with label candidates beside the axis:
        [(position, text item, off-centre distance)]."""
        if len(places) < 2:
            return []
        spacing = min(b - a for a, b in zip(places, places[1:]))
        cands = []
        for j, tx in enumerate(page.nominal_labels):
            b = tx["bbox"]
            s = tx["size"] or 1.0
            lo, hi = (b[1], b[3]) if orient == "x" else (b[0], b[2])
            gp = gap_of(tx)
            if (lo <= apos <= hi and not g.get("grid")) or not (-_NOM_REACH_LO * s <= gp <= _NOM_REACH_EMS * s):
                continue
            # where along the axis the label points (for unreadable outlined
            # words any of its glyphs or ends may be the anchor)
            ancs = [_label_anchor(tx, orient, apos)]
            if tx.get("centres") and not tx.get("glyph"):     # short outlined word
                k = 0 if orient == "x" else 1
                ancs += [c[k] for c in tx["centres"]] + [b[k], b[k + 2]]
            for i, t in enumerate(places):
                d = min(abs(a - t) for a in ancs)
                if d <= max(_NOM_ON_TICK * spacing, _NOM_ON_TICK * s) + 1e-9:
                    cands.append((d, i, j, gp, s))
        if not cands:
            return []
        # category labels form one row at one distance from the axis: the
        # nearest candidate of each place defines the row (captions, titles
        # and the inner letters of slanted labels lie further away)
        nearest = {}
        for _d, i, _j, gp, _s in cands:
            nearest[i] = min(nearest.get(i, gp), gp)
        mg = median(nearest.values())
        ms = median(s for d, i, j, gp, s in cands if abs(gp - nearest[i]) < 1e-9)
        # long names staggered over two rows, alternate places in each
        # (Teaching-disciplined-softdev-008, Fig. 4: "Exercise 2", "Exercise
        # 4" ... on the first row, "Exercise 3", "Exercise 5" ... a line
        # further out): the places whose nearest label lies a line beyond
        # the first row take their labels from the second row
        row2 = {}
        first = sorted(i for i, gp in nearest.items() if abs(gp - mg) <= _NOM_ROW_GAP * ms)
        far = sorted(i for i, gp in nearest.items() if _NOM_ROW_GAP * ms < gp - mg <= 2.0 * ms)
        if len(first) >= 2 and len(far) >= 2:
            both = sorted(first + far)
            rows = [i in far for i in both]
            if all(a != b for a, b in zip(rows, rows[1:])):
                mg2 = median(nearest[i] for i in far)
                row2 = dict.fromkeys(far, mg2)
        cands = [c for c in cands if abs(c[4] - ms) <= _NOM_ROW_SIZE * ms and
                 abs(c[3] - row2.get(c[1], mg)) <= _NOM_ROW_GAP * ms]
        cands.sort()
        used_t, used_l, pairs = set(), set(), []
        for d, i, j, _gp, _s in cands:
            if i in used_t or j in used_l:
                continue
            used_t.add(i)
            used_l.add(j)
            pairs.append((places[i], page.nominal_labels[j], d))
        return pairs

    # labels at the ticks, or (Excel) midway between ticks: keep the layout
    # that labels the larger share of its places, then the better centred
    on_ticks = match(ticks)
    between = match([(a + b) / 2 for a, b in zip(ticks, ticks[1:])])
    best = None
    # (ticks at the ends of the axis line - a frame's sides - carry no
    # category label: 2355585.2355594-006's 31 benchmarks between its
    # panels' sides)
    n_on = len(ticks) - sum(1 for t in ticks if min(abs(t - alo), abs(t - ahi)) <= _END_TICK_PT
                            and not any(abs(t - p) < 1e-9 for p, _, _ in on_ticks))
    for pairs, n_places in ((on_ticks, n_on), (between, len(ticks) - 1)):
        layout = "between" if pairs is between else "on"
        if len(pairs) < max(2, _NOM_MIN_PLACES * n_places):
            continue
        side = [1 if tx["bbox"][1 if orient == "x" else 0] > apos else -1 for _, tx, _ in pairs]
        if abs(sum(side)) < _NOM_SIDE * len(side):
            continue                          # labels on both sides: not a label row
        # (shares within 5% are alike: then the better centred layout -
        # the same page's slanted names, 0.6 pt off their ticks and 1.3 pt
        # off the midpoints)
        key = (math.floor(len(pairs) / n_places * _NOM_FRACTION_STEP + 1e-9) / _NOM_FRACTION_STEP,
               -sum(d for _, _, d in pairs) / len(pairs))
        if best is None:
            best = (key, pairs, layout, n_places)
        elif min(key[0], best[0][0]) >= _NOM_COVERED and \
                min(-key[1], -best[0][1]) <= _NOM_SPREAD * max(-key[1], -best[0][1]):
            # both label most of their places, one less than half as far
            # off centre: that one (an outlined word may be anchored at
            # any of its glyphs, which pairs it loosely with any place)
            if -key[1] < -best[0][1]:
                best = (key, pairs, layout, n_places)
        elif key > best[0]:
            best = (key, pairs, layout, n_places)
    if g.get("label_pairs"):
        # the labels are known: one at each position (axes.
        # _number_category_ticks_axis, two alternating rows merged - too
        # close together to be matched again: VaskeBeaman2006-Lessonslearned-003)
        lp = g["label_pairs"]
        best = ((1.0, 0.0), [(c, tx, 0.0) for c, tx in lp], "on", len(lp))
    if best is None:
        return None
    pairs = sorted(best[1], key=lambda p: p[0])
    # two stray words are no category axis; but two readable names, one in
    # each of the two gaps between three ticks on an axis line, are an Excel
    # bar chart of two categories ("Yes", "No") - and two readable names on
    # the only two ticks of an axis line, level with each other, are an R
    # strip chart's two groups (BehavioralNetworkScience-121: "early",
    # "late")
    level = len(pairs) == 2 and abs(pairs[0][1]["bbox"][1 if orient == "x" else 0] -
                                    pairs[1][1]["bbox"][1 if orient == "x" else 0]) <= \
        _NOM_ON_TICK * max(pairs[0][1]["size"] or 1.0, 1.0)
    two = (len(pairs) == 2 and best[3] == 2 and line is not None and
           (best[2] == "between" or (best[2] == "on" and len(ticks) == 2 and level))
           and all(tx.get("text") and not tx.get("outlined") and
                   any(ch.isalpha() for ch in tx["text"]) for _, tx, _ in pairs))
    if len(pairs) < _NOM_MIN and not two:
        return None
    # categories are spread along a real axis, not crowded into specks
    # (the sides of small multiples may be shorter: 2411.16433v1-066's bar
    # charts, 24 pt wide)
    # (categories 3 pt apart at least - 1 pt when the labels are known, two
    # rows of rising numbers merged: VaskeBeaman2006-Lessonslearned-003's
    # Figure 1f, 2.8 pt apart)
    if (ahi - alo < _NOM_MIN_LENGTH_PT and not g.get("small_multiple")) or min(b[0] - a[0] for a, b in zip(pairs, pairs[1:])) < \
            (1.0 if g.get("label_pairs") else _NOM_MIN_GAP_PT):
        return None
    out = []
    # names drawn as outlines cannot be read reliably: number them instead
    readable = all(tx.get("text") and not tx.get("outlined") for _, tx, _ in pairs)
    if not readable and best[2] == "on":
        # (numbered, the names may as well be the ticks: every tick inside
        # the line's ends a category, when labels were found for 80% of
        # them - two slanted names run together, or one lost, would leave a
        # tick without one and give its points to a neighbour:
        # 2355585.2355594-006's 32 benchmarks, 31 names made out)
        inner = [t for t in ticks if min(abs(t - alo), abs(t - ahi)) > _END_TICK_PT]
        if len(pairs) >= _NOM_INNER * len(inner) and len(inner) > len(pairs):
            got = {round(t, 3): tx for t, tx, _ in pairs}
            ref = pairs[0][1]
            pairs = [(t, got.get(round(t, 3), ref), 0.0) for t in inner]
    for k, (t, tx, _) in enumerate(pairs, 1):
        out.append(((t, tx["text"].strip() if readable else "#%d" % k), tx))
    if debug:
        print("[debug] nominal %s-axis: %s" % (orient, [(round(t, 1), v) for (t, v), _ in out]),
              file=sys.stderr)
    return out


_SPLIT_REACH = 0.3  # labels within 0.3 of a spacing of the ticks
_SPLIT_OFF = 0.12   # a label over 0.12 of a spacing off its tick is between ticks


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
        inside = [t for t in ticks if lo - _SPLIT_REACH * spacing <= t <= hi + _SPLIT_REACH * spacing]
        if len(inside) < 2:
            out.append(tx)
            continue
        n = len(gl)
        def centre(i, j, gl=gl):
            return (gl[i][1][k] + gl[j - 1][2][k]) / 2
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
                        if d > _SPLIT_OFF * spacing:      # labels are centred on ticks
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
    once, best matches first.  Returns a LabelPairs list of (tick, value).

    A y label turned along the axis may end at its tick instead
    (Seongmin-PhD-044: ggplot's turned y labels, justified to the tick):
    pairing by either end is used only when it pairs two or more labels
    more than centring does (an end may lie near the next tick)."""
    centred = _assign_labels(ticks, orient, outer, sign, numeric, False)
    if orient != "y":
        return centred
    ends = _assign_labels(ticks, orient, outer, sign, numeric, True)
    return ends if len(ends) >= len(centred) + 2 else centred


_PAIR_REACH_EMS = 0.8   # a label within 0.8 font sizes along
_PAIR_ENDS_EMS = 0.3    # a turned label's ends within 0.3 of a font size
_PAIR_FAR_EMS = 1.5     # 1.5 font sizes for turned labels
_PAIR_BEFORE_EMS = 0.5  # a label from half a font size inside
_PAIR_AFTER_EMS = 5     # to 5 font sizes outside its axis
_PAIR_LIMIT = 0.5       # at most half a spacing from its tick
_PAIR_GAP_COST = 0.2    # cost of a label's distance from the axis


def _assign_labels(ticks, orient, outer, sign, numeric, by_ends):
    spacing = min((b - a for a, b in zip(ticks, ticks[1:])), default=0) or 1e9
    ordered = all(a <= b for a, b in zip(ticks, ticks[1:]))
    cands = []
    for j, tx in enumerate(numeric):
        size = tx["size"] or 1.0
        x0, y0, x1, y1 = tx["bbox"]
        cx, cy = tx["center"]
        # ref: the label's position along the axis; gap: its distance
        # beyond the tick ends; ptol: how far off-centre it may be
        refs = None
        if orient == "y":           # tick is horizontal, labels left/right
            ref = cy
            gap = (outer - x1) if sign < 0 else (x0 - outer)
            ptol = _PAIR_REACH_EMS * size
            ang = abs(tx.get("angle", 0.0)) % 180
            if by_ends and tx["rotated"] and abs(ang - 90) <= _SLANT_DEG:
                # (either end may point at the tick, at a small cost)
                refs = [(cy, 0.0), (y0, _PAIR_ENDS_EMS * size), (y1, _PAIR_ENDS_EMS * size)]
        else:                       # tick is vertical, labels below/above
            ang = abs(tx.get("angle", 0.0)) % 180
            if tx["rotated"] and abs(ang - 90) > _SLANT_DEG:
                # oblique labels point at their tick with the end
                # nearest to the axis
                p0, p1 = tx["p0"], tx["p1"]
                anc = p1 if abs(p1[1] - outer) < abs(p0[1] - outer) else p0
                ref = anc[0]
                ptol = _PAIR_FAR_EMS * size
            else:
                ref = cx
                ptol = _PAIR_REACH_EMS * size
            gap = (outer - y1) if sign < 0 else (y0 - outer)
        if gap < -_PAIR_BEFORE_EMS * size or gap > _PAIR_AFTER_EMS * size:
            continue                          # on the wrong side, or too far
        lim = min(ptol, _PAIR_LIMIT * spacing + 1e-9)
        for at, cost in refs or [(ref, 0.0)]:
            # the ticks it may be centred on (by bisection: rows of ticks
            # can be long and labels many)
            if ordered:
                near = range(bisect.bisect_left(ticks, at - lim),
                             bisect.bisect_right(ticks, at + lim))
            else:
                near = range(len(ticks))
            for i in near:
                dperp = abs(at - ticks[i])
                if dperp > lim:
                    continue                  # not centred on this tick
                cands.append((dperp + cost + _PAIR_GAP_COST * max(gap, 0), i, j))
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
    return LabelPairs.of([((t, v), tx) for t, v, tx in trip])


class LabelPairs(list):
    """List of (tick position, label value) that also remembers the reading
    direction (degrees) and the text items of the labels used: the reading
    direction tells whether a graph is turned, and the items are needed to
    find month/year rows and to give each label to one axis only."""
    def __init__(self, pairs, angles, items=()):
        list.__init__(self, pairs)
        self.angles = angles
        self.items = list(items)

    @classmethod
    def of(cls, labelled):
        """From [((tick, value), text item)]."""
        return cls([tv for tv, _ in labelled], [tx.get("angle", 0.0) for _, tx in labelled],
                   [tx for _, tx in labelled])


_SNAP_DEG = 15  # angles snapped to 0, 90, 180 within 15 degrees


def snapped_angle(angles):
    """Common reading direction of labels: 0, 90, -90 or 180 (None if mixed
    or oblique)."""
    if not angles:
        return None
    snaps = []
    for a in angles:
        s = min((0, 90, -90, 180, -180), key=lambda r: abs(a - r))
        if abs(a - s) > _SNAP_DEG:
            return None
        snaps.append(180 if s == -180 else s)
    return snaps[0] if all(s == snaps[0] for s in snaps) else None


_OTHER_SIDE_COST = 1000.0  # a label on the far side costs this much more
_SHARED_SLACK_PT = 0.5     # a label within an axis's extent: 0.5 pt
_SHARED_MIN = 3            # a shared axis keeps 3 labels or more


def resolve_shared_labels(axes):
    """A tick label belongs to one axis only.  Mirrored tick rows (ticks on
    all four sides of a box) and neighbouring panels can reach the same
    labels; each label goes to the axis line nearest to it, and axes left
    with too few labels are dropped.  Labels that one axis reads as a
    numeric scale go to it rather than to a nearer axis that takes them for
    categories (a grid line of a plot beside the y labels of an inset in
    it) - but never across another claimant's axis line: a label lies on
    the outside of its axis, so an axis whose line runs between the label
    and a second claimant takes it (Memory_systems_cacheDRAMdisk-051: bar
    edges inside a bar chart read as ticks and fitted its category labels
    0.8, 1.6, ... 25.6 to log and linear scales)."""
    def dist(a, tx):
        b = tx["bbox"]
        lo, hi = (b[0], b[2]) if a["orient"] == "y" else (b[1], b[3])
        d = max(lo - a["pos"], a["pos"] - hi, 0.0)
        # a label never lies inside the box of the axis it belongs to
        if a.get("inside") and ((lo + hi) / 2 - a["pos"]) * a["inside"] > 0:
            d += _OTHER_SIDE_COST
        return d
    def across(a, b, tx):
        """The line of axis a runs between label tx and axis b."""
        if not a["has_line"] or a["orient"] != b["orient"]:
            return False
        k = 0 if a["orient"] == "x" else 1
        c = tx["center"][k]
        if not a["lo"] - _SHARED_SLACK_PT <= c <= a["hi"] + _SHARED_SLACK_PT:
            return False
        lab = tx["center"][1 - k]
        return (lab - a["pos"]) * (b["pos"] - a["pos"]) < 0 and abs(b["pos"] - a["pos"]) > _SHARED_SLACK_PT
    claims = {}
    for ai, a in enumerate(axes):
        for _, tx in a.get("labels", ()):
            claims.setdefault(id(tx), []).append(ai)
    owner = {}
    for ai, a in enumerate(axes):
        cat = 1 if a["map"] and a["map"]["kind"] == "nominal" else 0
        for _, tx in a.get("labels", ()):
            k = id(tx)
            if any(aj != ai and across(axes[aj], a, tx) for aj in claims[k]):
                continue
            d = (cat, dist(a, tx))
            if k not in owner or d[0] < owner[k][0][0] or \
                    (d[0] == owner[k][0][0] and d[1] < owner[k][0][1] - 1e-6):
                owner[k] = (d, ai)
    out = []
    for ai, a in enumerate(axes):
        labels = a.get("labels")
        if not labels:
            out.append(a)
            continue
        kept = [(tv, tx) for tv, tx in labels if id(tx) in owner and owner[id(tx)][1] == ai]
        if len(kept) == len(labels):
            out.append(a)
            continue
        pairs = LabelPairs.of(kept)
        if a["map"]["kind"] == "nominal":
            m = nominal_map(kept) if len(kept) >= _SHARED_MIN else None
        else:
            m = fit_axis(pairs)
        if m is None:
            continue
        b = dict(a, map=m, ticks=pairs, labels=kept,
                 label_angle=snapped_angle(pairs.angles))
        out.append(b)
    return out


_MULT_RE = re.compile(r"^(?:[x\u00d7*]\s*)?10\^([+-]?\d+)$")


_MULT_BELOW_EMS = 0.5  # a multiplier from half a font size below the axis's end
_MULT_REACH_EMS = 3    # to 3 font sizes past it
_MULT_SIDE_EMS = 6     # beside the axis within 6 font sizes
_MULT_LEVEL_EMS = 2.5  # level with its labels within 2.5 font sizes


def apply_axis_multipliers(axes, texts):
    """Scale factors written once at the end of an axis, e.g. 'x10^-9' above
    the top of a y axis or at the right end of an x axis.  (The 'x' itself
    is often a symbol glyph or a drawing, so only '10^n' may remain.)"""
    used = {id(tx) for a in axes for _, tx in a.get("labels", ())}
    for a in axes:
        labels = a.get("labels") or []
        if a["map"]["kind"] == "nominal" or not labels:
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
                ok = (a["hi"] - _MULT_BELOW_EMS * s <= b[1] <= a["hi"] + _MULT_REACH_EMS * s and
                      a["pos"] - _MULT_SIDE_EMS * s <= b[0] <= a["pos"] + 2 * s)
                d = abs(b[1] - a["hi"])
            else:
                lab_c = sum(tx["center"][1] for _, tx in labels) / len(labels)
                ok = (a["hi"] - _MULT_REACH_EMS * s <= b[0] <= a["hi"] + _MULT_REACH_EMS * s and
                      abs(t["center"][1] - lab_c) <= _MULT_LEVEL_EMS * s)
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

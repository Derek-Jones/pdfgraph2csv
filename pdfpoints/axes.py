"""Finding axes.

Tick marks are groups of short parallel segments of identical length
(or, on plots without ticks, grid lines) touching an axis line.  Each
group is labelled and fitted (see labels.py and scales.py) to give an axis:
a dict with its orientation, extent, position and value mapping.
"""

import bisect
import math
import re
import sys

from .context import PAGE
from .geometry import (
    axis_aligned, median, merge_collinear, straight_segments, thin_rect_line, vertices)
from .labels import (
    LabelPairs, _label_anchor, assign_labels, compose_month_axis, duration_axis,
    fix_short_year_centuries, nominal_axis, snapped_angle,
    split_labels_at_ticks)
from .scales import fit_axis, nominal_map, piecewise_axis
from .text import month_index


def tick_groups(segs):
    """Groups of short parallel segments with identical extent."""
    groups = []
    # groups filed by their low end in buckets of 1 pt (the largest
    # tolerance): a segment joins the first group made that matches
    buckets = {}
    for lo, hi, pos in sorted(segs):
        L = hi - lo
        # long grid lines of side-by-side plots differ only slightly in
        # extent: keep their groups apart
        tol = max(0.05, min(0.1 * L, 1.0))
        b = int(math.floor(lo))
        best = None
        for bb in (b - 1, b, b + 1):
            for k in buckets.get(bb, ()):
                g = groups[k]
                if (best is None or k < best) and abs(g["lo"] - lo) <= tol and \
                        abs(g["hi"] - hi) <= tol:
                    best = k
        if best is not None:
            groups[best]["pos"].append(pos)
        else:
            buckets.setdefault(b, []).append(len(groups))
            groups.append({"lo": lo, "hi": hi, "pos": [pos]})
    res = []
    for g in groups:
        pos = []
        for q in sorted(set(round(p, 4) for p in g["pos"])):
            if not pos or q - pos[-1] > 0.05:   # the same tick filled and outlined
                pos.append(q)
        if len(pos) < 2:
            continue
        L = g["hi"] - g["lo"]
        span = pos[-1] - pos[0]
        if span <= 0:
            continue
        # short segments are tick marks; long ones may be grid lines, which
        # stand in for ticks on plots that have none (used only as fallback)
        # (against the run of lines, or against their spacing: a row of grid
        # lines may run through several side-by-side panels)
        gap = median(b - a for a, b in zip(pos, pos[1:]))
        res.append({"lo": g["lo"], "hi": g["hi"], "pos": pos, "len": L, "span": span,
                    "grid": L > 0.25 * span or L > 3 * gap})
    res.sort(key=lambda g: g["grid"])          # real ticks first
    return res


def _interior_side(a, perp_lines):
    """+1 / -1: the side of an axis line on which its plot box lies, from
    the perpendicular frame lines that meet the axis' ends (0 = unknown)."""
    if not a["has_line"]:
        return 0
    side = 0
    for end in (a["lo"], a["hi"]):
        for lo, hi, pos in perp_lines:
            if abs(pos - end) > 1.0:
                continue
            if abs(lo - a["pos"]) < 1.0 and hi - a["pos"] > 5:
                side += 1
            elif abs(hi - a["pos"]) < 1.0 and a["pos"] - lo > 5:
                side -= 1
    return (side > 0) - (side < 0)


def outlined_stroke_lines(subpaths, min_len=20.0, max_width=2.0):
    """The centre lines of long straight strokes converted to filled
    outlines that are not thin bars on their own: a panel border drawn as
    the band between an outer and an inner rectangle (two contours, or one
    contour joining them).  Two parallel edges at most `max_width` apart,
    each at least `min_len` long and overlapping along most of their
    length, are the two sides of one stroke."""
    edges = {"h": [], "v": []}
    for a, b in straight_segments({"subpaths": subpaths}):
        aa = axis_aligned(a, b)
        if aa and aa[2] - aa[1] >= min_len:
            edges[aa[0]].append(aa[1:])
    out = []
    for k, es in edges.items():
        es.sort(key=lambda e: e[2])
        used = set()
        for i, (lo, hi, pos) in enumerate(es):
            if i in used:
                continue
            for j in range(i + 1, len(es)):
                lo2, hi2, pos2 = es[j]
                if pos2 - pos > max_width:
                    break
                if j in used or pos2 - pos <= 0.01:
                    continue
                ov = min(hi, hi2) - max(lo, lo2)
                if ov >= 0.8 * min(hi - lo, hi2 - lo2):
                    out.append((k, max(lo, lo2), min(hi, hi2), (pos + pos2) / 2))
                    used.update((i, j))
                    break
    return out


def _page_segments(paths):
    """The page's horizontal and vertical straight pieces, as three
    {"h": [(lo, hi, pos)], "v": [...]} collections:
      open: pieces of open strokes (and strokes converted to thin filled
            rectangles), the candidates for tick marks and grid lines;
      all:  every straight piece, of which axis lines are made;
      dark: the dark ones, frames and panel borders.
    The minus signs of outlined labels (PAGE.minus_paths) are no ticks."""
    open_, all_, dark_ = {"h": [], "v": []}, {"h": [], "v": []}, {"h": [], "v": []}
    # the colours of the open strokes at each position, for telling the
    # line samples of a legend (one colour each) from tick marks
    _TICK_COLOURS["h"].clear()
    _TICK_COLOURS["v"].clear()
    for p in paths:
        if not p["stroke"]:
            if p["fill"] and p["idx"] not in PAGE.minus_paths:
                # strokes converted to thin filled rectangles
                wide = []
                for sp in p["subpaths"]:
                    ln = thin_rect_line(sp)
                    aa = axis_aligned(*ln) if ln else None
                    if aa:
                        all_[aa[0]].append(aa[1:])
                        open_[aa[0]].append(aa[1:])
                    else:
                        wide.append(sp)
                if wide:
                    dark = sum(p["fill_rgb"] or (0, 0, 0)) < 1.5
                    for k, lo, hi, pos in outlined_stroke_lines(wide):
                        all_[k].append((lo, hi, pos))
                        if dark:
                            dark_[k].append((lo, hi, pos))
            continue
        dark = sum(p["stroke_rgb"] or (0, 0, 0)) < 1.5
        for sp in p["subpaths"]:
            if sp["closed"] and p["idx"] not in PAGE.minus_paths:
                # a tick drawn as a tiny outlined (and maybe filled)
                # rectangle (InDesign): its centre line is the tick
                ln = thin_rect_line(sp)
                aa = axis_aligned(*ln) if ln else None
                if aa and aa[2] - aa[1] <= 12:
                    open_[aa[0]].append(aa[1:])
                    # its edges are no lines: the ends of a row of such
                    # ticks would join into a false axis line at their tips
                    all_[aa[0]].append(aa[1:])
                    continue
            for a, b in straight_segments({"subpaths": [sp]}):
                aa = axis_aligned(a, b)
                if not aa:
                    continue
                all_[aa[0]].append(aa[1:])
                if dark:
                    dark_[aa[0]].append(aa[1:])
                if not sp["closed"]:
                    open_[aa[0]].append(aa[1:])
                    rgb = p["stroke_rgb"]
                    _TICK_COLOURS[aa[0]].setdefault(round(aa[3], 1), set()).add(
                        tuple(round(c, 2) for c in rgb) if rgb else None)
    return open_, all_, dark_


_TICK_COLOURS = {"h": {}, "v": {}}       # orientation -> position -> colours


def _legend_samples(g0, k):
    """Whether a group of 'ticks' is the line samples of a legend (the
    densities of 2204.07073-010's inset, one line per year): each in a
    colour, three or more colours, none of them grey or black (tick marks
    are drawn in the axis colour; a coloured axis has one colour)."""
    cols = set()
    for t in g0["pos"]:
        cols |= _TICK_COLOURS[k].get(round(t, 1), set())
    if len(cols) < 3 or None in cols:
        return False
    return all(max(c) - min(c) > 0.2 for c in cols)


def _labels_in_use(axes):
    """Ids of the text items that already label one of `axes`."""
    return {id(tx) for a in axes for _, tx in a.get("labels", ())}


def _axes_on(axes, orient, line, tol):
    """The axes of `axes` lying along `line` (lo, hi, pos), within `tol`."""
    lo, hi, pos = line
    return [b for b in axes if b["orient"] == orient and abs(b["pos"] - pos) <= tol and
            b["lo"] < hi and lo < b["hi"]]


def _evenly_spaced(cs):
    """Whether the sorted positions cs step evenly (within 5%)."""
    gaps = [q - p for p, q in zip(cs, cs[1:])]
    med = median(gaps)
    return med > 0 and all(abs(d - med) <= 0.05 * med for d in gaps)


def _label_tick_group(line, cs, size, **flags):
    """A tick group for an axis without tick marks whose label centres `cs`
    stand in for the ticks: notional ticks a quarter of the labels' size
    long across the line (they decide how far away labels are looked for)."""
    pos = line[2]
    L = 0.25 * size
    return dict({"lo": pos - L, "hi": pos + L, "len": L, "grid": False, "label_ticks": True,
                 "pos": cs, "span": cs[-1] - cs[0]}, **flags)


def find_axes(paths, texts, debug=False):
    """Return a list of axis dicts (orientation 'x' or 'y')."""
    open_, all_, dark_ = _page_segments(paths)
    hs_open, vs_open, hs_all, vs_all = open_["h"], open_["v"], all_["h"], all_["v"]
    background_grid(paths, hs_all, vs_all, hs_open, vs_open)
    hs_dark, vs_dark = dark_["h"], dark_["v"]
    hs_lines = merge_collinear(hs_all)
    vs_lines = merge_collinear(vs_all)
    hs_dark, vs_dark = merge_collinear(hs_dark), merge_collinear(vs_dark)
    PAGE.dark_lines = (hs_dark, vs_dark)
    PAGE.all_lines = (hs_lines, vs_lines)
    PAGE.bare_axes = []
    numeric = [t for t in texts if t["value"] is not None]
    for t in texts:
        mi = month_index(t["text"]) if t["value"] is None else None
        if mi is not None:
            numeric.append(dict(t, value=float(mi), month=mi))
    axes = []
    # horizontal ticks -> y axis (lines are vertical), vertical ticks -> x axis
    for orient, ticksegs, lines in (("y", hs_open, vs_lines), ("x", vs_open, hs_lines)):
        for g0 in tick_groups(ticksegs):
            if _legend_samples(g0, "h" if orient == "y" else "v"):
                if debug:
                    print("[debug] %s-axis candidate: ticks at %s are a legend's line samples (coloured)"
                          % (orient, ["%.2f" % t for t in g0["pos"]]), file=sys.stderr)
                continue
            L = g0["len"]
            tol = max(0.05, 0.3 * L)
            # a group of identical ticks may belong to several axes (side by
            # side panels): split it by the axis lines the ticks touch
            subgroups = []
            covered = set()
            if g0["grid"]:
                tol = max(0.5, 0.002 * L)
            for lo, hi, pos in lines:
                if not (g0["lo"] - tol <= pos <= g0["hi"] + tol):
                    continue
                if hi - lo < (0.3 * L if g0["grid"] else 3 * L):
                    continue
                sub = [t for t in g0["pos"] if lo - tol <= t <= hi + tol]
                if len(sub) >= 2 and (hi - lo) >= 0.5 * (sub[-1] - sub[0]):
                    d = min(abs(pos - g0["lo"]), abs(pos - g0["hi"]))
                    subgroups.append((d, sub, (lo, hi, pos)))
            # keep the closest line for each set of ticks
            # (grid lines run between two frame lines: the axis is normally
            # the bottom / left one)
            subgroups.sort(key=lambda s: (s[0] if s[0] > 1.0 else 0.0, -len(s[1]), s[2][2])
                           if g0["grid"] else (s[0],))
            chosen = []
            for d, sub, line in subgroups:
                if covered.issuperset(sub):
                    continue
                covered.update(sub)
                chosen.append((sub, line))
            rest = [t for t in g0["pos"] if t not in covered]
            if len(rest) >= 2:
                chosen.append((rest, None))
            # grid lines: a piece cut off by a line across them (no axis
            # line: below) whose ticks all lie in another piece cut off by a
            # line is no set of its own - the vertical edges of 3485513-020's
            # bars cut its grid of 0 ... 1.5: the tallest bar's edge spans
            # the whole grid, a lower one only 0, 0.5, which took the axis.
            # (Side-by-side panels' pieces lie within the leftover set, which
            # has no line, and stay.)
            if g0["grid"]:
                def crossing(line):
                    if line is None:
                        return True
                    lo, hi, pos = line
                    tol2 = max(0.5, 0.01 * (hi - lo))
                    return not (abs(pos - g0["lo"]) <= tol2 or abs(pos - g0["hi"]) <= tol2)
                chosen = [(sub, line) for sub, line in chosen
                          if not (crossing(line) and any(set(sub) < set(o) and ol is not None
                                                         for o, ol in chosen))]
            for sub, line in chosen:
                if g0["grid"]:
                    if line is not None:
                        lo, hi, pos = line
                        tol2 = max(0.5, 0.01 * (hi - lo))
                        if not (abs(pos - g0["lo"]) <= tol2 or abs(pos - g0["hi"]) <= tol2):
                            line = None    # a grid line across them, not an axis line
                    if line is None:
                        # no axis line at all (ggplot2's theme_minimal: only
                        # grid lines, major and minor): the grid's own low
                        # end is the edge of the panel the labels stand by
                        line = (sub[0], sub[-1], g0["lo"])
                        if any(a["orient"] == orient and abs(a["pos"] - line[2]) <= 1.0 and
                               a["lo"] < line[1] and line[0] < a["hi"] for a in axes):
                            continue
                        axes_from_group(dict(g0, pos=sub, implicit=True), orient, line,
                                        numeric, axes, debug)
                        continue
                    lo, hi, pos = line
                    tol2 = max(0.5, 0.01 * (hi - lo))
                    if any(a["has_line"] for a in _axes_on(axes, orient, line, tol2)):
                        continue           # this axis already has real ticks
                g = dict(g0, pos=sub)
                if axes_from_group(g, orient, line, numeric, axes, debug) or line is None:
                    continue
                # one long frame line shared by a column (row) of panels, as
                # in lattice / facet plots: split it at the panel borders
                # (perpendicular frame lines meeting it away from any tick)
                lo, hi, pos = line
                perp = hs_dark if orient == "y" else vs_dark
                tol3 = max(0.5, 0.3 * L)
                meet = [(plo, phi, pp) for plo, phi, pp in perp
                        if lo + tol3 < pp < hi - tol3 and plo - tol3 <= pos <= phi + tol3
                        and _far_from_all(pp, sub, 0.15)]
                longest = max((phi - plo for plo, phi, pp in meet), default=0)
                # panel borders run across the whole grid; grid lines
                # inside a panel are short
                cuts = sorted(set(round(pp, 3) for plo, phi, pp in meet
                                  if phi - plo >= 0.4 * longest))
                if not cuts:
                    continue
                edges = [lo] + cuts + [hi]
                for a, b in zip(edges, edges[1:]):
                    part = [t for t in sub if a - 0.15 <= t <= b + 0.15]
                    if len(part) >= 2 and b - a > 3 * L:
                        # (no line-end ticks: the pieces end at the cuts)
                        axes_from_group(dict(g0, pos=part, extended=True), orient, (a, b, pos),
                                        numeric, axes, debug)
    _frame_side_axes(axes, hs_lines, vs_lines, hs_open, vs_open, numeric, debug)
    # axis lines without any tick marks (ggplot2 with axis.ticks blank):
    # the labels beside the line mark the positions
    for orient, lines in (("x", hs_lines), ("y", vs_lines)):
        for lo, hi, pos in lines:
            if hi - lo < 30:
                continue
            there = _axes_on(axes, orient, (lo, hi, pos), max(1.0, 0.01 * (hi - lo)))
            # (an axis made of two "ticks" - the frame's side lines - and
            # two labels near them gives way to a longer row of labels)
            if any(b["map"]["kind"] == "nominal" or b["map"].get("n", 0) > 2 for b in there):
                continue
            others = [b for b in axes if not any(b is t for t in there)]
            trial = list(others)
            if _label_ticks_axis(orient, (lo, hi, pos), numeric, trial, debug) and \
                    trial[-1]["map"].get("n", 0) > max([b["map"].get("n", 0) for b in there] or [0]):
                axes[:] = trial
            elif not there:
                # category labels (words, or outlines that cannot be read)
                _category_label_ticks_axis(orient, (lo, hi, pos), axes, debug)
    axes += _one_label_log_axes(axes, numeric, hs_open, vs_open, debug)
    for a in axes:
        a["inside"] = _interior_side(a, hs_lines if a["orient"] == "y" else vs_lines)
    return axes


def _light_rect(p, sp):
    """(x0, y0, x1, y1) of a filled axis-aligned rectangle in a light,
    not white, colour (a plot background: seaborn, ggplot2), else None."""
    rgb = p.get("fill_rgb")
    if not p["fill"] or rgb is None or min(rgb) < 0.75 or min(rgb) > 0.995:
        return None
    if any(s[0] != "l" for s in sp["segs"]) or not 3 <= len(sp["segs"]) <= 4:
        return None
    pts = vertices(sp)
    xs = sorted(set(round(x, 2) for x, _ in pts))
    ys = sorted(set(round(y, 2) for _, y in pts))
    if len(xs) != 2 or len(ys) != 2:
        return None
    return xs[0], ys[0], xs[1], ys[1]


def background_grid(paths, hs_all, vs_all, hs_open, vs_open):
    """Plots without tick marks or axis lines whose grid is drawn on a light
    background (seaborn's darkgrid, ggplot2's theme_grey):
      * one background rectangle with grid lines running across it: its
        edges are the axis lines the grid lines start on;
      * the background tiled with blocks of one colour separated by thin
        gaps (the grid shows through): each gap is a grid line, and the
        outline of the tiled area gives the axis lines.
    Adds the lines (and the gap grid lines) to the segment lists."""
    rects = {}
    for p in paths:
        if p["stroke"]:
            continue
        for sp in p["subpaths"]:
            r = _light_rect(p, sp)
            if r is not None and r[2] - r[0] >= 2 and r[3] - r[1] >= 2:
                rects.setdefault(tuple(round(c, 2) for c in p["fill_rgb"]), []).append(r)

    def edges(box):
        x0, y0, x1, y1 = box
        hs_all.extend([(x0, x1, y0), (x0, x1, y1)])
        vs_all.extend([(y0, y1, x0), (y0, y1, x1)])

    for rs in rects.values():
        big = [r for r in rs if r[2] - r[0] >= 40 and r[3] - r[1] >= 40]
        for r in big:
            x0, y0, x1, y1 = r
            tol = max(1.0, 0.01 * max(x1 - x0, y1 - y0))
            across = sum(1 for lo, hi, pos in vs_open
                         if abs(lo - y0) <= tol and abs(hi - y1) <= tol and x0 < pos < x1) + \
                sum(1 for lo, hi, pos in hs_open
                    if abs(lo - x0) <= tol and abs(hi - x1) <= tol and y0 < pos < y1)
            if across >= 2:
                edges(r)
        if len(rs) < 4:
            continue
        # tiles: blocks whose sides face each other across a thin gap
        ux0, uy0 = min(r[0] for r in rs), min(r[1] for r in rs)
        ux1, uy1 = max(r[2] for r in rs), max(r[3] for r in rs)
        if ux1 - ux0 < 40 or uy1 - uy0 < 40:
            continue
        area = sum((r[2] - r[0]) * (r[3] - r[1]) for r in rs)
        if area < 0.8 * (ux1 - ux0) * (uy1 - uy0):
            continue                          # not a tiled background
        xgaps, ygaps = set(), set()
        # a gap is thin: at most 8 pt and 15% of the blocks beside it
        for a in rs:
            for b in rs:
                gx, gy = b[0] - a[2], b[1] - a[3]
                if 0 < gx <= min(8.0, 0.15 * min(a[2] - a[0], b[2] - b[0])) and \
                        min(a[3], b[3]) - max(a[1], b[1]) > 1:
                    xgaps.add(round((a[2] + b[0]) / 2, 2))
                if 0 < gy <= min(8.0, 0.15 * min(a[3] - a[1], b[3] - b[1])) and \
                        min(a[2], b[2]) - max(a[0], b[0]) > 1:
                    ygaps.add(round((a[3] + b[1]) / 2, 2))
        if len(xgaps) + len(ygaps) < 2:
            continue
        for x in xgaps:
            vs_open.append((uy0, uy1, x))
            vs_all.append((uy0, uy1, x))
        for y in ygaps:
            hs_open.append((ux0, ux1, y))
            hs_all.append((ux0, ux1, y))
        edges((ux0, uy0, ux1, uy1))


def _frame_side_axes(axes, hs_lines, vs_lines, hs_open, vs_open, numeric, debug):
    """Axes on the sides of a plot frame whose end labels sit at the
    frame's corners without a tick (and that may have only one tick of
    their own: a right-hand scale of 0.01, 0.1, 1 with a tick at 0.1 only).
    For each axis found with a line, the perpendicular frame lines starting
    at its ends that carry no axis yet are tried with their two ends (and
    any ticks touching them) as tick positions; at least three labels must
    fit."""
    for a in list(axes):
        if not a["has_line"]:
            continue
        orient = "y" if a["orient"] == "x" else "x"
        lines = vs_lines if orient == "y" else hs_lines
        ticks = hs_open if orient == "y" else vs_open
        span = a["hi"] - a["lo"]
        tol = max(1.0, 0.01 * span)
        for end in (a["lo"], a["hi"]):
            for lo, hi, pos in lines:
                if abs(pos - end) > tol or hi - lo < 20:
                    continue
                if not (abs(lo - a["pos"]) <= tol or abs(hi - a["pos"]) <= tol):
                    continue                  # does not start at the axis line
                if _axes_on(axes, orient, (lo, hi, pos), tol):
                    continue                  # already an axis
                own = [(tlo, thi, tp) for tlo, thi, tp in ticks
                       if lo + tol < tp < hi - tol and thi - tlo < 0.1 * (hi - lo)
                       and (abs(tlo - pos) <= 0.5 or abs(thi - pos) <= 0.5
                            or tlo < pos < thi)]
                L = max([thi - tlo for tlo, thi, _ in own] or [2.0])
                tp = []
                for q in sorted([lo, hi] + [t for _, _, t in own]):
                    if not tp or q - tp[-1] > 0.05:
                        tp.append(q)
                g = {"lo": pos - L, "hi": pos + L, "len": L, "grid": False, "frame_ends": True,
                     "pos": tp}
                g["span"] = g["pos"][-1] - g["pos"][0]
                if not axes_from_group(g, orient, (lo, hi, pos), numeric, axes, debug):
                    if not _label_ticks_axis(orient, (lo, hi, pos), numeric, axes, debug):
                        _category_label_ticks_axis(orient, (lo, hi, pos), axes, debug)


# Helvetica / Arial digit metrics (1/1000 em): advance, ink left, ink right.
# Labels are centred by their advance width; a label drawn as outlines has
# only its ink box, which "1" (ink well right of its middle) and others pull
# off centre by up to 0.04 em.
_DIGIT_INK = {"0": (556, 37, 519), "1": (556, 101, 359), "2": (556, 26, 507),
              "3": (556, 34, 522), "4": (556, 25, 523), "5": (556, 32, 514),
              "6": (556, 38, 518), "7": (556, 37, 523), "8": (556, 38, 517),
              "9": (556, 42, 514), ".": (278, 87, 191), ",": (278, 87, 191),
              "-": (333, 44, 289), "\u2212": (584, 39, 545)}


def _advance_centre(t):
    """Middle of a horizontal label along x: of its advance box when known
    (real text), estimated from the ink box with standard digit metrics for
    a label drawn as outlines."""
    b = t["bbox"]
    s = t.get("text", "").strip()
    if not t.get("outlined") or not s or any(ch not in _DIGIT_INK for ch in s):
        return 0.5 * (b[0] + b[2])
    adv = sum(_DIGIT_INK[ch][0] for ch in s)
    ink_l = _DIGIT_INK[s[0]][1]
    ink_r = adv - _DIGIT_INK[s[-1]][0] + _DIGIT_INK[s[-1]][2]
    if ink_r <= ink_l:
        return 0.5 * (b[0] + b[2])
    scale = (b[2] - b[0]) / (ink_r - ink_l)
    return b[0] + (0.5 * adv - ink_l) * scale


def _label_ticks_axis(orient, line, numeric, axes, debug):
    """An axis line without tick marks whose labels mark the positions
    (Excel's category axis of a line chart: 1, 101, 201, ... evenly along the
    line, no ticks): a row of at least three numbers beside the line, within
    its span, evenly spaced, whose centres are the tick positions.  The
    values step evenly (linear) or by a constant ratio (log)."""
    lo, hi, pos = line
    tol = max(1.0, 0.01 * (hi - lo))
    # labels that already serve an axis with ticks are not this line's
    taken = _labels_in_use(axes)
    row = []
    for t in numeric:
        if t.get("rotated") or t.get("month") is not None or id(t) in taken:
            continue
        b, size = t["bbox"], t["size"] or 1.0
        c = _advance_centre(t) if orient == "x" else 0.5 * (b[1] + b[3])
        near, far = (b[1], b[3]) if orient == "x" else (b[0], b[2])
        gap = max(near - pos, pos - far)
        if lo - tol <= c <= hi + tol and 0 <= gap <= 2 * size:
            row.append((c, t, -1 if far <= pos + 0.5 * size else 1))
    if len(row) < 3:
        return False
    # one side of the line, one baseline (x) / one edge (y)
    side = max((-1, 1), key=lambda k: sum(1 for r in row if r[2] == k))
    row = sorted((r for r in row if r[2] == side), key=lambda r: r[0])
    key = (lambda t: t["bbox"][1]) if orient == "x" else \
        (lambda t: t["bbox"][2] if side < 0 else t["bbox"][0])
    ref = median(key(t) for _, t, _ in row)
    row = [r for r in row if abs(key(r[1]) - ref) <= 0.3 * (r[1]["size"] or 1.0)]
    if len(row) < 3:
        return False
    cs = [c for c, _, _ in row]
    if not _evenly_spaced(cs):
        return False
    vals = [t["value"] for _, t, _ in row]
    steps = [q - p for p, q in zip(vals, vals[1:])]
    if any(abs(d - steps[0]) > 1e-9 * max(1.0, abs(steps[0])) for d in steps) or steps[0] == 0:
        # or a log axis: a constant ratio (1E-21, 1E-19, ... 1E-03)
        if not all(v > 0 for v in vals):
            return False
        logs = [math.log10(q / p) for p, q in zip(vals, vals[1:])]
        if logs[0] == 0 or any(abs(d - logs[0]) > 1e-6 * abs(logs[0]) for d in logs):
            return False
    g = _label_tick_group(line, cs, median(t["size"] or 1.0 for _, t, _ in row),
                          frame_ends=True)
    return axes_from_group(g, orient, line, [t for _, t, _ in row], axes, debug)


def _slanted(t, orient):
    """A label turned at a slant to an x axis (not upright, not level)."""
    if orient != "x" or not t.get("rotated"):
        return False
    ang = abs(t.get("angle", 0.0)) % 180
    return 5 < ang < 175 and abs(ang - 90) > 15


def _fitted_grid(cs):
    """Evenly spaced positions fitted (least squares on their order) to
    the sorted positions cs, or None when one is more than 15% of a step
    off its place."""
    n = len(cs)
    mi = (n - 1) / 2.0
    mc = sum(cs) / n
    den = sum((i - mi) ** 2 for i in range(n))
    step = sum((i - mi) * (c - mc) for i, c in enumerate(cs)) / den
    if step <= 0:
        return None
    grid = [mc + (i - mi) * step for i in range(n)]
    if any(abs(c - q) > 0.15 * step for c, q in zip(cs, grid)):
        return None
    return grid


def _category_label_ticks_axis(orient, line, axes, debug):
    """An axis line without tick marks whose category labels mark the
    positions: a row of at least three labels (words, or outlined words that
    cannot be read) beside the line, within its span, evenly spaced; the
    centres of the labels (a label of two lines counts once) are the
    category positions."""
    lo, hi, pos = line
    tol = max(1.0, 0.01 * (hi - lo))
    taken = _labels_in_use(axes)
    k = 0 if orient == "x" else 1
    near = []
    for t in PAGE.nominal_labels:
        # (a name that reads as a quantity with a unit, "2mm", is a word
        # among words: 3485513-020's benchmark names)
        if id(t) in taken or (t.get("value") is not None and
                              not re.search(r"[A-Za-z]", t.get("text") or "")):
            continue
        b, size = t["bbox"], t.get("size") or 1.0
        lo2, hi2 = (b[1], b[3]) if orient == "x" else (b[0], b[2])
        gap = max(lo2 - pos, pos - hi2)
        # a slanted label points at its category with its end nearest the
        # line (3485513-020: names slanted 60 degrees under a line chart)
        c = _label_anchor(t, orient, pos) if _slanted(t, orient) else 0.5 * (b[k] + b[k + 2])
        # (a slanted label's end may stand a little past the line's end:
        # 3485513-020's last name, 2.9 pt beyond it)
        tl = max(tol, size) if _slanted(t, orient) else tol
        if lo - tl <= c <= hi + tl and 0 <= gap <= 4 * size:
            near.append((c, gap, size, t))
    if len(near) < 3:
        return False
    slanted = sum(1 for r in near if _slanted(r[3], orient)) > 0.5 * len(near)
    if slanted:
        near = [r for r in near if _slanted(r[3], orient)]
    # pieces of one word (an outlined word read glyph by glyph) joined:
    # beside each other on one line, less than 0.6 of a font size apart
    near.sort(key=lambda r: r[3]["bbox"][k])
    words = []
    for c, gap, size, t in near:
        b = t["bbox"]
        for w in (() if slanted else words):      # (slanted labels' boxes overlap)
            wb = w["bbox"]
            if orient == "x":
                same = abs(b[1] - wb[1]) <= 0.4 * size and b[0] - wb[2] <= 0.6 * size and wb[0] - b[2] <= 0.6 * size
            else:
                same = abs(b[0] - wb[0]) <= 0.4 * size and b[1] - wb[3] <= 0.6 * size and wb[1] - b[3] <= 0.6 * size
            if same:
                w["bbox"] = (min(wb[0], b[0]), min(wb[1], b[1]), max(wb[2], b[2]), max(wb[3], b[3]))
                w["gap"] = min(w["gap"], gap)
                w["items"].append(t)
                break
        else:
            words.append({"bbox": tuple(b), "gap": gap, "size": size, "items": [t], "c": c})
    near = [(w["c"] if slanted else 0.5 * (w["bbox"][k] + w["bbox"][k + 2]), w["gap"], w["size"],
             w["items"][0]) for w in words]
    # one category per position (the lines of a two-line label share it)
    near.sort(key=lambda r: r[0])
    cats = []
    for c, gap, size, t in near:
        if cats and abs(c - cats[-1][0]) <= 0.3 * size:
            if gap < cats[-1][1]:
                cats[-1] = (c, gap, size, t)
            continue
        cats.append((c, gap, size, t))
    if len(cats) < 3 or min(r[1] for r in cats) > 2 * cats[0][2]:
        return False
    cs = [r[0] for r in cats]
    if slanted:
        # the ends of slanted words wander with their last letters (0.36 to
        # 1.06 pt in 3485513-020): evenly spaced positions fitted to them,
        # each end within 15% of a step of its place
        cs = _fitted_grid(cs)
        if cs is None:
            return False
    elif not _evenly_spaced(cs):
        return False
    g = _label_tick_group(line, cs, median(r[2] for r in cats), extended=True)
    return axes_from_group(g, orient, line, [], axes, debug)


def _far_from_all(x, sorted_vals, d):
    """Is x more than d away from every value of the sorted list?"""
    k = bisect.bisect_left(sorted_vals, x)
    return all(abs(x - sorted_vals[j]) > d for j in (k - 1, k) if 0 <= j < len(sorted_vals))


def axes_from_group(g, orient, line, numeric, axes, debug):
    """Turn one group of ticks (and the axis line it touches, if any) into
    an axis with a value mapping; appends to `axes`."""
    if line is not None and not g.get("grid") and not g.get("frame_ends") \
            and not g.get("extended") and len(g["pos"]) >= 3:
        # evenly spaced ticks on a frame whose corners carry the end labels
        # without a tick (InDesign, Illustrator): the line's ends one
        # spacing beyond the outer ticks may be ticks too.  Kept only when
        # they let more labels fit than the ticks alone.
        pos = g["pos"]
        gaps = [b - a for a, b in zip(pos, pos[1:])]
        sp = median(gaps)
        extra = [e for e, t in ((line[0], pos[0]), (line[1], pos[-1]))
                 if abs(abs(t - e) - sp) <= 0.03 * sp]
        if extra and all(abs(d - sp) <= 0.02 * sp for d in gaps):
            nb = len(PAGE.bare_axes)
            trial = []
            axes_from_group(dict(g, pos=sorted(pos + extra), extended=True), orient, line,
                            numeric, trial, False)
            base = []
            axes_from_group(dict(g, extended=True), orient, line, numeric, base, False)
            del PAGE.bare_axes[nb:]
            mt = trial[0]["map"] if trial and trial[0]["map"]["kind"] != "nominal" else None
            mb = base[0]["map"] if base and base[0]["map"]["kind"] != "nominal" else None
            n_ext = mt["n"] if mt else 0
            n_base = mb["n"] if mb else 0
            # more labels, and (unless the ticks alone fit too few) a fit as
            # good: a label at the line's end that is not at a tick (an
            # axis starting before its first value) spoils the fit
            if n_ext > n_base and (n_base < 3 or
                                   mt["resid"] <= 3 * mb.get("resid", 0.0) + 1e-4):
                g = dict(g, pos=sorted(pos + extra))
            g = dict(g, extended=True)
    L = g["len"]
    tol = max(0.05, 0.3 * L)
    tmin, tmax = g["pos"][0], g["pos"][-1]
    if tmax - tmin < 8.0:
        # ticks within a few points of each other: strokes of markers or
        # error bars (with misread "labels" among them), not an axis
        if debug:
            print("[debug] %s-axis candidate: ticks at %s span under 8 pt" % (
                orient, ["%.2f" % p for p in g["pos"]]), file=sys.stderr)
        return False
    if line is not None:
        alo, ahi, apos = line
        # the end of the ticks away from the axis line
        far = g["lo"] if abs(apos - g["hi"]) < abs(apos - g["lo"]) else g["hi"]
        if g["lo"] + tol < apos < g["hi"] - tol:      # ticks cross the axis
            outers = [g["lo"], g["hi"]]
        else:
            # ticks normally point outwards with the labels beyond them, but
            # some programs (e.g. Excel) draw them inwards with the labels on
            # the other side of the axis line: try both, keep the better one
            # (grid lines standing in for ticks: labels beyond the axis line
            # first, then beyond the far ends of the grid lines)
            outers = [apos, far] if g.get("grid") else [far, apos]
    else:
        alo, ahi, apos = tmin, tmax, None
        outers = [g["lo"], g["hi"]]
    best = None
    for outer in outers:
        if apos is not None and abs(outer - apos) > 1e-9:
            sign = 1 if outer > apos else -1
        elif apos is not None:             # labels opposite the tick direction
            sign = -1 if far > apos else 1
        else:
            sign = 1 if outer == g["hi"] else -1
        pairs = assign_labels(g["pos"], orient, outer, sign,
                              split_labels_at_ticks(g["pos"], orient, numeric))
        if best is None or len(pairs) > len(best[0]):
            best = (pairs, outer)
    pairs, outer = best
    pairs = fix_short_year_centuries(pairs)
    pairs = compose_month_axis(pairs, numeric, orient, apos if apos is not None else outer)
    dur = duration_axis(pairs)
    if dur is not None:
        pairs, work = dur
    m = fit_axis(pairs, rescue=line is not None)
    if dur is not None and work is not None and (m is None or m["n"] < len(pairs)):
        # (a day of work, 8 hours, may be what the ticks are spaced by)
        mw = fit_axis(work, rescue=line is not None)
        if mw is not None and (m is None or mw["n"] > m["n"]):
            m, pairs = mw, work
    if apos is not None and (m is None or m["n"] < len(pairs)):
        pw = piecewise_axis(pairs, orient, apos)
        if pw is not None:
            m = pw
    if line is None and m is not None and m["kind"] != "nominal" and (
            m["n"] < 3):
        # without an axis line, short parallel strokes (e.g. of '+'
        # markers) easily pass for ticks: demand a convincing labelling
        m = None
    if debug:
        print("[debug] %s-axis candidate: ticks at %s, line=%s, labels=%s, map=%s" % (
            orient, ["%.2f" % p for p in g["pos"]], line is not None,
            [(round(c, 2), v) for c, v in pairs], m), file=sys.stderr)
    lab = None
    if m is None or (m["n"] <= 2 and len(g["pos"]) >= 6):
        # no numbers, or two stray "numbers" (misread letters) on a long
        # row of ticks: try category labels
        lab = nominal_axis(g, orient, line, debug)
    if lab is not None:
        mi = [month_index(tx["text"]) if tx.get("text") else None for _, tx in lab]
        dated = None
        if all(v is not None for v in mi):
            # category labels that are month names: a date axis after all
            items = [dict(tx, value=float(v), month=v) for (_, tx), v in zip(lab, mi)]
            mp = LabelPairs([(t, float(v)) for ((t, _), _), v in zip(lab, mi)],
                            [0.0] * len(lab), items)
            mp = compose_month_axis(mp, numeric, orient, apos if apos is not None else outer)
            mm = fit_axis(mp)
            if mm is not None and mm["n"] == len(lab):
                dated = (mm, mp)
        if dated:
            m, pairs = dated
        else:
            m = nominal_map(lab)
            pairs = LabelPairs([tv for tv, _ in lab], [0.0] * len(lab), [tx for _, tx in lab])
    if g.get("frame_ends") and m is not None and (m["kind"] == "nominal" or m["n"] < 3):
        m = None
    if m is None:
        if line is not None and not g.get("frame_ends"):
            # a graph sharing another graph's labelled axis (stacked panels
            # with the labels under the bottom one only) keeps its own ticks
            PAGE.bare_axes.append({"orient": orient, "pos": apos, "lo": alo, "hi": ahi,
                                   "tick_pos": list(g["pos"]), "tick_len": L})
        return False
    labels = list(zip(pairs, pairs.items))
    axis = {"orient": orient, "lo": alo, "hi": ahi,
            "pos": apos if apos is not None else outer,
            "has_line": line is not None, "map": m, "ticks": pairs, "labels": labels,
            "tick_len": L, "tick_pos": list(g["pos"]),
            "label_ticks": bool(g.get("label_ticks")),
            # (the labels' reading direction: a graph turned on the page)
            "label_angle": snapped_angle(getattr(pairs, "angles", []))}
    if g.get("label_ticks"):
        # label centres as ticks: the error bound the user asked for
        unc = label_tick_uncertainty(m, labels)
        if unc is not None:
            axis["tick_unc"] = unc
    axes.append(axis)
    return True


def label_tick_uncertainty(m, labels):
    """How far (page points) the true positions may be from an axis whose
    ticks are its label centres: programs centre a label on its cap height,
    its em box or its ink - up to 0.2 of the font size apart (an R plot's
    labels sit 0.15 em above their ticks: the error bars against the
    paper's confidence intervals show it) - and the centres stray from the
    fitted scale by the largest residual.  None for
    category and broken axes."""
    if m is None or m["kind"] not in ("linear", "log") or not labels or m["a"] == 0:
        return None
    dev = 0.0
    for (c, v), _t in labels:
        if m["kind"] == "log":
            if v <= 0:
                continue
            v = math.log10(v)
        dev = max(dev, abs((v - m["b"]) / m["a"] - c))
    return 0.2 * median(t.get("size") or 1.0 for _, t in labels) + dev


def drop_duplicate_axes(axes):
    """Major and minor ticks on one axis line can both end up matched to
    labels (the same ones, or stray numbers nearby).  Keep one axis per
    line: the one whose ticks match the most labels, then the one with the
    longer ticks (the major ticks), then the better fit.  The tolerance is
    half a tick; for two numeric axes that share no label it takes ticks
    of at most 10 pt: grid lines standing in for ticks are long - 204 pt in
    3485513-020, whose middle chart's y axis (labels 0 ... 3) was taken
    for a duplicate of the left chart's (0.0 ... 1.5), 86 pt away.  (A
    category axis of grid lines labelled with axis titles still gives way
    to the real axis half a grid line away: 3276496-020.)"""
    def shared(a, b):
        return (a["map"]["kind"] == "nominal" or b["map"]["kind"] == "nominal" or
                bool({id(t) for _, t in a.get("labels", ())} & {id(t) for _, t in b.get("labels", ())}))

    keep = []
    order = sorted(axes, key=lambda a: (a["map"]["kind"] == "nominal", -len(a["ticks"]),
                                        -a["tick_len"], a["map"]["resid"]))
    for a in order:
        dup = False
        for b in keep:
            if (b["orient"] == a["orient"] and b["has_line"] == a["has_line"] and
                    abs(b["pos"] - a["pos"]) <= max(0.5, 0.5 * (max(a["tick_len"], b["tick_len"]) if shared(a, b)
                                                         else min(10.0, max(a["tick_len"], b["tick_len"])))) + 1e-9 and
                    b["lo"] < a["hi"] and a["lo"] < b["hi"]):
                dup = True
                break
        if not dup:
            keep.append(a)
    return [a for a in axes if any(a is k for k in keep)]


def drop_scattered_tick_axes(axes):
    """A linear axis whose tick marks are not evenly spaced is no axis, when
    another, evenly spaced one covers the same stretch of the same line:
    its "ticks" are strokes that happen to stand on the axis line at one
    length.  The atoms of jordan-teh-026's stem plots stand on the x axis
    like tick marks; stems of one length (0.126, 0.395 pt ...) made groups
    of four to seven "ticks", two or three of them near labels, and these
    axes took labels from the axis of the real ticks, which then fitted a
    slightly wrong scale to the two labels it kept.  Evenly spaced: with
    four ticks or more, at least half the gaps between neighbouring ticks
    are one gap (within 1%, or 0.1 pt).  (The real axis keeps its gap
    though stems of its tick length join it: 8 of its 13 gaps are 9.62 pt.)
    Log and category axes are left alone."""
    def scattered(a):
        m = a.get("map") or {}
        pos = sorted(a.get("tick_pos") or [])
        if m.get("kind") != "linear" or len(pos) < 4:
            return False
        gaps = [b - c for c, b in zip(pos, pos[1:])]
        best = max(sum(abs(h - g) <= max(0.1, 0.01 * g) for h in gaps) for g in gaps)
        return best < 0.5 * len(gaps)

    def same_stretch(a, b):
        return (a is not b and a["orient"] == b["orient"] and abs(a["pos"] - b["pos"]) <= 0.5 and
                abs(a["lo"] - b["lo"]) <= 0.5 and abs(a["hi"] - b["hi"]) <= 0.5)

    drop = {id(a) for a in axes if scattered(a) and
            any(same_stretch(a, b) and b.get("labels") and not scattered(b) for b in axes)}
    return [a for a in axes if id(a) not in drop]


def _one_label_log_axes(axes, numeric, hs_open, vs_open, debug=False):
    """Log axes with a single label, scaled by their minor ticks.

    2401.16279-023 (matplotlib): the y axes of the two lower right graphs
    label one tick only, 10^2; below it stand unlabelled ticks whose gaps
    (9.87, 7.01, 5.43, 4.44, 3.75 ... pt) shrink as those between log10(2),
    log10(3) ... log10(9) do: the ticks of a log axis at 2x10^1 ... 9x10^1.
    The decade's length follows from them, and with it where 10^1 would
    stand.

    For an axis line with tick marks but no scale, and exactly one numeric
    label beside it, a power of ten 10^k at one of its ticks (within 0.4 of
    the label's size): every other tick on the line must stand where some
    m x 10^j (m = 1 ... 9) would on a log axis through 10^k with one
    decade length D (within max(0.15 pt, 1% of D)).  D is taken from each
    tick and value in turn and the D that places most ticks kept; it must
    place at least four ticks and 80% of them, at four or more different
    m (evenly spaced ticks place few at once), then it is refitted to
    those ticks by least squares.  Values grow along the page's
    coordinate (up, right)."""
    out = []
    for b in list(PAGE.bare_axes):
        orient, X, lo, hi = b["orient"], b["pos"], b["lo"], b["hi"]
        line = (lo, hi, X)
        if any(a["map"] and a["map"]["kind"] != "nominal" for a in _axes_on(axes + out, orient, line, 1.0)):
            continue
        segs = hs_open if orient == "y" else vs_open
        ticks = sorted({round(p, 3) for s_lo, s_hi, p in segs
                        if (abs(s_lo - X) <= 0.5 or abs(s_hi - X) <= 0.5) and lo - 0.5 <= p <= hi + 0.5})
        if len(ticks) < 5:
            continue
        ax = 1 if orient == "y" else 0         # coordinate along the axis
        near = []
        for t in numeric:
            if t.get("rotated"):
                continue
            bb, s = t["bbox"], t["size"] or 1.0
            c = t["center"][ax]
            if not lo - 0.5 * s <= c <= hi + 0.5 * s:
                continue
            gap = (X - bb[2]) if orient == "y" else (X - bb[3])   # left of / below the line
            if -0.5 <= gap <= 4 * s:
                near.append(t)
        if len(near) != 1:
            continue
        t = near[0]
        m = re.fullmatch(r"\s*10\^([+-]?\d+)\s*", t["text"].replace("−", "-"))
        if not m:
            continue
        k = int(m.group(1))
        s = t["size"] or 1.0
        p0 = min(ticks, key=lambda p: abs(p - t["center"][ax]))
        if abs(p0 - t["center"][ax]) > 0.4 * s:
            continue
        minor = [p for p in ticks if abs(p - p0) > 0.05]
        logs = sorted({j + math.log10(mm) for j in range(-4, 5) for mm in range(1, 10)} - {0.0})
        best = None
        for p in minor:
            for L in logs:
                D = (p - p0) / L
                if D <= 1.0:
                    continue
                tol = max(0.15, 0.01 * D)
                hits = []
                for q in minor:
                    r = (q - p0) / D
                    Lq = min(logs, key=lambda u: abs(u - r))
                    if abs(Lq - r) * D <= tol:
                        hits.append((q, Lq))
                mants = {round(10 ** (Lq - math.floor(Lq + 1e-9))) for _, Lq in hits}
                key = (len(hits), len(mants))
                if best is None or key > best[0]:
                    best = (key, D, hits, mants)
        if best is None:
            continue
        (n_hit, n_mant), D, hits, mants = best
        if n_hit < 4 or n_hit < 0.8 * len(minor) or n_mant < 4:
            if debug:
                print("[debug] %s-axis at %.2f: one label %s, ticks fit no log pattern (%d of %d)"
                      % (orient, X, t["text"], n_hit, len(minor)), file=sys.stderr)
            continue
        D = sum((q - p0) * Lq for q, Lq in hits) / sum(Lq * Lq for _, Lq in hits)
        resid = max(abs((q - p0) / D - Lq) for q, Lq in hits)
        a = 1.0 / D
        mp = {"kind": "log", "a": a, "b": k - a * p0, "n": 1, "resid": resid,
              "range": 9.0 * 10.0 ** k, "one_label": True}
        pairs = LabelPairs([(p0, 10.0 ** k)], [0.0], [t])
        if debug:
            print("[debug] %s-axis at %.2f: one label %s at %.2f, %d minor ticks on a log scale, "
                  "decade %.2f pt" % (orient, X, t["text"], p0, n_hit, D), file=sys.stderr)
        out.append({"orient": orient, "lo": lo, "hi": hi, "pos": X, "has_line": True,
                    "map": mp, "ticks": pairs, "labels": list(zip(pairs, pairs.items)),
                    "tick_len": b["tick_len"], "tick_pos": list(ticks), "label_ticks": False,
                    "label_angle": 0})
    return out

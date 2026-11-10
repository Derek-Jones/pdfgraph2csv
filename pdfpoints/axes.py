"""Finding axes.

Tick marks are groups of short parallel segments of identical length
(or, on plots without ticks, grid lines) touching an axis line.  Each
group is labelled and fitted (see labels.py and scales.py) to give an axis:
a dict with its orientation, extent, position and value mapping.
"""

import bisect
import math
import sys

from .context import PAGE
from .geometry import (
    axis_aligned, merge_collinear, straight_segments, thin_rect_line)
from .labels import (
    LabelPairs, assign_labels, compose_month_axis,
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
        res.append({"lo": g["lo"], "hi": g["hi"], "pos": pos, "len": L, "span": span,
                    "grid": L > 0.25 * span})
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


def find_axes(paths, texts, debug=False):
    """Return a list of axis dicts (orientation 'x' or 'y')."""
    hs_open, vs_open, hs_all, vs_all = [], [], [], []
    hs_dark, vs_dark = [], []          # dark lines: frames and panel borders
    for p in paths:
        if not p["stroke"]:
            if p["fill"] and p["idx"] not in PAGE.minus_paths:
                # strokes converted to thin filled rectangles (but not the
                # minus signs of outlined labels)
                for sp in p["subpaths"]:
                    ln = thin_rect_line(sp)
                    aa = axis_aligned(*ln) if ln else None
                    if aa:
                        k, lo, hi, pos = aa
                        (hs_all if k == "h" else vs_all).append((lo, hi, pos))
                        (hs_open if k == "h" else vs_open).append((lo, hi, pos))
            continue
        rgb = p["stroke_rgb"] or (0, 0, 0)
        dark = sum(rgb) < 1.5
        for sp in p["subpaths"]:
            if sp["closed"] and p["idx"] not in PAGE.minus_paths:
                # a tick drawn as a tiny outlined (and maybe filled)
                # rectangle (InDesign): its centre line is the tick
                ln = thin_rect_line(sp)
                aa = axis_aligned(*ln) if ln else None
                if aa and aa[2] - aa[1] <= 12:
                    k, lo, hi, pos = aa
                    (hs_open if k == "h" else vs_open).append((lo, hi, pos))
                    # its edges are no lines: the ends of a row of such
                    # ticks would join into a false axis line at their tips
                    (hs_all if k == "h" else vs_all).append((lo, hi, pos))
                    continue
            for a, b in straight_segments({"subpaths": [sp]}):
                aa = axis_aligned(a, b)
                if not aa:
                    continue
                k, lo, hi, pos = aa
                (hs_all if k == "h" else vs_all).append((lo, hi, pos))
                if dark:
                    (hs_dark if k == "h" else vs_dark).append((lo, hi, pos))
                if not sp["closed"]:
                    (hs_open if k == "h" else vs_open).append((lo, hi, pos))
    background_grid(paths, hs_all, vs_all, hs_open, vs_open)
    hs_lines = merge_collinear(hs_all)
    vs_lines = merge_collinear(vs_all)
    hs_dark, vs_dark = merge_collinear(hs_dark), merge_collinear(vs_dark)
    PAGE.dark_lines = (hs_dark, vs_dark)
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
                    if any(a["orient"] == orient and a["has_line"] and
                           abs(a["pos"] - pos) <= tol2 and a["lo"] < hi and lo < a["hi"]
                           for a in axes):
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
    for a in axes:
        a["inside"] = _interior_side(a, hs_lines if a["orient"] == "y" else vs_lines)
    return axes


def _light_rect(p, sp):
    """(x0, y0, x1, y1) of a filled axis-aligned rectangle in a light,
    not white, colour (a plot background: seaborn, ggplot2), else None."""
    rgb = p.get("fill_rgb")
    if not p["fill"] or rgb is None or min(rgb) < 0.75 or min(rgb) > 0.995:
        return None
    pts = [sp["start"]] + [s[-1] for s in sp["segs"]]
    if any(s[0] != "l" for s in sp["segs"]) or not 3 <= len(sp["segs"]) <= 4:
        return None
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

    for colour, rs in rects.items():
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
                if any(b["orient"] == orient and abs(b["pos"] - pos) <= tol and
                       b["lo"] < hi and lo < b["hi"] for b in axes):
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
                axes_from_group(g, orient, (lo, hi, pos), numeric, axes, debug)


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
        sp = sorted(gaps)[len(gaps) // 2]
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
    if line is not None:
        alo, ahi, apos = line
        if g["lo"] + tol < apos < g["hi"] - tol:      # ticks cross the axis
            outers = [g["lo"], g["hi"]]
        else:
            # ticks normally point outwards with the labels beyond them, but
            # some programs (e.g. Excel) draw them inwards with the labels on
            # the other side of the axis line: try both, keep the better one
            far = g["lo"] if abs(apos - g["hi"]) < abs(apos - g["lo"]) else g["hi"]
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
            far = g["lo"] if abs(apos - g["hi"]) < abs(apos - g["lo"]) else g["hi"]
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
    m = fit_axis(pairs, rescue=line is not None)
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
    axes.append({"orient": orient, "lo": alo, "hi": ahi,
                 "pos": apos if apos is not None else outer,
                 "has_line": line is not None, "map": m, "ticks": pairs,
                 "labels": list(zip(pairs, pairs.items)),
                 "tick_len": L, "tick_pos": list(g["pos"]), "label_angle": snapped_angle(getattr(pairs, "angles", []))})
    return True


def drop_duplicate_axes(axes):
    """Major and minor ticks on one axis line can both end up matched to
    labels (the same ones, or stray numbers nearby).  Keep one axis per
    line: the one whose ticks match the most labels, then the one with the
    longer ticks (the major ticks), then the better fit."""
    keep = []
    order = sorted(axes, key=lambda a: (a["map"]["kind"] == "nominal", -len(a["ticks"]),
                                        -a["tick_len"], a["map"]["resid"]))
    for a in order:
        dup = False
        for b in keep:
            if (b["orient"] == a["orient"] and b["has_line"] == a["has_line"] and
                    abs(b["pos"] - a["pos"]) <= max(0.5, 0.5 * max(a["tick_len"], b["tick_len"])) and
                    b["lo"] < a["hi"] and a["lo"] < b["hi"]):
                dup = True
                break
        if not dup:
            keep.append(a)
    return [a for a in axes if any(a is k for k in keep)]

"""Finding axes.

Tick marks are groups of short parallel segments of identical length
(or, on plots without ticks, grid lines) touching an axis line.  Each
group is labelled and fitted (see labels.py and scales.py) to give an axis:
a dict with its orientation, extent, position and value mapping.
"""

import sys

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
    for lo, hi, pos in sorted(segs):
        L = hi - lo
        # long grid lines of side-by-side plots differ only slightly in
        # extent: keep their groups apart
        tol = max(0.05, min(0.1 * L, 1.0))
        for g in groups:
            if abs(g["lo"] - lo) <= tol and abs(g["hi"] - hi) <= tol:
                g["pos"].append(pos)
                break
        else:
            groups.append({"lo": lo, "hi": hi, "pos": [pos]})
    res = []
    for g in groups:
        pos = sorted(set(round(p, 4) for p in g["pos"]))
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
            if p["fill"]:          # strokes converted to thin filled rectangles
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
    hs_lines = merge_collinear(hs_all)
    vs_lines = merge_collinear(vs_all)
    hs_dark, vs_dark = merge_collinear(hs_dark), merge_collinear(vs_dark)
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
                    if line is None:
                        continue
                    lo, hi, pos = line
                    tol2 = max(0.5, 0.01 * (hi - lo))
                    if not (abs(pos - g0["lo"]) <= tol2 or abs(pos - g0["hi"]) <= tol2):
                        continue           # grid lines must start on the axis line
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
                        and all(abs(pp - t) > 0.15 for t in sub)]
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
                        axes_from_group(dict(g0, pos=part), orient, (a, b, pos), numeric, axes, debug)
    for a in axes:
        a["inside"] = _interior_side(a, hs_lines if a["orient"] == "y" else vs_lines)
    return axes


def axes_from_group(g, orient, line, numeric, axes, debug):
    """Turn one group of ticks (and the axis line it touches, if any) into
    an axis with a value mapping; appends to `axes`."""
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
    m = fit_axis(pairs)
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
    if m is None:
        return False
    axes.append({"orient": orient, "lo": alo, "hi": ahi,
                 "pos": apos if apos is not None else outer,
                 "has_line": line is not None, "map": m, "ticks": pairs,
                 "labels": list(zip(pairs, pairs.items)),
                 "tick_len": L, "label_angle": snapped_angle(getattr(pairs, "angles", []))})
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

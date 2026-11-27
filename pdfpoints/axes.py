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
        b = math.floor(lo)
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
        # (positions kept as drawn: rounding them to 4 decimals put the
        # ticks of matplotlib's 6-decimal axes 5e-5 pt off, more than the
        # program's own accuracy - mpl-errorbars)
        for q in sorted(g["pos"]):
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
                    "grid": 0.25 * span < L or 3 * gap < L})
    res.sort(key=lambda g: g["grid"])          # real ticks first
    return res


def _even_runs(pos):
    """Split sorted tick positions into runs of even spacing (within 3%;
    each run starts at the tick that breaks the last one's step); None
    unless there are two or more runs, each of two or more ticks."""
    runs, cur = [], [pos[0]]
    for p in pos[1:]:
        if len(cur) >= 2 and abs((p - cur[-1]) - (cur[1] - cur[0])) > 0.03 * (cur[1] - cur[0]):
            runs.append(cur)
            cur = [p]
        else:
            cur.append(p)
    runs.append(cur)
    if len(runs) < 2 or any(len(r) < 2 for r in runs):
        return None
    return runs


def _split_even_runs(g, orient, line, numeric, axes, debug, segs=()):
    """Ticks of panels side by side (or one above another) with no axis
    lines of their own (at most the edges of the panels' backgrounds, run
    together) form one row: Seongmin-PhD-044's ggplot panels (no axis
    lines) put the ticks of four Iteration axes, labelled 1 ... 6, 1 ... 6,
    1 ... 5, 1 ... 5, in one row, which reads as no scale.  When the whole
    row gives no numeric scale, it is split into runs of evenly spaced
    ticks, kept when every run gives a numeric scale of its own (three or
    more labels, or every tick of a run of two labelled: the replace panel's
    time axis shows only 1000 and 2000) and together they read two or more labels more than the
    whole row (whose scale may fit one panel's labels alone).  Returns True
    if the split was used."""
    if len(g["pos"]) < 6:
        return False
    runs = _even_runs(g["pos"])
    # (runs of two ticks only are no panels: Memory_systems_cacheDRAMdisk-051's
    # category ticks 0.8, 1.6 ... 25.6 are spaced 24, 35, 41, 35, 24 pt)
    if not runs or max(len(r) for r in runs) < 3:
        return False
    whole = []
    nb = len(PAGE.bare_axes)
    axes_from_group(dict(g), orient, line, numeric, whole, False)
    del PAGE.bare_axes[nb:]
    n_whole = whole[-1]["map"].get("n", 0) if whole and whole[-1]["map"]["kind"] != "nominal" else 0
    trial = []
    for r in runs:
        nb = len(PAGE.bare_axes)
        before = len(trial)
        axes_from_group(dict(g, pos=r), orient, _clip_line(line, runs, r, segs), numeric, trial, False)
        del PAGE.bare_axes[nb:]
        if len(trial) != before + 1 or trial[-1]["map"]["kind"] == "nominal" or \
                trial[-1]["map"].get("n", 0) < min(3, len(r)):
            return False
    # (the whole row may fit the labels of one of its panels: the runs
    # must explain more labels)
    if sum(a["map"]["n"] for a in trial) < n_whole + 2:
        return False
    for r in runs:
        axes_from_group(dict(g, pos=r), orient, _clip_line(line, runs, r, segs), numeric, axes, debug)
    return True


def _clip_line(line, runs, run, segs=()):
    """The part of an axis line (lo, hi, pos) shared by runs of ticks that
    belongs to `run`: the piece of the line (unmerged `segs`, such as the
    edge of a panel's background) its ticks lie along; failing that, half a
    tick spacing beyond its ticks (no further than
    midway to the neighbouring run), and the line's own end beyond an outer
    run (None stays None)."""
    if line is None:
        return None
    lo, hi, pos = line
    # the shortest unmerged piece of the line (the edge of a panel's
    # background) that the run's ticks lie along
    holding = [(b - a, a, b) for a, b, q in segs
               if abs(q - pos) <= 0.5 and a - 0.5 <= run[0] and run[-1] <= b + 0.5]
    if holding:
        _, a, b = min(holding)
        if b - a < hi - lo - 1.0:
            return (max(lo, a), min(hi, b), pos)
    k = runs.index(run)
    h = 0.5 * (run[1] - run[0])
    a = max((runs[k - 1][-1] + run[0]) / 2, run[0] - h) if k > 0 else lo
    b = min((run[-1] + runs[k + 1][0]) / 2, run[-1] + h) if k + 1 < len(runs) else hi
    return (max(lo, a), min(hi, b), pos)


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


def _box_medians(paths):
    """Small filled boxes (bboxes of single four-sided subpaths no larger
    than 20 pt): a stroke spanning one exactly, inside it, is the median
    line of a box plot's legend key (see _key_medians)."""
    out = []
    for p in paths:
        if not p["fill"]:
            continue
        for sp in p["subpaths"]:
            if len(sp["segs"]) not in (3, 4):
                continue
            vs = vertices(sp)
            xs, ys = [q[0] for q in vs], [q[1] for q in vs]
            w, h = max(xs) - min(xs), max(ys) - min(ys)
            if 1.0 <= w <= 20 and 1.0 <= h <= 20:
                out.append((min(xs), min(ys), max(xs), max(ys)))
    return out


def _key_medians(g0, orient, boxes):
    """Do most of a tick group's strokes lie across a small filled box,
    inside it, over 60% or more of its width?  Those are legend keys: the
    median lines of box-plot keys (Seongmin-PhD-044: ggplot's keys
    MOBS-UNI ... ORBS, their names to the right, read as a category y axis
    that took the place of the panel's numeric one) or the line samples on
    ggplot's grey key backgrounds (wp_21_1036-019: read as a second scale
    on the right)."""
    hits = 0
    for t in g0["pos"]:
        for b in boxes:
            if orient == "y":
                lo, hi, a, c = b[0], b[2], b[1], b[3]
            else:
                lo, hi, a, c = b[1], b[3], b[0], b[2]
            # (a box thick enough to hold a stroke well inside it: a tick
            # drawn as a thin filled rectangle runs across its own outline,
            # 2510.19281v2-013)
            if lo - 0.3 <= g0["lo"] and g0["hi"] <= hi + 0.3 and \
                    g0["hi"] - g0["lo"] >= 0.6 * (hi - lo) and c - a >= 2.5 and \
                    a + 0.8 < t < c - 0.8:
                hits += 1
                break
    return hits >= 0.6 * len(g0["pos"])


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


def _labels_in_use(axes, strong=False):
    """Ids of the text items that already label one of `axes` (with
    strong=True: of an axis fitted to three labels or more, or a category
    axis)."""
    return {id(tx) for a in axes
            if not strong or a["map"]["kind"] == "nominal" or a["map"].get("n", 0) > 2
            for _, tx in a.get("labels", ())}


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
    key_boxes = _box_medians(paths)
    # horizontal ticks -> y axis (lines are vertical), vertical ticks -> x axis
    for orient, ticksegs, lines in (("y", hs_open, vs_lines), ("x", vs_open, hs_lines)):
        # (lines sorted by position, so that each tick group visits only
        # those within its reach: ArianeWuerbach-Phd-219's 19 trace plots,
        # thousands of short strokes, gave 21 000 groups x thousands of
        # lines - 57 s)
        lines = sorted(lines, key=lambda ln: ln[2])
        line_pos = [ln[2] for ln in lines]
        perp_all = sorted(hs_dark if orient == "y" else vs_dark, key=lambda ln: ln[2])
        perp_pos = [ln[2] for ln in perp_all]
        for g0 in tick_groups(ticksegs):
            if _key_medians(g0, orient, key_boxes):
                if debug:
                    print("[debug] %s-axis candidate: ticks at %s are legend keys' medians"
                          % (orient, ["%.2f" % t for t in g0["pos"]]), file=sys.stderr)
                continue
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
            for lo, hi, pos in lines[bisect.bisect_left(line_pos, g0["lo"] - tol):
                                     bisect.bisect_right(line_pos, g0["hi"] + tol)]:
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
            for _d, sub, line in subgroups:
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
                def crossing(line, glo=g0["lo"], ghi=g0["hi"]):
                    if line is None:
                        return True
                    lo, hi, pos = line
                    tol2 = max(0.5, 0.01 * (hi - lo))
                    return not (abs(pos - glo) <= tol2 or abs(pos - ghi) <= tol2)
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
                if not g0["grid"] and _split_even_runs(g, orient, line, numeric, axes, debug,
                                                       vs_all if orient == "y" else hs_all):
                    continue
                n0 = len(axes)
                made = axes_from_group(g, orient, line, numeric, axes, debug)
                if line is None:
                    continue
                # (an axis made nominal from numeric labels may be panels
                # stacked on one line, each with its own scale - the labels
                # stepping back at each border: 2355585.2355594-006's four
                # log panels): try the split below as well
                nominal_made = made and len(axes) > n0 and \
                    all(a["map"]["kind"] == "nominal" for a in axes[n0:])
                if made and not nominal_made:
                    continue
                # one long frame line shared by a column (row) of panels, as
                # in lattice / facet plots: split it at the panel borders
                # (perpendicular frame lines meeting it away from any tick)
                lo, hi, pos = line
                tol3 = max(0.5, 0.3 * L)
                perp = perp_all[bisect.bisect_right(perp_pos, lo + tol3):
                                bisect.bisect_left(perp_pos, hi - tol3)]
                meet = [(plo, phi, pp) for plo, phi, pp in perp
                        if lo + tol3 < pp < hi - tol3 and plo - tol3 <= pos <= phi + tol3
                        and _far_from_all(pp, sub, 0.15)]
                longest = max((phi - plo for plo, phi, pp in meet), default=0)
                # panel borders run across the whole grid; grid lines
                # inside a panel are short
                cuts = sorted({round(pp, 3) for plo, phi, pp in meet
                                  if phi - plo >= 0.4 * longest})
                if not cuts:
                    continue
                edges = [lo, *cuts, hi]
                trial = list(axes[:n0]) if nominal_made else axes
                for a, b in zip(edges, edges[1:]):
                    part = [t for t in sub if a - 0.15 <= t <= b + 0.15]
                    if len(part) >= 2 and b - a > 3 * L:
                        # (no line-end ticks: the pieces end at the cuts)
                        axes_from_group(dict(g0, pos=part, extended=True), orient, (a, b, pos),
                                        numeric, trial, debug)
                if nominal_made:
                    new = trial[n0:]
                    if sum(1 for a in new if a["map"]["kind"] != "nominal") >= 2:
                        axes[:] = trial
    _clip_at_panel_borders(axes, hs_dark, vs_dark)
    _between_facing_axes(axes, debug)
    _frame_side_axes(axes, hs_lines, vs_lines, hs_open, vs_open, numeric, debug)
    axes[:] = [a for a in axes if not _ticks_in_labels(a)]
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
                if not _category_label_ticks_axis(orient, (lo, hi, pos), axes, debug):
                    _number_category_ticks_axis(orient, (lo, hi, pos), axes, debug)
    axes += _one_label_log_axes(axes, numeric, hs_open, vs_open, debug)
    _two_label_log_axes(axes, debug)
    for a in axes:
        a["inside"] = _interior_side(a, hs_lines if a["orient"] == "y" else vs_lines)
    # category labels stand outside the plot: a row of them all on the
    # plot's side of the axis line is the values printed in its bars
    # (2204.07073-010: "87%" ... "77%" inside the stacked bars made a
    # category axis of the bar chart's own ticks).  Its ticks stay a bare
    # axis, to take the labels of a stacked graph's shared axis.
    out = []
    # (numbers following no scale made categories on a line: a scale fitted
    # to two of them on that line - its first and last at the line's ends,
    # the plot's sides taken for ticks - is no axis: VaskeBeaman2006-
    # Lessonslearned-003's Figure 1f)
    numcats = [a for a in axes if a.get("number_categories")]
    for a in axes:
        if any(c is not a and c["orient"] == a["orient"] and abs(c["pos"] - a["pos"]) <= 1.0 and
               min(c["hi"], a["hi"]) - max(c["lo"], a["lo"]) > 0.5 * (a["hi"] - a["lo"]) and
               a["map"]["kind"] != "nominal" and a["map"].get("n", 3) <= 2 for c in numcats):
            continue
        if _shadowed(a, axes):
            continue
        if _labels_nearer_other(a, axes):
            continue
        if _labels_past_plot(a, axes):
            continue
        if not _labels_inside(a):
            out.append(a)
        elif a["has_line"]:
            PAGE.bare_axes.append({"orient": a["orient"], "pos": a["pos"], "lo": a["lo"],
                                   "hi": a["hi"], "tick_pos": list(a["tick_pos"]),
                                   "tick_len": a["tick_len"]})
    _share_out_line(out)
    return out


def _share_out_line(axes):
    """Panels side by side on one axis line, each with ticks and labels
    of its own (2020.01.30.927558.full-023: 1 2 ... 8 under each of three
    and four panels, the line drawn across the row, the y axis at the left
    end only): numeric axes on one line (within 1 pt), spanning the same
    stretch (within 2 pt), whose ticks do not overlap, share the line out
    at the midpoints between their tick ranges (each a panel's axis; one
    left on the whole line would be one plot found three times)."""
    groups = []
    for a in axes:
        if not a["has_line"] or not a.get("tick_pos") or a["map"]["kind"] == "nominal":
            continue
        for gr in groups:
            b = gr[0]
            if b["orient"] == a["orient"] and abs(a["pos"] - b["pos"]) <= 1.0 and \
                    abs(a["lo"] - b["lo"]) <= 2.0 and abs(a["hi"] - b["hi"]) <= 2.0:
                gr.append(a)
                break
        else:
            groups.append([a])
    for gr in groups:
        if len(gr) < 2:
            continue
        gr.sort(key=lambda a: min(a["tick_pos"]))
        if any(max(a["tick_pos"]) >= min(b["tick_pos"]) for a, b in zip(gr, gr[1:])):
            continue
        for a, b in zip(gr, gr[1:]):
            cut = 0.5 * (max(a["tick_pos"]) + min(b["tick_pos"]))
            a["hi"], b["lo"] = cut, cut


def _low_category_labels(g, orient, line, m, axes, debug):
    """Category labels of an x axis drawn at a zero line inside the plot
    and set below the plot, at the foot of its y axis (Excel's "label
    position: low" - 3832783.3834484-004: the ticks at 0.00%, the names
    SELECT ... TPC-C under -5.00%, the bars below 0 kept clear of them).
    For an x axis line with ticks whose numbers are none or two (bar value
    labels by the line, "0.42%", "2.88%"), starting within 1.5 pt of a
    lined y axis with a scale that runs on below it (by 3 pt or more):
    category labels found as if the axis line were at that y axis's foot,
    one between each pair of ticks or at each tick, all of them.  Returns
    the labels, or None."""
    if orient != "x" or line is None or (m is not None and m["n"] > 2):
        return None
    alo, ahi, apos = line
    for y in axes:
        if y["orient"] != "y" or not y["has_line"] or y["map"]["kind"] == "nominal" or \
                abs(y["pos"] - alo) > 1.5 or not y["lo"] < apos - 3.0 < y["hi"]:
            continue
        lab = nominal_axis(g, orient, (alo, ahi, y["lo"]), debug)
        if lab is not None and len(lab) >= len(g["pos"]) - 1:
            return lab
    return None


def _labels_past_plot(a, axes):
    """A category x axis on a line that a y axis with a scale spans well
    inside (beyond 5% of it from either end), whose labels all lie past
    that y axis's ends: a zero line inside the plot, the panel titles
    above the plot taken for its categories (2020.01.30.927558.full-023:
    "IIAB", "Delta", "M-Avg" over bars hanging from 0)."""
    if a["orient"] != "x" or a["map"]["kind"] != "nominal" or not a.get("labels") or \
            a.get("low_labels"):
        return False            # (labels set low on purpose: _low_category_labels)
    for y in axes:
        if y["orient"] != "y" or y["map"]["kind"] == "nominal" or not y["has_line"]:
            continue
        span = y["hi"] - y["lo"]
        if not (y["lo"] + 0.05 * span < a["pos"] < y["hi"] - 0.05 * span) or \
                not a["lo"] - 2 <= y["pos"] <= a["hi"] + 2:
            continue
        if all(not y["lo"] <= tx["center"][1] <= y["hi"] for _, tx in a["labels"]):
            return True
    return False


def _labels_nearer_other(a, axes):
    """Is axis a, placed by its labels (no ticks), labelled from a column
    that stands nearer another parallel axis line, on whose side they are,
    an axis with more labels of that column?  (VaskeBeaman2006-Lessons-
    learned-003: the right frame side of Figure 1e took the top three
    labels, 100 ... 140, of Figure 1f's y axis just right of it.)"""
    if not a.get("from_labels") or not a.get("labels"):
        return False
    k = 0 if a["orient"] == "y" else 1
    cs = [tx["center"][k] for _, tx in a["labels"]]
    mine = median(abs(c - a["pos"]) for c in cs)
    for b in axes:
        if b is a or b["orient"] != a["orient"] or not b.get("labels") or \
                len(b["labels"]) <= len(a["labels"]):
            continue
        if b["lo"] > a["hi"] or a["lo"] > b["hi"]:
            continue
        theirs = median(abs(c - b["pos"]) for c in cs)
        col = [tx["center"][k] for _, tx in b["labels"]]
        if theirs < mine and abs(median(col) - median(cs)) <= 0.5 * max(
                (tx["size"] or 1.0) for _, tx in a["labels"]) * 3:
            return True
    return False


def _clip_at_panel_borders(axes, hs_dark, vs_dark):
    """An axis line run along side-by-side lattice panels whose labelled
    ticks all lie in one panel (ArianeWuerbach-Phd-064: the x axis of the
    Female panel at the bottom, of the Male panel at the top, each line
    across both panels; R lattice's alternating axes) ends at the panel
    border beyond them: a long frame line ending on it away from any tick.
    Only when the ticks beyond the border repeat the labelled ones without
    labels (three or more, spaced alike); they are a bare axis (they may
    lend a scale).  A short end beyond a border (8% of the line or less)
    with no tick and a text in it is a strip, a panel's title box: the axis
    ends below it."""
    for a in axes:
        if not a["has_line"] or not a.get("ticks") or a["map"]["kind"] == "nominal":
            continue
        lo, hi, pos = a["lo"], a["hi"], a["pos"]
        perp = hs_dark if a["orient"] == "y" else vs_dark
        tol = max(0.5, 0.3 * (a.get("tick_len") or 1.0))
        allpos = sorted(a.get("tick_pos") or [c for c, _ in a["ticks"]])
        # (a border ends on the axis line: it does not cross it)
        meet = [(plo, phi, pp) for plo, phi, pp in perp
                if lo + tol < pp < hi - tol and (abs(plo - pos) <= tol or abs(phi - pos) <= tol)
                and _far_from_all(pp, allpos, 0.15)]
        if not meet:
            continue
        longest = max(phi - plo for plo, phi, _ in meet)
        cuts = sorted({round(pp, 3) for plo, phi, pp in meet if phi - plo >= 0.4 * longest})
        lab = sorted(c for c, _ in a["ticks"])
        if len(lab) < 2:
            continue
        step = median([q - p for p, q in zip(lab, lab[1:])])
        left = [c for c in cuts if c > max(lab)]
        right = [c for c in cuts if c < min(lab)]
        new_lo = max(right) if right else lo
        new_hi = min(left) if left else hi
        if (new_lo, new_hi) == (lo, hi):
            continue
        # beyond the border, the same ticks again without labels (three or
        # more, spaced as the labelled ones): the next panel's axis
        beyond, strip = [], False
        for b_lo, b_hi in ((lo, new_lo), (new_hi, hi)):
            if b_hi - b_lo <= 1.0:
                continue
            rest = [t for t in allpos if b_lo + 0.15 < t < b_hi - 0.15]
            if not rest and b_hi - b_lo <= 0.08 * (hi - lo) and _titled(a, b_lo, b_hi, meet):
                strip = True
                continue        # a strip (panel title box) at the line's end
            gaps = [q - p for p, q in zip(rest, rest[1:])]
            if len(rest) < 3 or any(abs(g - step) > 0.02 * step + 0.1 for g in gaps):
                beyond = None
                break
            beyond.append((b_lo, b_hi, rest))
        if beyond is None or not (beyond or strip):
            continue
        for b_lo, b_hi, rest in beyond:
            PAGE.bare_axes.append({"orient": a["orient"], "pos": pos, "lo": b_lo, "hi": b_hi,
                                   "tick_pos": rest, "tick_len": a.get("tick_len")})
        a["lo"], a["hi"] = new_lo, new_hi
        if a.get("tick_pos"):
            a["tick_pos"] = [t for t in a["tick_pos"] if new_lo - 0.15 <= t <= new_hi + 0.15]


def _titled(a, b_lo, b_hi, meet):
    """Does a text lie in the end piece (b_lo, b_hi) of axis a's line,
    beside the borders ending there (a lattice strip holds its panel's
    name: "Female", "Male")?"""
    k = 0 if a["orient"] == "x" else 1
    span = [(plo, phi) for plo, phi, pp in meet if b_lo - 0.5 <= pp <= b_hi + 0.5]
    if not span:
        return False
    plo, phi = min(s[0] for s in span), max(s[1] for s in span)
    for t in PAGE.nominal_labels:
        c = t.get("center")
        if c and b_lo < c[k] < b_hi and plo <= c[1 - k] <= phi and t.get("text", "").strip():
            return True
    return False


def _ticks_in_labels(a):
    """An axis without a line whose "ticks" run through its own labels:
    the minus signs of labels -4 ... -1 drawn as separate dashes
    (cheyette2024limited-011's panel (c)).  A real tick stands beside its
    label, never inside it."""
    if a["has_line"] or not a.get("labels"):
        return False
    k = 0 if a["orient"] == "y" else 1
    inside = sum(1 for _, tx in a["labels"] if tx["bbox"][k] < a["pos"] < tx["bbox"][k + 2])
    return inside >= max(2, 0.5 * len(a["labels"]))


def _shadowed(a, axes):
    """An axis fitted to two labels whose line runs within 2 pt of an axis
    fitted to three or more, along most (80%) of the same stretch, its
    labels on the far side of that axis's line from that axis's own: a grid
    line beside the axis that took a legend's numbers
    (10.5445IR1000121285-038's panel (f): "0.2" and "1" read for an x axis
    on its 10^-11 grid line, 1.2 pt above the real one)."""
    m = a["map"]
    if m["kind"] == "nominal" or m.get("n", 3) > 2:
        return False
    for b in axes:
        mb = b["map"]
        if b is a or b["orient"] != a["orient"] or mb["kind"] == "nominal" or mb.get("n", 0) < 3:
            continue
        over = min(a["hi"], b["hi"]) - max(a["lo"], b["lo"])
        if abs(a["pos"] - b["pos"]) > 2.0 or over < 0.8 * (a["hi"] - a["lo"]):
            continue
        # (its labels on the other side of the stronger axis's line from
        # that axis's own labels: inside the plot)
        k = 1 if a["orient"] == "x" else 0
        side_b = [tx["center"][k] - b["pos"] for _, tx in b.get("labels", ())]
        side_a = [tx["center"][k] - b["pos"] for _, tx in a.get("labels", ())]
        if side_a and side_b and all(sa * median(side_b) < 0 for sa in side_a):
            return True
    return False


def _labels_inside(a):
    """A category x axis whose labels all lie on its plot's side.  (Not y:
    ggplot panels side by side share one column of category names between
    them, on the right panel's side of its axis line: 2610.20068v1-009.)
    Nor an axis placed by its labels alone (no tick marks) whose labels all
    lie inside its plot: those are a legend's numeric names beside the
    frame (10.5445IR1000121285-038: V_DS 0.4, 0.6, 0.8, 1 in a column by
    the plot's right side read as a right y axis)."""
    if not a.get("inside") or not a.get("labels"):
        return False
    k = 1 if a["orient"] == "x" else 0
    inside = all((tx["center"][k] - a["pos"]) * a["inside"] > 0 for _, tx in a["labels"])
    if (a.get("from_labels") or a["map"].get("n", 3) <= 2) and a["map"]["kind"] != "nominal":
        # (or fitted to two labels only: panel (f)'s grid line at 10^-11
        # took the legend's "0.2" and "1" for an x axis)
        return inside
    if a["orient"] != "x" or a["map"]["kind"] != "nominal":
        return False
    return inside


def _light_rect(p, sp):
    """(x0, y0, x1, y1) of a filled axis-aligned rectangle in a light,
    not white, colour (a plot background: seaborn, ggplot2), else None."""
    rgb = p.get("fill_rgb")
    if not p["fill"] or rgb is None or min(rgb) < 0.75 or min(rgb) > 0.995:
        return None
    if any(s[0] != "l" for s in sp["segs"]) or not 3 <= len(sp["segs"]) <= 4:
        return None
    pts = vertices(sp)
    xs = sorted({round(x, 2) for x, _ in pts})
    ys = sorted({round(y, 2) for _, y in pts})
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


def _between_facing_axes(axes, debug):
    """A category x axis with no line and no ticks between two y axes
    that face each other (Seongmin-PhD-036: R barplot()s with a scale on
    each side, axis() drawn for y only, the bar groups named by slanted
    labels under them): neighbouring y axes with lines and numeric scales,
    the left one labelled on its left and the right one on its right,
    whose lines start at one height (within 1 pt), with no x axis between
    them there; the stretch between their feet is the axis line, and the
    category labels under it its categories (_category_label_ticks_axis)."""
    ys = sorted((a for a in axes if a["orient"] == "y" and a["has_line"] and
                 a["map"]["kind"] in ("linear", "log") and a.get("labels")),
                key=lambda a: (round(a["lo"]), a["pos"]))

    def side(a):
        cs = [0.5 * (tx["bbox"][0] + tx["bbox"][2]) for _, tx in a["labels"] if tx.get("bbox")]
        return 0 if not cs else (-1 if sum(cs) / len(cs) < a["pos"] else 1)
    for a, b in zip(ys, ys[1:]):
        if abs(a["lo"] - b["lo"]) > 1.0 or b["pos"] - a["pos"] < 30 or \
                side(a) != -1 or side(b) != 1:
            continue
        lo, hi, pos = a["pos"], b["pos"], 0.5 * (a["lo"] + b["lo"])
        if any(x["orient"] == "x" and abs(x["pos"] - pos) <= 2.0 and
               x["lo"] < hi - 1 and x["hi"] > lo + 1 for x in axes):
            continue
        _category_label_ticks_axis("x", (lo, hi, pos), axes, debug)


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
                # (numbers that follow no scale first: the line's ends would
                # pair the first and last of them as a two-label scale -
                # VaskeBeaman2006-Lessonslearned-003's 1 ... 150 under bars
                # for days 1, 2 ... 20, 21, ... 198; the rule declines rows
                # that fit a scale)
                if _number_category_ticks_axis(orient, (lo, hi, pos), axes, debug):
                    continue
                if not axes_from_group(g, orient, (lo, hi, pos), numeric, axes, debug) and \
                        not _label_ticks_axis(orient, (lo, hi, pos), numeric, axes, debug):
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
    values step evenly (linear) or by a constant ratio (log).  Two labels
    do when the line meets, at one end, an axis of the other direction
    fitted to three labels or more: the corner of a plot
    (cheyette2024limited-011's panel (a): y labels 40% and 60% only, no
    ticks, under an x axis 40% ... 80%)."""
    lo, hi, pos = line
    tol = max(1.0, 0.01 * (hi - lo))
    # (numbers that follow no scale, perhaps in two alternating rows, are
    # categories: of two rows only two labels might share a baseline and
    # pass for a corner's scale - VaskeBeaman2006-Lessonslearned-003)
    if orient == "x" and _number_category_ticks_axis(orient, line, axes, debug):
        return True
    # labels that already serve an axis with ticks are not this line's -
    # unless that axis fits only two of them: cheyette2024limited-011's
    # error-bar caps in panel (c) read as ticks reached the y labels 0, 1, 2
    # of panel (d), 36 pt away; the labels go to the nearer axis line later
    # (labels.resolve_shared_labels)
    taken = _labels_in_use(axes, strong=True)
    least = 2 if _at_corner(orient, line, axes) else 3
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
    if len(row) < least:
        return False
    # one side of the line, one baseline (x) / one edge (y)
    side = max((-1, 1), key=lambda k: sum(1 for r in row if r[2] == k))
    row = sorted((r for r in row if r[2] == side), key=lambda r: r[0])
    key = (lambda t: t["bbox"][1]) if orient == "x" else \
        (lambda t: t["bbox"][2] if side < 0 else t["bbox"][0])
    ref = median(key(t) for _, t, _ in row)
    row = [r for r in row if abs(key(r[1]) - ref) <= 0.3 * (r[1]["size"] or 1.0)]
    if len(row) < least:
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
    if len(row) == 2:
        g = _label_tick_group(line, cs, median(t["size"] or 1.0 for _, t, _ in row),
                              extended=True)
    else:
        g = _label_tick_group(line, cs, median(t["size"] or 1.0 for _, t, _ in row),
                              frame_ends=True)
    n = len(axes)
    ok = axes_from_group(g, orient, line, [t for _, t, _ in row], axes, debug)
    for a in axes[n:]:
        a["from_labels"] = True           # (placed by its labels: _labels_inside)
    return ok


def _at_corner(orient, line, axes):
    """Does an axis of the other direction, fitted to three labels or more,
    have its line end where `line` (lo, hi, pos) runs, near one of its ends?"""
    lo, hi, pos = line
    for a in axes:
        if a["orient"] == orient or not a["has_line"] or a["map"]["kind"] == "nominal" or \
                a["map"].get("n", 0) < 3:
            continue
        if min(abs(a["lo"] - pos), abs(a["hi"] - pos)) <= 1.5 and \
                min(abs(a["pos"] - lo), abs(a["pos"] - hi)) <= 1.5:
            return True
    return False


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
    # labels inside a plot (the box of a numeric x axis and a numeric y
    # axis) are no axis labels: wp_21_1036-019's legend names, in the plot's
    # top right corner, beside its right side
    boxes = [(xa["lo"], ya["lo"], xa["hi"], ya["hi"])
             for xa in axes if xa["orient"] == "x" and xa["map"]["kind"] != "nominal"
             for ya in axes if ya["orient"] == "y" and ya["map"]["kind"] != "nominal"]
    near = []
    for t in PAGE.nominal_labels:
        # (a name that reads as a quantity with a unit, "2mm", is a word
        # among words: 3485513-020's benchmark names)
        if id(t) in taken or (t.get("value") is not None and
                              not re.search(r"[A-Za-z]", t.get("text") or "")):
            continue
        b, size = t["bbox"], t.get("size") or 1.0
        lo2, hi2 = (b[1], b[3]) if orient == "x" else (b[0], b[2])
        mx, my = 0.5 * (b[0] + b[2]), 0.5 * (b[1] + b[3])
        if any(x0 < mx < x1 and y0 < my < y1 for x0, y0, x1, y1 in boxes):
            continue
        gap = max(lo2 - pos, pos - hi2)
        # a slanted label points at its category with its end nearest the
        # line (3485513-020: names slanted 60 degrees under a line chart)
        c = _label_anchor(t, orient, pos) if _slanted(t, orient) else 0.5 * (b[k] + b[k + 2])
        # (a slanted label's end may stand a little past the line's end:
        # 3485513-020's last name, 2.9 pt beyond it)
        tl = max(tol, size) if _slanted(t, orient) else tol
        # (y labels set flush left stand further off: kept below if their
        # column holds one near the line)
        if lo - tl <= c <= hi + tl and 0 <= gap <= (4 if orient == "x" else 25) * size:
            near.append((c, gap, size, t))
    flush = None
    if orient == "y":
        near, flush = _flush_left_column(near, pos)
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
        # (slanted labels' boxes overlap; a flush-left column's names are
        # one per line, its lines no two-line labels)
        for w in (() if slanted or flush else words):
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
    if flush:
        g["flush_left"] = flush           # (nominal_axis: one row at the column's gap)
    return axes_from_group(g, orient, line, [], axes, debug)


def _flush_left_column(near, pos):
    """Category labels of a y axis: those within 4 text sizes of the line,
    and labels set flush left in a column with them (2020.01.30.927558.
    full-026: model names left of horizontal bars, "M-Avg, ε=KL(Δ)×n"
    reaching the axis, "IIAB, ε=|Δ|" ending 40 pt short): three or more
    labels on the line's left whose left edges agree within 1 pt, evenly
    spaced, one of them within 4 text sizes of the line, all count, one
    name per line.  Returns the labels and (left edge, the column's least
    gap), or None if there is no such column."""
    close = [r for r in near if r[1] <= 4 * r[2]]
    left = [r for r in near if r[3]["bbox"][2] <= pos + 1.0]
    keep = {id(r) for r in close}
    flush = None
    for r in close:
        col = [o for o in left if abs(o[3]["bbox"][0] - r[3]["bbox"][0]) <= 1.0]
        # (evenly spaced, one name per line: lines of two-line labels
        # are closer together than their categories)
        if len(col) >= 3 and _evenly_spaced(sorted(o[3]["center"][1] for o in col)):
            keep.update(id(o) for o in col)
            flush = (r[3]["bbox"][0], min(o[1] for o in col))
    return [r for r in near if id(r) in keep], flush


def _number_category_ticks_axis(orient, line, axes, debug):
    """An x axis line without tick marks whose labels are numbers that
    follow no scale: categories named by numbers (Memory_systems_cacheDRAMdisk-051's
    PERL chart: system bandwidths 0.1, 0.2, 0.4 ... 25.6, each centred under
    its group of bars, unevenly spaced).  A row of four or more level
    numbers beside the line (within 2 label sizes, one baseline), within
    its span, rising along it, not fitting a linear or log scale; their
    centres are the category positions.  A second row just below (within
    1.8 label sizes) whose labels fall one in each gap of the first's (80%
    of them or more) is merged with it: labels set alternately in two rows
    (VaskeBeaman2006-Lessonslearned-003: 1 3 5 ... over 2 4 6 ...)."""
    if orient != "x":
        return False
    lo, hi, pos = line
    tol = max(1.0, 0.01 * (hi - lo))
    taken = _labels_in_use(axes)
    row = []
    for t in PAGE.nominal_labels:
        v = t.get("value")
        if v is None or t.get("rotated") or t.get("date") or id(t) in taken:
            continue
        b, size = t["bbox"], t["size"] or 1.0
        gap = max(b[1] - pos, pos - b[3])
        c = 0.5 * (b[0] + b[2])
        if lo - tol <= c <= hi + tol and 0 <= gap <= 4 * size and b[3] <= pos + 0.5 * size:
            row.append((c, t, gap))
    # (the first row within 2 label sizes of the line; a second further)
    if sum(1 for r in row if r[2] <= 2 * (r[1]["size"] or 1.0)) < 2:
        return False
    row = [(c, t) for c, t, _ in row]
    # rows of labels by baseline, the nearest the line first
    rows = []
    for r in sorted(row, key=lambda r: -r[1]["bbox"][1]):
        if rows and abs(rows[-1][0] - r[1]["bbox"][1]) <= 0.3 * (r[1]["size"] or 1.0):
            rows[-1][1].append(r)
        else:
            rows.append([r[1]["bbox"][1], [r]])
    near = [rw for rw in rows if max(rw[1][0][1]["bbox"][1] - pos, pos - rw[1][0][1]["bbox"][3])
            <= 2 * (rw[1][0][1]["size"] or 1.0)]
    if not near:
        return False
    first = max(near, key=lambda rw: len(rw[1]))
    row = sorted(first[1], key=lambda r: r[0])
    # a second row just below whose labels fall in the first row's gaps,
    # alternating with them (labels too crowded for one row: 1 3 5 ... over
    # 2 4 6 ..., VaskeBeaman2006-Lessonslearned-003's right-hand charts)
    below = [rw for rw in rows if rw is not first and
             0 < first[0] - rw[0] <= 1.8 * median(t["size"] or 1.0 for _, t in row)]
    if below and len(row) >= 2:
        second = sorted(max(below, key=lambda rw: len(rw[1]))[1], key=lambda r: r[0])
        cs = [c for c, _ in row]
        gaps = [k for c, _ in second for k in range(len(cs) - 1) if cs[k] < c < cs[k + 1]]
        if len(second) >= 2 and len(gaps) >= 0.8 * len(second) and len(set(gaps)) == len(gaps):
            row = sorted(row + second, key=lambda r: r[0])
    if len(row) < 4:
        return False
    # a label drawn turned upside down among upright ones (S1383762124002030
    # page 7: the "7" of 1, 7, 18, 29 ... read as "6") is a misreading
    # that makes a scale look uneven: no categories then
    if any(abs((t.get("angle") or 0.0) % 360 - 180) < 1 for _, t in row):
        return False
    vals = [t["value"] for _, t in row]
    if any(q <= p for p, q in zip(vals, vals[1:])):
        return False
    pairs = LabelPairs([(c, t["value"]) for c, t in row], [0.0] * len(row), [t for _, t in row])
    m = fit_axis(pairs)
    if m is not None and m["n"] == len(row):
        return False                     # a scale after all (not this rule's)
    g = _label_tick_group(line, [c for c, _ in row], median(t["size"] or 1.0 for _, t in row),
                          extended=True)
    g["label_pairs"] = list(row)
    n0 = len(axes)
    ok = axes_from_group(g, orient, line, [], axes, debug)
    for a in axes[n0:]:
        a["number_categories"] = True
    return ok


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
    # (only labels that can pair with these ticks: along the axis by the
    # ticks, across it within reach of a tick end - the pairing allows 5
    # label sizes - which spares a page of thousands of tick groups a scan
    # of every label for each: ArianeWuerbach-Phd-219)
    ka = 0 if orient == "x" else 1
    t_lo, t_hi = min(g["pos"]), max(g["pos"])
    o_lo, o_hi = min(outers), max(outers)
    near = [tx for tx in numeric
            if tx["bbox"][ka + 2] >= t_lo - 2 * (tx["size"] or 1.0) - 0.5 * (t_hi - t_lo) and
            tx["bbox"][ka] <= t_hi + 2 * (tx["size"] or 1.0) + 0.5 * (t_hi - t_lo) and
            tx["bbox"][3 - ka] >= o_lo - 6 * (tx["size"] or 1.0) and
            tx["bbox"][1 - ka] <= o_hi + 6 * (tx["size"] or 1.0)]
    for outer in outers:
        if apos is not None and abs(outer - apos) > 1e-9:
            sign = 1 if outer > apos else -1
        elif apos is not None:             # labels opposite the tick direction
            sign = -1 if far > apos else 1
        else:
            sign = 1 if outer == g["hi"] else -1
        pairs = assign_labels(g["pos"], orient, outer, sign,
                              split_labels_at_ticks(g["pos"], orient, near))
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
    low = _low_category_labels(g, orient, line, m, axes, debug)
    if low is not None:
        lab = low
    elif m is None or (m["n"] <= 2 and len(g["pos"]) >= 6):
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
        elif len({(tx.get("text") or "").strip().lower() for _, tx in lab}) == 1 and \
                (lab[0][1].get("text") or "").strip():
            # (one name at every tick is no category axis: categories
            # differ - Seongmin-PhD-036's "W-ORBS" under each of two charts,
            # at the feet of their left axes, taken for ticks)
            m = None
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
            "low_labels": low is not None and lab is low,
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


_POWER_LABEL = re.compile(r"^10\^[-\u2212]?\d+$")


def _two_label_log_axes(axes, debug=False):
    """An axis of two ticks, labelled v and 2v or v and 10^k v (both
    positive; more ticks mean labels left unread: jordan-teh-026), whose line runs on past where 0 would stand on a linear
    scale, by a label spacing or more, with no label there: a log scale
    (a linear one would label 0 and the negative values below).
    Seongmin-PhD-044's replace panel shows only 1000 and 2000 on its time
    axis (the other time axes are log 2), and read as linear its boxes
    went down to -2700 seconds.  The mapping is turned into a log one
    through the same two ticks.  Only on a page with another log axis
    whose labels step by the same ratio (histogram's small panels label
    2.5 and 5 on linear axes) - or when both labels are written as powers
    of ten ("10^2", "10^4"), which needs neither."""
    ratios = set()
    for a in axes:
        m = a.get("map")
        vals = sorted(v for (_, v), _ in (a.get("labels") or ())
                      if isinstance(v, (int, float)) and v > 0)
        if m and m["kind"] == "log" and len(vals) >= 3:
            # (2, or a power of ten: Maj-Petr_PhD-077 labels 10, 1000,
            # 100000 on three panels and only 10 and 1000 on the fourth)
            for r in (2.0, 10.0, 100.0, 1000.0):
                if all(abs(b / x - r) <= 1e-6 * r for x, b in zip(vals, vals[1:])):
                    ratios.add(r)
    for a in axes:
        m = a.get("map")
        labs = a.get("labels") or ()
        if not m or m["kind"] != "linear" or m.get("n") != 2 or len(labs) != 2 or not a["has_line"]:
            continue
        if len(a.get("ticks") or ()) != 2:
            continue                          # unlabelled ticks: labels left unread
        if not all(isinstance(p[1], (int, float)) for p, _ in labs):
            continue
        (c1, v1), (c2, v2) = sorted((p for p, _ in labs), key=lambda p: p[1])
        if v1 <= 0 or c1 == c2:
            continue
        ratio = v2 / v1
        # (labels written as powers of ten, 10^2 and 10^4, mark a log
        # axis by themselves: 2305.15675v1-015's log-log histogram, alone
        # on its page)
        powers = all(_POWER_LABEL.match(tx["text"].strip()) for _, tx in labs)
        if not powers and not any(abs(ratio - r) <= 1e-9 * r for r in ratios):
            continue
        c0 = -m["b"] / m["a"]                 # where 0 would stand
        step = abs(c2 - c1)
        # the line runs on below the smaller label, unlabelled, past where 0
        # would stand and by a quarter step at least (ratio 100:
        # Maj-Petr_PhD-077's 10 and 1000, 0 within half a point of the 10)
        down = -1.0 if c2 > c1 else 1.0
        end = a["lo"] if down < 0 else a["hi"]
        reach = max(abs(c0 - c1), 0.25 * step) - 0.5
        if not powers and ((end - c1) * down < reach or abs(c0 - c1) > abs(c0 - c2)):
            continue                          # 0 not beyond the smaller value
        la = (math.log10(v2) - math.log10(v1)) / (c2 - c1)
        a["map"] = dict(m, kind="log", a=la, b=math.log10(v1) - la * c1)
        if debug:
            print("[debug] %s-axis at %.2f: labels %g, %g only, 0 inside the line: log scale"
                  % (a["orient"], a["pos"], v1, v2), file=sys.stderr)


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
        # (the ticks only now, for the few lines with one 10^k label: every
        # bare line scanning all segments cost seconds on big pages)
        segs = hs_open if orient == "y" else vs_open
        ticks = sorted({round(p, 3) for s_lo, s_hi, p in segs
                        if (abs(s_lo - X) <= 0.5 or abs(s_hi - X) <= 0.5) and lo - 0.5 <= p <= hi + 0.5})
        if len(ticks) < 5:
            continue
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

"""Legends: legend keys (a marker or line sample with a label to its right)
and the naming of every data symbol's series from them.

The series column of the output comes from here.  Keys are reported as
points too (legend_key = 1), so they must be told from data points: a key
has its label just to its right, stands apart on its line, and lines up
with the other keys of its legend.
"""

import re

from .colours import color_name
from .geometry import bbox_of, median, rect_distance, rect_of, thin_rect_line, vertices
from .graphs import frame_symbols, frame_texts
from .spatial import BoxGrid, SortedIndex
from .symbols import symbol_signature
from .text import is_number


_SAMPLE_LEVEL_PT = 0.05  # a line sample is level within 0.05 pt
_SAMPLE_MAX_PT = 60      # and under 60 pt long


def legend_line_samples(paths):
    """Short horizontal strokes: the line samples of legend entries; also
    such strokes converted to thin filled rectangles (Inkscape, cairo)."""
    out = []
    for p in paths:
        if not p["stroke"]:
            if p["fill"] and len(p["subpaths"]) == 1:
                ln = thin_rect_line(p["subpaths"][0])
                if ln is not None:
                    (ax, ay), (bx, by) = ln
                    if abs(ay - by) < _SAMPLE_LEVEL_PT and 2 < abs(ax - bx) < _SAMPLE_MAX_PT:
                        out.append((min(ax, bx), max(ax, bx), (ay + by) / 2))
            continue
        for sp in p["subpaths"]:
            if sp["closed"] or len(sp["segs"]) != 1 or sp["segs"][0][0] != "l":
                continue
            a, b = sp["start"], sp["segs"][0][1]
            if abs(a[1] - b[1]) < _SAMPLE_LEVEL_PT and 2 < abs(a[0] - b[0]) < _SAMPLE_MAX_PT:
                out.append((min(a[0], b[0]), max(a[0], b[0]), (a[1] + b[1]) / 2))
    return out


def find_legend(symbols, texts, hlines=(), *, page):
    """Legend keys: a marker with a (non-numeric) label just to its right on
    the same line - measured from the end of the line sample the marker sits
    on, if any.  Returns {symbol index: label}.

    Markers stacked on one spot (and repeated line samples) are looked at
    once: ThomasBockPhD-073 stacks tens of thousands of identical markers,
    each with its own line sample, and looking at each pair took minutes.
    Every copy gets the key its spot gets."""
    spots, copies = {}, []
    for i, s in enumerate(symbols):
        k = (s["cx"], s["cy"], s["size"])
        if k not in spots:
            spots[k] = len(copies)
            copies.append([i])
        else:
            copies[spots[k]].append(i)
    if len(copies) == len(symbols):
        return _find_legend(symbols, texts, set(hlines), [1] * len(symbols), page=page)
    reps = [symbols[c[0]] for c in copies]
    keys = _find_legend(reps, texts, set(hlines), [len(c) for c in copies], page=page)
    return {i: label for r, label in keys.items() for i in copies[r]}


_LEAD_LEVEL_EMS = 0.5  # a value read out after a lead-in: level within half a font size
_LEAD_GAP_EMS = 1.5    # within 1.5 font sizes after it


def _reads_out_value(t, texts):
    """Text ending in a colon with a number just after it on its line."""
    if not t["text"].strip().endswith(":"):
        return False
    size = t["size"] or 1.0
    return any(is_number(o) and abs(o["center"][1] - t["center"][1]) < _LEAD_LEVEL_EMS * size and
               0 <= o["bbox"][0] - t["bbox"][2] <= _LEAD_GAP_EMS * size for o in texts)


_LABEL_MAX_CHARS = 60       # a legend label is at most 60 characters
_LABEL_LEVEL_EMS = 0.6      # a label level with its key: within 0.6 of a font size
_SAMPLE_CELL_PT = 8.0       # line samples filed in cells of 8 pt
_SAMPLE_REACH_PT = 0.5      # a key on a sample: within 0.5 pt of its ends
_SAMPLE_LEVEL_SIZES = 0.3   # and 0.3 of the key's size across
_LABEL_BEFORE_EMS = 0.2     # a label starts from 0.2 of a font size before the key's right
_LABEL_AFTER_EMS = 3        # to 3 font sizes after it
_NEAR_KEYS_EMS = 20         # keys beside a label: within 20 font sizes to its right
_HELPER_GLYPH = 0.3         # glyphs under 0.3 of the label's size are invisible helpers
_SUBSCRIPT_MAX = 0.9        # a subscript is under 0.9 of the label's size
_SUBSCRIPT_BACK_EMS = 0.1   # it starts from 0.1 of a font size before the label's end
_SUBSCRIPT_GAP_EMS = 0.3    # to 0.3 after
_SUBSCRIPT_LEVEL_EMS = 0.7  # level within 0.7 of a font size
_NEXT_WORD_SIZE = 0.05      # the next word of a label: its size within 5%
_NEXT_WORD_GAP_EMS = 0.4    # within 0.4 of a font size after
_NEXT_WORD_LEVEL_EMS = 0.1  # on the label's baseline within 0.1 of a font size
_CURVE_NEIGHBOUR = 0.5      # a marker on a dense curve has neighbours within half its size across
_CURVE_MIN_GAP = 0.25       # from a quarter of its size
_STACKED_PT = 1.5           # stacked legend entries line up within 1.5 pt
_STACKED_ROWS_EMS = 4       # rows within 4 font sizes per entry


def _find_legend(symbols, texts, hlines, weight, *, page):
    """find_legend on distinct markers; weight[i]: copies of marker i."""
    entries = {}
    # possible labels (a long line of a paragraph is none), by height on
    # the page, so each marker only looks at the texts on its own line
    # (a lead-in to a value - "RMSE: 2.14", in a fit annotation beside a
    # stray data point, ThomasBockPhD-073 - names no series)
    labels = SortedIndex([t for t in texts
                          if not (is_number(t) or t["rotated"] or not t["text"].strip()
                                  or len(t["text"].strip()) > _LABEL_MAX_CHARS) and not _reads_out_value(t, texts)],
                         key=lambda t: t["center"][1])
    reach = _LABEL_LEVEL_EMS * max((t["size"] or 1.0 for t in labels.items), default=1.0)
    # line samples (horizontal), so a marker looks only at the samples
    # around itself
    hl_grid = BoxGrid(_SAMPLE_CELL_PT)
    for x0, x1, y in hlines:
        hl_grid.add((x0, x1, y), (x0 - _SAMPLE_REACH_PT, y, x1 + _SAMPLE_REACH_PT, y))
    by_left = sorted(texts, key=lambda o: o["bbox"][0])     # (for label continuations)
    by_y = SortedIndex(symbols, key=lambda u: u["cy"])
    keys_by_label = {}
    for i, s in enumerate(symbols):
        # (a bar stands on the baseline: never a key - the tallest bars of
        # Memory_systems_cacheDRAMdisk-051 reach the subtitle beside them.
        # A box plot's legend key is read as a little box plot, and must be
        # found as a key: Seongmin-PhD-044)
        if s["shape"] in ("bar", "stem", "tile", "errorbar", "area"):
            continue
        right = s["cx"] + s["size"] / 2
        tol = _SAMPLE_LEVEL_SIZES * max(s["size"], 1.0)
        for x0, x1, y in hl_grid.near((s["cx"], s["cy"] - tol, s["cx"], s["cy"] + tol)):
            if x0 - _SAMPLE_REACH_PT <= s["cx"] <= x1 + _SAMPLE_REACH_PT and abs(y - s["cy"]) < tol:
                right = max(right, x1)
        best = None
        for t in labels.between(s["cy"] - reach, s["cy"] + reach):
            size = t["size"] or 1.0
            gap = t["bbox"][0] - right
            if not (-_LABEL_BEFORE_EMS * size <= gap <= _LABEL_AFTER_EMS * size):
                continue
            if abs(t["center"][1] - s["cy"]) > _LABEL_LEVEL_EMS * size:
                continue
            # text outside the graph that holds the marker (a data point at
            # the edge of the plot next to the body text) is no legend label
            if any(r[0] < s["cx"] < r[2] and r[1] < s["cy"] < r[3] and
                   not (r[0] <= t["center"][0] <= r[2] and r[1] <= t["center"][1] <= r[3])
                   for r in page.graph_rects):
                continue
            if best is None or gap < best[0]:
                best = (gap, t)
        if best:
            t = best[1]
            label = t["text"].strip()
            # (markers: not the legend's frame box; the markers at the label's
            # height found once per label, by bisection: thousands of points
            # beside a label took minutes on ESEUR-slowpages)
            near_keys = keys_by_label.get(id(t))
            if near_keys is None:
                ty, reach_y = t["center"][1], 2 * t["size"]
                near_keys = keys_by_label[id(t)] = [
                    u for u in by_y.between(ty - reach_y, ty + reach_y)
                    if u["size"] < 2 * t["size"] and abs(u["cy"] - ty) < reach_y
                    and t["bbox"][2] < u["cx"] < t["bbox"][2] + _NEAR_KEYS_EMS * t["size"]]
            # subscripts / superscripts that continue the label: f + 16
            end = t["bbox"][2]
            whole = label       # (the label up to its last word that is no number)
            joined = set()

            def script(o, at):
                return o is not t and id(o) not in joined and o["size"] < _SUBSCRIPT_MAX * t["size"] and \
                    o["size"] >= _HELPER_GLYPH * t["size"] and \
                    -_SUBSCRIPT_BACK_EMS * t["size"] <= o["bbox"][0] - at < _SUBSCRIPT_GAP_EMS * t["size"] and \
                    abs(o["center"][1] - t["center"][1]) < _SUBSCRIPT_LEVEL_EMS * t["size"]
            for o in by_left:
                if o["size"] < _HELPER_GLYPH * t["size"] or id(o) in joined:
                    continue                 # invisible helper glyphs
                if script(o, end):
                    # (a subscript and a superscript set one over the other,
                    # the lower first: 2411.16433v1-066's legend names, N
                    # with 2 below and PO above -> "N2PO")
                    stack = sorted((u for u in by_left if u is o or script(u, o["bbox"][0])),
                                   key=lambda u: u["center"][1])
                    for u in stack:
                        label += u["text"].strip()
                        joined.add(id(u))
                    end = max(u["bbox"][2] for u in stack)
                    whole = label
                elif o is not t and abs(o["size"] - t["size"]) <= _NEXT_WORD_SIZE * t["size"] and \
                        0 < o["bbox"][0] - end <= _NEXT_WORD_GAP_EMS * t["size"] and \
                        abs(o["p0"][1] - t["p0"][1]) < _NEXT_WORD_LEVEL_EMS * t["size"] and \
                        not o["rotated"] and \
                        not any(end < u["cx"] < o["bbox"][0] and
                                abs(u["cy"] - t["center"][1]) < t["size"] for u in near_keys):
                    # the next word of the label, set as a separate piece
                    # ("FULL" in small capitals, then "higher"); a number
                    # only when a word follows it (economies-open-
                    # intelligence-005's "Top 20 (Inclusive)")
                    label += " " + o["text"].strip()
                    end = o["bbox"][2]
                    if o["value"] is None:
                        whole = label
            label = whole
            entries[i] = (label, t)
    keys = {i: e[0] for i, e in entries.items()}
    # a key stands apart on its line; markers along a dense data curve have
    # neighbours just left and right of them (concentric layers are fine)
    if keys:
        grid = {}
        cell = max(1.0, median(s["size"] for s in symbols))
        for j, s in enumerate(symbols):
            grid.setdefault((int(s["cx"] // cell), int(s["cy"] // cell)), []).append(j)
        for i in list(keys):
            s = symbols[i]
            reach = 2.0 * s["size"]
            gx, gy = int(s["cx"] // cell), int(s["cy"] // cell)
            n = int(reach // cell) + 1
            for dx in range(-n, n + 1):
                for dy in (-1, 0, 1):
                    for j in grid.get((gx + dx, gy + dy), ()):
                        o = symbols[j]
                        ddx = abs(o["cx"] - s["cx"])
                        if j != i and abs(o["cy"] - s["cy"]) < _CURVE_NEIGHBOUR * s["size"] and \
                                _CURVE_MIN_GAP * s["size"] < ddx < reach:
                            keys.pop(i, None)
    # legend entries line up with each other (stacked or side by side); an
    # annotation next to a data point does not.  When a page has an aligned
    # legend, unaligned candidates are dropped.
    ids = list(keys)
    n_ids = sum(weight[i] for i in ids)
    grouped = set()
    for a in ids:
        for b in ids:
            if a >= b or entries[a][1] is entries[b][1]:
                continue
            sa, sb = symbols[a], symbols[b]
            ta, tb = entries[a][1], entries[b][1]
            stacked = abs(sa["cx"] - sb["cx"]) <= _STACKED_PT and abs(ta["bbox"][0] - tb["bbox"][0]) <= _STACKED_PT \
                and abs(sa["cy"] - sb["cy"]) < _STACKED_ROWS_EMS * max(ta["size"], 1.0) * max(1, n_ids)
            side = abs(sa["cy"] - sb["cy"]) <= 1.0 and abs(ta["center"][1] - tb["center"][1]) <= 1.0
            if stacked or side:
                grouped.update((a, b))
    if grouped:
        same_spot = {i for i in ids if any(
            j in grouped and entries[j][1] is entries[i][1] for j in ids)}
        keys = {i: v for i, v in keys.items() if i in grouped or i in same_spot}
    return keys


_NUMBERED_RUN = 3  # a numbered legend: runs of 3 or more
_COLUMN_EMS = 1.5  # its labels in one column within 1.5 font sizes


def numbered_legend(symbols, texts):
    """Colour swatches labelled 1, 2, 3, ... stacked in a column: a legend
    whose series names are numbers (find_legend ignores numeric labels).
    Returns {symbol index: label}."""
    cands = []
    for i, s in enumerate(symbols):
        if s["shape"] not in ("square", "rectangle") or not s["filled"]:
            continue
        right = s["cx"] + s["size"] / 2
        best = None
        for t in texts:
            v = t["value"]
            if v is None or t["rotated"] or v != int(v) or not t["text"].strip().isdigit():
                continue
            size = t["size"] or 1.0
            gap = t["bbox"][0] - right
            if -_LABEL_BEFORE_EMS * size <= gap <= _LABEL_AFTER_EMS * size and abs(t["center"][1] - s["cy"]) <= _LABEL_LEVEL_EMS * size:
                if best is None or gap < best[0]:
                    best = (gap, t)
        if best:
            cands.append((i, best[1]))
    keys = {}
    used = set()
    for i, t in cands:
        if i in used:
            continue
        col = [(j, u) for j, u in cands
               if abs(symbols[j]["cx"] - symbols[i]["cx"]) <= 1.0 and
               abs(u["bbox"][0] - t["bbox"][0]) <= _COLUMN_EMS * (t["size"] or 1.0)]
        col.sort(key=lambda ju: -symbols[ju[0]]["cy"])          # top down
        # runs of consecutive numbers (one legend per panel)
        runs, run = [], []
        for j, u in col:
            if run and int(u["value"]) != int(run[-1][1]["value"]) + 1:
                runs.append(run)
                run = []
            run.append((j, u))
        runs.append(run)
        for run in runs:
            if len(run) >= _NUMBERED_RUN:
                for j, u in run:
                    keys[j] = u["text"].strip()
        used.update(j for j, _ in col)
    return keys


_GRAPH_REACH_FRAC = 0.25     # samples within a quarter of the graph's size of it
_DASH_FILL_PT = 1.5          # a filled dash is under 1.5 pt thick
_DASH_MAX_PT = 10            # and 1 to 10 pt long
_BAND_MAX_PT = 3             # a band sample is under 3 pt thick
_BAND_MIN_PT = 10            # and 10 to 60 pt long
_BAND_ASPECT = 5             # at least 5 times as long as thick
_ROW_GAP_PT = 6              # dashes of a row under 6 pt apart
_ROW_LEVEL_PT = 0.5          # level within 0.5 pt
_STROKED_GAP_PT = 0.3        # stroked dashes at least 0.3 pt apart
_STROKED_DASH_PT = 10        # and under 10 pt long
_SOLID_MIN_PT = 3            # a solid sample is over 3 pt long
_LINE_LABEL_AFTER_EMS = 0.2  # a line's label from 0.2 of a font size before its sample's end
_LINE_LABEL_LEVEL_EMS = 0.6  # level within 0.6 of a font size


def legend_for_lines(series, paths, texts, rect=None, *, page):
    """Legend entries of line series: a short horizontal line sample (or a
    row of dashes) in the series' style with a label just to its right.
    With the graph's box `rect`, only samples within it or beside it (a
    quarter of its size off, or half when no other graph is nearer) count:
    logpaper5Rediscoveries-007's right graph took the names of the left
    one's legend (D-Lognormal for its solid line) instead of its own (Year
    1, 2, 3)."""
    names = {}
    samples = []
    if rect is not None:
        mx, my = _GRAPH_REACH_FRAC * (rect[2] - rect[0]), _GRAPH_REACH_FRAC * (rect[3] - rect[1])
        area = (rect[0] - mx, rect[1] - my, rect[2] + mx, rect[3] + my)
        far = (rect[0] - 2 * mx, rect[1] - 2 * my, rect[2] + 2 * mx, rect[3] + 2 * my)

    def near_graph(cx, cy):
        # within a quarter of the graph's size, or within half of it when
        # no other graph of the page is nearer (Sovinsky-paper-017: a
        # two-row legend under the x axis title, its second key 49 pt below
        # a 161 pt plot)
        if area[0] <= cx <= area[2] and area[1] <= cy <= area[3]:
            return True
        if not (far[0] <= cx <= far[2] and far[1] <= cy <= far[3]):
            return False
        d = rect_distance(rect, cx, cy)
        return all(rect_distance(r, cx, cy) > d for r in page.graph_rects if tuple(r) != tuple(rect))
    for p in paths:
        for sp in p["subpaths"]:
            pts = vertices(sp)
            b = bbox_of(pts)
            if rect is not None and not near_graph((b[0] + b[2]) / 2, (b[1] + b[3]) / 2):
                continue
            if p["stroke"] and not sp["closed"] and len(sp["segs"]) == 1 and \
                    abs(b[3] - b[1]) < _SAMPLE_LEVEL_PT and 1 < b[2] - b[0] < _SAMPLE_MAX_PT:
                # (strokes of 1 to 3 pt only as dashes of a row: a dash
                # pattern may end on a short one)
                samples.append((("solid",), p["stroke_rgb"], b))
            elif p["fill"] and len(sp["segs"]) in (3, 4) and abs(b[3] - b[1]) < _DASH_FILL_PT and 1 < b[2] - b[0] < _DASH_MAX_PT:
                samples.append((("dashed",), p["fill_rgb"], b))
            elif p["fill"] and not p["stroke"] and len(sp["segs"]) in (3, 4) and \
                    0 < b[3] - b[1] < _BAND_MAX_PT and _BAND_MIN_PT <= b[2] - b[0] < _SAMPLE_MAX_PT and b[2] - b[0] >= _BAND_ASPECT * (b[3] - b[1]) and \
                    rect_of(sp):
                # a line sample filled as a thin band, its height the line's
                # width (2020.01.30.927558.full-012's "True value" and
                # "Slider value", 12.8 x 1.7 pt, for 0.7 pt strokes)
                samples.append((("solid",), p["fill_rgb"], b))
    # rows of dashes form one sample; so do short strokes in a row with gaps
    # between them, dashes stroked one by one (Sovinsky-paper-017's
    # "- - - - -" key, five strokes 2.5 pt apart)
    # (samples are taken left to right, so a row ending 6 pt or more left of
    # one is never continued again: only the open rows of a colour are
    # tried, in the order they were begun - every sample against every row
    # took minutes on ESEUR-slowpages' thousands of short strokes)
    rows, open_rows = [], {}
    for st, rgb, b in sorted(samples, key=lambda s: s[2][0]):
        live = open_rows[rgb] = [r for r in open_rows.get(rgb, ()) if b[0] - r[2][2] < _ROW_GAP_PT]
        if st == ("dashed",):
            for r in live:
                if r[0] == st and r[1] == rgb and abs(r[2][1] - b[1]) < _ROW_LEVEL_PT and 0 <= b[0] - r[2][2] < _ROW_GAP_PT:
                    r[2] = (r[2][0], min(r[2][1], b[1]), b[2], max(r[2][3], b[3]))
                    r[3] += 1
                    break
            else:
                rows.append([st, rgb, b, 1])
                live.append(rows[-1])
        else:
            for r in live:
                if r[1] == rgb and r[0] != ("dashed",) and abs(r[2][1] - b[1]) < _ROW_LEVEL_PT and \
                        _STROKED_GAP_PT <= b[0] - r[2][2] < _ROW_GAP_PT and b[2] - b[0] < _STROKED_DASH_PT and r[4] < _STROKED_DASH_PT:
                    r[0] = ("stroked-dashes",)
                    r[2] = (r[2][0], min(r[2][1], b[1]), b[2], max(r[2][3], b[3]))
                    r[4] = b[2] - b[0]
                    break
            else:
                rows.append([st, rgb, b, 2, b[2] - b[0]])
                live.append(rows[-1])
    for r in rows:
        if r[0] == ("stroked-dashes",):
            r[0] = ("dashed",)
    rows = [r[:4] for r in rows if r[0] == ("dashed",) or r[2][2] - r[2][0] > _SOLID_MIN_PT]
    for st, rgb, b, n in rows:
        if n < 2:
            continue
        cy = (b[1] + b[3]) / 2
        best = None
        for t in texts:
            if t["rotated"] or not t["text"].strip() or is_number(t):
                continue
            gap = t["bbox"][0] - b[2]
            if -_LINE_LABEL_AFTER_EMS * t["size"] <= gap <= 2 * t["size"] and abs(t["center"][1] - cy) < _LINE_LABEL_LEVEL_EMS * t["size"]:
                if best is None or gap < best[0]:
                    best = (gap, t["text"].strip())
        if not best:
            continue
        for i, s in enumerate(series):
            if s["style"][0] == st[0] and s["rgb"] == rgb:
                names.setdefault(i, best[1])
    return names


def _clean_label(label):
    """A legend name: one unknown character between numbers ("85\ufffd90",
    a dash in a font that cannot be read) is a range dash."""
    return re.sub(r"(?<=\d)\ufffd(?=\d)", "\u2013", label) if label else label


def find_page_legend(symbols, texts, blobs, graphs, paths, *, page):
    """Legend keys of the page: {symbol index: series name}.  Combines
    keys with text labels (also in turned graphs), colour swatches labelled
    1, 2, 3 ... and keys whose label is drawn as unreadable outlines (their
    name is left blank).  A marker clipped out of view (an outlier far
    beyond a plot's range, which may land on text elsewhere on the page)
    is no legend key."""
    shown = [i for i, s in enumerate(symbols) if not clipped_out(s)]
    if len(shown) < len(symbols):
        keys = _page_legend([symbols[i] for i in shown], texts, blobs, graphs, paths, page=page)
        return {shown[i]: _clean_label(name) for i, name in keys.items()}
    return {i: _clean_label(name) for i, name in _page_legend(symbols, texts, blobs, graphs, paths, page=page).items()}


_CAPTION_START = re.compile(r"(?i)(fig(ure|\.)|table)\s*(?:[a-z]\.?)?[0-9]")


def _caption_between(s, rect, caps):
    """Does a caption line lie between symbol s and graph rect (across
    s's x, between them up or down)?"""
    x0, y0, x1, y1 = rect
    for t in caps:
        bx0, by0, bx1, by1 = t["bbox"]
        if not (bx0 <= s["cx"] <= bx1 or bx0 <= (x0 + x1) / 2 <= bx1):
            continue
        if (s["cy"] < by0 and by1 < y0) or (s["cy"] > by1 and by0 > y1):
            return True
    return False


_SWATCH_MIN_W = 4        # a bar swatch is 4 to 15 pt wide
_SWATCH_MAX_W = 15       # (the widest)
_SWATCH_MIN_H = 1.5      # 1.5 to 5 pt tall
_SWATCH_MAX_H = 5        # (the tallest)
_SWATCH_ASPECT = 1.8     # and 1.8 times as wide as tall
_SWATCH_LABEL_EMS = 1.5  # its label within 1.5 font sizes
_SWATCH_LEVEL = 0.5      # level within half its size


def patch_swatches(paths, texts, graphs):
    """Legend patches of a bar chart, too oblong to be markers
    (2401.16279-023's Figure 6: matplotlib's 7.4 x 2.6 pt patches before
    "t_RCD", "CAS latency", "t_RAS", "t_RC"): filled rectangles without
    outline, 4 to 15 pt wide, 1.5 to 5 pt tall and 1.8 times as wide as
    tall or more, inside a graph, each with a text just to its right on
    its line (within 1.5 of its size), two or more standing in a column
    (one left edge) in different colours.  Returned as square swatch
    symbols (filled rectangles are swatches) for the legend to find."""
    rects = [g["rect"] for g in graphs]
    cands = []
    for p in paths:
        if not p["fill"] or p["stroke"] or p.get("fill_rgb") is None or len(p["subpaths"]) != 1:
            continue
        sp = p["subpaths"][0]
        if len(sp["segs"]) not in (3, 4) or any(s[0] != "l" for s in sp["segs"]):
            continue
        pts = [sp["start"]] + [s[-1] for s in sp["segs"]]
        xs, ys = sorted({round(q[0], 3) for q in pts}), sorted({round(q[1], 3) for q in pts})
        if len(xs) != 2 or len(ys) != 2:
            continue
        w, h = xs[1] - xs[0], ys[1] - ys[0]
        if not (_SWATCH_MIN_W <= w <= _SWATCH_MAX_W and _SWATCH_MIN_H <= h <= _SWATCH_MAX_H and w >= _SWATCH_ASPECT * h):
            continue
        cx, cy = (xs[0] + xs[1]) / 2, (ys[0] + ys[1]) / 2
        if not any(r[0] < cx < r[2] and r[1] < cy < r[3] for r in rects):
            continue
        label = any(0 <= t["bbox"][0] - xs[1] <= _SWATCH_LABEL_EMS * (t["size"] or 1.0) and
                    abs(t["center"][1] - cy) <= _SWATCH_LEVEL * max(t["size"] or 1.0, h)
                    and t["text"].strip() and not t["rotated"] for t in texts)
        if label:
            cands.append((round(xs[0], 1), cx, cy, w, h, p))
    out = []
    cols = {}
    for c in cands:
        cols.setdefault(c[0], []).append(c)
    for col in cols.values():
        if len(col) < 2 or len({c[5]["fill_rgb"] for c in col}) != len(col):
            continue
        for _, cx, cy, w, h, p in col:
            out.append({"shape": "square", "cx": cx, "cy": cy, "size": h, "w": w, "h": h,
                        "filled": True, "rgb": p["fill_rgb"], "idx": p["idx"],
                        "clip": p.get("clip"), "patch": True})
    return out


_NUMERIC_LEVEL_EMS = 0.4   # a numeric key's label level within 0.4 of a font size
_NUMERIC_MAX_PT = 8        # numeric legend keys are at most 8 pt
_NUMERIC_GAP_EMS = 1.5     # the label within 1.5 font sizes
_NUMERIC_ROW_EMS = 3       # keys of a column within 3 font sizes
_NUMERIC_MIN = 3           # 3 keys or more
_NUMERIC_EVEN = 0.15       # evenly spaced within 15%
_NUMERIC_COLS_LEVEL = 0.3  # columns' rows level within 0.3 of a step
_NUMERIC_COLS_REACH = 12   # columns within 12 steps
_HEADING_BELOW = 0.5       # a heading from half a step below the top
_HEADING_ABOVE = 1.6       # to 1.6 steps above


def numeric_legend(symbols, texts):
    """Legend keys named by numbers (10.5445IR1000121285-038: V_DS 0.01,
    0.1, 0.2 | 0.4, 0.6, 0.8, 1 in two columns): three or more markers, each
    with a number just to its right on its line (within 1.5 of the number's
    size), standing in columns (one x each, two or more keys, evenly
    spaced), the columns' rows level with each other, all in different
    colours and with different numbers.  Returns ({symbol index: number as
    printed}, {texts of the heading just above the keys})."""
    found = {}
    # (the numbers sorted by height, so a marker looks only at those level
    # with it - every marker against every text cost seconds on big pages;
    # each one's candidates are taken in the texts' order, as before)
    nums = SortedIndex([(k, t) for k, t in enumerate(texts) if is_number(t) and not t["rotated"]],
                       key=lambda kt: kt[1]["center"][1])
    reach = _NUMERIC_LEVEL_EMS * max((t["size"] or 1.0 for _, t in nums.items), default=1.0)
    for i, s in enumerate(symbols):
        if s["shape"] in ("bar", "stem", "tile", "line") or s["size"] > _NUMERIC_MAX_PT or not s.get("rgb"):
            continue
        right = s["cx"] + s["size"] / 2
        best = None
        for _k, t in sorted(nums.between(s["cy"] - reach, s["cy"] + reach), key=lambda kt: kt[0]):
            ts = t["size"] or 1.0
            gap = t["bbox"][0] - right
            if 0 <= gap <= _NUMERIC_GAP_EMS * ts and abs(t["center"][1] - s["cy"]) <= _NUMERIC_LEVEL_EMS * ts:
                if best is None or gap < best[0]:
                    best = (gap, t)
        if best:
            found[i] = best[1]
    cols = {}
    for i in found:
        cols.setdefault(round(symbols[i]["cx"] * 2) / 2, []).append(i)
    # (a column runs on only while its keys are close: the legends of
    # panels one above the other share their x)
    runs = []
    for x, ids in cols.items():
        ids = sorted(ids, key=lambda i: symbols[i]["cy"])
        cur = [ids[0]]
        for i in ids[1:]:
            if symbols[i]["cy"] - symbols[cur[-1]]["cy"] > _NUMERIC_ROW_EMS * (found[i]["size"] or 1.0):
                runs.append((x, cur))
                cur = [i]
            else:
                cur.append(i)
        runs.append((x, cur))
    good = []
    for x, ids in runs:
        if len(ids) < 2:
            continue
        ys = sorted(symbols[i]["cy"] for i in ids)
        gaps = [b - a for a, b in zip(ys, ys[1:])]
        g = median(gaps)
        if g <= 0 or any(abs(d - g) > _NUMERIC_EVEN * g for d in gaps):
            continue
        good.append((x, g, ys, ids))
    keys, heads = {}, set()
    used = set()
    for x, g, ys, ids in good:
        if id(ids) in used:
            continue
        block = [(x, g, ys, ids)]
        for x2, g2, ys2, ids2 in good:
            short, long_ = (ys, ys2) if len(ys) <= len(ys2) else (ys2, ys)
            level = all(any(abs(a - b) <= _NUMERIC_COLS_LEVEL * g for b in long_) for a in short)
            if x2 != x and id(ids2) not in used and abs(g2 - g) <= _NUMERIC_EVEN * g and level and \
                    abs(x2 - x) <= _NUMERIC_COLS_REACH * g:
                block.append((x2, g2, ys2, ids2))
        members = [i for _, _, _, b in block for i in b]
        colours = {symbols[i]["rgb"] for i in members}
        values = {found[i]["text"].strip() for i in members}
        if len(members) < _NUMERIC_MIN or len(colours) != len(members) or len(values) != len(members):
            continue
        for _, _, _, b in block:
            used.add(id(b))
        for i in members:
            keys[i] = found[i]["text"].strip()
        # the heading: a text just above the top row, over the block
        top = max(symbols[i]["cy"] for i in members)
        x0 = min(symbols[i]["cx"] for i in members) - g
        x1 = max(found[i]["bbox"][2] for i in members) + g
        # (any other text over the keys' block: it may stand level with the
        # top key of a longer column - panel (f)'s "V_DS" beside "0.4")
        bottom = min(symbols[i]["cy"] for i in members)
        labels = {id(found[i]) for i in members}
        head = sorted((t for t in texts
                       if t["text"].strip() and not t["rotated"] and id(t) not in labels
                       and bottom - _HEADING_BELOW * g <= t["center"][1] <= top + _HEADING_ABOVE * g
                       and x0 <= t["center"][0] <= x1 and not is_number(t)), key=lambda t: t["bbox"][0])
        for t in head:
            heads.add(t["text"].strip())
        if head:
            # (as one label reads it: "V" and subscript "DS" -> "VDS")
            heads.add("".join(t["text"].strip() for t in head))
            heads.add(" ".join(t["text"].strip() for t in head))
    return keys, heads


def clipped_out(s):
    """Whether a symbol lies wholly outside the clipping box it was drawn
    with (so is not seen)."""
    c = s.get("clip")
    if not c:
        return False
    r = s.get("size", 0) / 2
    return (s["cx"] + r < c[0] or s["cx"] - r > c[2] or
            s["cy"] + r < c[1] or s["cy"] - r > c[3])


_PAGE_LINE_EMS = 0.3  # texts of one line within 0.3 of a font size


def _page_legend(symbols, texts, blobs, graphs, paths, *, page):
    # a text of marker characters only is a marker, not a label
    # (Seongmin-PhD-044's outliers are "\u25cf" in the plot's own font: one
    # beside another was a legend key named "\u25cf")
    from .fonts import DINGBAT_BY_UNICODE
    texts = [t for t in texts if not (t["text"].strip() and
                                      set(t["text"].strip()) <= set(DINGBAT_BY_UNICODE))]
    hlines = legend_line_samples(paths)
    legend = find_legend(symbols, texts, hlines, page=page)
    for i, label in numbered_legend(symbols, texts).items():
        legend.setdefault(i, label)
    keys, heads = numeric_legend(symbols, texts)
    for i, label in keys.items():
        legend.setdefault(i, label)
    for i in [i for i, label in legend.items() if label in heads and i not in keys]:
        del legend[i]                     # (the heading over a numeric legend)
    # a key with a figure caption between it and every graph belongs to
    # another figure (10.5445IR1000121285-038: a grey square of Figure
    # 2.11's diagram, under Figure 2.10's caption, keyed "ITO")
    caps = []
    for t in texts:
        if not t["rotated"] and _CAPTION_START.match(t["text"].strip()):
            # (the caption's whole first line)
            s = t["size"] or 1.0
            line = [o for o in texts if not o["rotated"] and abs(o["p0"][1] - t["p0"][1]) < _PAGE_LINE_EMS * s]
            caps.append({"bbox": (min(o["bbox"][0] for o in line), min(o["bbox"][1] for o in line),
                                  max(o["bbox"][2] for o in line), max(o["bbox"][3] for o in line))})
    if caps and graphs:
        for i in list(legend):
            s = symbols[i]
            if all(_caption_between(s, g["rect"], caps) for g in graphs):
                del legend[i]
    for i in _unreadable_legend_keys(symbols, texts, blobs, graphs, hlines, legend, page=page):
        legend[i] = ""
    for rot in sorted({g["rot"] for g in graphs} - {0}):
        for i, label in find_legend(frame_symbols(symbols, rot), frame_texts(texts, rot), page=page).items():
            legend.setdefault(i, label)
    return legend


_UNREAD_REACH_FRAC = 0.75  # unread keys within 0.75 of the graph's height
_UNREAD_COLUMN_SIZES = 3   # keys of a column within 3 sizes
_UNREAD_LEVEL = 0.3        # a key on a sample level within 0.3 of its size
_UNREAD_SPACING = 0.8      # keys spaced 0.8 of the biggest or more


def _unreadable_legend_keys(symbols, texts, blobs, graphs, hlines, legend, *, page):
    """Markers each followed by a word drawn as outlines that could not be
    read: legend keys, when they line up with each other just outside a
    graph, or (inside a graph) when at least three of them, all different
    markers, are stacked in a column - or two, when each sits on a line
    sample (the legend of a line chart: cheyette2024limited-011's panels
    (c) and (d), "Low/High localization ..." in outlines)."""
    unread = [{"text": "\x00", "value": None, "rotated": False, "bbox": b["bbox"],
               "center": b["center"], "size": b["size"], "idx": b["idx"],
               "p0": (b["bbox"][0], b["bbox"][1]), "p1": (b["bbox"][2], b["bbox"][1])}
              for b in blobs if not b.get("glyph")]
    if not unread:
        return []
    cands, inner = {}, {}
    for i, label in find_legend(symbols, texts + unread, hlines, page=page).items():
        s = symbols[i]
        if label != "\x00" or i in legend or s["shape"] in ("line", "bar", "stem") or s["shape"].startswith("box-"):
            continue
        d, g = min(((rect_distance(g["rect"], s["cx"], s["cy"]), k)
                    for k, g in enumerate(graphs)))
        rect = graphs[g]["rect"]
        if 0 < d <= _UNREAD_REACH_FRAC * (rect[3] - rect[1]):
            cands[i] = s
        elif d == 0:
            inner[i] = s
    # keys of a legend line up: a lone candidate is something else, unless
    # it lines up with a line sample of the same legend (a marker key above
    # or below the key of a fitted line, left edges aligned)
    def beside_line_sample(s):
        left = s["cx"] - s["size"] / 2
        return any(abs(x0 - left) <= s["size"] and 0 < abs(y - s["cy"]) <= _UNREAD_COLUMN_SIZES * s["size"]
                   for x0, x1, y in hlines)
    keys = [i for i, s in cands.items()
            if any(j != i and (abs(o["cy"] - s["cy"]) < 1.0 or abs(o["cx"] - s["cx"]) < 1.0)
                   for j, o in cands.items()) or beside_line_sample(s)]
    for i, s in inner.items():
        column = sorted((o for o in inner.values() if abs(o["cx"] - s["cx"]) < 1.0),
                        key=lambda o: o["cy"])
        sizes = [o["size"] for o in column]
        def on_sample(o):
            return any(x0 < o["cx"] < x1 and abs(y - o["cy"]) <= _UNREAD_LEVEL * o["size"]
                       for x0, x1, y in hlines)
        least = 2 if all(on_sample(o) for o in column) else 3
        if (len(column) >= least and len({symbol_signature(o) for o in column}) == len(column)
                and max(sizes) <= 2.0 * min(sizes)   # (shapes of one nominal size differ)
                and all(b["cy"] - a["cy"] >= _UNREAD_SPACING * max(sizes) for a, b in zip(column, column[1:]))):
            keys.append(i)                  # rows of similar keys, one under another
    return keys


def _claim(table, key, label):
    """Record that `key` is named `label`; a key claimed by two different
    labels is ambiguous (None) and names nothing."""
    table[key] = label if table.get(key, label) == label else None


def _nearest_graph(graphs, s):
    if not s.get("frame") and not any(rect_distance(g["rect"], s["cx"], s["cy"]) == 0 for g in graphs):
        on = [g for g in graphs if g.get("paper") and
              g["paper"][0] <= s["cx"] <= g["paper"][2] and g["paper"][1] <= s["cy"] <= g["paper"][3]]
        if len(on) == 1:
            return on[0]          # (on one chart's paper: graphs.set_graph_backgrounds)
    if s.get("frame") and not any(rect_distance(g["rect"], s["cx"], s["cy"]) == 0 for g in graphs):
        from .graphs import nearest_to_frame
        return nearest_to_frame(graphs, s["frame"])
    return min(graphs, key=lambda g: rect_distance(g["rect"], s["cx"], s["cy"]))


_OUTSIDE_SIZES = 0.5     # a key outside every graph by half its size
_KEY_SIZE_SAME = 0.1     # keys of one size within 10%
_WHITE = 0.97            # channels over 0.97: white
_BARS_NAMED_MIN = 3      # bar colours named: 3 bars or more
_BARS_NAMED_FRAC = 0.75  # with names for 75% of them
_SWATCH_COLOUR = 0.03    # a colour matching a swatch within 0.03


class SeriesNamer:
    """Gives each symbol its series name, from (in order of preference):
    the legend of its line (line charts), a legend key with the same marker
    in its graph, a colour swatch of its colour in its graph, or a figure
    legend outside every graph (small multiples) matched by marker or by
    colour.  Legend keys are named by their own label."""

    def __init__(self, symbols, legend, graphs, line_names):
        self.legend = legend
        self.line_names = line_names
        self.by_marker = {}       # (graph no, marker signature) -> label / None
        self.by_colour = {}       # (graph no, colour) -> label / None (swatches)
        self.key_colour = {}      # (graph no, colour) -> label / None (any filled key)
        self.by_shape = {}        # (graph no, shape, colour) -> label / None (image markers)
        self.form_keys = {}       # graph no -> {(shape, filled): label} when the keys' shapes differ
        self.figure = []          # (rgb, signature, label) of keys outside all graphs
        self.by_outline = {}      # (graph no, shape, outline colour) -> label (white keys)
        self.swatches = {}        # graph no -> [(rgb, label)] of its colour swatches
        self.page_colour = {}     # colour -> label / None, of every graph's swatches
        self.keyed = set()        # numbers of the graphs with legend keys of their own
        self._figure_cache = {}
        self._near_cache = {}
        self._shared = {}         # graph no -> shares two page swatch colours
        self.symbols = symbols
        for i, label in legend.items():
            s = symbols[i]
            g = _nearest_graph(graphs, s)
            # (the same marker with different labels is ambiguous)
            _claim(self.by_marker, (g["no"], symbol_signature(s)), label)
            # (a marker drawn as an image is filled, while its key may have
            # been exported as an outline: shape and colour must do)
            _claim(self.by_shape, (g["no"], s["shape"], color_name(s["rgb"])[1]), label)
            if label:
                self.form_keys.setdefault(g["no"], {}).setdefault(
                    (s["shape"], bool(s.get("filled"))), []).append(label)
            self.keyed.add(g["no"])
            if s["filled"] and s["rgb"]:
                # (a stacked area takes the name of a filled key of its
                # colour, whatever its shape: economies-open-intelligence-
                # 005's legend circles)
                _claim(self.key_colour, (g["no"], color_name(s["rgb"])[1]), label)
            if s["shape"] in ("rectangle", "square") and s["filled"]:
                _claim(self.by_colour, (g["no"], color_name(s["rgb"])[1]), label)
                if label:
                    _claim(self.page_colour, color_name(s["rgb"])[1], label)
                if label and s["rgb"]:
                    self.swatches.setdefault(g["no"], []).append((tuple(s["rgb"]), label))
            # (wholly outside: the top key of Memory_systems_cacheDRAMdisk-051's
            # legend, inside a plot, reaches 0.01 pt past its top edge)
            if s["rgb"] and all(rect_distance(g["rect"], s["cx"], s["cy"]) > _OUTSIDE_SIZES * s["size"]
                                for g in graphs):
                self.figure.append((s["rgb"], symbol_signature(s), label))
        # a swatch drawn as an outline only, among filled swatches of its
        # size, is white (the legend box's colour shows through):
        # Memory_systems_cacheDRAMdisk-051's "System Overhead + DRAM"
        filled_labels = {lb for i, lb in legend.items()
                         if symbols[i]["shape"] in ("rectangle", "square") and symbols[i]["filled"]}
        for i, label in legend.items():
            s = symbols[i]
            if not label or s["filled"] or s["shape"] not in ("rectangle", "square") or \
                    label in filled_labels:
                continue
            g = _nearest_graph(graphs, s)
            sizes = [symbols[j]["size"] for j, lb in legend.items()
                     if lb in filled_labels and symbols[j]["filled"] and
                     _nearest_graph(graphs, symbols[j]) is g]
            if not sizes or not any(abs(z - s["size"]) <= _KEY_SIZE_SAME * s["size"] for z in sizes):
                continue
            white = (1.0, 1.0, 1.0)
            _claim(self.by_colour, (g["no"], color_name(white)[1]), label)
            _claim(self.page_colour, color_name(white)[1], label)
            self.swatches.setdefault(g["no"], []).append((white, label))
        # (near colours name nothing in a graph whose swatches are themselves
        # near each other: symbols-on-axes' swatches #ff0500, #ff0e00 ...
        # sample a continuous colour scale its markers are drawn along)
        for gno, keys in list(self.swatches.items()):
            if any(la != lb and max(abs(a - b) for a, b in zip(ka, kb)) <= 2 * self.NEAR_SWATCH
                   for ka, la in keys for kb, lb in keys):
                del self.swatches[gno]
        # (a shape names a series only if every key of the graph has its own
        # shape, each naming one series)
        for gno, keys in list(self.form_keys.items()):
            if len(keys) >= 2 and all(len(set(v)) == 1 and len(v) == 1 for v in keys.values()):
                self.form_keys[gno] = {k: v[0] for k, v in keys.items()}
            else:
                del self.form_keys[gno]
        # a key filled white with a coloured outline (on a white legend box)
        # looks like an open marker of the outline's colour: it also names
        # the markers of its shape in that colour, open or filled, and those
        # outlined in it - unless a key of their own does
        for i, label in legend.items():
            s = symbols[i]
            out = s.get("outline_rgb")
            if not (s["filled"] and out and s["rgb"] and min(s["rgb"]) > _WHITE and min(out) <= _WHITE):
                continue
            g = _nearest_graph(graphs, s)
            for filled in (False, True):
                self.by_marker.setdefault((g["no"], symbol_signature(dict(s, filled=filled, rgb=out))), label)
            _claim(self.by_outline, (g["no"], s["shape"], color_name(out)[1]), label)

    def name(self, si, s, g):
        """Series name of symbol number `si` (`s`) in graph `g`."""
        named = self.line_names.get(id(s)) or self.by_marker.get((g["no"], symbol_signature(s)))
        if named:
            return named
        if s.get("image"):
            named = self.by_shape.get((g["no"], s["shape"], color_name(s["rgb"])[1]))
            if named:
                return named
        if s.get("outline_rgb") and si not in self.legend:
            named = self.by_outline.get((g["no"], s["shape"], color_name(s["outline_rgb"])[1]))
            if named:
                return named
        if si in self.legend:
            return self.legend[si]
        if s["shape"] == "area":
            named = self.key_colour.get((g["no"], color_name(s["rgb"])[1]))
            if named:
                return named
        if s["shape"] == "bar" and self._bar_per_category(g):
            # (each category its own bar and colour: the colour stands for
            # the category, which names the bar - no other graph's key:
            # 1356058.1356080-007's Figure 6, four bars in four greys, two
            # of them the greys of Figure 5's legend and of a triangle key)
            return self.by_colour.get((g["no"], color_name(s["rgb"])[1])) or \
                self._by_form(g, s) or self._by_near_swatch(g, s)
        return (self.by_colour.get((g["no"], color_name(s["rgb"])[1])) or self._figure_series(s)
                or self._by_form(g, s) or self._by_near_swatch(g, s) or self._page_swatch(g, s))

    def _bar_per_category(self, g):
        """Is graph g a bar chart with a category axis, one bar at each of
        its categories (three or more), no two in the same colour, no legend
        keys of its own, and not three quarters of its bars or more named,
        each by its own key, outside the graph?"""
        key = ("per_category", g["no"])
        if key in self._shared:
            return self._shared[key]
        ans = False
        if g["no"] not in self.keyed:
            for orient in ("x", "y"):
                m = g.get(orient, {}).get("map", {})
                if m.get("kind") != "nominal":
                    continue
                x0, y0, x1, y1 = g["rect"]
                bars = [o for o in self.symbols if o["shape"] == "bar" and
                        x0 - 1 <= o["cx"] <= x1 + 1 and y0 - 1 <= o["cy"] <= y1 + 1]
                at = [round(o["cx"] if orient == "x" else o["cy"], 0) for o in bars]
                cols = [color_name(o["rgb"])[1] for o in bars if o.get("rgb")]
                if len(bars) >= _BARS_NAMED_MIN and len(set(at)) == len(bars) and len(set(cols)) == len(bars):
                    # (unless keys outside the graph name three quarters of
                    # the bars or more, each its own: 3485513-020's chart of
                    # benchmarks, its legend naming 6 of its 7 bars)
                    names = [nm for nm in (self._figure_series(o) for o in bars) if nm]
                    ans = not (len(names) >= _BARS_NAMED_FRAC * len(bars) and len(set(names)) == len(names))
        self._shared[key] = ans
        return ans

    def _page_swatch(self, g, s):
        """A graph with no legend of its own takes a series name from the
        colour swatches of the page's other graphs, when that colour names
        one series on the whole page: Seongmin-PhD-044's time panels have no
        legend, their boxes coloured as in the legend of the panel beside
        each.  The graph must share two or more of those colours: one bar
        colour alone is no shared legend (Memory_systems_cacheDRAMdisk-051's
        PERL bars are the light grey of the charts' "CPU Execution", but
        stand for the whole time)."""
        if g["no"] in self.keyed or not s.get("rgb"):
            return ""
        name = self.page_colour.get(color_name(s["rgb"])[1])
        if not name:
            return ""
        if g["no"] not in self._shared:
            near = set()
            x0, y0, x1, y1 = g["rect"]
            for o in self.symbols:
                if o.get("rgb") and x0 <= o["cx"] <= x1 and y0 <= o["cy"] <= y1:
                    near.add(color_name(o["rgb"])[1])
            self._shared[g["no"]] = sum(1 for c in near if self.page_colour.get(c)) >= 2
        return name if self._shared[g["no"]] else ""

    # largest difference in any channel (0..1) between a marker's colour
    # and the swatch that names it, and how much nearer that swatch must be
    # than any other
    NEAR_SWATCH = 0.15
    NEAR_SWATCH_RATIO = 2.0

    def _by_near_swatch(self, g, s):
        """A marker whose colour is near, but not exactly, that of one
        colour swatch of its graph's legend takes the swatch's name.  The
        1949 network of 2204.07073-010 draws its nodes in #c90204 and
        #1740dc while the legend's swatches are #c01025 (Physical) and
        #143dfa (Cognitive), about 0.13 apart in one channel.  The swatch
        must be within NEAR_SWATCH in every channel and NEAR_SWATCH_RATIO
        times nearer than any swatch with another name, so a colour between
        two keys, or far from all of them, stays unnamed."""
        rgb = s.get("rgb")
        keys = self.swatches.get(g["no"])
        if not rgb or not keys:
            return ""
        ck = (g["no"], tuple(rgb))
        if ck not in self._near_cache:
            near = sorted((max(abs(a - b) for a, b in zip(rgb, k)), label) for k, label in keys)
            d, label = near[0]
            other = [dd for dd, lb in near if lb != label]
            ok = d <= self.NEAR_SWATCH and all(dd > self.NEAR_SWATCH_RATIO * d for dd in other)
            self._near_cache[ck] = label if ok else ""
        return self._near_cache[ck]

    def _by_form(self, g, s):
        """A chart that colours its points along a colour bar (by year,
        say) keeps the legend's shapes but not its colours: when every
        legend key of the graph has a different shape, a point takes the
        name of the key with its shape."""
        keys = self.form_keys.get(g["no"])
        if not keys:
            return ""
        return keys.get((s["shape"], bool(s.get("filled")))) or ""

    def _figure_series(self, s):
        """(cached: the answer depends only on the colour and the marker)"""
        rgb = s["rgb"]
        if not rgb or not self.figure:
            return ""
        key = (rgb, symbol_signature(s), s["shape"])
        if key not in self._figure_cache:
            self._figure_cache[key] = self._figure_series_uncached(s)
        return self._figure_cache[key]

    def _figure_series_uncached(self, s):
        """A data line is not named by a marker key outside all graphs that
        merely shares its colour: song2025rigorous-002's black phase-plot
        path (no legend of its own) is not the black dot of panel e's key
        ("Correct model but there are ...")."""
        if s["shape"] == "line":
            return ""
        rgb = s["rgb"]
        same = {label for _, sig, label in self.figure if sig == symbol_signature(s)}
        if len(same) == 1:                 # the same marker as one key
            return same.pop()
        near = [(max(abs(a - b) for a, b in zip(rgb, k)), label) for k, _, label in self.figure]
        d, label = min(near)
        if d > _SWATCH_COLOUR:
            return ""
        # keys of that colour with other markers: only one may match
        if len({lb for dd, lb in near if dd <= _SWATCH_COLOUR}) > 1 and s["shape"] not in ("line", "bar", "stem") and not s["shape"].startswith("box-"):
            return ""
        return label

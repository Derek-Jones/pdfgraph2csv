"""Legends: legend keys (a marker or line sample with a label to its right)
and the naming of every data symbol's series from them.
"""

import bisect
import math

from .colours import color_name
from .context import PAGE
from .geometry import thin_rect_line, bbox_of, rect_distance
from .graphs import frame_symbols, frame_texts
from .symbols import symbol_signature
from .text import is_number


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
                    if abs(ay - by) < 0.05 and 2 < abs(ax - bx) < 60:
                        out.append((min(ax, bx), max(ax, bx), (ay + by) / 2))
            continue
        for sp in p["subpaths"]:
            if sp["closed"] or len(sp["segs"]) != 1 or sp["segs"][0][0] != "l":
                continue
            a, b = sp["start"], sp["segs"][0][1]
            if abs(a[1] - b[1]) < 0.05 and 2 < abs(a[0] - b[0]) < 60:
                out.append((min(a[0], b[0]), max(a[0], b[0]), (a[1] + b[1]) / 2))
    return out


def find_legend(symbols, texts, hlines=()):
    """Legend keys: a marker with a (non-numeric) label just to its right on
    the same line - measured from the end of the line sample the marker sits
    on, if any.  Returns {symbol index: label}."""
    entries = {}
    # possible labels (a long line of a paragraph is none), by height on
    # the page, so each marker only looks at the texts on its own line
    labels = sorted(((t["center"][1], t) for t in texts
                     if not (is_number(t) or t["rotated"] or not t["text"].strip()
                             or len(t["text"].strip()) > 60)), key=lambda ct: ct[0])
    label_y = [cy for cy, _ in labels]
    reach = 0.6 * max((t["size"] or 1.0 for _, t in labels), default=1.0)
    # line samples (horizontal) filed in a grid by height and by every x cell
    # they span, so a marker looks only at the samples around itself
    hl_cell = 8.0
    hl_grid = {}
    for x0, x1, y in hlines:
        gy = int(math.floor(y / hl_cell))
        for gx in range(int(math.floor((x0 - 0.5) / hl_cell)),
                        int(math.floor((x1 + 0.5) / hl_cell)) + 1):
            hl_grid.setdefault((gx, gy), []).append((x0, x1, y))
    by_left = sorted(texts, key=lambda o: o["bbox"][0])     # (for label continuations)
    for i, s in enumerate(symbols):
        right = s["cx"] + s["size"] / 2
        tol = 0.3 * max(s["size"], 1.0)
        if hl_grid:
            gx = int(math.floor(s["cx"] / hl_cell))
            for gy in range(int(math.floor((s["cy"] - tol) / hl_cell)),
                            int(math.floor((s["cy"] + tol) / hl_cell)) + 1):
                for x0, x1, y in hl_grid.get((gx, gy), ()):
                    if x0 - 0.5 <= s["cx"] <= x1 + 0.5 and abs(y - s["cy"]) < tol:
                        right = max(right, x1)
        best = None
        lo = bisect.bisect_left(label_y, s["cy"] - reach)
        hi = bisect.bisect_right(label_y, s["cy"] + reach)
        for _, t in labels[lo:hi]:
            size = t["size"] or 1.0
            gap = t["bbox"][0] - right
            if not (-0.2 * size <= gap <= 3 * size):
                continue
            if abs(t["center"][1] - s["cy"]) > 0.6 * size:
                continue
            # text outside the graph that holds the marker (a data point at
            # the edge of the plot next to the body text) is no legend label
            if any(r[0] < s["cx"] < r[2] and r[1] < s["cy"] < r[3] and
                   not (r[0] <= t["center"][0] <= r[2] and r[1] <= t["center"][1] <= r[3])
                   for r in PAGE.graph_rects):
                continue
            if best is None or gap < best[0]:
                best = (gap, t)
        if best:
            t = best[1]
            label = t["text"].strip()
            # (markers: not the legend's frame box)
            near_keys = [u for u in symbols if u["size"] < 2 * t["size"]
                         and abs(u["cy"] - t["center"][1]) < 2 * t["size"]
                         and t["bbox"][2] < u["cx"] < t["bbox"][2] + 20 * t["size"]]
            # subscripts / superscripts that continue the label: f + 16
            end = t["bbox"][2]
            for o in by_left:
                if o["size"] < 0.3 * t["size"]:
                    continue                 # invisible helper glyphs
                if o is not t and o["size"] < 0.9 * t["size"] and \
                        -0.1 * t["size"] <= o["bbox"][0] - end < 0.3 * t["size"] and \
                        abs(o["center"][1] - t["center"][1]) < 0.7 * t["size"]:
                    label += o["text"].strip()
                    end = o["bbox"][2]
                elif o is not t and abs(o["size"] - t["size"]) <= 0.05 * t["size"] and \
                        0 < o["bbox"][0] - end <= 0.4 * t["size"] and \
                        abs(o["p0"][1] - t["p0"][1]) < 0.1 * t["size"] and \
                        not o["rotated"] and o["value"] is None and \
                        not any(end < u["cx"] < o["bbox"][0] and
                                abs(u["cy"] - t["center"][1]) < t["size"] for u in near_keys):
                    # the next word of the label, set as a separate piece
                    # ("FULL" in small capitals, then "higher")
                    label += " " + o["text"].strip()
                    end = o["bbox"][2]
            entries[i] = (label, t)
    keys = {i: e[0] for i, e in entries.items()}
    # a key stands apart on its line; markers along a dense data curve have
    # neighbours just left and right of them (concentric layers are fine)
    if keys:
        grid = {}
        cell = max(1.0, sorted(s["size"] for s in symbols)[len(symbols) // 2])
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
                        if j != i and abs(o["cy"] - s["cy"]) < 0.5 * s["size"] and \
                                0.25 * s["size"] < ddx < reach:
                            keys.pop(i, None)
    # legend entries line up with each other (stacked or side by side); an
    # annotation next to a data point does not.  When a page has an aligned
    # legend, unaligned candidates are dropped.
    ids = list(keys)
    grouped = set()
    for a in ids:
        for b in ids:
            if a >= b or entries[a][1] is entries[b][1]:
                continue
            sa, sb = symbols[a], symbols[b]
            ta, tb = entries[a][1], entries[b][1]
            stacked = abs(sa["cx"] - sb["cx"]) <= 1.5 and abs(ta["bbox"][0] - tb["bbox"][0]) <= 1.5 \
                and abs(sa["cy"] - sb["cy"]) < 4 * max(ta["size"], 1.0) * max(1, len(ids))
            side = abs(sa["cy"] - sb["cy"]) <= 1.0 and abs(ta["center"][1] - tb["center"][1]) <= 1.0
            if stacked or side:
                grouped.update((a, b))
    if grouped:
        same_spot = {i for i in ids if any(
            j in grouped and entries[j][1] is entries[i][1] for j in ids)}
        keys = {i: v for i, v in keys.items() if i in grouped or i in same_spot}
    return keys


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
            if -0.2 * size <= gap <= 3 * size and abs(t["center"][1] - s["cy"]) <= 0.6 * size:
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
               abs(u["bbox"][0] - t["bbox"][0]) <= 1.5 * (t["size"] or 1.0)]
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
            if len(run) >= 3:
                for j, u in run:
                    keys[j] = u["text"].strip()
        used.update(j for j, _ in col)
    return keys


def legend_for_lines(series, paths, texts):
    """Legend entries of line series: a short horizontal line sample (or a
    row of dashes) in the series' style with a label just to its right."""
    names = {}
    samples = []
    for p in paths:
        for sp in p["subpaths"]:
            pts = [sp["start"]] + [s[-1] for s in sp["segs"]]
            b = bbox_of(pts)
            if p["stroke"] and not sp["closed"] and len(sp["segs"]) == 1 and \
                    abs(b[3] - b[1]) < 0.05 and 3 < b[2] - b[0] < 60:
                samples.append((("solid",), p["stroke_rgb"], b))
            elif p["fill"] and len(sp["segs"]) in (3, 4) and abs(b[3] - b[1]) < 1.5 and 1 < b[2] - b[0] < 10:
                samples.append((("dashed",), p["fill_rgb"], b))
    # rows of dashes form one sample
    rows = []
    for st, rgb, b in sorted(samples, key=lambda s: s[2][0]):
        if st == ("dashed",):
            for r in rows:
                if r[1] == rgb and abs(r[2][1] - b[1]) < 0.5 and 0 <= b[0] - r[2][2] < 6:
                    r[2] = (r[2][0], min(r[2][1], b[1]), b[2], max(r[2][3], b[3]))
                    r[3] += 1
                    break
            else:
                rows.append([st, rgb, b, 1])
        else:
            rows.append([st, rgb, b, 2])
    for st, rgb, b, n in rows:
        if n < 2:
            continue
        cy = (b[1] + b[3]) / 2
        best = None
        for t in texts:
            if t["rotated"] or not t["text"].strip() or is_number(t):
                continue
            gap = t["bbox"][0] - b[2]
            if -0.2 * t["size"] <= gap <= 2 * t["size"] and abs(t["center"][1] - cy) < 0.6 * t["size"]:
                if best is None or gap < best[0]:
                    best = (gap, t["text"].strip())
        if not best:
            continue
        for i, s in enumerate(series):
            if s["style"][0] == st[0] and s["rgb"] == rgb:
                names.setdefault(i, best[1])
    return names


def find_page_legend(symbols, texts, blobs, graphs, paths):
    """Legend keys of the page: {symbol index: series name}.  Combines
    keys with text labels (also in turned graphs), colour swatches labelled
    1, 2, 3 ... and keys whose label is drawn as unreadable outlines (their
    name is left blank).  A marker clipped out of view (an outlier far
    beyond a plot's range, which may land on text elsewhere on the page)
    is no legend key."""
    shown = [i for i, s in enumerate(symbols) if not clipped_out(s)]
    if len(shown) < len(symbols):
        keys = _page_legend([symbols[i] for i in shown], texts, blobs, graphs, paths)
        return {shown[i]: name for i, name in keys.items()}
    return _page_legend(symbols, texts, blobs, graphs, paths)


def clipped_out(s):
    """Whether a symbol lies wholly outside the clipping box it was drawn
    with (so is not seen)."""
    c = s.get("clip")
    if not c:
        return False
    r = s.get("size", 0) / 2
    return (s["cx"] + r < c[0] or s["cx"] - r > c[2] or
            s["cy"] + r < c[1] or s["cy"] - r > c[3])


def _page_legend(symbols, texts, blobs, graphs, paths):
    hlines = legend_line_samples(paths)
    legend = find_legend(symbols, texts, hlines)
    for i, label in numbered_legend(symbols, texts).items():
        legend.setdefault(i, label)
    for i in _unreadable_legend_keys(symbols, texts, blobs, graphs, hlines, legend):
        legend[i] = ""
    for rot in sorted({g["rot"] for g in graphs} - {0}):
        for i, label in find_legend(frame_symbols(symbols, rot), frame_texts(texts, rot)).items():
            legend.setdefault(i, label)
    return legend


def _unreadable_legend_keys(symbols, texts, blobs, graphs, hlines, legend):
    """Markers each followed by a word drawn as outlines that could not be
    read: legend keys, when they line up with each other just outside a
    graph, or (inside a graph) when at least three of them, all different
    markers, are stacked in a column."""
    unread = [{"text": "\x00", "value": None, "rotated": False, "bbox": b["bbox"],
               "center": b["center"], "size": b["size"], "idx": b["idx"],
               "p0": (b["bbox"][0], b["bbox"][1]), "p1": (b["bbox"][2], b["bbox"][1])}
              for b in blobs if not b.get("glyph")]
    if not unread:
        return []
    cands, inner = {}, {}
    for i, label in find_legend(symbols, texts + unread, hlines).items():
        s = symbols[i]
        if label != "\x00" or i in legend or s["shape"] in ("line", "bar"):
            continue
        d, g = min(((rect_distance(g["rect"], s["cx"], s["cy"]), k)
                    for k, g in enumerate(graphs)))
        rect = graphs[g]["rect"]
        if 0 < d <= 0.75 * (rect[3] - rect[1]):
            cands[i] = s
        elif d == 0:
            inner[i] = s
    # keys of a legend line up: a lone candidate is something else, unless
    # it lines up with a line sample of the same legend (a marker key above
    # or below the key of a fitted line, left edges aligned)
    def beside_line_sample(s):
        left = s["cx"] - s["size"] / 2
        return any(abs(x0 - left) <= s["size"] and 0 < abs(y - s["cy"]) <= 3 * s["size"]
                   for x0, x1, y in hlines)
    keys = [i for i, s in cands.items()
            if any(j != i and (abs(o["cy"] - s["cy"]) < 1.0 or abs(o["cx"] - s["cx"]) < 1.0)
                   for j, o in cands.items()) or beside_line_sample(s)]
    for i, s in inner.items():
        column = sorted((o for o in inner.values() if abs(o["cx"] - s["cx"]) < 1.0),
                        key=lambda o: o["cy"])
        sizes = [o["size"] for o in column]
        if (len(column) >= 3 and len({symbol_signature(o) for o in column}) == len(column)
                and max(sizes) <= 1.5 * min(sizes)
                and all(b["cy"] - a["cy"] >= 0.8 * max(sizes) for a, b in zip(column, column[1:]))):
            keys.append(i)                  # rows of similar keys, one under another
    return keys


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
        self.figure = []          # (rgb, signature, label) of keys outside all graphs
        self.by_outline = {}      # (graph no, shape, outline colour) -> label (white keys)
        self._figure_cache = {}
        for i, label in legend.items():
            s = symbols[i]
            g = min(graphs, key=lambda g: rect_distance(g["rect"], s["cx"], s["cy"]))
            key = (g["no"], symbol_signature(s))
            # the same marker with different labels is ambiguous
            self.by_marker[key] = label if self.by_marker.get(key, label) == label else None
            if s["shape"] in ("rectangle", "square") and s["filled"]:
                ck = (g["no"], color_name(s["rgb"])[1])
                self.by_colour[ck] = label if self.by_colour.get(ck, label) == label else None
            if s["rgb"] and all(rect_distance(g["rect"], s["cx"], s["cy"]) > 0 for g in graphs):
                self.figure.append((s["rgb"], symbol_signature(s), label))
        # a key filled white with a coloured outline (on a white legend box)
        # looks like an open marker of the outline's colour: it also names
        # the markers of its shape in that colour, open or filled, and those
        # outlined in it - unless a key of their own does
        for i, label in legend.items():
            s = symbols[i]
            out = s.get("outline_rgb")
            if not (s["filled"] and out and s["rgb"] and min(s["rgb"]) > 0.97 and min(out) <= 0.97):
                continue
            g = min(graphs, key=lambda g: rect_distance(g["rect"], s["cx"], s["cy"]))
            for filled in (False, True):
                self.by_marker.setdefault((g["no"], symbol_signature(dict(s, filled=filled, rgb=out))), label)
            ok = (g["no"], s["shape"], color_name(out)[1])
            self.by_outline[ok] = label if self.by_outline.get(ok, label) == label else None

    def name(self, si, s, g):
        """Series name of symbol number `si` (`s`) in graph `g`."""
        named = self.line_names.get(id(s)) or self.by_marker.get((g["no"], symbol_signature(s)))
        if named:
            return named
        if s.get("outline_rgb") and si not in self.legend:
            named = self.by_outline.get((g["no"], s["shape"], color_name(s["outline_rgb"])[1]))
            if named:
                return named
        if si in self.legend:
            return self.legend[si]
        return self.by_colour.get((g["no"], color_name(s["rgb"])[1])) or self._figure_series(s)

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
        rgb = s["rgb"]
        same = {label for _, sig, label in self.figure if sig == symbol_signature(s)}
        if len(same) == 1:                 # the same marker as one key
            return same.pop()
        near = [(max(abs(a - b) for a, b in zip(rgb, k)), label) for k, _, label in self.figure]
        d, label = min(near)
        if d > 0.03:
            return ""
        # keys of that colour with other markers: only one may match
        if len({lb for dd, lb in near if dd <= 0.03}) > 1 and s["shape"] not in ("line", "bar"):
            return ""
        return label

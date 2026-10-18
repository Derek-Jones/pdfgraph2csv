"""Legends: legend keys (a marker or line sample with a label to its right)
and the naming of every data symbol's series from them.
"""

from .colours import color_name
from .context import PAGE
from .geometry import bbox_of, rect_distance
from .graphs import frame_symbols, frame_texts
from .symbols import symbol_signature
from .text import is_number


def legend_line_samples(paths):
    """Short horizontal strokes: the line samples of legend entries."""
    out = []
    for p in paths:
        if not p["stroke"]:
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
    for i, s in enumerate(symbols):
        right = s["cx"] + s["size"] / 2
        for x0, x1, y in hlines:
            if x0 - 0.5 <= s["cx"] <= x1 + 0.5 and abs(y - s["cy"]) < 0.3 * max(s["size"], 1.0):
                right = max(right, x1)
        best = None
        for t in texts:
            if is_number(t) or t["rotated"] or not t["text"].strip():
                continue
            size = t["size"] or 1.0
            # a long line of a paragraph, or text outside the graph that
            # holds the marker (a data point at the edge of the plot next to
            # the body text), is no legend label
            if len(t["text"].strip()) > 60 or any(
                    r[0] < s["cx"] < r[2] and r[1] < s["cy"] < r[3] and
                    not (r[0] <= t["center"][0] <= r[2] and r[1] <= t["center"][1] <= r[3])
                    for r in PAGE.graph_rects):
                continue
            gap = t["bbox"][0] - right
            if not (-0.2 * size <= gap <= 3 * size):
                continue
            if abs(t["center"][1] - s["cy"]) > 0.6 * size:
                continue
            if best is None or gap < best[0]:
                best = (gap, t)
        if best:
            t = best[1]
            label = t["text"].strip()
            # subscripts / superscripts that continue the label: f + 16
            end = t["bbox"][2]
            for o in sorted(texts, key=lambda o: o["bbox"][0]):
                if o["size"] < 0.3 * t["size"]:
                    continue                 # invisible helper glyphs
                if o is not t and o["size"] < 0.9 * t["size"] and \
                        -0.1 * t["size"] <= o["bbox"][0] - end < 0.3 * t["size"] and \
                        abs(o["center"][1] - t["center"][1]) < 0.7 * t["size"]:
                    label += o["text"].strip()
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
    name is left blank)."""
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
    """Markers just outside a graph, lined up with each other, each followed
    by a word drawn as outlines that could not be read: legend keys."""
    unread = [{"text": "\x00", "value": None, "rotated": False, "bbox": b["bbox"],
               "center": b["center"], "size": b["size"], "idx": b["idx"],
               "p0": (b["bbox"][0], b["bbox"][1]), "p1": (b["bbox"][2], b["bbox"][1])}
              for b in blobs if not b.get("glyph")]
    if not unread:
        return []
    cands = {}
    for i, label in find_legend(symbols, texts + unread, hlines).items():
        s = symbols[i]
        if label != "\x00" or i in legend or s["shape"] in ("line", "bar"):
            continue
        d, g = min(((rect_distance(g["rect"], s["cx"], s["cy"]), k)
                    for k, g in enumerate(graphs)))
        rect = graphs[g]["rect"]
        if 0 < d <= 0.75 * (rect[3] - rect[1]):
            cands[i] = s
    # keys of a legend line up: a lone candidate is something else
    return [i for i, s in cands.items()
            if any(j != i and (abs(o["cy"] - s["cy"]) < 1.0 or abs(o["cx"] - s["cx"]) < 1.0)
                   for j, o in cands.items())]


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

    def name(self, si, s, g):
        """Series name of symbol number `si` (`s`) in graph `g`."""
        named = self.line_names.get(id(s)) or self.by_marker.get((g["no"], symbol_signature(s)))
        if named:
            return named
        if si in self.legend:
            return self.legend[si]
        return self.by_colour.get((g["no"], color_name(s["rgb"])[1])) or self._figure_series(s)

    def _figure_series(self, s):
        rgb = s["rgb"]
        if not rgb or not self.figure:
            return ""
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

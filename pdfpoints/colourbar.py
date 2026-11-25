"""Heat maps: tiles coloured by a value read off a colour bar.

The user asked for heat maps to be read (Maj-Petr_PhD-077: four ggplot
geom_bin2d panels, thousands of grey tiles whose shade gives a count on a
log colour bar): one point per tile, at its centre, with the value its
colour stands for on the colour bar beside the graph.

A colour bar is a gradient image one pixel wide or tall (ggplot draws it as
an inline image, the interpreter records it as a colour strip), with
numeric labels along one long side and its title above it.  A tile's colour
is matched along the bar's pixels (between the two neighbouring pixels it
lies between, as the image is drawn interpolated), and the place found is
turned into a value by a scale fitted to the bar's labels (linear or log,
as for an axis).
"""

import math
import re

from .geometry import median
from .labels import LabelPairs
from .scales import fit_axis, map_value

# a tile colour farther than this (RGB, 0..1) from the bar's colours has no value
_FAR = 0.08


def strip_pixels(data, w, h, predictor=1):
    """[(r, g, b)] of an 8-bit image one pixel wide or tall, its bytes
    `data` (decoded, maybe with PNG predictors: Predictor >= 10); gray, RGB
    and CMYK by their length.  None if the bytes do not fit."""
    n = w * h
    rows = h
    if predictor >= 10:
        # each row: a filter byte, then the row's bytes
        per = len(data) // rows - 1 if rows else 0
        comps = per // w if w else 0
        if comps not in (1, 3, 4) or (per + 1) * rows != len(data):
            return None
        out, prev = bytearray(), bytearray(per)
        for r in range(rows):
            f = data[r * (per + 1)]
            row = bytearray(data[r * (per + 1) + 1:(r + 1) * (per + 1)])
            for i in range(per):
                left = row[i - comps] if i >= comps else 0
                up = prev[i]
                ul = prev[i - comps] if i >= comps else 0
                if f == 1:
                    row[i] = (row[i] + left) & 255
                elif f == 2:
                    row[i] = (row[i] + up) & 255
                elif f == 3:
                    row[i] = (row[i] + (left + up) // 2) & 255
                elif f == 4:
                    p = left + up - ul
                    pa, pb, pc = abs(p - left), abs(p - up), abs(p - ul)
                    pr = left if pa <= pb and pa <= pc else (up if pb <= pc else ul)
                    row[i] = (row[i] + pr) & 255
            out += row
            prev = row
        data = bytes(out)
    comps = len(data) // n if n else 0
    if comps not in (1, 3, 4) or comps * n != len(data):
        return None
    rgb = []
    for k in range(n):
        px = data[k * comps:(k + 1) * comps]
        if comps == 1:
            rgb.append((px[0] / 255.0,) * 3)
        elif comps == 3:
            rgb.append((px[0] / 255.0, px[1] / 255.0, px[2] / 255.0))
        else:
            c, m, y, kk = (v / 255.0 for v in px)
            rgb.append(((1 - c) * (1 - kk), (1 - m) * (1 - kk), (1 - y) * (1 - kk)))
    return rgb


def colour_strip(image):
    """A long thin image (read_image's (w, h, rgb, alpha)) whose every row
    across it is one colour (within 0.02): a colour bar's gradient,
    {"w", "h", "rgb"} along its length (one pixel across); else None.
    matplotlib draws its bars as such images (2308.04785-006: 47 x 945
    indexed pixels); ggplot's are one pixel wide already."""
    if not image:
        return None
    w, h, rgb, _ = image
    if h >= w:
        rows = [rgb[r * w:(r + 1) * w] for r in range(h)]
    else:
        rows = [[rgb[r * w + c] for r in range(h)] for c in range(w)]
    for row in rows:
        if any(max(abs(a - b) for a, b in zip(px, row[0])) > 0.02 for px in row):
            return None
    mid = [row[len(row) // 2] for row in rows]
    return {"w": 1, "h": h, "rgb": mid} if h >= w else {"w": w, "h": 1, "rgb": mid}


def _apply(ctm, u, v):
    a, b, c, d, e, f = ctm
    return (a * u + c * v + e, b * u + d * v + f)


def colour_bars(strips, texts):
    """The colour bars of a page: [{"box", "orient" ("y" for an upright
    bar, "x" for a level one), "stops" [(place along the bar, rgb)], "map"
    (the scale of its labels), "title"}] for each colour strip with two or
    more numeric labels beside one long side."""
    bars = []
    for st in strips:
        w, h, ctm, rgb = st["w"], st["h"], st["ctm"], st["rgb"]
        corners = [_apply(ctm, u, v) for u, v in ((0, 0), (1, 0), (0, 1), (1, 1))]
        xs, ys = [p[0] for p in corners], [p[1] for p in corners]
        box = (min(xs), min(ys), max(xs), max(ys))
        bw, bh = box[2] - box[0], box[3] - box[1]
        if max(bw, bh) < 5 or min(bw, bh) <= 0:
            continue
        orient = "y" if bh >= bw else "x"
        k = 1 if orient == "y" else 0
        n = len(rgb)
        stops = []
        for i, c in enumerate(rgb):
            # pixel i's centre: along the image's long side (rows run top
            # to bottom, from v = 1 down)
            u, v = ((i + 0.5) / w, 0.5) if h == 1 else (0.5, 1 - (i + 0.5) / h)
            stops.append((_apply(ctm, u, v)[k], c))
        stops.sort(key=lambda s: s[0])
        if n < 2:
            continue
        # the bar runs half a pixel past its end pixels' centres: the
        # gradient carried on to its edges (the darkest tiles of
        # Maj-Petr_PhD-077, #000000, lie past the last centre's #0d0d0d)
        lo_e, hi_e = (box[1], box[3]) if orient == "y" else (box[0], box[2])
        for (pa, ca), (pb, cb), edge in ((stops[0], stops[1], lo_e), (stops[-1], stops[-2], hi_e)):
            if abs(pb - pa) > 1e-9 and abs(edge - pa) > 1e-9:
                f = (edge - pa) / (pa - pb)
                c = tuple(min(1.0, max(0.0, a + (a - b) * f)) for a, b in zip(ca, cb))
                stops.append((edge, c))
        stops.sort(key=lambda s: s[0])
        # labels: numbers beside one long side, within the bar's length
        lo, hi = (box[1], box[3]) if orient == "y" else (box[0], box[2])
        side = []
        for t in texts:
            if t.get("value") is None or t.get("rotated") or t.get("date"):
                continue
            s = t["size"] or 1.0
            c = t["center"][k]
            if not lo - 0.6 * s <= c <= hi + 0.6 * s:
                continue
            if orient == "y":
                gap = max(t["bbox"][0] - box[2], box[0] - t["bbox"][2])
            else:
                gap = max(t["bbox"][1] - box[3], box[1] - t["bbox"][3])
            if -0.2 * s <= gap <= 3 * s:
                side.append((c, t))
        if len(side) < 2:
            continue
        pairs = LabelPairs([(c, t["value"]) for c, t in side], [0.0] * len(side),
                           [t for _, t in side])
        m = fit_axis(pairs)
        if m is None or m["kind"] not in ("linear", "log"):
            continue
        bars.append({"box": box, "orient": orient, "stops": stops, "map": m,
                     "title": _bar_title(box, texts, [t for _, t in side]), "labels": {id(t) for _, t in side},
                     "label_values": [t["value"] for _, t in side]})
    return bars


def _bar_title(box, texts, labels=()):
    """The text just above a colour bar ("count"): not a number, within 3
    of its sizes above the bar's top, overlapping it across; else the
    words turned along the right side of an upright bar (within 40 pt),
    level with it, in one column, in reading order, starting within 1.2 of
    their sizes past the bar's labels (horowitz2014-004's right axis title,
    two sizes past its bar's years, is the axis's)."""
    best = None
    for t in texts:
        if t.get("value") is not None or t.get("rotated") or not t["text"].strip():
            continue
        s = t["size"] or 1.0
        gap = t["bbox"][1] - box[3]
        if -0.2 * s <= gap <= 3 * s and t["bbox"][0] <= box[2] + s and t["bbox"][2] >= box[0] - s:
            if best is None or gap < best[0]:
                best = (gap, t["text"].strip())
    if best:
        return best[1]
    # (none: words turned along an upright bar's right side, past its
    # labels, level with it - 2020.01.30.927558.full-048's "Log likelihood
    # difference", three words read top to bottom)
    bx0, by0, bx1, by1 = box
    col = [t for t in texts if t.get("rotated") and t["text"].strip() and
           bx1 < t["center"][0] <= bx1 + 40 and by0 - 2 <= t["center"][1] <= by1 + 2]
    if not col:
        return ""
    x = min(col, key=lambda t: t["center"][0])["center"][0]
    col = [t for t in col if abs(t["center"][0] - x) <= 0.5 * (t["size"] or 1.0)]
    edge = max([t["bbox"][2] for t in labels if t["center"][0] > bx1] or [bx1])
    if min(t["bbox"][0] for t in col) - edge > 1.2 * (col[0]["size"] or 1.0):
        return ""
    down = (col[0].get("angle") or 0) < 0
    col.sort(key=lambda t: -t["center"][1] if down else t["center"][1])
    return " ".join(t["text"].strip() for t in col)


def bar_value(bar, rgb):
    """The value colour `rgb` stands for on colour bar `bar` (None if it is
    not among the bar's colours)."""
    best = None
    stops = bar["stops"]
    for (p0, c0), (p1, c1) in zip(stops, stops[1:]):
        d = [b - a for a, b in zip(c0, c1)]
        dd = sum(x * x for x in d)
        t = 0.0 if dd == 0 else max(0.0, min(1.0, sum((r - a) * x for r, a, x in zip(rgb, c0, d)) / dd))
        far = math.dist(rgb, [a + t * x for a, x in zip(c0, d)])
        if best is None or far < best[0]:
            best = (far, p0 + t * (p1 - p0))
    if best is None or best[0] > _FAR:
        return None
    return map_value(bar["map"], best[1])


def _luma(c):
    return 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]


def bar_value_luma(bar, rgb):
    """The value colour `rgb` stands for on colour bar `bar` by brightness
    alone, when the bar's brightness rises (or falls) all along it (no step
    back over 0.01: MATLAB's parula, 0.24 to 0.89), else None.  For heat
    maps stored as JPEG pictures, whose colour is kept at half resolution:
    cells narrower than two pixels blend their neighbours' colours, while
    brightness is kept per pixel (2020.01.30.927558.full-048: where a
    cell's colour is on the bar, the two readings differ by 0.7 in median,
    1.6 at the 90th percentile, on a scale of 0 to 50)."""
    st = [(p, _luma(c)) for p, c in bar["stops"]]
    if len(st) < 2:
        return None
    if st[-1][1] < st[0][1]:
        st = [(p, -y) for p, y in st]
        y = -_luma(rgb)
    else:
        y = _luma(rgb)
    if any(b < a - 0.01 for (_, a), (_, b) in zip(st, st[1:])):
        return None
    mono, m = [], -math.inf
    for p, v in st:
        m = max(m, v)
        mono.append((m, p))
    if y <= mono[0][0]:
        return map_value(bar["map"], mono[0][1])
    for (y0, p0), (y1, p1) in zip(mono, mono[1:]):
        if y0 <= y <= y1:
            t = 0.0 if y1 == y0 else (y - y0) / (y1 - y0)
            return map_value(bar["map"], p0 + t * (p1 - p0))
    return map_value(bar["map"], mono[-1][1])


def _on_tile(s, grid, cell):
    """Does mark s lie on a tile's place (within a quarter of its size)?"""
    gx, gy = int(s["cx"] // cell), int(s["cy"] // cell)
    return any(abs(t["cx"] - s["cx"]) <= 0.25 * t["w"] and abs(t["cy"] - s["cy"]) <= 0.25 * t["h"]
               for dx in (-1, 0, 1) for dy in (-1, 0, 1)
               for t in grid.get((gx + dx, gy + dy), ()))


def heat_tiles(g, paths):
    """The tiles of a heat map in graph g: fifty or more filled rectangles
    (no outline), upright, of one size (within 5%), centred inside the
    plot, in three or more colours, half of them or more beside another
    one tile away.  Returns [tile symbol] or []."""
    x0, y0, x1, y1 = g["rect"]
    cands = []
    for p in paths:
        if not p["fill"] or p["stroke"] or p.get("fill_rgb") is None:
            continue
        for sp in p["subpaths"]:
            segs = sp["segs"]
            if len(segs) not in (3, 4) or any(s[0] != "l" for s in segs):
                continue
            pts = [sp["start"]] + [s[-1] for s in segs]
            xs, ys = sorted({round(q[0], 3) for q in pts}), sorted({round(q[1], 3) for q in pts})
            if len(xs) != 2 or len(ys) != 2:
                continue                       # not an upright rectangle
            cx, cy = (xs[0] + xs[1]) / 2, (ys[0] + ys[1]) / 2
            if x0 < cx < x1 and y0 < cy < y1:
                cands.append((xs[1] - xs[0], ys[1] - ys[0], cx, cy, p))
    if len(cands) < 50:
        return []
    tw = median(c[0] for c in cands)
    th = median(c[1] for c in cands)
    if tw <= 0 or th <= 0 or tw > 0.2 * (x1 - x0) or th > 0.2 * (y1 - y0):
        return []
    tiles = [c for c in cands if abs(c[0] - tw) <= 0.05 * tw and abs(c[1] - th) <= 0.05 * th]
    if len(tiles) < 50 or len({c[4]["fill_rgb"] for c in tiles}) < 3:
        return []
    # tiles abut: half of them or more have a neighbour one tile across or
    # up (the dots of dotted grid lines, 2355585.2355594-006, stand apart)
    at = {(round(c[2] / (0.25 * tw)), round(c[3] / (0.25 * th))) for c in tiles}
    def touching(c):
        kx, ky = round(c[2] / (0.25 * tw)), round(c[3] / (0.25 * th))
        return any((kx + dx, ky + dy) in at for dx, dy in
                   ((4, 0), (-4, 0), (0, 4), (0, -4), (3, 0), (5, 0), (-3, 0), (-5, 0),
                    (0, 3), (0, 5), (0, -3), (0, -5)))
    if sum(1 for c in tiles if touching(c)) < 0.5 * len(tiles):
        return []
    return [{"shape": "tile", "cx": cx, "cy": cy, "size": w, "w": w, "h": h, "filled": True,
             "rgb": p["fill_rgb"], "idx": p["idx"], "res": p.get("res"), "tool": p.get("tool"),
             "clip": p.get("clip")}
            for w, h, cx, cy, p in tiles]


def _bar_gap(rect, b):
    """How far colour bar b lies outside plot `rect`, if beside it - an
    upright bar level with half the plot's height or more, a level one
    over half its width or more (beside the right axis, above the plot) -
    else None."""
    x0, y0, x1, y1 = rect
    bx0, by0, bx1, by1 = b["box"]
    if bx0 < x1 and bx1 > x0 and by0 < y1 and by1 > y0:
        return None                        # inside the plot: not its bar
    if b["orient"] == "y":
        if min(by1, y1) - max(by0, y0) < 0.5 * min(by1 - by0, y1 - y0):
            return None
    elif min(bx1, x1) - max(bx0, x0) < 0.5 * min(bx1 - bx0, x1 - x0):
        return None
    return math.hypot(max(bx0 - x1, x0 - bx1, 0.0), max(by0 - y1, y0 - by1, 0.0))


def graph_bar(g, bars, graphs=()):
    """The colour bar of graph g: the nearest one beside its plot (_bar_gap)
    within half the plot's width, and no nearer to another of `graphs`
    (horowitz2014-004: the bars of the bottom row are not the middle
    row's)."""
    near = None
    for b in bars:
        d = _bar_gap(g["rect"], b)
        if d is None or d > 0.5 * (g["rect"][2] - g["rect"][0]):
            continue
        if any(h is not g and (_bar_gap(h["rect"], b) or math.inf) < d for h in graphs):
            continue
        if near is None or d < near[0]:
            near = (d, b)
    return near[1] if near else None


# a caption naming what colour shows: "colour indicates the year", "points
# coloured by temperature", "colour represents density (a.u.)"
_COLOUR_SAYS = re.compile(
    r"\bcolou?r(?:s|ed|ing)?(?: scale| bar| map| code)?\s+"
    r"(?:by|indicates?|shows?|represents?|denotes?|gives?|encodes?|is|are|of)\s+"
    r"(?:the\s+|their\s+|its\s+|each\s+(?:point's\s+)?)?"
    r"([A-Za-z][\w\-]*(?:\s+[a-z][\w\-]*)?)", re.I)
# a caption naming the matrix or heat map: "Correlation matrices for ...",
# "the confusion matrix", "heat map of the response time"
_MATRIX_OF = re.compile(r"\b([A-Za-z][\w\-]*)\s+(?:matrix|matrices|heat\s*-?\s*maps?)\b", re.I)
_MAP_OF = re.compile(r"\bheat\s*-?\s*maps?\s+(?:of|for|showing)\s+(?:the\s+)?"
                     r"([A-Za-z][\w\-]*(?:\s+[a-z][\w\-]*)?)", re.I)
_STOP = {"and", "with", "in", "on", "for", "from", "of", "to", "at", "as", "the", "a", "an",
         "while", "where", "which", "that", "versus", "vs"}


def value_name(bar, caption, title=""):
    """The name of what a colour bar's colours stand for: its title; else
    what the graph's caption or title says colour shows ("colour indicates
    year"); else what they name the heat map ("heat map of latency") or
    the matrix ("Correlation matrices": correlation, 2308.04785-006's
    unlabelled bars), in lower case; else "year" when its labels are all
    whole years (1800-2100: the unlabelled bars of horowitz2014-004,
    1986 ... 2002); else ""."""
    if bar["title"]:
        return bar["title"]
    for rx, lower in ((_COLOUR_SAYS, False), (_MAP_OF, True), (_MATRIX_OF, True)):
        for text in (caption or "", title or ""):
            m = rx.search(text)
            if not m:
                continue
            words = m.group(1).split()
            while words and words[-1].lower() in _STOP:
                words.pop()
            if words and words[0].lower() not in _STOP and \
                    words[0].lower() not in ("a", "this", "these", "each", "our"):
                name = " ".join(words)
                return name.lower() if lower else name
    vals = bar.get("label_values") or []
    if vals and all(float(v).is_integer() and 1800 <= v <= 2100 for v in vals):
        return "year"
    return ""


def heatmap_values(graphs, symbols, strips, texts, graph_of):
    """--heatmap: each marker of a graph with a colour bar gets the value
    its colour stands for on that bar (graph_bar, bar_value) - the year of
    each point of horowitz2014-004's bottom two graphs, read off their
    jet bars.  A colour not on the bar (the grey points of Figure 1.1.6,
    shown for comparison) has none.  Lines, tiles (valued already) and
    lone error bars get no value; bars do, when their colour is on the bar.  The graph's value_name is the
    bar's (value_name)."""
    bars = colour_bars(strips, texts) if strips else []
    if not bars:
        return
    of = {}
    for g in graphs:
        if any(s["shape"] == "tile" for s in symbols if graph_of(s) is g):
            continue
        bar = graph_bar(g, bars, graphs)
        if bar:
            of[id(g)] = bar
            g["value_name"] = value_name(bar, g.get("caption", ""), g.get("title", ""))
    if not of:
        return
    for s in symbols:
        if s["shape"] in ("line", "stem", "tile", "errorbar") or s["shape"].startswith("box-"):
            continue
        # (bars too: a bar coloured by its value - 2020.01.30.927558.full-
        # 048's "Average" bars, yellow to blue; a bar whose colour is not
        # on the colour bar has none)
        g = graph_of(s)
        bar = of.get(id(g)) if g is not None else None
        if bar and s.get("rgb") is not None:
            s["value"] = bar_value(bar, s["rgb"])


def _cells(m, lo, hi, npx):
    """Cell centres (page positions) along one side of a heat map picture
    spanning lo..hi: a category axis's ticks within it; on a linear axis
    one cell per whole unit when the span is a whole number of units, 2 to
    npx of them (within 5%).  [] if neither."""
    if m["kind"] == "nominal":
        return sorted(c for c, _ in m.get("ticks", ()) if lo <= c <= hi)
    if m["kind"] != "linear" or not m.get("a"):
        return []
    span = abs(map_value(m, hi) - map_value(m, lo))
    n = round(span)
    if not 2 <= n <= npx or abs(span - n) > 0.05 * n:
        return []
    step = (hi - lo) / n
    return [lo + (i + 0.5) * step for i in range(n)]


def image_tiles(g, pictures):
    """The cells of a heat map drawn as a picture (2020.01.30.927558.full-
    048: MATLAB's image of 12 models by 408 datasets, a 556 x 319 pixel
    JPEG): a picture placed upright that fills the plot (90% of it or
    more, within it but for 2 pt).  Cells along each side by _cells; each
    is a tile at its centre, coloured by the pixel there.  [] if none."""
    from .image_marks import read_image
    x0, y0, x1, y1 = g["rect"]
    area = (x1 - x0) * (y1 - y0)
    for pic in pictures or ():
        bx0, by0, bx1, by1 = pic["box"]
        a, b, c, d, _, _ = pic["ctm"]
        if abs(b) > 1e-6 or abs(c) > 1e-6 or a <= 0 or d <= 0:
            continue
        if bx0 < x0 - 2 or by0 < y0 - 2 or bx1 > x1 + 2 or by1 > y1 + 2 or \
                (bx1 - bx0) * (by1 - by0) < 0.9 * area:
            continue
        img = read_image(pic["xobj"])
        if not img:
            continue
        w, h, rgb, _ = img
        xs = _cells(g["x"]["map"], bx0, bx1, w)
        ys = _cells(g["y"]["map"], by0, by1, h)
        if len(xs) < 2 or len(ys) < 2 or len(xs) * len(ys) > 50000:
            continue
        cw = (bx1 - bx0) / len(xs) if g["x"]["map"]["kind"] != "nominal" else \
            min(q - p for p, q in zip(xs, xs[1:]))
        ch = (by1 - by0) / len(ys) if g["y"]["map"]["kind"] != "nominal" else \
            min(q - p for p, q in zip(ys, ys[1:]))
        tiles = []
        for cy in ys:
            r = min(h - 1, max(0, int((by1 - cy) / (by1 - by0) * h)))
            for cx in xs:
                col = min(w - 1, max(0, int((cx - bx0) / (bx1 - bx0) * w)))
                tiles.append({"shape": "tile", "cx": cx, "cy": cy, "size": min(cw, ch), "w": cw,
                              "h": ch, "filled": True, "rgb": rgb[r * w + col], "idx": pic.get("idx", 0),
                              "picture": True})
        return tiles
    return []


def _level_bar(g, bars, tiles):
    """A colour bar level with graph g (over half of the shorter of the two
    heights shared) anywhere to its right, on which 80% or more of the
    tiles' colours lie: a bar beside the panel at the right of a row,
    serving the row (2020.01.30.927558.full-048)."""
    x0, y0, x1, y1 = g["rect"]
    best = None
    for b in bars:
        bx0, by0, bx1, by1 = b["box"]
        if bx0 < x1 or min(by1, y1) - max(by0, y0) < 0.5 * min(by1 - by0, y1 - y0):
            continue
        sample = tiles[::max(1, len(tiles) // 200)]
        on = sum(1 for t in sample if bar_value(b, t["rgb"]) is not None)
        # (a picture's cells: a quarter of them, if the bar's brightness
        # reads the rest - bar_value_luma)
        need = 0.25 if sample[0].get("picture") and bar_value_luma(b, sample[0]["rgb"]) is not None \
            else 0.8
        if on >= need * len(sample) and (best is None or bx0 < best[0]):
            best = (bx0, b)
    return best[1] if best else None


def add_heat_tiles(graphs, symbols, paths, strips, texts, pictures=(), heatmap=False):
    """Heat maps: for each graph with heat tiles, its other marks on the
    tiles' places go and each tile becomes a point, with the value its
    colour stands for on the nearest colour bar outside the plot (within
    half the plot's width; else a bar level with it further right,
    _level_bar).  With `heatmap` (--heatmap), a picture filling a plot is
    read as a heat map too (image_tiles).  The bar's title is the graph's
    value name."""
    bars = colour_bars(strips, texts) if strips else []
    for g in graphs:
        tiles = heat_tiles(g, paths)
        if not tiles and heatmap:
            tiles = image_tiles(g, pictures)
        if not tiles:
            continue
        bar = graph_bar(g, bars, graphs) or _level_bar(g, bars, tiles)
        for t in tiles:
            t["value"] = bar_value(bar, t["rgb"]) if bar else None
            if bar and t["value"] is None and t.get("picture"):
                t["value"] = bar_value_luma(bar, t["rgb"])
        if bar:
            g["value_name"] = value_name(bar, g.get("caption", ""), g.get("title", ""))
        # (marks on a tile's place, within a quarter of its size: the cell
        # squares of 2308.04785-006's correlation matrices)
        cell = max(tiles[0]["w"], tiles[0]["h"])
        grid = {}
        for t in tiles:
            grid.setdefault((int(t["cx"] // cell), int(t["cy"] // cell)), []).append(t)

        symbols[:] = [s for s in symbols if not _on_tile(s, grid, cell)]
        symbols += tiles

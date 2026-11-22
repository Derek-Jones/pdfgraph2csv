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
                     "title": _bar_title(box, texts), "labels": {id(t) for _, t in side}})
    return bars


def _bar_title(box, texts):
    """The text just above a colour bar ("count"): not a number, within 3
    of its sizes above the bar's top, overlapping it across."""
    best = None
    for t in texts:
        if t.get("value") is not None or t.get("rotated") or not t["text"].strip():
            continue
        s = t["size"] or 1.0
        gap = t["bbox"][1] - box[3]
        if -0.2 * s <= gap <= 3 * s and t["bbox"][0] <= box[2] + s and t["bbox"][2] >= box[0] - s:
            if best is None or gap < best[0]:
                best = (gap, t["text"].strip())
    return best[1] if best else ""


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


def _on_tile(s, grid, cell):
    """Does mark s lie on a tile's place (within a quarter of its size)?"""
    gx, gy = int(s["cx"] // cell), int(s["cy"] // cell)
    return any(abs(t["cx"] - s["cx"]) <= 0.25 * t["w"] and abs(t["cy"] - s["cy"]) <= 0.25 * t["h"]
               for dx in (-1, 0, 1) for dy in (-1, 0, 1)
               for t in grid.get((gx + dx, gy + dy), ()))


def heat_tiles(g, paths):
    """The tiles of a heat map in graph g: fifty or more filled rectangles
    (no outline), upright, of one size (within 5%), centred inside the
    plot, in three or more colours.  Returns [tile symbol] or []."""
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
    return [{"shape": "tile", "cx": cx, "cy": cy, "size": w, "w": w, "h": h, "filled": True,
             "rgb": p["fill_rgb"], "idx": p["idx"], "res": p.get("res"), "tool": p.get("tool"),
             "clip": p.get("clip")}
            for w, h, cx, cy, p in tiles]


def add_heat_tiles(graphs, symbols, paths, strips, texts):
    """Heat maps: for each graph with heat tiles, its other marks on the
    tiles' places go and each tile becomes a point, with the value its
    colour stands for on the nearest colour bar outside the plot (within
    half the plot's width).  The bar's title is the graph's value name."""
    bars = colour_bars(strips, texts) if strips else []
    for g in graphs:
        tiles = heat_tiles(g, paths)
        if not tiles:
            continue
        x0, y0, x1, y1 = g["rect"]
        near = None
        for b in bars:
            bx0, by0, bx1, by1 = b["box"]
            if bx0 < x1 and bx1 > x0 and by0 < y1 and by1 > y0:
                continue                       # inside the plot: not its bar
            d = math.hypot(max(bx0 - x1, x0 - bx1, 0.0), max(by0 - y1, y0 - by1, 0.0))
            if d <= 0.5 * (x1 - x0) and (near is None or d < near[0]):
                near = (d, b)
        bar = near[1] if near else None
        for t in tiles:
            t["value"] = bar_value(bar, t["rgb"]) if bar else None
        if bar:
            g["value_name"] = bar["title"]
        # (marks on a tile's place, within a quarter of its size: the cell
        # squares of 2308.04785-006's correlation matrices)
        cell = max(tiles[0]["w"], tiles[0]["h"])
        grid = {}
        for t in tiles:
            grid.setdefault((int(t["cx"] // cell), int(t["cy"] // cell)), []).append(t)

        symbols[:] = [s for s in symbols if not _on_tile(s, grid, cell)]
        symbols += tiles

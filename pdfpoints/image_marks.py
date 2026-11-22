"""Markers drawn as small images.

Some programs draw each marker as a little picture rather than a path:
Excel for Mac exports gradient-filled markers as an image with a soft mask
(the mask gives the marker's shape), often with a second, larger and faint
black image under it as a drop shadow.  The interpreter records every image
no bigger than 30 pt (`image_marks`); here each one is decoded and:
  * faint images (no pixel more than half opaque) are shadows or glows and
    are dropped;
  * the shape is read from the opaque pixels (alpha >= 1/2): square,
    circle, diamond or triangle, or "image" when none fits;
  * the colour is the most common colour of the opaque pixels (a gradient
    marker's border has the series colour), replaced by the colour of a
    data line with a corner at the marker's centre when there is one (the
    line's colour is exact and is the colour of the legend key);
  * the data point is the centre of the image's box: programs centre the
    picture on the point.
Only 8-bit images with raw (Flate, LZW, ...) data in a grey, RGB or CMYK
space are read; JPEG images and palettes are skipped.
"""

import collections

from pdfminer.pdftypes import resolve1

from .geometry import vertices


def _decoded(st):
    try:
        return st.get_data()
    except Exception:
        return None


def _components(cs):
    """Colour components of a colour space, or None if unsupported."""
    cs = resolve1(cs)
    name = getattr(cs, "name", None)
    if name in ("DeviceGray", "CalGray", "G"):
        return 1
    if name in ("DeviceRGB", "CalRGB", "RGB"):
        return 3
    if name in ("DeviceCMYK", "CMYK"):
        return 4
    if isinstance(cs, list) and cs:
        kind = getattr(resolve1(cs[0]), "name", None)
        if kind == "ICCBased":
            n = resolve1(resolve1(cs[1]).get("N"))
            return n if n in (1, 3, 4) else None
        if kind in ("CalRGB", "CalGray"):
            return 3 if kind == "CalRGB" else 1
    return None


def _palette(cs):
    """The colours of an /Indexed colour space as byte tuples, or None."""
    cs = resolve1(cs)
    if not (isinstance(cs, list) and len(cs) == 4 and getattr(resolve1(cs[0]), "name", None) == "Indexed"):
        return None
    n = _components(cs[1])
    look = resolve1(cs[3])
    if n is None:
        return None
    if hasattr(look, "get_data"):
        look = _decoded(look)
    if isinstance(look, str):
        look = look.encode("latin-1")
    if not isinstance(look, (bytes, bytearray)) or len(look) < n:
        return None
    return [tuple(look[i:i + n]) for i in range(0, len(look) - n + 1, n)]


def _filters(st):
    f = resolve1(st.get("Filter"))
    fs = f if isinstance(f, list) else [f] if f is not None else []
    return [getattr(resolve1(x), "name", str(x)) for x in fs]


def read_image(xobj):
    """(width, height, [(r, g, b)] per pixel, [alpha 0..1] per pixel), rows
    top to bottom; None if the image cannot be read."""
    if any(f in ("DCTDecode", "JPXDecode", "JBIG2Decode", "CCITTFaxDecode") for f in _filters(xobj)):
        return None
    w, h = resolve1(xobj.get("Width")), resolve1(xobj.get("Height"))
    if resolve1(xobj.get("BitsPerComponent")) != 8 or not isinstance(w, int) or not isinstance(h, int):
        return None
    palette = _palette(xobj.get("ColorSpace"))
    n = 1 if palette else _components(xobj.get("ColorSpace"))
    data = _decoded(xobj) if n else None
    if data is None or len(data) < w * h * n:
        return None
    if palette:
        # (an indexed image: matplotlib's colour bars, 2308.04785-006)
        data = bytes(b for k in range(w * h) for b in palette[min(data[k], len(palette) - 1)])
        n = len(palette[0])
    rgb = []
    for k in range(w * h):
        px = data[k * n:(k + 1) * n]
        if n == 1:
            rgb.append((px[0] / 255.0,) * 3)
        elif n == 3:
            rgb.append((px[0] / 255.0, px[1] / 255.0, px[2] / 255.0))
        else:
            c, m, y, kk = (v / 255.0 for v in px)
            rgb.append(((1 - c) * (1 - kk), (1 - m) * (1 - kk), (1 - y) * (1 - kk)))
    alpha = [1.0] * (w * h)
    sm = resolve1(xobj.get("SMask"))
    if sm is not None:
        sw, shh = resolve1(sm.get("Width")), resolve1(sm.get("Height"))
        sd = _decoded(sm)
        if resolve1(sm.get("BitsPerComponent")) != 8 or sd is None or \
                not isinstance(sw, int) or not isinstance(shh, int) or len(sd) < sw * shh:
            return None
        # (a mask may have its own resolution: sampled at each pixel)
        alpha = [sd[min(shh - 1, j * shh // h) * sw + min(sw - 1, i * sw // w)] / 255.0
                 for j in range(h) for i in range(w)]
    else:
        # no mask: white is the ground the marker was drawn on
        alpha = [0.0 if min(c) > 0.95 else 1.0 for c in rgb]
    return w, h, rgb, alpha


def _shape(grid):
    """The marker shape of a boolean grid (rows top to bottom on the page)."""
    rows = [r for r in grid if any(r)]
    if not rows:
        return "image"
    cols = [i for i in range(len(grid[0])) if any(r[i] for r in rows)]
    x0, x1 = cols[0], cols[-1]
    W, H = x1 - x0 + 1, len(rows)
    widths = [sum(r[x0:x1 + 1]) for r in rows]
    fill = sum(widths) / float(W * H)
    if W < 3 or H < 3 or not 0.6 <= W / float(H) <= 1.6:
        return "image"
    k = max(1, H // 5)
    top, bottom = sum(widths[:k]) / float(k), sum(widths[-k:]) / float(k)
    widest = max(range(H), key=lambda j: widths[j])
    if fill >= 0.88:
        return "square"
    if (top <= 0.45 * W and bottom >= 0.75 * W) or (bottom <= 0.45 * W and top >= 0.75 * W):
        return "triangle"
    if top <= 0.45 * W and bottom <= 0.45 * W and 0.3 <= widest / float(H - 1 or 1) <= 0.7:
        return "diamond" if fill < 0.68 else "circle"
    return "image"


def _soft_round(w, h, rgb):
    """An anti-aliased disc drawn on white with no mask: every pixel but
    pure white counts as ink, so it reads as a square (or as nothing) by its
    opaque pixels.  Teaching-disciplined-softdev-008 draws its blue markers
    as 10 x 9 pixel images.  Weighing each pixel by its ink (1 - its
    lightest channel): a disc has empty corners (each under 0.3) and covers
    65% to 90% of its box, with no row of the top or bottom fifth filled
    to three quarters (a square does; a diamond covers about half).
    Returns "circle" or None."""
    if w < 5 or h < 5 or not 0.6 <= w / float(h) <= 1.6:
        return None
    ink = [[1.0 - min(rgb[j * w + i]) for i in range(w)] for j in range(h)]
    corners = (ink[0][0], ink[0][w - 1], ink[h - 1][0], ink[h - 1][w - 1])
    fill = sum(map(sum, ink)) / float(w * h)
    k = max(1, h // 5)
    ends = ink[:k] + ink[-k:]
    if max(corners) < 0.3 and 0.65 <= fill <= 0.9 and all(sum(r) < 0.75 * w for r in ends):
        return "circle"
    return None


def image_symbols(marks, paths):
    """Symbol dicts for the images among `marks` that are markers."""
    # corners of stroked data lines: they give a marker its exact colour
    corners = collections.defaultdict(list)      # rounded corner -> stroke colours
    for p in paths:
        if p["stroke"] and not p["fill"]:
            for sp in p["subpaths"]:
                if len(sp["segs"]) >= 1:
                    vs = vertices(sp)
                    # the dots and lines of a grid are no data line:
                    # Teaching-disciplined-softdev-008's dotted grid runs
                    # through every marker, and its silver dots gave the
                    # blue markers their colour
                    xs, ys = [q[0] for q in vs], [q[1] for q in vs]
                    if len(sp["segs"]) == 1 and (max(xs) - min(xs) < 0.05 or max(ys) - min(ys) < 0.05):
                        continue
                    for q in vs:
                        corners[(round(q[0]), round(q[1]))].append((q, p["stroke_rgb"]))
    out = []
    cache = {}
    for m in marks:
        key = id(m["xobj"])
        if key not in cache:
            cache[key] = read_image(m["xobj"])
        img = cache[key]
        if img is None:
            continue
        w, h, rgb, alpha = img
        if max(alpha) < 0.5:
            continue                        # a shadow or a glow
        a, b, c, d = m["ctm"][:4]
        if abs(b) > 1e-6 or abs(c) > 1e-6 or a == 0 or d == 0:
            shape = "image"                 # (turned images: shape not read)
        else:
            # image rows run top to bottom when d > 0; columns left to right when a > 0
            grid = [[alpha[j * w + i] >= 0.5 for i in range(w)] for j in range(h)]
            if d < 0:
                grid.reverse()
            if a < 0:
                grid = [r[::-1] for r in grid]
            shape = _shape(grid)
            if resolve1(m["xobj"].get("SMask")) is None and shape in ("square", "image"):
                shape = _soft_round(w, h, rgb) or shape
        opaque = [rgb[k] for k in range(w * h) if alpha[k] >= 0.5]
        colour = collections.Counter(tuple(round(v, 3) for v in c) for c in opaque).most_common(1)[0][0]
        x0, y0, x1, y1 = m["box"]
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        # the opaque part's size: pixels times their size on the page
        xs = [k % w for k in range(w * h) if alpha[k] >= 0.5]
        ys = [k // w for k in range(w * h) if alpha[k] >= 0.5]
        size = max((max(xs) - min(xs) + 1) / float(w) * (x1 - x0),
                   (max(ys) - min(ys) + 1) / float(h) * (y1 - y0))
        tol = 0.15 * size
        near = [rgb_ for q, rgb_ in corners.get((round(cx), round(cy)), ())
                if abs(q[0] - cx) <= tol and abs(q[1] - cy) <= tol]
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                if dx or dy:
                    near += [rgb_ for q, rgb_ in corners.get((round(cx) + dx, round(cy) + dy), ())
                             if abs(q[0] - cx) <= tol and abs(q[1] - cy) <= tol]
        if near:
            colour = collections.Counter(near).most_common(1)[0][0]
        out.append({"shape": shape, "filled": True, "rgb": colour, "cx": cx, "cy": cy,
                    "size": size, "idx": m["idx"], "clip": m["clip"], "tool": m["tool"],
                    "res": None, "image": True})
    return out


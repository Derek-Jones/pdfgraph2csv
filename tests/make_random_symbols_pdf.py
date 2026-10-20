#!/usr/bin/env python3
"""Write tests/data/random-<symbol>.pdf and its true values
random-<symbol>.reference.csv (standard library only).

Each PDF is one scatter plot of 1000 points whose x and y values are drawn
from a uniform distribution on [0, 100] (a fixed seed per symbol, so the
files are reproducible).  Axes run from 0 to 100 with labelled ticks every
20; one data unit is 4 pt.  Coordinates are written with 3 decimals, as
plotting programs do, so a point is known to about 0.0002 data units.

Every marker is drawn the way a plotting program draws it, centred on the
data point by that program's convention:

  circle            filled circle of four Bezier curves (R, Excel)
  open-circle       stroked circle of four Bezier curves (R pch 1)
  circle8           filled circle of eight Bezier curves in a Form XObject
                    placed with "cm ... Do" (matplotlib "o")
  dingbat-circle    ZapfDingbats a71 glyph (R pdf() device, pch 16/19), the
                    point at (0.396, 0.347) em of the glyph
  diamond           stroked diamond of four lines, m l l l l (R pch 5)
  filled-diamond    filled diamond (R pch 18)
  fill-outline-diamond  each diamond filled, then stroked (Excel)
  square            filled square drawn with re (R pch 15)
  open-square       stroked square drawn with re (R pch 0)
  triangle          filled equilateral triangle, point at its centre (R
                    pch 17: top vertex r above, base r/2 below)
  down-triangle     the same pointing down (R pch 25 style)
  mpl-triangle      triangle filling a square box, point at the box centre
                    (matplotlib "^": vertices (0,1), (-1,-1), (1,-1))
  pentagon          regular pentagon about its centre (matplotlib "p")
  hexagon           regular hexagon about its centre (matplotlib "h")
  star              five-pointed star about its centre (matplotlib "*")
  plus              two strokes, all vertical bars first, then all
                    horizontal bars (R pch 3)
  cross             two diagonal strokes (R pch 4)
  asterisk          four strokes, a cross and a plus with rays of equal
                    length, each stroked separately (R pch 8)
  asterisk-unequal  the same with diagonal rays sqrt(2) times longer
"""

import math
import os
import random

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

X0, Y0, SPAN = 100.0, 100.0, 400.0          # plot box: 100..500 pt both ways
N = 1000
R = 2.5                                      # marker "radius" in pt
K = 0.5522847498                             # Bezier circle constant


def px(v):
    return X0 + SPAN * v / 100.0


def py(v):
    return Y0 + SPAN * v / 100.0


def f(v):
    return "%.3f" % v


def circle_path(x, y, r):
    """Four Bezier quadrants, counter-clockwise from (x + r, y)."""
    k = K * r
    return ("%s %s m %s %s %s %s %s %s c %s %s %s %s %s %s c "
            "%s %s %s %s %s %s c %s %s %s %s %s %s c h " % tuple(map(f, (
                x + r, y,
                x + r, y + k, x + k, y + r, x, y + r,
                x - k, y + r, x - r, y + k, x - r, y,
                x - r, y - k, x - k, y - r, x, y - r,
                x + k, y - r, x + r, y - k, x + r, y))))


def poly_path(pts, close=True):
    s = "%s %s m " % (f(pts[0][0]), f(pts[0][1]))
    s += "".join("%s %s l " % (f(a), f(b)) for a, b in pts[1:])
    return s + ("h " if close else "")


def regular(x, y, r, n, start=90.0):
    return [(x + r * math.cos(math.radians(start + 360.0 * k / n)),
             y + r * math.sin(math.radians(start + 360.0 * k / n))) for k in range(n)]


def star(x, y, r, inner=0.381966):
    pts = []
    for k in range(10):
        rr = r if k % 2 == 0 else r * inner
        a = math.radians(90 + 36 * k)
        pts.append((x + rr * math.cos(a), y + rr * math.sin(a)))
    return pts


# R's triangle: TRC0 = sqrt(4 pi / (3 sqrt 3)), TRC1 = TRC0 sqrt(3) / 2, TRC2 = TRC0 / 2
TRC0 = math.sqrt(4 * math.pi / (3 * math.sqrt(3)))
TRC1 = TRC0 * math.sqrt(3) / 2
TRC2 = TRC0 / 2


def r_triangle(x, y, r, up=True):
    xc = r * 4.0 / 3.0 / TRC0         # scale so the triangle is 2r tall
    rr, xx, yy = TRC0 * xc, TRC1 * xc, TRC2 * xc
    s = 1 if up else -1
    return [(x, y + s * rr), (x + xx, y - s * yy), (x - xx, y - s * yy)]


def marker(sym, x, y):
    """Content for one marker at page point (x, y) (vertical-first plus
    signs are handled in content())."""
    r = R
    if sym == "circle":
        return "0 0 1 rg " + circle_path(x, y, r) + "f\n"
    if sym == "open-circle":
        return "0 0 1 RG 0.75 w " + circle_path(x, y, r) + "S\n"
    if sym == "circle8":
        return "q 1 0 0 1 %s %s cm /M0 Do Q\n" % (f(x), f(y))
    if sym == "dingbat-circle":
        s = 7.0
        return "BT /ZaDb %g Tf %s %s Td (l) Tj ET\n" % (s, f(x - 0.396 * s), f(y - 0.347 * s))
    if sym == "diamond":
        pts = [(x - r, y), (x, y + r), (x + r, y), (x, y - r), (x - r, y)]
        return "0 0 1 RG 0.75 w " + poly_path(pts, close=False) + "S\n"
    if sym == "filled-diamond":
        return "0 0 1 rg " + poly_path([(x - r, y), (x, y + r), (x + r, y), (x, y - r)]) + "f\n"
    if sym == "fill-outline-diamond":
        p = poly_path([(x - r, y), (x, y + r), (x + r, y), (x, y - r)])
        return "0 0 1 rg " + p + "f\n0 0 0.5 RG 0.5 w " + p + "S\n"
    if sym == "square":
        return "0 0 1 rg %s %s %s %s re f\n" % (f(x - r), f(y - r), f(2 * r), f(2 * r))
    if sym == "open-square":
        return "0 0 1 RG 0.75 w %s %s %s %s re S\n" % (f(x - r), f(y - r), f(2 * r), f(2 * r))
    if sym == "triangle":
        return "0 0 1 rg " + poly_path(r_triangle(x, y, r)) + "f\n"
    if sym == "down-triangle":
        return "0 0 1 rg " + poly_path(r_triangle(x, y, r, up=False)) + "f\n"
    if sym == "mpl-triangle":
        return "0 0 1 rg " + poly_path([(x, y + r), (x - r, y - r), (x + r, y - r)]) + "f\n"
    if sym == "pentagon":
        return "0 0 1 rg " + poly_path(regular(x, y, r, 5)) + "f\n"
    if sym == "hexagon":
        return "0 0 1 rg " + poly_path(regular(x, y, r, 6)) + "f\n"
    if sym == "star":
        return "0 0 1 rg " + poly_path(star(x, y, r * 1.2)) + "f\n"
    if sym == "cross":
        return "0 0 1 RG 0.75 w %s %s m %s %s l %s %s m %s %s l S\n" % tuple(map(f, (
            x - r, y - r, x + r, y + r, x - r, y + r, x + r, y - r)))
    if sym in ("asterisk", "asterisk-unequal"):
        # R pch 8: a cross from (-xc, -xc) to (xc, xc), then a plus with
        # arms sqrt(2) xc, all rays equal; the unequal variant has diagonal
        # rays sqrt(2) times longer than the straight ones
        d = r / math.sqrt(2) if sym == "asterisk" else r
        return ("0 0 1 RG 0.75 w %s %s m %s %s l S\n%s %s m %s %s l S\n"
                "%s %s m %s %s l S\n%s %s m %s %s l S\n") \
            % tuple(map(f, (x - d, y - d, x + d, y + d, x - d, y + d, x + d, y - d,
                            x - r, y, x + r, y, x, y - r, x, y + r)))
    raise ValueError(sym)


SYMBOLS = ["circle", "open-circle", "circle8", "dingbat-circle", "diamond", "filled-diamond",
           "fill-outline-diamond", "square", "open-square", "triangle", "down-triangle",
           "mpl-triangle", "pentagon", "hexagon", "star", "plus", "cross", "asterisk", "asterisk-unequal"]


# the symbol name pdfgraph2csv.py must report for each
REPORTED = {"circle": "filled-circle", "open-circle": "open-circle", "circle8": "filled-circle",
            "dingbat-circle": "filled-circle", "diamond": "open-diamond",
            "filled-diamond": "filled-diamond", "fill-outline-diamond": "filled-diamond",
            "square": "filled-square", "open-square": "open-square",
            "triangle": "filled-triangle", "down-triangle": "filled-triangle",
            "mpl-triangle": "filled-triangle", "pentagon": "filled-polygon",
            "hexagon": "filled-polygon", "star": "filled-polygon", "plus": "plus",
            "cross": "cross", "asterisk": "asterisk", "asterisk-unequal": "asterisk"}


def points(sym):
    rng = random.Random("pdfgraph2csv-%s" % sym)
    return [(rng.uniform(0, 100), rng.uniform(0, 100)) for _ in range(N)]


def axes():
    c = ["0 G 0.8 w %s %s m %s %s l S\n" % (f(X0), f(Y0), f(X0 + SPAN), f(Y0)),
         "%s %s m %s %s l S\n" % (f(X0), f(Y0), f(X0), f(Y0 + SPAN))]
    for v in range(0, 101, 20):
        x, y = px(v), py(v)
        c.append("%s %s m %s %s l S\n" % (f(x), f(Y0), f(x), f(Y0 - 5)))
        c.append("0 g BT /F1 9 Tf %s %s Td (%d) Tj ET\n" % (f(x - 2.5 * len(str(v))), f(Y0 - 15), v))
        c.append("%s %s m %s %s l S\n" % (f(X0), f(y), f(X0 - 5), f(y)))
        c.append("BT /F1 9 Tf %s %s Td (%d) Tj ET\n" % (f(X0 - 9 - 5 * len(str(v))), f(y - 3), v))
    return "".join(c)


def content(sym, pts):
    c = [axes()]
    c.append("0 g BT /F1 12 Tf 230 520 Td (Random %s) Tj ET\n" % sym)
    if sym == "plus":                         # R: all vertical bars, then all horizontal ones
        c.append("0 0 1 RG 0.75 w\n")
        for v, w in pts:
            x, y = px(v), py(w)
            c.append("%s %s m %s %s l S\n" % (f(x), f(y - R), f(x), f(y + R)))
        for v, w in pts:
            x, y = px(v), py(w)
            c.append("%s %s m %s %s l S\n" % (f(x - R), f(y), f(x + R), f(y)))
    else:
        for v, w in pts:
            c.append(marker(sym, px(v), py(w)))
    return "".join(c).encode("latin-1")


def m0_form():
    """matplotlib's marker /M0: a filled circle of eight Bezier curves about
    the origin."""
    r, k = R, 0.2652031 * R           # 8 arcs of 45 degrees
    pts = [(r * math.cos(math.radians(45 * i)), r * math.sin(math.radians(45 * i))) for i in range(9)]
    s = "0 0 1 rg %s %s m " % (f(pts[0][0]), f(pts[0][1]))
    for i in range(8):
        a0, a1 = math.radians(45 * i), math.radians(45 * (i + 1))
        c1 = (pts[i][0] - k * math.sin(a0) / R * R, pts[i][1] + k * math.cos(a0) / R * R)
        c2 = (pts[i + 1][0] + k * math.sin(a1), pts[i + 1][1] - k * math.cos(a1))
        s += "%s %s %s %s %s %s c " % tuple(map(f, (c1[0], c1[1], c2[0], c2[1],
                                                    pts[i + 1][0], pts[i + 1][1])))
    return (s + "h f").encode()


def write_pdf(path, sym, pts):
    body = content(sym, pts)
    form = m0_form()
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 600 600] /Resources << "
        b"/Font << /F1 5 0 R /ZaDb 6 0 R >> /XObject << /M0 7 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length %d >>\nstream\n" % len(body) + body + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /ZapfDingbats >>",
        b"<< /Type /XObject /Subtype /Form /BBox [-5 -5 5 5] /Length %d >>\nstream\n"
        % len(form) + form + b"\nendstream",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    with open(path, "wb") as fh:
        fh.write(out)


def write_reference(path, sym, pts):
    """The true values, in drawing order (x, y with 10 significant digits),
    with the symbol name the program must report."""
    with open(path, "w") as fh:
        fh.write("symbol,x_coord,y_coord\n")
        for v, w in pts:
            fh.write("%s,%.10g,%.10g\n" % (REPORTED[sym], v, w))


if __name__ == "__main__":
    for sym in SYMBOLS:
        pts = points(sym)
        write_pdf(os.path.join(DATA, "random-%s.pdf" % sym), sym, pts)
        write_reference(os.path.join(DATA, "random-%s.reference.csv" % sym), sym, pts)
    print("written %d files to %s" % (2 * len(SYMBOLS), DATA))

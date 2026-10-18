#!/usr/bin/env python3
"""Write tests/data/synthetic-*.pdf (standard library only).

synthetic-line-plus.pdf is upright; synthetic-rotated-cw.pdf and
synthetic-rotated-ccw.pdf contain the same graph turned by 90 degrees
clockwise / counter-clockwise (labels and title turn with it), so all three
must give exactly the same data values.

One graph with two kinds of markers whose true data values are known:
  * circles, each made of four Bezier curves, filled;
  * plus signs made of two separate stroked lines, drawn the way R does it:
    ALL vertical bars first, then ALL horizontal bars, so a plus sign's two
    strokes are far apart in the content stream.
The data contain a duplicated plus and a duplicated circle (both must be
reported twice), and a legend with one key per marker type.
Ticks and Helvetica labels make it a normal linear plot:
x 0..100 (ticks every 20), y 0..50 (ticks every 10).
"""
import os

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

X0, X1, Y0, Y1 = 100.0, 500.0, 100.0, 400.0          # plot rectangle (page units)
XMAX, YMAX = 100.0, 50.0


def px(x):
    return X0 + (X1 - X0) * x / XMAX


def py(y):
    return Y0 + (Y1 - Y0) * y / YMAX


CIRCLES = [(10, 5), (25, 12), (40, 20), (40, 20), (55, 31), (90, 44)]
PLUSES = [(15, 40), (30, 33), (50, 10), (50, 10), (70, 25), (85, 8)]
R = 3.0        # circle radius
H = 4.0        # half length of a plus bar
K = 0.5523 * R


def circle(cx, cy):
    return ("%.3f %.3f m\n"
            "%.3f %.3f %.3f %.3f %.3f %.3f c\n"
            "%.3f %.3f %.3f %.3f %.3f %.3f c\n"
            "%.3f %.3f %.3f %.3f %.3f %.3f c\n"
            "%.3f %.3f %.3f %.3f %.3f %.3f c\nh B\n") % (
        cx + R, cy,
        cx + R, cy + K, cx + K, cy + R, cx, cy + R,
        cx - K, cy + R, cx - R, cy + K, cx - R, cy,
        cx - R, cy - K, cx - K, cy - R, cx, cy - R,
        cx + K, cy - R, cx + R, cy - K, cx + R, cy)


def text(x, y, s, size=9):
    return "BT /F1 %g Tf %.3f %.3f Td (%s) Tj ET\n" % (size, x, y, s)


def content():
    c = ["1 J 1 j\n"]
    # axes: two long lines with outward ticks and labels
    c.append("0 G 0.8 w %.1f %.1f m %.1f %.1f l S\n" % (X0, Y0, X1, Y0))
    c.append("%.1f %.1f m %.1f %.1f l S\n" % (X0, Y0, X0, Y1))
    for v in range(0, 101, 20):
        x = px(v)
        c.append("%.3f %.1f m %.3f %.1f l S\n" % (x, Y0, x, Y0 - 5))
        c.append("0 g " + text(x - 2.5 * len(str(v)), Y0 - 16, str(v)))
    for v in range(0, 51, 10):
        y = py(v)
        c.append("%.1f %.3f m %.1f %.3f l S\n" % (X0, y, X0 - 5, y))
        c.append(text(X0 - 8 - 5 * len(str(v)), y - 3.2, str(v)))
    c.append(text(280, Y0 - 32, "Size"))
    c.append(text(250, Y1 + 20, "Synthetic test plot", 11))
    # circles (red, filled), legend circle included
    c.append("1 0 0 rg 0 0 0 RG 0.5 w\n")
    for x, y in CIRCLES:
        c.append(circle(px(x), py(y)))
    c.append(circle(420, 380))
    # plus signs (blue): all vertical bars, then all horizontal bars
    plus_pts = [(px(x), py(y)) for x, y in PLUSES] + [(420, 365)]
    c.append("0 0 1 RG 0.8 w\n")
    for x, y in plus_pts:
        c.append("%.3f %.3f m %.3f %.3f l S\n" % (x, y - H, x, y + H))
    for x, y in plus_pts:
        c.append("%.3f %.3f m %.3f %.3f l S\n" % (x - H, y, x + H, y))
    # legend labels
    c.append("0 g " + text(430, 377, "measured"))
    c.append(text(430, 362, "estimated"))
    return "".join(c).encode("latin-1")


def write_pdf(path, rotate=0):
    body = content()
    if rotate:   # turn the whole graph (labels included) about the page centre
        c, sn = (0, -1) if rotate == -90 else (0, 1)
        cx, cy = 300.0, 250.0
        # translate(c) * rotate * translate(-c)
        e = cx - (c * cx - sn * cy)
        f = cy - (sn * cx + c * cy)
        body = (b"q %d %d %d %d %.3f %.3f cm\n" % (c, sn, -sn, c, e, f)) + body + b"Q\n"
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 600 600] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length %d >>\nstream\n" % len(body) + body + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
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
    with open(path, "wb") as f:
        f.write(out)


if __name__ == "__main__":
    os.makedirs(DATA, exist_ok=True)
    for name, rot in (("synthetic-line-plus.pdf", 0),
                      ("synthetic-rotated-cw.pdf", -90),
                      ("synthetic-rotated-ccw.pdf", 90)):
        p = os.path.join(DATA, name)
        write_pdf(p, rot)
        print("written", p)

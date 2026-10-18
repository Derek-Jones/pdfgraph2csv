#!/usr/bin/env python3
"""Write tests/data/synthetic-date-axis.pdf and its hand-made reference CSV
synthetic-date-axis.reference.csv (standard library only).

A scatter plot whose x tick labels are dates ("Jan 2010", "Apr 2010", ...,
"Jan 2011", read with python-dateutil as year + month/12) and whose labels
and title are drawn with a font that names its glyphs in an /Encoding
/Differences array (codes 128 and up), so the text can only be read through
the glyph names (Adobe Glyph List, via fontTools).  The title contains the
ligature glyph /fi.  True values: x = 2010 + month/12, y as given.
"""
import os

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

X0, X1, Y0, Y1 = 100.0, 500.0, 100.0, 400.0
POINTS = [(1, 20), (2, 35), (4, 30), (5, 55), (7, 60), (8, 45), (10, 80), (11, 70)]
MONTHS = ["Jan", "Apr", "Jul", "Oct", "Jan"]

# glyph names given codes 128, 129, ... by /Differences
GLYPHS = ["J", "a", "n", "A", "p", "r", "J_u", "u", "l", "O", "c", "t", "zero", "one",
          "two", "space", "P", "o", "fi", "s", "b", "y", "m", "h"]
CODE = {g: 128 + i for i, g in enumerate(GLYPHS)}
CHAR = {"J": "J", "a": "a", "n": "n", "A": "A", "p": "p", "r": "r", "u": "u", "l": "l",
        "O": "O", "c": "c", "t": "t", "0": "zero", "1": "one", "2": "two", " ": "space",
        "P": "P", "o": "o", "s": "s", "b": "b", "y": "y", "m": "m", "h": "h"}


def px(month):
    return X0 + (X1 - X0) * month / 12.0


def py(v):
    return Y0 + (Y1 - Y0) * v / 100.0


def encode(s):
    """Text -> PDF string of the custom codes ("fi" uses the ligature)."""
    out, i = [], 0
    while i < len(s):
        if s.startswith("fi", i):
            out.append(CODE["fi"])
            i += 2
            continue
        out.append(CODE[CHAR[s[i]]])
        i += 1
    return "".join("\\%03o" % c for c in out)


def content():
    c = ["0 G 0.8 w %.1f %.1f m %.1f %.1f l S\n" % (X0, Y0, X1, Y0),
         "%.1f %.1f m %.1f %.1f l S\n" % (X0, Y0, X0, Y1)]
    for k, m in enumerate(range(0, 13, 3)):
        x = px(m)
        label = "%s %d" % (MONTHS[k], 2010 if m < 12 else 2011)
        c.append("%.3f %.1f m %.3f %.1f l S\n" % (x, Y0, x, Y0 - 5))
        c.append("0 g BT /F2 8 Tf %.3f %.1f Td (%s) Tj ET\n" % (x - 17.0, Y0 - 15, encode(label)))
    for v in range(0, 101, 20):
        y = py(v)
        c.append("%.1f %.3f m %.1f %.3f l S\n" % (X0, y, X0 - 5, y))
        c.append("BT /F1 8 Tf %.3f %.3f Td (%d) Tj ET\n" % (X0 - 9 - 4.5 * len(str(v)), y - 3, v))
    c.append("BT /F2 11 Tf 230 420 Td (%s) Tj ET\n" % encode("Profits by month"))
    c.append("0 0 1 rg\n")
    for m, v in POINTS:                       # filled squares
        c.append("%.3f %.3f 6 6 re f\n" % (px(m) - 3, py(v) - 3))
    return "".join(c).encode("latin-1")


def write_pdf(path):
    body = content()
    diffs = "[128 " + " ".join("/" + g for g in GLYPHS) + "]"
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 600 500] "
        b"/Resources << /Font << /F1 5 0 R /F2 6 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length %d >>\nstream\n" % len(body) + body + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
        b"/Encoding << /Type /Encoding /Differences " + diffs.encode() + b" >> >>",
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


def write_reference(path):
    rows = ["page,graph,symbol,series,legend_key,x_coord,y_coord,color,color_hex"]
    for m, v in POINTS:
        rows.append("1,1,filled-square,,0,%.6g,%.6g,blue,#0000ff"
                    % (2010 + m / 12.0, v))
    with open(path, "w") as f:
        f.write("\n".join(rows) + "\n")


if __name__ == "__main__":
    write_pdf(os.path.join(DATA, "synthetic-date-axis.pdf"))
    write_reference(os.path.join(DATA, "synthetic-date-axis.reference.csv"))
    print("written to", DATA)

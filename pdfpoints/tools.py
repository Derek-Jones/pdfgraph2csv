"""Which program drew a graph, from what the PDF records.

A plot embedded in a document (LaTeX's \\includegraphics, InDesign, ...) is
usually kept as a Form XObject, and pdfTeX copies the embedded file's
document information into it (/PTEX.InfoDict: Creator, Producer); other
programs may attach XMP metadata (xmp:CreatorTool) to the XObject.  A PDF
that is itself a plot (written by R, matplotlib, ...) says so in its own
document information.

Creator names the program that made the content; Producer the one that
wrote the PDF.  Programs that only convert or print to PDF (Ghostscript,
Acrobat Distiller, printer drivers, PDF libraries) say nothing about how a
graph was drawn and are not reported.  The document's own Creator/Producer
is used only when it names a plotting program: a LaTeX or Word document
containing a chart does not tell which program drew the chart.
"""

import bisect
import re

# programs that convert, print or merely write PDF
_CONVERTER = re.compile(
    r"ghostscript|distiller|pscript\d*\.dll|adobeps|pdfium|quartz pdfcontext|"
    r"print to pdf|cairo\b|pdf ?library|pdflib|itext|ps2pdf|epstopdf|dvipdf|"
    r"pdfwriter|pdf ?printer|cutepdf|primopdf|bullzip|nitro pro|foxit|"
    r"skia/pdf|microsoft: print|pdfcreator|qt \d|macos version", re.I)

# plotting and statistics programs (for the document-level information)
_PLOTTING = re.compile(
    r"^r( \d|$)|\bmatplotlib\b|\bgnuplot\b|\bmatlab\b|\boctave\b|\bexcel\b|"
    r"\borigin(lab|pro)?\b|\bmathematica\b|\bwolfram\b|\bstata\b|^sas\b|\bspss\b|"
    r"\bprism\b|\bgraphpad\b|\bsigmaplot\b|\bigor\b|\bgrace\b|\bveusz\b|\bplotly\b|"
    r"\bbokeh\b|\bmaple\b|\bjmp\b|\bminitab\b|\btableau\b|\bjulia\b|\bs-plus\b|"
    r"^s graphics|\bstatistica\b|\bgretl\b|\beviews\b|\bkaleidagraph\b|\bscilab\b|"
    r"\blabview\b|\bggplot|\bseaborn\b|\bvega\b|\bpgfplots\b|\bgle\b|\bpyx\b|"
    r"\bqtiplot\b|\bscidavis\b|\blabplot\b|\bdatagraph\b|\bdeltagraph\b|\bstatgraphics\b",
    re.I)


def _clean(s):
    """A Creator/Producer string tidied for output: no surrounding
    parentheses, no web address, single spaces."""
    if not s:
        return ""
    if isinstance(s, bytes):
        s = _decode(s)
    s = " ".join(str(s).replace("\x00", "").split())
    s = re.sub(r"\\([()\\])", r"\1", s)          # escapes left in by the writer
    if s.startswith("(") and s.endswith(")"):
        s = s[1:-1].strip()
    s = re.sub(r"[.;,]?\s*Operating System:.*$", "", s, flags=re.I)   # MATLAB
    # a trailing web address, also in parentheses: "Inkscape 1.1.2 (https://inkscape.org)"
    s = re.sub(r",?\s*\(?\s*(https?://|www\.)[^\s)]*\)?\s*$", "", s).strip(" ,;")
    return s


def _decode(b):
    if b.startswith(b"\xfe\xff"):
        return b[2:].decode("utf-16-be", "replace")
    if b.startswith(b"\xff\xfe"):
        return b[2:].decode("utf-16-le", "replace")
    try:
        return b.decode("utf-8")
    except UnicodeDecodeError:
        return b.decode("latin-1")


def tool_name(creator, producer, creator_tool=""):
    """The program a Creator / Producer / xmp:CreatorTool triple names as
    having made the content, or "" if they only name converters."""
    c = _clean(creator)
    p = _clean(producer)
    x = _clean(creator_tool)
    # Acrobat's Office add-in names the Office program it ran in
    for s in (c, p, x):
        m = re.search(r"PDFMaker.*\bfor (Microsoft )?(Excel|Word|PowerPoint)", s, re.I)
        if m:
            return "Microsoft " + m.group(2).capitalize()
    c = "" if _CONVERTER.search(c) else c
    p = "" if _CONVERTER.search(p) else p
    x = "" if _CONVERTER.search(x) else x
    if c and p and p.lower().startswith(c.lower()) and len(p) > len(c):
        return p                          # "R" + "R 4.0.2": the version too
    return c or x or p


def is_plotting_program(name):
    return bool(name) and bool(_PLOTTING.search(name))


_CREATOR_TOOL = re.compile(rb"CreatorTool(?:>|=\")([^<\"]*)")


def xmp_creator_tool(xmp_bytes):
    m = _CREATOR_TOOL.search(xmp_bytes or b"")
    return _decode(m.group(1)) if m else ""


# -- the tool recorded for the paths of one graph -----------------------------

class PathsByX:
    """The paths of a page sorted by the x of their first point, to hand
    each graph only those in its column (pages of small multiples have
    hundreds of graphs and tens of thousands of paths)."""

    def __init__(self, paths):
        order = sorted(range(len(paths)), key=lambda k: paths[k]["subpaths"][0]["start"][0])
        self.paths = paths
        self.order = order
        self.xs = [paths[k]["subpaths"][0]["start"][0] for k in order]

    def between(self, lo, hi):
        """The paths whose first point has lo <= x <= hi, in drawing order."""
        a = bisect.bisect_left(self.xs, lo)
        b = bisect.bisect_right(self.xs, hi)
        return [self.paths[k] for k in sorted(self.order[a:b])]


def graph_tool(g, paths, glyph_symbols):
    """The program that drew a graph, as recorded for the embedded graphic
    its paths were drawn in: the most common one among the paths (and
    Dingbats markers) inside the graph's box.  "" if none is recorded."""
    x0, y0, x1, y1 = g["rect"]
    mx, my = 0.05 * (x1 - x0), 0.05 * (y1 - y0)
    count = {}
    for p in paths:
        t = p.get("tool")
        if not t:
            continue
        sp = p["subpaths"][0]
        x, y = sp["start"]
        if x0 - mx <= x <= x1 + mx and y0 - my <= y <= y1 + my:
            count[t] = count.get(t, 0) + 1
    for s in glyph_symbols:
        t = s.get("tool")
        if t and x0 <= s["cx"] <= x1 and y0 <= s["cy"] <= y1:
            count[t] = count.get(t, 0) + 1
    return max(count, key=lambda t: (count[t], t)) if count else ""

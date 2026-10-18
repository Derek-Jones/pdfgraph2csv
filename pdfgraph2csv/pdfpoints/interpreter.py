"""Executing a page's drawing operators.

pdfminer.six's PDFPageInterpreter does the work of a content-stream
interpreter: it keeps the current transformation matrix, the q/Q stack and
the text state (font, size, spacing, text and line matrices), and loads the
fonts and resources.  The operators themselves are tokenized by qpdf
(pikepdf), which is many times faster than pdfminer.six's own parser on the
huge streams of plots with 100 000+ markers.  The
subclass `ContentInterpreter` adds what plot extraction needs and pdfminer
does not keep:

  * paths are recorded (in page coordinates, in drawing order) together
    with their fill and stroke colours, fill opacity (ExtGState /ca) and
    clipping box (W / W*, which pdfminer ignores);
  * colours are converted to RGB from any colour space, including Indexed;
  * text is recorded glyph by glyph, split into separate labels where a PDF
    writer packed several into one string;
  * ZapfDingbats marker glyphs are recorded as marker symbols;
  * images are recorded as boxes (they may hide text drawn earlier);
  * a Form XObject inherits the graphics state of the page that draws it
    (as the PDF specification says; pdfminer starts it afresh);
  * a malformed operator is skipped instead of ending the page.

`Interpreter` collects the results of one page.
"""

import decimal
import math
import sys

import pikepdf
from pdfminer.pdfdevice import PDFDevice
from pdfminer.pdfinterp import PDFContentParser, PDFPageInterpreter
from pdfminer.pdftypes import PDFStream, resolve1, stream_value
from pdfminer.psparser import LIT, PSEOF, PSKeyword, keyword_name, literal_name

from .context import PAGE, SETTINGS
from .fonts import DINGBAT_ANCHOR, DINGBAT_SYMBOLS, FontInfo
from .geometry import bbox_of, mapply, mmul

IDENTITY = (1, 0, 0, 1, 0, 0)


class Interpreter:
    """Executes a page and collects, in page coordinates and drawing order:
    `paths` (painted paths), `texts` (text items), `glyph_symbols`
    (ZapfDingbats markers) and `images` ((box, drawing step))."""

    def __init__(self, doc):
        self.doc = doc
        self.paths = []
        self.texts = []
        self.glyph_symbols = []
        self.images = []
        self.order = 0
        self.fonts = {}          # id(pdfminer font) -> FontInfo

    def run_page(self, page):
        """Execute a pdfminer PDFPage.  Page coordinates are the PDF's own
        user space (the page's /Rotate and media box offset are not applied)."""
        interp = ContentInterpreter(self.doc.rsrcmgr, PDFDevice(self.doc.rsrcmgr), self)
        interp.render_contents(page.resources, page.contents, ctm=IDENTITY)

    def record(self, kind, item):
        """Store a drawn object with the next drawing step number."""
        item["idx"] = self.order
        self.order += 1
        getattr(self, kind).append(item)

    def font_info(self, font, spec):
        """FontInfo for a pdfminer font (cached)."""
        key = id(font)
        if key not in self.fonts:
            self.fonts[key] = FontInfo(font, spec)
        return self.fonts[key]


class ExtraState:
    """The parts of the graphics state that pdfminer does not keep (or
    keeps in a form not used here); saved and restored by q / Q."""

    def __init__(self):
        self.fill = (0.0, 0.0, 0.0)       # RGB, or None for an unknown colour
        self.stroke = (0.0, 0.0, 0.0)
        self.fill_cs = ("gray", None)     # colour spaces, see colour_space()
        self.stroke_cs = ("gray", None)
        self.ca = 1.0                     # fill opacity
        self.clip = None                  # clipping box (x0, y0, x1, y1), None = page
        self.font = None                  # FontInfo of the current font

    def copy(self):
        c = ExtraState.__new__(ExtraState)
        c.__dict__.update(self.__dict__)
        return c


class ContentInterpreter(PDFPageInterpreter):
    """pdfminer's interpreter, extended to record paths, colours, clipping,
    opacity, text, markers and images (see the module description)."""

    MAX_DEPTH = 25                        # Form XObject nesting

    def __init__(self, rsrcmgr, device, page=None, depth=0, inherit=None):
        super().__init__(rsrcmgr, device)
        # (older pdfminer.six versions do not track nested streams)
        self.stream_ids = getattr(self, "stream_ids", set())
        self.parent_stream_ids = getattr(self, "parent_stream_ids", set())
        self.page = page                  # the Interpreter collecting results
        self.depth = depth
        self.inherit = inherit            # state handed down to a Form XObject
        self.clip_next = False            # W / W*: the current path becomes a clip

    def dup(self):
        return self.__class__(self.rsrcmgr, self.device, self.page, self.depth)

    def init_state(self, ctm):
        super().init_state(ctm)
        self.extra = ExtraState()
        self.extra_stack = []
        if self.inherit is not None:      # a Form XObject: continue the caller's state
            textstate, graphicstate, extra = self.inherit
            self.textstate, self.graphicstate, self.extra = textstate, graphicstate, extra

    def execute(self, streams):
        """Run the operators of the content streams.  They are tokenized by
        qpdf (pikepdf), which is far faster than pdfminer.six's parser on big
        streams (plots with 100 000+ markers); pdfminer.six's parser is the
        fallback for content qpdf rejects.  An operator that fails is
        skipped (one malformed operator must not lose the page)."""
        valid = []
        self.stream_ids.clear()
        for obj in streams:
            stream = stream_value(obj)
            if stream.objid is not None and stream.objid in self.parent_stream_ids:
                continue                  # a Form XObject drawing itself
            valid.append(stream)
            if stream.objid is not None:
                self.stream_ids.add(stream.objid)
        try:
            data = b"\n".join(s.get_data() for s in valid)
            instructions = pikepdf.parse_content_stream(pikepdf.Stream(_scratch_pdf(), data))
        except Exception:
            self._execute_pdfminer(valid)
            return
        if len(instructions) > 500000:    # say why the program is busy
            print("note: page %d draws %.1f million objects; this may take a few minutes"
                  % (PAGE.number, len(instructions) / 1e6), file=sys.stderr, flush=True)
        for inst in instructions:
            if not isinstance(inst, pikepdf.ContentStreamInstruction):
                continue                  # inline images
            self._run_operator(str(inst.operator), [_from_pikepdf(o) for o in inst.operands])

    def _execute_pdfminer(self, streams):
        try:
            parser = PDFContentParser(streams)
        except PSEOF:
            return                        # empty page
        operands = []
        while True:
            try:
                _, obj = parser.nextobject()
            except PSEOF:
                break
            except Exception:
                continue
            if isinstance(obj, PSKeyword):
                self._run_operator(keyword_name(obj), operands)
                operands = []
            else:
                operands.append(obj)

    def _run_operator(self, name, operands):
        """Call do_<operator> with its operands (those given since the
        previous operator; colour operators use them all)."""
        handler = _HANDLERS.get((type(self), name))
        if handler is None:
            method = getattr(type(self), "do_" + name.replace("*", "_a").replace('"', "_w")
                             .replace("'", "_q"), None)
            handler = (method, method.__code__.co_argcount - 1) if method else (None, 0)
            _HANDLERS[(type(self), name)] = handler
        method, nargs = handler
        if method is None or len(operands) < nargs:
            return
        self.operands = operands
        try:
            method(self, *operands[len(operands) - nargs:]) if nargs else method(self)
        except Exception:
            pass

    # -- graphics state ----------------------------------------------------
    def do_q(self):
        super().do_q()
        self.extra_stack.append(self.extra.copy())

    def do_Q(self):
        if self.gstack:
            super().do_Q()
            self.extra = self.extra_stack.pop()

    def do_gs(self, name):
        """ExtGState: only the fill opacity /ca is used."""
        eg = self._resource("ExtGState", name)
        if isinstance(eg, dict) and eg.get("ca") is not None:
            self.extra.ca = _num(resolve1(eg.get("ca")))

    def _resource(self, category, name):
        """A named resource of the current resource dictionary."""
        res = resolve1(self.resources) if self.resources else None
        if not isinstance(res, dict):
            return None
        group = resolve1(res.get(category))
        return resolve1(group.get(literal_name(name))) if isinstance(group, dict) else None

    # -- path painting and clipping ------------------------------------------
    def _paint(self, fill, stroke, close=False):
        """Record the current path (if painted) and apply a pending clip."""
        if close:
            self.curpath.append(("h",))
        subpaths = build_subpaths(self.curpath, self.ctm)
        if (fill or stroke) and subpaths:
            e = self.extra
            self.page.record("paths", {
                "subpaths": subpaths, "fill": fill, "stroke": stroke,
                "fill_rgb": e.fill, "stroke_rgb": e.stroke,
                "opaque": e.ca >= 0.99, "clip": e.clip})
        if self.clip_next and subpaths:
            pts = [q for sp in subpaths for q in [sp["start"]] +
                   [r for seg in sp["segs"] for r in seg[1:]]]
            b, c = bbox_of(pts), self.extra.clip
            self.extra.clip = b if c is None else (max(b[0], c[0]), max(b[1], c[1]),
                                                   min(b[2], c[2]), min(b[3], c[3]))
        self.clip_next = False
        self.curpath = []

    def do_S(self):
        self._paint(False, True)

    def do_s(self):
        self._paint(False, True, close=True)

    def do_f(self):
        self._paint(True, False, close=True)

    do_F = do_f_a = do_f

    def do_B(self):
        self._paint(True, True)

    do_B_a = do_B

    def do_b(self):
        self._paint(True, True, close=True)

    do_b_a = do_b

    def do_n(self):
        self._paint(False, False)

    def do_W(self):
        self.clip_next = True

    do_W_a = do_W

    # -- colour --------------------------------------------------------------
    # (pdfminer's colour operators take a fixed number of operands; here a
    # colour takes all operands given, as the colour space may need any
    # number)
    def _set_colour(self, fill, space=None):
        comps = self.operands
        e = self.extra
        if fill:
            if space:
                e.fill_cs = (space, None)
            e.fill = to_rgb(e.fill_cs, comps)
        else:
            if space:
                e.stroke_cs = (space, None)
            e.stroke = to_rgb(e.stroke_cs, comps)

    def do_g(self):
        self._set_colour(True, "gray")

    def do_G(self):
        self._set_colour(False, "gray")

    def do_rg(self):
        self._set_colour(True, "rgb")

    def do_RG(self):
        self._set_colour(False, "rgb")

    def do_k(self):
        self._set_colour(True, "cmyk")

    def do_K(self):
        self._set_colour(False, "cmyk")

    def do_sc(self):
        self._set_colour(True)

    do_scn = do_sc

    def do_SC(self):
        self._set_colour(False)

    do_SCN = do_SC

    def do_cs(self, name):
        self.extra.fill_cs = colour_space(name, self._resource("ColorSpace", name))
        self.extra.fill = (0.0, 0.0, 0.0)

    def do_CS(self, name):
        self.extra.stroke_cs = colour_space(name, self._resource("ColorSpace", name))
        self.extra.stroke = (0.0, 0.0, 0.0)

    # -- text ------------------------------------------------------------------
    def do_Tf(self, fontid, fontsize):
        """Select a font; an undefined font shows no text."""
        if literal_name(fontid) not in self.fontmap:
            self.textstate.font = None
            self.extra.font = None
            return
        super().do_Tf(fontid, fontsize)
        spec = self._resource("Font", fontid) or {}
        self.extra.font = self.page.font_info(self.textstate.font, spec)

    def do_TJ(self, seq):
        if self.textstate.font is not None and self.extra.font is not None:
            self.show(seq if isinstance(seq, list) else [seq])

    def show(self, items):
        """Show text.  Glyphs are positioned one by one (Tc, Tw, Tz, TJ
        adjustments) and the string is split into separate text items
        wherever the visible gap between consecutive glyphs exceeds the font
        size, so labels that a PDF writer packed into one TJ/Tj with wide
        character spacing come out as separate labels (e.g. Acrobat
        Distiller's "[(-)6404(1)83(13)-55(57)]TJ").  Space characters only
        move the pen; a space character or a gap wider than 0.15 em inside a
        piece becomes a single space, so words stay joined.  ZapfDingbats
        marker glyphs are recorded as marker symbols instead of text."""
        ts = self.textstate
        font = self.extra.font
        fs, tc, tw, rise = ts.fontsize, ts.charspace, ts.wordspace, ts.rise
        th = ts.scaling / 100.0               # horizontal scaling
        lx, ly = ts.linematrix
        # text space -> page: the line matrix, advanced along the line
        base = mmul(mmul((1, 0, 0, 1, lx, ly), ts.matrix), self.ctm)
        pen = 0.0                             # current glyph origin, text space units
        pieces = []                           # [text, start, end, glyphs]
        last_end = None
        saw_space = False                     # a space character since the previous glyph
        em = abs(fs * th) or 1.0
        for item in items:
            if isinstance(item, (int, float)):        # TJ adjustment, 1/1000 em
                pen += -item / 1000.0 * fs * th
                continue
            if not isinstance(item, bytes):
                continue
            for code, u in font.decode(item):
                w = font.width(code, u) / 1000.0
                if font.dingbats and code in DINGBAT_SYMBOLS and ts.render not in (3, 7):
                    self.dingbat_marker(code, base, pen, th)
                    last_end = None                   # a marker separates text
                elif not font.dingbats and u.isspace():
                    saw_space = True
                elif not font.dingbats:
                    gend = pen + w * fs * th          # end of the visible glyph
                    if last_end is None or not pieces or abs(pen - last_end) > em:
                        pieces.append([u, pen, gend, [(u, pen, gend)]])
                    else:
                        if saw_space or pen - last_end > 0.15 * em:
                            pieces[-1][0] += " "
                        pieces[-1][0] += u
                        pieces[-1][2] = gend
                        pieces[-1][3].append((u, pen, gend))
                    last_end = gend
                    saw_space = False
                pen += (w * fs + tc + (tw if (code == 32 and not font.two_byte) else 0)) * th
        size = math.hypot(base[2] * fs, base[3] * fs)
        for txt, s0, s1, gl in pieces:
            p0 = mapply(base, s0, rise)
            top = mapply(base, s0, rise + 0.7 * fs)
            self.page.record("texts", {
                "text": txt, "p0": p0, "p1": mapply(base, s1, rise),
                "up": (top[0] - p0[0], top[1] - p0[1]), "size": size,
                # each glyph: (char, start point, end point) on the page
                "glyphs": [(c, mapply(base, a, rise), mapply(base, b, rise))
                           for c, a, b in gl]})
        ts.linematrix = (lx + pen, ly)

    def dingbat_marker(self, code, base, pen, th):
        """A ZapfDingbats marker glyph at pen position `pen`."""
        ts, e = self.textstate, self.extra
        fs, rise = ts.fontsize, ts.rise
        shape, (bx0, by0, bx1, by1) = DINGBAT_SYMBOLS[code]
        if SETTINGS.glyph_centre == "bbox":
            cxg, cyg = (bx0 + bx1) / 2000.0, (by0 + by1) / 2000.0
        else:
            cxg, cyg = DINGBAT_ANCHOR
        c = mapply(base, pen + cxg * fs * th, rise + cyg * fs)
        e0 = mapply(base, pen + bx0 / 1000.0 * fs * th, rise + by0 / 1000.0 * fs)
        e1 = mapply(base, pen + bx1 / 1000.0 * fs * th, rise + by1 / 1000.0 * fs)
        filled = ts.render in (0, 2, 4, 6)    # modes 0/2/4/6 fill the glyph; 1/5 stroke it
        self.page.record("glyph_symbols", {
            "shape": shape, "cx": c[0], "cy": c[1],
            "size": max(abs(e1[0] - e0[0]), abs(e1[1] - e0[1])),
            "filled": filled, "rgb": e.fill if filled else e.stroke})

    # -- XObjects ----------------------------------------------------------------
    def do_Do(self, xobjid):
        """Run a Form XObject (with its own matrix and resources, inheriting
        this graphics state), or note where an image was placed."""
        xobj = resolve1(self.xobjmap.get(literal_name(xobjid)))
        if not isinstance(xobj, PDFStream):
            return
        subtype = literal_name(xobj.get("Subtype")) if xobj.get("Subtype") else ""
        if subtype == "Form" and self.depth < self.MAX_DEPTH:
            matrix = resolve1(xobj.get("Matrix")) or IDENTITY
            if not (isinstance(matrix, list) and len(matrix) == 6):
                matrix = IDENTITY
            matrix = tuple(_num(resolve1(x)) for x in matrix)
            res = resolve1(xobj.get("Resources")) or self.resources
            sub = self.__class__(self.rsrcmgr, self.device, self.page, self.depth + 1,
                                 (self.textstate.copy(), self.graphicstate.copy(),
                                  self.extra.copy()))
            sub.parent_stream_ids.update(self.parent_stream_ids | self.stream_ids)
            sub.render_contents(res, [xobj], ctm=mmul(matrix, self.ctm))
        elif subtype == "Image":
            pts = [mapply(self.ctm, u, v) for u, v in ((0, 0), (1, 0), (0, 1), (1, 1))]
            xs, ys = [p[0] for p in pts], [p[1] for p in pts]
            self.page.images.append(((min(xs), min(ys), max(xs), max(ys)), self.page.order))
            self.page.order += 1


_HANDLERS = {}                            # (class, operator) -> (method, operand count)
_SCRATCH = []


def _scratch_pdf():
    """An empty pikepdf document to hold content streams for tokenizing."""
    if not _SCRATCH:
        _SCRATCH.append(pikepdf.new())
    return _SCRATCH[0]


def _from_pikepdf(o):
    """A pikepdf operand as the Python value pdfminer.six would produce:
    numbers as int/float, names as PSLiteral, strings as bytes, arrays as
    lists and dictionaries as dicts."""
    t = type(o)
    if t is int or t is float or t is bool:
        return o
    if t is decimal.Decimal:
        return float(o)
    if isinstance(o, pikepdf.Name):
        return LIT(str(o)[1:])
    if isinstance(o, pikepdf.String):
        return bytes(o)
    if isinstance(o, pikepdf.Array):
        return [_from_pikepdf(x) for x in o]
    if isinstance(o, pikepdf.Dictionary):
        return {str(k)[1:]: _from_pikepdf(v) for k, v in o.items()}
    return None


def build_subpaths(curpath, ctm):
    """pdfminer's path segments (user space) -> subpaths in page
    coordinates: [{start, segs: [("l", p) | ("c", p1, p2, p3)], closed}].
    A segment after a close-path starts a new subpath at the current point."""
    subpaths, sub, cur = [], None, None

    def P(x, y):
        return mapply(ctm, _num(x), _num(y))

    def new_sub(pt):
        s = {"start": pt, "segs": [], "closed": False}
        subpaths.append(s)
        return s

    for seg in curpath:
        op, a = seg[0], seg[1:]
        if op == "m":
            cur = P(a[0], a[1])
            sub = new_sub(cur)
        elif op == "l":
            if sub is None:
                sub = new_sub(cur or P(0, 0))
            cur = P(a[0], a[1])
            sub["segs"].append(("l", cur))
        elif op in ("c", "v", "y"):
            if sub is None:
                sub = new_sub(cur or P(0, 0))
            if op == "c":
                p1, p2, p3 = P(a[0], a[1]), P(a[2], a[3]), P(a[4], a[5])
            elif op == "v":                   # first control point = current point
                p1, p2, p3 = cur, P(a[0], a[1]), P(a[2], a[3])
            else:                             # y: second control point = end point
                p1, p2, p3 = P(a[0], a[1]), P(a[2], a[3]), P(a[2], a[3])
            sub["segs"].append(("c", p1, p2, p3))
            cur = p3
        elif op == "h" and sub is not None:
            sub["closed"] = True
            cur = sub["start"]
            sub = None
    return subpaths


# -- colour spaces ------------------------------------------------------------
_DEVICE = {"DeviceGray": "gray", "G": "gray", "CalGray": "gray",
           "DeviceRGB": "rgb", "RGB": "rgb", "CalRGB": "rgb", "Lab": "rgb",
           "DeviceCMYK": "cmyk", "CMYK": "cmyk"}


def colour_space(name, spec):
    """(kind, details) of a colour space given by name and its resource
    entry: kind is gray, rgb, cmyk, indexed (details: base space and lookup
    table) or unknown (patterns, Separation, DeviceN: their colours count as
    unknown)."""
    name = literal_name(name) if not isinstance(name, str) else name
    if name in _DEVICE:
        return (_DEVICE[name], None)
    return _colour_space_obj(spec)


def _colour_space_obj(cs):
    cs = resolve1(cs)
    if cs is None:
        return ("unknown", None)
    if not isinstance(cs, list):
        n = literal_name(cs) if not isinstance(cs, str) else cs
        return (_DEVICE.get(n, "unknown"), None)
    if not cs:
        return ("unknown", None)
    kind = literal_name(resolve1(cs[0]))
    if kind == "ICCBased" and len(cs) > 1:
        st = resolve1(cs[1])
        n = resolve1(st.get("N")) if isinstance(st, PDFStream) else 3
        return {1: ("gray", None), 3: ("rgb", None), 4: ("cmyk", None)}.get(n, ("unknown", None))
    if kind in ("CalRGB", "Lab"):
        return ("rgb", None)
    if kind == "CalGray":
        return ("gray", None)
    if kind in ("Indexed", "I") and len(cs) > 3:
        base = _colour_space_obj(cs[1])
        lookup = resolve1(cs[3])
        if isinstance(lookup, PDFStream):
            lookup = lookup.get_data()
        return ("indexed", (base, lookup if isinstance(lookup, bytes) else b""))
    return ("unknown", None)


def to_rgb(cs, comps):
    """Colour operands in a colour space -> (r, g, b) in 0..1, or None."""
    kind, extra = cs
    c = [_num(x) for x in comps if isinstance(x, (int, float))]
    try:
        if kind == "gray" and len(c) >= 1:
            return (c[0], c[0], c[0])
        if kind == "rgb" and len(c) >= 3:
            return (c[0], c[1], c[2])
        if kind == "cmyk" and len(c) >= 4:
            return ((1 - c[0]) * (1 - c[3]), (1 - c[1]) * (1 - c[3]), (1 - c[2]) * (1 - c[3]))
        if kind == "indexed" and len(c) >= 1:
            base, lookup = extra
            nb = {"gray": 1, "rgb": 3, "cmyk": 4}.get(base[0], 3)
            i = int(c[0]) * nb
            return to_rgb(base, [b / 255.0 for b in lookup[i:i + nb]])
    except Exception:
        pass
    return None


def _num(x):
    return float(x) if isinstance(x, (int, float)) else 0.0

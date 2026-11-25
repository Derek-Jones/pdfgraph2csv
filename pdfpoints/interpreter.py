"""Executing a page's drawing operators.

pdfminer.six's PDFPageInterpreter does the work of a content-stream
interpreter: it keeps the current transformation matrix, the q/Q stack and
the text state (font, size, spacing, text and line matrices), and loads the
fonts and resources.  The operators themselves are tokenized by
tokenizer.py (or by qpdf, for content with inline images), which is many
times faster than pdfminer.six's own parser on the huge streams of plots
with 100 000+ markers.  The
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
  * text outside a Form XObject's /BBox is hidden (Sovinsky-paper-017);
  * a malformed operator is skipped instead of ending the page.

`Interpreter` collects the results of one page.
"""

import decimal
import math
import re
import sys

import zlib

import pikepdf
from pdfminer.pdfdevice import PDFDevice
from pdfminer.pdfinterp import PDFContentParser, PDFPageInterpreter
from pdfminer.pdftypes import PDFStream, resolve1, stream_value
from pdfminer.psparser import LIT, PSEOF, PSKeyword, PSLiteral, keyword_name, literal_name

from .context import PAGE, SETTINGS
from .fonts import DINGBAT_ANCHOR, DINGBAT_SYMBOLS, FontInfo, dingbat_code, register_fonts
from pdfminer.utils import apply_matrix_pt, mult_matrix

from .colourbar import colour_strip, strip_pixels
from .geometry import bbox_of, control_points
from .image_marks import read_image
from .tokenizer import Floats, coordinate_decimals, has_inline_image, operators
from .tools import tool_name, xmp_creator_tool

IDENTITY = (1, 0, 0, 1, 0, 0)


class Interpreter:
    """Executes a page and collects, in page coordinates and drawing order:
    `paths` (painted paths), `texts` (text items), `glyph_symbols`
    (ZapfDingbats markers), `images` ((box, drawing step) of unmasked
    images, which may hide what is under them) and `image_marks` (images
    small enough to be markers)."""

    def __init__(self, doc):
        self.doc = doc
        self.paths = []
        self.texts = []
        self.glyph_symbols = []
        self.image_marks = []
        self.colour_strips = []  # one-pixel images: colour bars (colourbar.py)
        self.pictures = []       # big images: heat maps drawn as pictures (colourbar.py)
        self.images = []
        self.op_errors = {}      # (operator, exception type) -> [count, first message]
        self.order = 0
        self.fonts = {}          # id(pdfminer font) -> FontInfo

    def run_page(self, page, ctm=None):
        """Execute a pdfminer PDFPage.  Page coordinates are the PDF's own
        user space (the page's /Rotate and media box offset are not applied),
        or that space mapped by `ctm` (a page drawn turned: see
        pipeline.page_turn)."""
        interp = ContentInterpreter(self.doc.rsrcmgr, PDFDevice(self.doc.rsrcmgr), self)
        interp.render_contents(page.resources, page.contents, ctm=ctm or IDENTITY)

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
        self.form_box = None              # the /BBox of the Form XObjects being run (page space)
        self.font = None                  # FontInfo of the current font
        self.gs_name = ""                 # name of the last ExtGState set (drawing style)
        self.fill_pattern = None          # name of the fill colour's pattern, if one

    def copy(self):
        c = ExtraState.__new__(ExtraState)
        c.__dict__.update(self.__dict__)
        return c


class ContentInterpreter(PDFPageInterpreter):
    """pdfminer's interpreter, extended to record paths, colours, clipping,
    opacity, text, markers and images (see the module description)."""

    def init_resources(self, resources):
        # (fonts of every resource dictionary are noted: a subset whose
        # glyph names are made up is read through its sibling subsets)
        if resources:
            fonts = resolve1(resources.get("Font"))
            if isinstance(fonts, dict):
                register_fonts(fonts.values())
        return super().init_resources(resources)

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
        self.unit = None                  # resolution of the stream's numbers (10^-decimals)
        self.tool = None                  # the program that drew this content (if recorded)
        self.decimals = None              # decimals the stream's numbers are written with
        self.form_name = ""               # resource name of the Form XObject being run

    def dup(self):
        return self.__class__(self.rsrcmgr, self.device, self.page, self.depth)

    def init_state(self, ctm):
        super().init_state(ctm)
        self.start_ctm = ctm              # the stream's own space: patterns are placed in it
        self.extra = ExtraState()
        self.extra_stack = []
        if self.inherit is not None:      # a Form XObject: continue the caller's state
            textstate, graphicstate, extra = self.inherit
            self.textstate, self.graphicstate, self.extra = textstate, graphicstate, extra

    def execute(self, streams):
        """Run the operators of the content streams.  They are tokenized one
        at a time by tokenizer.py, which is far faster than pdfminer.six's
        parser on big streams (plots with 100 000+ markers) and, unlike qpdf's
        tokenizer, does not hold the whole stream as objects in memory.
        Content with inline images is tokenized by qpdf (pikepdf), and
        pdfminer.six's parser is the fallback for content qpdf rejects.  An
        operator that fails is skipped (one malformed operator must not lose
        the page)."""
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
        except Exception:
            self._execute_pdfminer(valid)
            return
        # coordinates are known to half a unit of their last decimal
        self.decimals = coordinate_decimals(data)
        self.unit = 10.0 ** -self.decimals
        if len(data) > 15000000:          # say why the program is busy
            print("note: page %d has %d MB of drawing instructions; this may take a minute or two"
                  % (PAGE.number, len(data) // 1000000), file=sys.stderr, flush=True)
        if not has_inline_image(data):
            run = self._run_operator
            for name, operands in operators(data):
                # path construction, by far the most common: when the
                # tokenizer gives floats the segment is recorded directly,
                # as pdfminer would record it
                n = _PATH_OPERANDS.get(name)
                if n is not None and type(operands) is Floats and len(operands) >= n:
                    self.curpath.append((name, *operands[len(operands) - n:]))
                else:
                    run(name, operands)
            return
        try:                              # inline images: qpdf knows where they end
            instructions = pikepdf.parse_content_stream(pikepdf.Stream(_scratch_pdf(), data))
        except Exception:
            self._execute_pdfminer(valid)
            return
        for inst in instructions:
            if isinstance(inst, pikepdf.ContentStreamInlineImage):
                self._inline_image(inst.iimage)
                continue
            if not isinstance(inst, pikepdf.ContentStreamInstruction):
                continue
            self._run_operator(str(inst.operator), [_from_pikepdf(o) for o in inst.operands])

    def _inline_image(self, ii):
        """An inline image one pixel wide or tall - a colour bar's gradient
        (ggplot, Maj-Petr_PhD-077) - is recorded as a colour strip: its
        placement (ctm) and pixel colours (colourbar.py)."""
        try:
            w, h = int(ii.width), int(ii.height)
            if min(w, h) != 1 or max(w, h) < 2 or int(ii.bits_per_component) != 8:
                return
            filters = [str(f) for f in (ii.filters or [])]
            data = ii.read_raw_bytes()
            if filters == ["/FlateDecode"]:
                data = zlib.decompress(data)
            elif filters:
                return
            parms = ii.decode_parms or []
            parms = parms[0] if isinstance(parms, list) and parms else parms
            predictor = int(parms.get("/Predictor", 1)) if hasattr(parms, "get") else 1
        except Exception:
            return
        rgb = strip_pixels(bytes(data), w, h, predictor)
        if rgb:
            self.page.record("colour_strips", {"ctm": self.ctm, "w": w, "h": h, "rgb": rgb})

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
        except Exception as e:            # a malformed operator spoils only itself;
            # counted, so that --debug shows them (a bug in a handler would
            # otherwise pass unseen)
            errs = self.page.op_errors
            key = (name, type(e).__name__)
            if key not in errs:
                errs[key] = [0, str(e)[:80]]
            errs[key][0] += 1

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
        self.extra.gs_name = literal_name(name) if not isinstance(name, str) else name
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
        if fill and subpaths and self.extra.fill_pattern:
            self._pattern_strip(self.extra.fill_pattern)
        if (fill or stroke) and subpaths:
            e = self.extra
            self.page.record("paths", {
                "subpaths": subpaths, "fill": fill, "stroke": stroke,
                "fill_rgb": e.fill, "stroke_rgb": e.stroke,
                "opaque": e.ca >= 0.99, "clip": e.clip,
                "res": _resolution(self.unit, self.ctm), "tool": self.tool,
                "scale": _resolution(1.0, self.ctm),
                "style": self._style()})
        if self.clip_next and subpaths:
            # (only the clip's bounding box is kept: enough to tell which
            # plot a marker belongs to, and to keep markers clipped out of
            # view, which the user wants reported)
            b = bbox_of([q for sp in subpaths for q in control_points(sp)])
            c = self.extra.clip
            self.extra.clip = b if c is None else (max(b[0], c[0]), max(b[1], c[1]),
                                                   min(b[2], c[2]), min(b[3], c[3]))
        self.clip_next = False
        self.curpath = []

    def _style(self):
        """How the current path is drawn, for guessing the program that drew
        it (styles.py): (line width in page units, line cap, line join,
        decimals of the numbers, Form XObject name, ExtGState name).  Equal
        tuples are shared."""
        gs = self.graphicstate
        try:
            lw = round(float(gs.linewidth) * math.sqrt(abs(self.ctm[0] * self.ctm[3] -
                                                            self.ctm[1] * self.ctm[2])), 3)
        except (TypeError, ValueError):
            lw = None
        t = (lw, gs.linecap, gs.linejoin, self.decimals, self.form_name, self.extra.gs_name)
        return _STYLES.setdefault(t, t)

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

    def do_scn(self):
        """A fill colour; in a Pattern space, a pattern by name."""
        ops = self.operands
        self.extra.fill_pattern = literal_name(ops[-1]) if ops and isinstance(ops[-1], PSLiteral) \
            else None
        self._set_colour(True)

    def do_SC(self):
        self._set_colour(False)

    do_SCN = do_SC

    def do_cs(self, name):
        self.extra.fill_cs = colour_space(name, self._resource("ColorSpace", name))
        self.extra.fill = (0.0, 0.0, 0.0)
        self.extra.fill_pattern = None

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
        base = mult_matrix(mult_matrix((1, 0, 0, 1, lx, ly), ts.matrix), self.ctm)
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
                if font.dingbats and dingbat_code(code, u) is not None and ts.render not in (3, 7):
                    self.dingbat_marker(dingbat_code(code, u), base, pen, th)
                    last_end = None                   # a marker separates text
                elif not font.dingbats and u.isspace():
                    saw_space = True
                elif not font.dingbats:
                    gend = pen + w * fs * th          # end of the visible glyph
                    # (numbers set wider apart than a space, 0.6 em, are
                    # separate labels: Seongmin-PhD-036's tick labels 1000
                    # ... 3500 in one run, 0.84 em apart)
                    numgap = pieces and last_end is not None and pen - last_end > 0.6 * em and \
                        pieces[-1][0][-1:].isdigit() and (u.isdigit() or u in "-\u2212.")
                    if last_end is None or not pieces or abs(pen - last_end) > em or numgap:
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
            p0 = apply_matrix_pt(base, (s0, rise))
            top = apply_matrix_pt(base, (s0, rise + 0.7 * fs))
            self.page.record("texts", {
                "text": txt, "p0": p0, "p1": apply_matrix_pt(base, (s1, rise)),
                "up": (top[0] - p0[0], top[1] - p0[1]), "size": size,
                "font": font.name, "rgb": self.extra.fill, "clip": self.extra.clip,
                "form_box": getattr(self.extra, "form_box", None),
                # each glyph: (char, start point, end point) on the page
                "glyphs": [(c, apply_matrix_pt(base, (a, rise)), apply_matrix_pt(base, (b, rise)))
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
        c = apply_matrix_pt(base, (pen + cxg * fs * th, rise + cyg * fs))
        e0 = apply_matrix_pt(base, (pen + bx0 / 1000.0 * fs * th, rise + by0 / 1000.0 * fs))
        e1 = apply_matrix_pt(base, (pen + bx1 / 1000.0 * fs * th, rise + by1 / 1000.0 * fs))
        filled = ts.render in (0, 2, 4, 6)    # modes 0/2/4/6 fill the glyph; 1/5 stroke it
        self.page.record("glyph_symbols", {
            "res": _resolution(self.unit, base), "tool": self.tool,
            # (the glyph's place is written in user space: the CTM's scale
            # carries the program's rounding to the page, not the font size)
            "scale": _resolution(1.0, self.ctm),
            "shape": shape, "cx": c[0], "cy": c[1],
            "size": max(abs(e1[0] - e0[0]), abs(e1[1] - e0[1])),
            "filled": filled, "rgb": e.fill if filled else e.stroke, "clip": e.clip})

    # -- XObjects ----------------------------------------------------------------
    _PATTERN_IMAGE = re.compile(
        rb"^\s*q\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)"
        rb"\s+cm\s+/(\S+)\s+Do\s+Q\s*$")

    def _pattern_strip(self, name):
        """A fill with a tiling pattern that only places an image: a colour
        bar when the image is a strip (Mohamed_Rakha_PhD-072: Cairo draws
        ggplot's gradient as a clip box filled with pattern p6, whose
        content is "q 3 0 0 21 0 0 cm /x9 Do Q", a 3 x 21 image).  The
        pattern matrix places it in the space of the stream using it; it is
        cut to the clip box (the image runs a row past each end of the
        visible bar, and is three times as wide)."""
        pat = self._resource("Pattern", name)
        if not isinstance(pat, PDFStream) or resolve1(pat.get("PatternType")) != 1:
            return
        try:
            m = self._PATTERN_IMAGE.match(pat.get_data())
        except Exception:
            return
        if not m:
            return
        res = resolve1(pat.get("Resources")) or {}
        xobjs = resolve1(res.get("XObject")) if isinstance(res, dict) else None
        img = resolve1(xobjs.get(m.group(7).decode("latin-1"))) if isinstance(xobjs, dict) else None
        if not isinstance(img, PDFStream) or literal_name(img.get("Subtype") or "") != "Image":
            return
        cm = tuple(float(v) for v in m.groups()[:6])
        pm = resolve1(pat.get("Matrix")) or list(IDENTITY)
        pm = tuple(_num(resolve1(v)) for v in pm) if len(pm) == 6 else IDENTITY
        ctm = mult_matrix(mult_matrix(cm, pm), self.start_ctm)
        strip = colour_strip(read_image(img))
        if not strip:
            return
        strip["ctm"] = _crop_strip(strip, ctm, self.extra.clip)
        a, b, c, d, e, f = strip["ctm"]
        if max(abs(a) + abs(c), abs(b) + abs(d)) >= 20:
            self.page.record("colour_strips", strip)

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
            extra = self.extra.copy()
            # the form's /BBox clips what it draws (Sovinsky-paper-017: a
            # whole A4 page of a Stata graph and its old caption "Figure 4:
            # ..." in a form whose box holds just the graph).  It is kept
            # apart from the clip and used only to hide text: as a clip it
            # gave every mark of a figure the figure's box, and the markers
            # of log-inset's insets went to the main graph
            bb = resolve1(xobj.get("BBox"))
            if isinstance(bb, list) and len(bb) == 4:
                try:
                    bb = [_num(resolve1(v)) for v in bb]
                    m = mult_matrix(matrix, self.ctm)
                    cs = [apply_matrix_pt(m, (u, v)) for u in (bb[0], bb[2]) for v in (bb[1], bb[3])]
                    b = (min(c[0] for c in cs), min(c[1] for c in cs),
                         max(c[0] for c in cs), max(c[1] for c in cs))
                    c = getattr(extra, "form_box", None)
                    extra.form_box = b if c is None else (max(b[0], c[0]), max(b[1], c[1]),
                                                          min(b[2], c[2]), min(b[3], c[3]))
                except (TypeError, ValueError):
                    pass
            sub = self.__class__(self.rsrcmgr, self.device, self.page, self.depth + 1,
                                 (self.textstate.copy(), self.graphicstate.copy(), extra))
            sub.parent_stream_ids.update(self.parent_stream_ids | self.stream_ids)
            # an embedded graphic that records its own program (innermost wins)
            sub.tool = form_tool(xobj) or self.tool
            sub.form_name = literal_name(xobjid) if not isinstance(xobjid, str) else xobjid
            sub.render_contents(res, [xobj], ctm=mult_matrix(matrix, self.ctm))
        elif subtype == "Image":
            pts = [apply_matrix_pt(self.ctm, (u, v)) for u, v in ((0, 0), (1, 0), (0, 1), (1, 1))]
            xs, ys = [p[0] for p in pts], [p[1] for p in pts]
            box = (min(xs), min(ys), max(xs), max(ys))
            # an image with a soft mask, a mask or drawn as a stencil (a
            # translucent watermark over the page) hides nothing for sure
            if not (xobj.get("SMask") or xobj.get("Mask") or resolve1(xobj.get("ImageMask"))):
                self.page.images.append((box, self.page.order))
            ww, hh = resolve1(xobj.get("Width")), resolve1(xobj.get("Height"))
            if isinstance(ww, int) and isinstance(hh, int) and max(ww, hh) >= 2 and \
                    max(ww, hh) >= 5 * min(ww, hh) and max(box[2] - box[0], box[3] - box[1]) >= 20:
                strip = colour_strip(read_image(xobj))   # a colour bar (colourbar.py)
                if strip:
                    strip["ctm"] = self.ctm
                    self.page.record("colour_strips", strip)
            if min(box[2] - box[0], box[3] - box[1]) >= 30.0 and isinstance(ww, int) and \
                    isinstance(hh, int) and min(ww, hh) >= 4:
                # (a heat map drawn as a picture: read only if a graph's
                # plot is filled by it - colourbar.image_tiles)
                self.page.pictures.append({"box": box, "xobj": xobj, "ctm": self.ctm})
            if 1.0 <= max(box[2] - box[0], box[3] - box[1]) <= 30.0:
                # small enough to be a marker drawn as a picture (Excel for
                # Mac draws gradient-filled markers this way): image_marks.py
                self.page.record("image_marks", {"box": box, "xobj": xobj, "ctm": self.ctm,
                                                 "clip": self.extra.clip, "tool": self.tool})
            else:
                self.page.order += 1


def _crop_strip(strip, ctm, clip):
    """The placement (unit square -> page) of colour strip `strip`, placed
    by `ctm`, cut to clip box `clip`: across, to the clip's width; along,
    to the pixels whose centres the clip shows (the strip's rgb shortened
    to them).  Unchanged if the placement is not upright or there is no
    clip."""
    a, b, c, d, e, f = ctm
    if clip is None or abs(b) > 1e-9 or abs(c) > 1e-9 or a == 0 or d == 0:
        return ctm
    x0, x1 = sorted((e, e + a))
    y0, y1 = sorted((f, f + d))
    cx0, cy0, cx1, cy1 = max(x0, clip[0]), max(y0, clip[1]), min(x1, clip[2]), min(y1, clip[3])
    if cx1 <= cx0 or cy1 <= cy0:
        return ctm
    n = len(strip["rgb"])
    if strip["h"] >= strip["w"]:          # upright: pixel i's centre at v = 1 - (i + 0.5) / n
        keep = [i for i in range(n) if cy0 <= f + d * (1 - (i + 0.5) / n) <= cy1]
        if len(keep) < 2:
            return ctm
        i0, i1 = keep[0], keep[-1] + 1
        strip["rgb"] = strip["rgb"][i0:i1]
        strip["h"] = i1 - i0
        lo_v, hi_v = 1 - i1 / n, 1 - i0 / n
        return (cx1 - cx0, 0.0, 0.0, d * (hi_v - lo_v), cx0, f + d * lo_v)
    keep = [i for i in range(n) if cx0 <= e + a * ((i + 0.5) / n) <= cx1]
    if len(keep) < 2:
        return ctm
    i0, i1 = keep[0], keep[-1] + 1
    strip["rgb"] = strip["rgb"][i0:i1]
    strip["w"] = i1 - i0
    return (a * (i1 - i0) / n, 0.0, 0.0, cy1 - cy0, e + a * i0 / n, cy0)


_FORM_TOOLS = {}                          # id(XObject stream) -> tool name
_STYLES = {}                              # shared drawing-style tuples


def form_tool(xobj):
    """The program that made an embedded graphic, from the document
    information pdfTeX keeps (/PTEX.InfoDict) or its XMP metadata; "" if
    none is recorded."""
    key = id(xobj)
    if key not in _FORM_TOOLS:
        name = ""
        try:
            info = resolve1(xobj.get("PTEX.InfoDict"))
            if isinstance(info, dict):
                name = tool_name(resolve1(info.get("Creator")), resolve1(info.get("Producer")))
            if not name:
                meta = resolve1(xobj.get("Metadata"))
                if isinstance(meta, PDFStream):
                    name = tool_name("", "", xmp_creator_tool(meta.get_data()))
        except Exception:
            name = ""
        _FORM_TOOLS[key] = (xobj, name)          # (the stream keeps its id valid)
    return _FORM_TOOLS[key][1]


def _resolution(unit, m):
    """The page-space size of one unit of the last decimal of the numbers
    drawn with matrix m (None when unknown)."""
    if unit is None:
        return None
    return unit * math.sqrt(abs(m[0] * m[3] - m[1] * m[2]))


_HANDLERS = {}                            # (class, operator) -> (method, operand count)
_PATH_OPERANDS = {"m": 2, "l": 2, "c": 6, "v": 4, "y": 4}
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
    A segment after a close-path starts a new subpath at the current point.
    Subpaths without segments (a bare move-to, as Inkscape writes after
    every shape) draw nothing and are left out: kept, their zero-size box
    on a marker's edge looked like a hole and made the marker a letter."""
    subpaths, sub, cur = [], None, None
    ma, mb, mc, md, me, mf = ctm

    def P(x, y):
        # (the segments' coordinates are floats: pdfminer and
        # ContentInterpreter.execute only record parsed numbers)
        return (ma * x + mc * y + me, mb * x + md * y + mf)

    def new_sub(pt):
        s = {"start": pt, "segs": [], "closed": False}
        subpaths.append(s)
        return s

    for seg in curpath:
        op = seg[0]
        if op == "c":                         # the common case first
            if sub is None:
                sub = new_sub(cur or P(0.0, 0.0))
            _, x1, y1, x2, y2, x3, y3 = seg
            cur = (ma * x3 + mc * y3 + me, mb * x3 + md * y3 + mf)
            sub["segs"].append(("c", (ma * x1 + mc * y1 + me, mb * x1 + md * y1 + mf),
                                (ma * x2 + mc * y2 + me, mb * x2 + md * y2 + mf), cur))
            continue
        a = seg[1:]
        if op == "m":
            cur = P(a[0], a[1])
            sub = new_sub(cur)
        elif op == "l":
            if sub is None:
                sub = new_sub(cur or P(0.0, 0.0))
            cur = P(a[0], a[1])
            sub["segs"].append(("l", cur))
        elif op in ("v", "y"):
            if sub is None:
                sub = new_sub(cur or P(0.0, 0.0))
            if op == "v":                     # first control point = current point
                p1, p2, p3 = cur, P(a[0], a[1]), P(a[2], a[3])
            else:                             # y: second control point = end point
                p1, p2, p3 = P(a[0], a[1]), P(a[2], a[3]), P(a[2], a[3])
            sub["segs"].append(("c", p1, p2, p3))
            cur = p3
        elif op == "h" and sub is not None:
            sub["closed"] = True
            cur = sub["start"]
            sub = None
    return [sp for sp in subpaths if sp["segs"]]


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

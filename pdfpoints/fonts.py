"""Fonts, as far as needed to read text and place glyphs.

pdfminer.six decodes strings with the font's encoding or CMap (including
CID fonts) and knows the ToUnicode maps and the metrics of the standard 14
fonts.  Glyph names in an encoding's /Differences array are mapped to
Unicode with the Adobe Glyph List as implemented by fontTools.  Codes of
CID fonts that no map explains are looked up in the embedded font program
(GlyphProgram: its cmap tables and glyph names).  The ZapfDingbats marker
glyphs used by plotting programs are listed here.
"""

import io
import re

from fontTools.agl import toUnicode
from pdfminer.cmapdb import CMap, CMapDB, FileCMap
from pdfminer.fontmetrics import FONT_METRICS
from pdfminer.pdftypes import PDFStream, resolve1
from pdfminer.psparser import literal_name

# Symbol glyphs of the ZapfDingbats font that plotting programs use as
# markers (R's pdf() device draws every circle as character 108, "a71").
# code -> (shape, glyph bounding box in 1/1000 em from the Adobe AFM file).
#
# Where is the data point?  Plotting programs place every Dingbats marker so
# that the data point is at (0.396, 0.347) em from the glyph origin - the
# centre of the circle glyph a71 - whatever the glyph.  This was verified on
# a file with '+' (a27) markers whose underlying data are integers: with this
# anchor both circles and pluses land on integers to the same tiny residual,
# while the plus glyph's own bounding-box centre (0.380, 0.346) em is off by
# 0.016 em.  SETTINGS.glyph_centre = "bbox" (option --glyph-centre bbox) uses each
# glyph's bounding-box centre instead.
DINGBAT_ANCHOR = (0.396, 0.347)


DINGBAT_SYMBOLS = {
    59: ("plus", (35, 0, 725, 692)),          # a27 open centre cross (U+271B)
    # a71: the AFM says 705 for the top; R's pdf() device centres its circles
    # with 708 (centre at 0.396, 0.347 em), which is used here.
    108: ("circle", (35, -14, 757, 708)),     # a71 black circle
    110: ("square", (35, 0, 726, 691)),       # a73 black square
    115: ("triangle", (35, 0, 858, 705)),     # a76 black up-pointing triangle
    116: ("triangle", (35, -14, 858, 692)),   # a77 black down-pointing triangle
    117: ("diamond", (35, -14, 754, 705)),    # a78 black diamond
}




# ligature glyphs are spelt out (fontTools maps "fi" to U+FB01)
_LIGATURES = str.maketrans({"\ufb00": "ff", "\ufb01": "fi", "\ufb02": "fl",
                            "\ufb03": "ffi", "\ufb04": "ffl", "\ufb05": "st", "\ufb06": "st"})


_CMAP_SECTION = re.compile(rb"begin(cidrange|cidchar)(.*?)end\1", re.S)
_CMAP_HEX = rb"<([0-9A-Fa-f\s]*)>"
_CMAP_RANGE = re.compile(_CMAP_HEX + rb"\s*" + _CMAP_HEX + rb"\s*(\d+)")
_CMAP_CHAR = re.compile(_CMAP_HEX + rb"\s*(\d+)")


def _embedded_cmap(font, spec):
    """A Type 0 font whose /Encoding is an embedded CMap stream (PDFTron
    writes one-byte "Identity" CMaps this way): pdfminer looks CMaps up by
    name only and decodes such strings to nothing, so the codes -> CIDs of
    the stream's cidrange / cidchar sections (and a usecmap base) are read
    here."""
    cmap = getattr(font, "cmap", None)
    enc = resolve1(spec.get("Encoding"))
    if not isinstance(enc, PDFStream) or not isinstance(cmap, CMap) or cmap.code2cid:
        return
    try:
        data = enc.get_data()
    except Exception:
        return
    new = FileCMap()
    base = re.search(rb"/([^\s/<>\[\]()]+)\s+usecmap", data)
    if base:
        try:
            new.use_cmap(CMapDB.get_cmap(base.group(1).decode("latin-1")))
        except (CMapDB.CMapNotFound, AssertionError):
            pass
    unhex = lambda h: bytes.fromhex(re.sub(rb"\s", b"", h).decode("ascii"))
    for kind, body in _CMAP_SECTION.findall(data):
        try:
            if kind == b"cidchar":
                for code, cid in _CMAP_CHAR.findall(body):
                    new.add_code2cid(unhex(code).decode("latin-1"), int(cid))
                continue
            for lo, hi, cid in _CMAP_RANGE.findall(body):
                lo, hi = unhex(lo), unhex(hi)
                if len(lo) != len(hi) or not lo or lo[:-1] != hi[:-1]:
                    continue
                for k in range(hi[-1] - lo[-1] + 1):
                    code = lo[:-1] + bytes([lo[-1] + k])
                    new.add_code2cid(code.decode("latin-1"), int(cid) + k)
        except ValueError:
            continue
    if not new.code2cid:
        return
    if re.search(rb"/WMode\s+1\b", data):
        new.set_attr("WMode", 1)
    font.cmap = new
    font.vertical = new.is_vertical()


class FontInfo:
    """What the text reader needs of a font: character codes -> Unicode and
    glyph advance widths.  Wraps a pdfminer font and its font dictionary."""

    def __init__(self, font, spec):
        self.font = font
        spec = resolve1(spec) if spec else {}
        spec = spec if isinstance(spec, dict) else {}
        self.base = str(getattr(font, "basefont", "") or "")
        # the font's name without a subset prefix ("ABCDEF+DejaVuSans")
        name = self.base
        if not name:                      # Type 3 fonts (matplotlib): /BaseFont or /Name
            for key in ("BaseFont", "Name"):
                v = resolve1(spec.get(key))
                if v is not None:
                    name = getattr(v, "name", None) or str(v)
                    break
        self.name = name.split("+", 1)[1] if len(name) > 7 and name[6] == "+" else name
        self.dingbats = "dingbat" in self.base.lower()
        _embedded_cmap(font, spec)
        self.two_byte = font.is_multibyte()
        self.diffs = _differences(spec)
        # /Widths of a simple font (Type 3 widths are in glyph space)
        self.widths = {}
        if not self.two_byte:
            first = resolve1(spec.get("FirstChar")) or 0
            for k, w in enumerate(resolve1(spec.get("Widths")) or []):
                w = resolve1(w)
                if isinstance(w, (int, float)):
                    self.widths[first + k] = w
        self.scale = getattr(font, "hscale", 0.001) * 1000.0
        self.metrics = _standard_metrics(self.base) if not self.widths else None
        self._unicode_cache = {}
        self._spec = spec
        self._program = None              # GlyphProgram, read when first needed
        self.pairs = False                # two-byte strings read as one-byte (see decode)

    def decode(self, data):
        """[(character code, Unicode text)] for the bytes of a string.

        A two-byte (Type 0) font that was taken for a one-byte one (no
        /Subtype, an unreadable descendant) shows its strings as byte pairs
        00 19 00 13: those are read as two-byte codes when the font
        program knows what they are."""
        if not self.two_byte and len(data) >= 2 and len(data) % 2 == 0 and \
                not any(data[0::2]) and any(data[1::2]):
            prog = self.program()
            if prog is not None and prog.two_byte:
                self.pairs = True
                return [((hi << 8) | lo, self._pair_unicode((hi << 8) | lo))
                        for hi, lo in zip(data[0::2], data[1::2])]
        return [(cid, self.unicode(cid)) for cid in self.font.decode(data)]

    def program(self):
        """The embedded font program's glyph names and Unicode map, or None."""
        if self._program is None:
            self._program = GlyphProgram.load(self._spec) or False
        return self._program or None

    def _pair_unicode(self, code):
        key = ("pair", code)
        u = self._unicode_cache.get(key)
        if u is None:
            prog = self.program()
            u = self._unicode_cache[key] = _printable(prog.unicode(code) if prog else "")
        return u

    def unicode(self, cid):
        u = self._unicode_cache.get(cid)
        if u is None:
            u = self._unicode_cache[cid] = _printable(self._lookup(cid).translate(_LIGATURES))
        return u

    def _lookup(self, c):
        """Unicode for one character code: the ToUnicode map, then glyph
        names of /Differences (Adobe Glyph List), then fixes for TeX symbol
        fonts and dashes, then the font's base encoding."""
        umap = getattr(self.font, "unicode_map", None)
        if umap is not None:
            try:
                return umap.get_unichr(c)
            except KeyError:
                pass
        if c in self.diffs:
            u = toUnicode(self.diffs[c])
            if u and not _controls(u):
                return u
            # a name that is no character name: "uni00000013" spells glyph
            # number 0x13 (Type 3 copies of TrueType fonts), which the Adobe
            # Glyph List reads as U+0000 U+0013.  The code keeps its
            # standard meaning then (48 is "0").
            if 0x20 <= c < 0x7F:
                return chr(c)
            if not u:
                return "?"
        if "CMSY" in self.base.upper() and c in (0, 0xA1):
            return "-"                       # TeX's minus sign
        if c in (0x96, 0x97, 0xAD):
            return "-"                       # en dash, em dash, soft hyphen
        if not self.two_byte:
            u = getattr(self.font, "cid2unicode", {}).get(c)
            if u and not _controls(u):
                return u
        # no map to Unicode in the PDF: the font program's own (its cmap
        # table, or its glyph names: "zero", "uni0036")
        if self.two_byte:                    # (codes of one-byte fonts are no glyph ids)
            prog = self.program()
            if prog is not None:
                u = prog.unicode(c)
                if u:
                    return u
        return chr(c) if 0 <= c < 0x110000 else "?"

    def width(self, code, u):
        """Advance width of a glyph in 1/1000 em."""
        if self.two_byte:                    # CID fonts: /W and /DW (pdfminer)
            return self.font.char_width(code) * 1000.0
        if self.pairs:                       # byte pairs: the descendant's /W
            prog = self.program()
            return prog.width(code) if prog else 500.0
        w = self.widths.get(code)
        if w is not None:
            return float(w) * self.scale
        if self.metrics:                     # standard 14 font without /Widths
            w = self.metrics.get(u)
            if w is not None:
                return float(w)
        return float(_HELVETICA.get(u, 556))


def _controls(u):
    """Does the text hold control characters?"""
    return any(ord(ch) < 0x20 or 0x7F <= ord(ch) < 0xA0 for ch in u)


def _printable(u):
    """Text without control characters (codes no map explains come out as
    them: they are dropped, so that an unreadable label is no label)."""
    if u and _controls(u):
        return "".join(ch for ch in u if not (ord(ch) < 0x20 or 0x7F <= ord(ch) < 0xA0))
    return u


class GlyphProgram:
    """What an embedded font program says about its glyphs: character code
    -> glyph (through /CIDToGIDMap for CID fonts) -> Unicode, from the
    program's cmap table (reversed) or its glyph names (Adobe Glyph List).
    For PDFs that give no ToUnicode map and whose codes pdfminer cannot
    explain.  TrueType and OpenType (FontFile2, FontFile3/OpenType) and bare
    CFF (FontFile3/Type1C, CIDFontType0C) programs are read."""

    def __init__(self, gid_unicode, cid_to_gid, two_byte, widths, dw):
        self.gid_unicode = gid_unicode
        self.cid_to_gid = cid_to_gid       # None = identity
        self.two_byte = two_byte
        self.widths = widths
        self.dw = dw

    def unicode(self, code):
        gid = code if self.cid_to_gid is None else self.cid_to_gid.get(code)
        return self.gid_unicode.get(gid, "") if gid is not None else ""

    def width(self, code):
        return float(self.widths.get(code, self.dw))

    @staticmethod
    def load(spec):
        try:
            return GlyphProgram._load(spec)
        except Exception:                 # a broken font program: no help from it
            return None

    @staticmethod
    def _load(spec):
        spec = resolve1(spec) if spec else {}
        if not isinstance(spec, dict):
            return None
        two_byte = False
        desc_font = spec
        dfs = resolve1(spec.get("DescendantFonts"))
        if dfs:
            desc_font = resolve1(dfs[0]) or {}
            two_byte = True
        sub = literal_name(resolve1(desc_font.get("Subtype"))) if desc_font.get("Subtype") else ""
        if sub in ("CIDFontType0", "CIDFontType2"):
            two_byte = True
        fd = resolve1(desc_font.get("FontDescriptor")) or {}
        data = kind = None
        for key in ("FontFile2", "FontFile3", "FontFile"):
            st = resolve1(fd.get(key))
            if isinstance(st, PDFStream):
                data, kind = st.get_data(), key
                if key == "FontFile3":
                    kind = literal_name(resolve1(st.get("Subtype"))) if st.get("Subtype") else "Type1C"
                break
        if data is None or kind == "FontFile":    # (Type 1 programs: not read)
            return None
        gid_unicode = _program_unicode(data, kind)
        if not gid_unicode:
            return None
        # CID -> glyph
        cid_to_gid = None
        m = resolve1(desc_font.get("CIDToGIDMap"))
        if isinstance(m, PDFStream):
            raw = m.get_data()
            cid_to_gid = {k // 2: (raw[k] << 8) | raw[k + 1] for k in range(0, len(raw) - 1, 2)}
        widths, dw = {}, resolve1(desc_font.get("DW")) or 1000
        w = resolve1(desc_font.get("W")) or []
        k = 0
        while k < len(w):
            first = resolve1(w[k])
            nxt = resolve1(w[k + 1]) if k + 1 < len(w) else None
            if isinstance(nxt, list):
                for j, v in enumerate(nxt):
                    widths[first + j] = resolve1(v)
                k += 2
            elif k + 2 < len(w):
                for c in range(first, resolve1(nxt) + 1):
                    widths[c] = resolve1(w[k + 2])
                k += 3
            else:
                break
        return GlyphProgram(gid_unicode, cid_to_gid, two_byte, widths, dw)


def _program_unicode(data, kind):
    """{glyph id: Unicode text} of a font program."""
    out = {}
    names = []
    if kind in ("Type1C", "CIDFontType0C"):
        from fontTools.cffLib import CFFFontSet
        cff = CFFFontSet()
        cff.decompile(io.BytesIO(data), None)
        top = cff[cff.fontNames[0]]
        names = top.getGlyphOrder()
    else:
        from fontTools.ttLib import TTFont
        tt = TTFont(io.BytesIO(data), lazy=True)
        names = tt.getGlyphOrder()
        index = {n: g for g, n in enumerate(names)}
        if "cmap" in tt:
            for table in tt["cmap"].tables:
                if not table.isUnicode():
                    continue
                for cp, name in sorted(table.cmap.items(), reverse=True):
                    g = index.get(name)
                    if g is not None and 0x20 <= cp:
                        out[g] = chr(cp)       # (the smallest code point wins)
    for g, name in enumerate(names):
        if g not in out and name and not name.startswith((".", "glyph", "cid")):
            u = toUnicode(name.split(".")[0])  # "zero.numr" -> "0"
            if u and all(ord(ch) >= 0x20 for ch in u):
                out[g] = u
    return out


def _differences(spec):
    """{code: glyph name} from the /Differences of the font's encoding."""
    enc = resolve1(spec.get("Encoding"))
    out = {}
    if isinstance(enc, dict):
        code = 0
        for item in resolve1(enc.get("Differences")) or []:
            item = resolve1(item)
            if isinstance(item, int):
                code = item
            else:
                out[code] = literal_name(item) if not isinstance(item, str) else item
                code += 1
    return out


def _standard_metrics(base):
    """Glyph widths (by character) of a standard font that a PDF uses
    without a /Widths array, recognised also under the usual alias names
    (Arial, TimesNewRoman, ...); None if unknown."""
    name = base.split("+", 1)[-1]                 # drop subset prefix ABCDEF+
    n = name.replace(" ", "").replace(",", "-").lower()
    bold = "bold" in n
    ital = "italic" in n or "oblique" in n
    if n.startswith("courier"):
        fam = "Courier" + ("-BoldOblique" if bold and ital else "-Bold" if bold
                           else "-Oblique" if ital else "")
    elif n.startswith(("times", "timesnewroman")):
        fam = "Times-" + ("BoldItalic" if bold and ital else "Bold" if bold
                          else "Italic" if ital else "Roman")
    elif n.startswith(("helvetica", "arial")):
        fam = "Helvetica" + ("-BoldOblique" if bold and ital else "-Bold" if bold
                             else "-Oblique" if ital else "")
    else:
        return None
    return FONT_METRICS[fam][1]


_HELVETICA = FONT_METRICS["Helvetica"][1]

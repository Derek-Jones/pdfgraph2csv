"""Fonts, as far as needed to read text and place glyphs.

pdfminer.six decodes strings with the font's encoding or CMap (including
CID fonts) and knows the ToUnicode maps and the metrics of the standard 14
fonts.  Glyph names in an encoding's /Differences array are mapped to
Unicode with the Adobe Glyph List as implemented by fontTools.  The
ZapfDingbats marker glyphs used by plotting programs are listed here.
"""

from fontTools.agl import toUnicode
from pdfminer.fontmetrics import FONT_METRICS
from pdfminer.pdftypes import resolve1
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


class FontInfo:
    """What the text reader needs of a font: character codes -> Unicode and
    glyph advance widths.  Wraps a pdfminer font and its font dictionary."""

    def __init__(self, font, spec):
        self.font = font
        spec = resolve1(spec) if spec else {}
        spec = spec if isinstance(spec, dict) else {}
        self.base = str(getattr(font, "basefont", "") or "")
        self.dingbats = "dingbat" in self.base.lower()
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

    def decode(self, data):
        """[(character code, Unicode text)] for the bytes of a string."""
        return [(cid, self.unicode(cid)) for cid in self.font.decode(data)]

    def unicode(self, cid):
        u = self._unicode_cache.get(cid)
        if u is None:
            u = self._unicode_cache[cid] = self._lookup(cid).translate(_LIGATURES)
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
            return toUnicode(self.diffs[c]) or "?"
        if "CMSY" in self.base.upper() and c in (0, 0xA1):
            return "-"                       # TeX's minus sign
        if c in (0x96, 0x97, 0xAD):
            return "-"                       # en dash, em dash, soft hyphen
        if not self.two_byte:
            u = getattr(self.font, "cid2unicode", {}).get(c)
            if u:
                return u
        return chr(c) if 0 <= c < 0x110000 else "?"

    def width(self, code, u):
        """Advance width of a glyph in 1/1000 em."""
        if self.two_byte:                    # CID fonts: /W and /DW (pdfminer)
            return self.font.char_width(code) * 1000.0
        w = self.widths.get(code)
        if w is not None:
            return float(w) * self.scale
        if self.metrics:                     # standard 14 font without /Widths
            w = self.metrics.get(u)
            if w is not None:
                return float(w)
        return float(_HELVETICA.get(u, 556))


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

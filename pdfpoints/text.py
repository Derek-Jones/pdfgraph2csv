"""Text items: merging glyph runs into words/labels, parsing numeric labels
(including 10^n, percentages, '95-style years, month names and dates,
read with python-dateutil) and minus
signs that were drawn as separate dashes.
"""

import calendar
import datetime
import math
import re

from dateutil import parser as dateparser

from .geometry import straight_segments, subpath_bbox


_NUMTXT_RE = re.compile(r"^[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?$")

# a word of running text: three letters or more (shorter ones - "of",
# "a", unit symbols, variable names - turn up in labels and legends too)
WORD_RE = re.compile(r"[^\W\d_]{3,}")


# a number followed by a unit or scale suffix: byte sizes (SI kB, MB, ...
# and binary KiB, MiB, ...; the value is in bytes), thousands / millions
# ("10k", "2M": ggplot2's label_number(scale_cut)), factors ("1.5x");
# "B" with a decimal point is billions ("2.00B": no fraction of a byte)
_SUFFIX = {"b": 1.0, "kb": 1e3, "mb": 1e6, "gb": 1e9, "tb": 1e12, "pb": 1e15,
           "kib": 1024.0, "mib": 1024.0 ** 2, "gib": 1024.0 ** 3, "tib": 1024.0 ** 4,
           "k": 1e3, "m": 1e6, "x": 1.0, "\u00d7": 1.0}
_SUFFIX_RE = re.compile(r"([+-]?(?:\d+\.?\d*|\.\d+))(B|[kKMGTP]B|[KMGT]iB|k|K|M|x|\u00d7)")


# durations: a number and a unit of time, the value in seconds (a log time
# axis labelled 1 s, 15 s, 1 min, ... 64 h).  A bare "m" (minutes, months
# or metres) is not taken; units are lower case ("2D" is no duration)
_DAY = 86400.0
_DURATION = {"ns": 1e-9, "\u00b5s": 1e-6, "\u03bcs": 1e-6, "us": 1e-6, "ms": 1e-3,
             "s": 1.0, "sec": 1.0, "secs": 1.0, "second": 1.0, "seconds": 1.0,
             "min": 60.0, "mins": 60.0, "minute": 60.0, "minutes": 60.0,
             "h": 3600.0, "hr": 3600.0, "hrs": 3600.0, "hour": 3600.0, "hours": 3600.0,
             "d": _DAY, "day": _DAY, "days": _DAY,
             "w": 7 * _DAY, "wk": 7 * _DAY, "wks": 7 * _DAY, "week": 7 * _DAY, "weeks": 7 * _DAY,
             "mo": 365.25 / 12 * _DAY, "mos": 365.25 / 12 * _DAY, "month": 365.25 / 12 * _DAY,
             "months": 365.25 / 12 * _DAY,
             "y": 365.25 * _DAY, "yr": 365.25 * _DAY, "yrs": 365.25 * _DAY,
             "year": 365.25 * _DAY, "years": 365.25 * _DAY}
_DURATION_RE = re.compile(r"((?:\d+\.?\d*|\.\d+))\s*(%s)" % "|".join(
    sorted((re.escape(u) for u in _DURATION), key=len, reverse=True)))


# physical quantities with an SI prefix: power (300 mW, 1 W), frequency (500
# MHz, 5 GHz), lengths (22 nm, 0.18 um), voltage, current, energy,
# capacitance, resistance; the value is in the base unit, so that an axis
# labelled 300 mW, 1 W is one scale.  A metre needs its prefix (a bare "m"
# may be minutes, months or millions)
_SI_PREFIX = {"": 1.0, "p": 1e-12, "n": 1e-9, "u": 1e-6, "\u00b5": 1e-6, "\u03bc": 1e-6,
              "m": 1e-3, "k": 1e3, "K": 1e3, "M": 1e6, "G": 1e9, "T": 1e12}
_SI_RE = re.compile(r"([+-]?(?:\d+\.?\d*|\.\d+))\s*([pnu\u00b5\u03bcmkKMGT]?)(W|Hz|V|A|J|F|\u03a9|Ohm)"
                    r"|([+-]?(?:\d+\.?\d*|\.\d+))\s*([pnu\u00b5\u03bcmk])(m)")


def parse_quantity(s):
    """'300 mW' -> 0.3, '5 GHz' -> 5e9, '0.18 um' -> 1.8e-7; None if `s` is
    not a quantity with a (prefixed) SI unit."""
    m = _SI_RE.fullmatch(s.strip().replace("\u00a0", " "))
    if not m:
        return None
    num, pre = (m.group(1), m.group(2)) if m.group(1) is not None else (m.group(4), m.group(5))
    return float(num) * _SI_PREFIX[pre]


# the same units counted in working time, as charts of task lengths count
# them (METR's "1 day", "1 week", "1 month" of work): a day of 8 hours, a
# week of 5 such days, a month of 167 hours and a year of 2000 hours
_WORK = {"d": 8 * 3600.0, "w": 40 * 3600.0, "mo": 167 * 3600.0, "y": 2000 * 3600.0}
_WORK_UNIT = {u: k for k, units in (("d", ("d", "day", "days")), ("w", ("w", "wk", "wks", "week", "weeks")),
                                    ("mo", ("mo", "mos", "month", "months")),
                                    ("y", ("y", "yr", "yrs", "year", "years")))
              for u in units}


def duration_parts(s):
    """'15 min' -> (15.0, seconds in its unit, seconds in its unit counted
    in working time); None if `s` is not a duration."""
    m = _DURATION_RE.fullmatch(s.strip().replace("\u00a0", " "))
    if not m:
        return None
    unit = m.group(2)
    work = _WORK.get(_WORK_UNIT.get(unit), _DURATION[unit])
    return float(m.group(1)), _DURATION[unit], work


def parse_duration(s):
    """'1 s', '15 min', '64 h', '2 days', '1.5yr' -> seconds; None if `s` is
    not a duration."""
    m = _DURATION_RE.fullmatch(s.strip().replace("\u00a0", " "))
    return float(m.group(1)) * _DURATION[m.group(2)] if m else None


_GROUPED = re.compile(r"[+-]?[1-9]\d{0,2}(,\d{3})+")


def comma_kind(s):
    """How a number's comma reads: 'decimal' (one comma not followed by
    exactly three digits - "4,0", "0,9991", "1,E-01" - or one after a lone
    0: "0,250"; or a comma after the last dot: "1.234,5"), 'ambiguous' (one
    comma before three digits: "1,500"), 'thousands' (several groups of
    three, or a dot after the comma) or None (no comma)."""
    t = s.strip().replace("\u2212", "-").replace("\u00a0", "").replace(" ", "")
    t = t.replace("$", "").replace("%", "")
    if "," not in t:
        return None
    if "." in t:
        return "decimal" if t.rfind(",") > t.rfind(".") else "thousands"
    m = re.match(r"([+-]?\d*),(.*)$", t)
    if t.count(",") > 1 or not m:
        return "thousands"
    whole, rest = m.group(1), m.group(2)
    if whole.lstrip("+-") == "0" and rest[:1].isdigit():
        return "decimal"
    if _GROUPED.fullmatch(t) and t.count(",") == 1:
        return "ambiguous"
    if re.match(r"\d{3}(\D|$)", rest) and t.count(",") == 1 and not re.fullmatch(r"\d{3}", rest):
        return "thousands"                       # 1,500kB
    return "decimal"


_FLOAT_MAX_EXP = 300  # exponents beyond 10^300 are beyond the range of a float
_CENTURY_PIVOT = 50   # '50 to '99 are 1950 to 1999, '00 to '49 2000 to 2049


def parse_number(s, decimal_comma=False):
    """Numeric value of a label: plain numbers, 1,000 / $5 / 25%, 10^3 and
    2x10^3, unicode minus signs, sizes and scaled numbers (10kB, 1MB, 2KiB,
    10k, 1.5x: see _SUFFIX), durations (in seconds, see parse_duration),
    quantities with SI units (in the base unit, see parse_quantity),
    '95-style years and dates (as decimal years, see parse_date); None if
    not a number, or not one a float can hold (such as 10^602 in body
    text).  A comma is a decimal point where comma_kind says so, and in an
    ambiguous "1,500" when decimal_comma is set (the page writes decimal
    commas elsewhere): Korotayev_Doomsday_preprint-005's axis 4,0 ... 0,0
    read 40 ... 0."""
    kind = comma_kind(s) if "," in s else None
    if kind == "decimal" or (kind == "ambiguous" and decimal_comma):
        s = s.replace(".", "") if "." in s else s
        s = s.replace(",", ".")
    d = parse_duration(s)
    if d is not None:
        return d
    q = parse_quantity(s)
    if q is not None:
        return q
    # (a soft hyphen drawn as the minus: prob-book-171's "\u00ad5", printed
    # to PDF by Microsoft)
    t = (s.strip().replace("\u2212", "-").replace("\u2013", "-")
         .replace("\u2014", "-").replace("\u00ad", "-").replace("\u00a0", "").replace(" ", ""))
    t = t.replace(",", "").replace("$", "").replace("%", "")
    # (fractional exponents too: 2355585.2355594-006's "10^+0.2",
    # "10^-1.0")
    m = re.fullmatch(r"([+-]?[\d.]+)?[x\u00d7\*]?10\^([+-]?(?:\d+(?:\.\d*)?|\.\d+))", t)
    if m:  # 10^3  or 2x10^3
        exp = float(m.group(2))
        if abs(exp) > _FLOAT_MAX_EXP:                 # beyond the range of a float
            return None
        try:
            mant = float(m.group(1)) if m.group(1) else 1.0
        except ValueError:                 # e.g. "1.2.3"
            return None
        return mant * 10.0 ** exp
    if _NUMTXT_RE.match(t):
        v = float(t)
        return v if math.isfinite(v) else None
    m = _SUFFIX_RE.fullmatch(t)
    if m:  # 10kB, 1MB, 10k, 1.5x
        if m.group(2) == "B" and "." in m.group(1):
            # a fraction of a byte is no size: "2.00B", "18.0B" are billions
            # (d3's number format; 978-3-031-36060-2_2-006's y labels, with
            # "500M" on the same axis)
            return float(m.group(1)) * 1e9
        return float(m.group(1)) * _SUFFIX[m.group(2).lower()]
    m = SHORT_YEAR_RE.fullmatch(t)
    if m:  # '95 = 1995, '05 = 2005 (century checked per axis)
        yy = int(m.group(1))
        return float(1900 + yy if yy >= _CENTURY_PIVOT else 2000 + yy)
    return parse_date(s)


_DATES = dateparser.parserinfo()          # month names: Jan, January, Sept, ...
_FULL_MONTHS = [names[-1].lower() for names in _DATES.MONTHS]


_MONTH_MIN_LETTERS = 3  # a month name is 3 letters or more


def month_index(s):
    """'Jan', 'January', 'Sept', 'jan.', 'Janu' -> 0 ... 'Dec' -> 11 (None if
    not a month name).  Month names come from python-dateutil."""
    w = s.strip().rstrip(".")
    if not w.isalpha():
        return None
    m = _DATES.month(w)
    if m:
        return m - 1
    w = w.lower()                          # other abbreviations of 3+ letters
    if len(w) >= _MONTH_MIN_LETTERS:
        for i, full in enumerate(_FULL_MONTHS):
            if full.startswith(w):
                return i
    return None


# dates written out in full: 2010-03-15, Mar 2010, 15 March 2010, March 15, 2010
_MONTH_WORD = r"[A-Za-z]{3,9}\.?"
_DATE_RES = [re.compile(p) for p in (
    r"\d{4}-\d{1,2}-\d{1,2}",
    _MONTH_WORD + r"[\s\-]*\d{4}",
    r"\d{1,2}[\s\-]*" + _MONTH_WORD + r"[\s\-]*\d{4}",
    _MONTH_WORD + r"\s*\d{1,2},?\s*\d{4}")]
# Excel's "mmm-yy" style: Jan-10, Jan '10 (= January 2010)
_MONTH_YY_RE = re.compile(r"(" + _MONTH_WORD + r")[\s\-]*['\u2019]?(\d\d)")


def parse_date(s):
    """A date label as a decimal year: year + month/12 (months counted 0..11,
    as on month axes) + the fraction of the month; None if `s` is not a
    date.  Only unambiguous forms with a month name or a full ISO date are
    accepted (so ranges such as 2010-11 stay unparsed)."""
    s = s.strip()
    m = _MONTH_YY_RE.fullmatch(s)
    if m and month_index(m.group(1)) is not None:
        yy = int(m.group(2))
        return (1900 + yy if yy >= _CENTURY_PIVOT else 2000 + yy) + month_index(m.group(1)) / 12.0
    if not any(r.fullmatch(s) for r in _DATE_RES):
        return None
    try:
        d = dateparser.parse(s, default=datetime.datetime(2000, 1, 1))
    except (ValueError, OverflowError):
        return None
    days = calendar.monthrange(d.year, d.month)[1]
    return d.year + (d.month - 1 + (d.day - 1) / days) / 12.0


SHORT_YEAR_RE = re.compile("[\u0027\u2019\u2018\u2032`](\\d\\d)")


_SAME_SIZE_FRAC = 0.05  # texts of one size: within 5%
_SIGN_GAP_EMS = 0.3     # an exponent's sign within 0.3 of a font size


def _join_exponent_signs(texts):
    """A raised sign drawn on its own before the digits of an exponent (TeX
    sets the minus of "10^{-3}" from a symbol font: "10", "−", "3") is
    joined to the digits that follow it at its size and height, so that
    the exponent is read whole ("−3", then "10^−3")."""
    out = []
    k = 0
    while k < len(texts):
        t = texts[k]
        n = texts[k + 1] if k + 1 < len(texts) else None
        if n is not None and t["text"].strip() in ("-", "\u2212", "+") and \
                re.fullmatch(r"\s*\d+\s*", n["text"]) and \
                abs(t["size"] - n["size"]) < _SAME_SIZE_FRAC * max(t["size"], 1e-6) and \
                math.hypot(n["p0"][0] - t["p1"][0], n["p0"][1] - t["p1"][1]) < _SIGN_GAP_EMS * max(t["size"], 1e-6):
            j = dict(t)
            j["text"] = t["text"].strip() + n["text"].strip()
            j["p1"] = n["p1"]
            if "glyphs" in t and "glyphs" in n:
                j["glyphs"] = t["glyphs"] + n["glyphs"]
            out.append(j)
            k += 2
            continue
        out.append(t)
        k += 1
    return out


_ACROSS_EMS = 0.1       # texts on one baseline: within 0.1 of a font size across
_WORD_GAP_EMS = 0.15    # pieces of a word: within 0.15 of a font size
_SPACED_GAP_EMS = 0.45  # of a spaced word (or across a times sign): 0.45


def _forwards(t):
    """A piece whose glyphs are drawn last first (each glyph ends where the
    one drawn before it begins: InDesign's slanted and turned labels in
    Memory_systems_cacheDRAMdisk-051, "ety" for "yte") in reading order."""
    gl = t.get("glyphs")
    if not gl or len(gl) < 2 or len(gl) != len(t["text"].replace(" ", "")):
        return t
    s = max(t["size"], 1e-6)
    gaps = [k for k, c in enumerate(t["text"].replace("  ", " ")) if c == " "]
    k = 0
    for a, b in zip(gl, gl[1:]):
        k += 1
        ux, uy = a[2][0] - a[1][0], a[2][1] - a[1][1]
        n = math.hypot(ux, uy)
        if n < 1e-6 or math.hypot(b[2][0] - b[1][0], b[2][1] - b[1][1]) < 1e-6:
            return t
        gx, gy = a[1][0] - b[2][0], a[1][1] - b[2][1]
        along, across = (gx * ux + gy * uy) / n, abs(gx * uy - gy * ux) / n
        spaced = k in gaps
        if spaced:
            k += 1
        if across > _ACROSS_EMS * s or not (-_WORD_GAP_EMS * s < along < (_SPACED_GAP_EMS if spaced else _WORD_GAP_EMS) * s):
            return t
    t = dict(t)
    t["glyphs"] = gl[::-1]
    t["text"] = t["text"][::-1]
    t["p0"], t["p1"] = gl[-1][1], gl[0][2]
    return t


_SAME_DIRECTION = 0.99  # texts running the same way: cosine 0.99 or more
_UP_SAME_EMS = 0.01     # their up vectors equal within 0.01 of a font size


def _goes_before(t, o):
    """Piece t, drawn after o, ends where o begins on o's baseline (text set
    last letter first; Memory_systems_cacheDRAMdisk-051).  Returns the text
    to put between them ("" or a space for a word gap), or None."""
    s = max(o["size"], 1e-6)
    if abs(t["size"] - o["size"]) >= _SAME_SIZE_FRAC * s or not t["text"].strip() or \
            not o["text"].strip() or t["up"] != o["up"] and \
            math.hypot(t["up"][0] - o["up"][0], t["up"][1] - o["up"][1]) > _UP_SAME_EMS * s:
        return None
    dx, dy = o["p1"][0] - o["p0"][0], o["p1"][1] - o["p0"][1]
    tx, ty = t["p1"][0] - t["p0"][0], t["p1"][1] - t["p0"][1]
    n, m = math.hypot(dx, dy), math.hypot(tx, ty)
    if n < 1e-6 or m < 1e-6 or (dx * tx + dy * ty) / (n * m) < _SAME_DIRECTION:
        return None
    gx, gy = o["p0"][0] - t["p1"][0], o["p0"][1] - t["p1"][1]
    along = (gx * dx + gy * dy) / n
    across = abs(gx * dy - gy * dx) / n
    if across > _ACROSS_EMS * s:
        return None
    if abs(along) < _WORD_GAP_EMS * s:
        return ""
    if _WORD_GAP_EMS * s <= along < _SPACED_GAP_EMS * s and t["text"][-1:] != " " and o["text"][:1] != " ":
        return " "
    return None


_BYTE_UNIT = re.compile(r"\d\s*(?:[kKMGTP]i?B|bytes?)\b|\b(?:[kKMGTP]i?B|bytes?)\b")
_WHOLE_B = re.compile(r"[+-]?\d+B")


def billions_not_bytes(texts):
    """A whole number followed by "B" ("5B", "20B") is billions - as K is
    thousands and M millions (PsychologyToPhylogeny-AnalysisCultEvo-170:
    the user's rule) - unless the page names a byte unit somewhere ("KB",
    "MiB", "bytes": then "512B" is a size).  (A fraction of a byte is no
    size, so "2.00B" is billions anyway: parse_number.)  Sets the texts'
    values in place."""
    if any(_BYTE_UNIT.search(t["text"]) for t in texts):
        return
    for t in texts:
        s = t["text"].strip()
        if _WHOLE_B.fullmatch(s):
            t["value"] = float(s[:-1]) * 1e9


_REPEAT_EMS = 0.1  # a text drawn again within 0.1 of a font size is a repeat


def drop_repeated_texts(texts):
    """Copies of a text drawn again on (nearly) the same spot - same
    string, font, size and colour, its start within a tenth of its size -
    are one text (Mohamed_Rakha_PhD-072: each of ggplot's four quadrant
    labels drawn 25 776 times, once per data row, 0.01 - 0.04 pt apart;
    103 133 texts made the page take minutes).  Keeps the first."""
    kept, seen = [], {}
    for t in texts:
        s = max(t["size"], 1e-6)
        key = (t["text"], t.get("font"), round(s, 2), t.get("rgb"))
        x, y = t["p0"]
        cell = (round(x / s), round(y / s))
        near = seen.setdefault(key, {})
        if any(abs(x - qx) <= _REPEAT_EMS * s and abs(y - qy) <= _REPEAT_EMS * s
               for dx in (-1, 0, 1) for dy in (-1, 0, 1)
               for qx, qy in near.get((cell[0] + dx, cell[1] + dy), ())):
            continue
        near.setdefault(cell, []).append((x, y))
        kept.append(t)
    return kept


_SMALLCAP_LO = 0.6      # small capitals: 0.6 to 0.85 of the capitals' size
_SMALLCAP_HI = 0.85     # (the largest small capitals)
_SUPER_MAX = 0.9        # a superscript is under 0.9 of the base's size
_SUPER_RAISE_LO = 0.15  # raised by 0.15 to 0.8 of its size
_SUPER_RAISE_HI = 0.8   # (the highest raise)
_SUPER_GAP_EMS = 0.3    # within 0.3 of its size after the base
_UPRIGHT_DEG = 10       # text within 10 degrees of level is not rotated
_SUB_MAX = 0.8          # a subscript is under 0.8 of the base's size
_SUB_DROP_LO = 0.05     # lowered by 0.05 to 0.5 of the base's size
_SUB_DROP_HI = 0.5      # (the lowest drop)
_SUB_GAP_EMS = 0.15     # starting within 0.15 of the base's size after it


def _subscript_of(t, o):
    """Is t a subscript of o: a small number or letter or two, set just
    lowered right after o's last letter?"""
    if not (t["size"] < _SUB_MAX * o["size"]) or not o["text"].strip()[-1:].isalpha() or \
            o.get("rotated") or t.get("rotated"):
        return False
    if not re.fullmatch(r"\d{1,2}|[A-Za-z]{1,2}", t["text"]):
        return False
    u = math.hypot(*o["up"])
    if u < 1e-9:
        return False
    ux, uy = o["up"][0] / u, o["up"][1] / u
    gx, gy = t["p0"][0] - o["p1"][0], t["p0"][1] - o["p1"][1]
    drop = -(gx * ux + gy * uy)
    along = gx * uy - gy * ux
    return (_SUB_DROP_LO * o["size"] < drop < _SUB_DROP_HI * o["size"] and
            -_SUB_GAP_EMS * o["size"] < along < _SUB_GAP_EMS * o["size"])


def join_subscripts(words):
    """Words with the subscripts set right after them joined on ("N" and
    "2" -> "N2", "DT" and "3" -> "DT3": 2411.16433v1-066's category labels,
    whose subscripts were read as tick numbers 1, 2, 3), for reading
    category labels; a word ends with its subscript ("DT3" and "N3" set
    close are two labels).  Returns (the words, the ids of the subscripts
    joined)."""
    out, subs = [], set()
    for t in words:
        o = out[-1] if out else None
        if o is not None and not o.get("_sub") and _subscript_of(t, o):
            j = dict(o, text=o["text"].rstrip() + t["text"].strip(), p1=t["p1"], _sub=True, value=None)
            if "glyphs" in o and "glyphs" in t:
                j["glyphs"] = o["glyphs"] + t["glyphs"]
            b = o["bbox"]
            tb = t["bbox"]
            j["bbox"] = (min(b[0], tb[0]), min(b[1], tb[1]), max(b[2], tb[2]), max(b[3], tb[3]))
            j["center"] = ((j["bbox"][0] + j["bbox"][2]) / 2, (j["bbox"][1] + j["bbox"][3]) / 2)
            out[-1] = j
            subs.add(id(t))
            continue
        out.append(t)
    for k, t in enumerate(out):
        if t.get("_sub"):
            t = dict(t)
            del t["_sub"]
            out[k] = t
    return out, subs


def merge_texts(texts):
    """Join text pieces that continue each other on the same baseline."""
    out = []
    texts = [_forwards(t) for t in _join_exponent_signs(texts)]
    for t in texts:
        if out:
            o = out[-1]
            before = _goes_before(t, o)
            if before is not None:
                o = dict(o)
                o["text"] = t["text"] + before + o["text"]
                o["p0"] = t["p0"]
                if "glyphs" in o and "glyphs" in t:
                    o["glyphs"] = t["glyphs"] + o["glyphs"]
                out[-1] = o
                continue
            d = math.hypot(t["p0"][0] - o["p1"][0], t["p0"][1] - o["p1"][1])
            # mathtext spaces a multiplication sign: "3 × 10^1" (matplotlib's
            # log-axis labels)
            times = (t["text"].strip() == "\u00d7" and o["text"].strip()[-1:].isdigit()) or \
                (o["text"].strip().endswith("\u00d7") and t["text"].strip()[:1].isdigit())
            # (R's plotmath spaces ":" and "=" as operators too:
            # Seongmin-PhD-036's slanted "VSM(γ : 0.6)" labels, 1.2 pt gaps
            # at 6.6 pt)
            spaced = (t["text"].strip() in (":", "=") and o["text"].strip()[-1:].isalnum()) or \
                (o["text"].strip().endswith((":", "=")) and t["text"].strip()[:1].isalnum()) or \
                o["text"].rstrip().endswith(",")
            # (a comma and a word space go on: "M-Avg," and "ε=|Δ|" in two
            # fonts, 2020.01.30.927558.full-026's model names)
            gap = _SPACED_GAP_EMS if times or spaced else _WORD_GAP_EMS
            if (abs(t["size"] - o["size"]) < _SAME_SIZE_FRAC * max(t["size"], 1e-6) and
                    d < gap * max(t["size"], 1e-6) and t["text"].strip() and
                    o["text"].strip()):
                o = dict(o)
                # (a spaced operator keeps its space: "G = 0.9")
                if spaced and d >= _WORD_GAP_EMS * max(t["size"], 1e-6) and not o["text"].endswith(" ") \
                        and not t["text"].startswith(" "):
                    o["text"] += " "
                o["text"] += t["text"]
                o["p1"] = t["p1"]
                if "glyphs" in o and "glyphs" in t:
                    o["glyphs"] = o["glyphs"] + t["glyphs"]
                out[-1] = o
                continue
            # small capitals: "F" then a smaller "ULL" on the same baseline,
            # touching it (LaTeX \textsc: the word keeps the larger size)
            ts, os_ = t["text"].strip(), o["text"].strip()
            if (_SMALLCAP_LO * o["size"] <= t["size"] <= _SMALLCAP_HI * o["size"] and ts.isalpha() and
                    ts.isupper() and os_[-1:].isalpha() and os_[-1:].isupper() and
                    d < _WORD_GAP_EMS * o["size"] and not t["text"][:1].isspace()):
                o = dict(o)
                o["text"] += t["text"]
                o["p1"] = t["p1"]
                if "glyphs" in o and "glyphs" in t:
                    o["glyphs"] = o["glyphs"] + t["glyphs"]
                out[-1] = o
                continue
            # superscript exponent, e.g. "10" followed by a smaller raised "3"
            raise_ = ((t["p0"][0] - o["p1"][0]) * o["up"][0] +
                      (t["p0"][1] - o["p1"][1]) * o["up"][1]) / max(
                math.hypot(*o["up"]), 1e-9)
            along = math.hypot(t["p0"][0] - o["p1"][0] - (o["up"][0] * raise_ / max(math.hypot(*o["up"]), 1e-9)),
                               t["p0"][1] - o["p1"][1] - (o["up"][1] * raise_ / max(math.hypot(*o["up"]), 1e-9)))
            if (t["size"] < _SUPER_MAX * o["size"] and _SUPER_RAISE_LO * o["size"] < raise_ < _SUPER_RAISE_HI * o["size"]
                    and along < _SUPER_GAP_EMS * o["size"] and o["text"].strip().endswith("10")
                    and re.fullmatch(r"\s*[-\u2212+]?\d+\s*", t["text"])):
                o = dict(o)
                o["text"] = o["text"].strip() + "^" + t["text"].strip()
                # extend the label along its baseline to the exponent's end
                bx, by = o["p1"][0] - o["p0"][0], o["p1"][1] - o["p0"][1]
                bl = math.hypot(bx, by)
                if bl > 1e-9:
                    ux, uy = bx / bl, by / bl
                    d = (t["p1"][0] - o["p0"][0]) * ux + (t["p1"][1] - o["p0"][1]) * uy
                    if d > bl:
                        o["p1"] = (o["p0"][0] + ux * d, o["p0"][1] + uy * d)
                out[-1] = o
                continue
        out.append(dict(t))
    for t in out:
        p0, p1, up = t["p0"], t["p1"], t["up"]
        xs = [p0[0], p1[0], p0[0] + up[0], p1[0] + up[0]]
        ys = [p0[1], p1[1], p0[1] + up[1], p1[1] + up[1]]
        t["bbox"] = (min(xs), min(ys), max(xs), max(ys))
        t["center"] = ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2)
        ang = math.degrees(math.atan2(p1[1] - p0[1], p1[0] - p0[0])) if p1 != p0 else 0.0
        t["rotated"] = not (abs(ang) < _UPRIGHT_DEG or abs(abs(ang) - 180) < _UPRIGHT_DEG)
        t["angle"] = ang
        t["value"] = parse_number(t["text"])
        t["date"] = t["value"] is not None and parse_date(t["text"]) is not None
    # a page that writes decimal commas ("4,0", "0,5") writes "1,500" as 1.5
    # too: one convention to a document (one page at least)
    if any(t["value"] is not None and comma_kind(t["text"]) == "decimal" for t in out):
        for t in out:
            if comma_kind(t["text"]) == "ambiguous":
                t["value"] = parse_number(t["text"], decimal_comma=True)
    return out


def split_numbers(t):
    """A level text of two or more numbers set as one string with spaces
    ("12.8 25.6": Memory_systems_cacheDRAMdisk-051's last two category
    labels, close together) as one item per number, placed by its glyphs;
    any other text as itself.  Returns a list."""
    words = t["text"].split()
    gl = t.get("glyphs")
    if len(words) < 2 or t.get("rotated") or not gl or \
            any(parse_number(w) is None for w in words) or \
            len([g for g in gl if not g[0].isspace()]) != sum(len(w) for w in words):
        return [t]
    gl = [g for g in gl if not g[0].isspace()]
    out, k = [], 0
    up = t["up"]
    for w in words:
        part = gl[k:k + len(w)]
        k += len(w)
        p0, p1 = part[0][1], part[-1][2]
        xs = [p0[0], p1[0], p0[0] + up[0], p1[0] + up[0]]
        ys = [p0[1], p1[1], p0[1] + up[1], p1[1] + up[1]]
        u = dict(t, text=w, p0=p0, p1=p1, glyphs=part, value=parse_number(w),
                 bbox=(min(xs), min(ys), max(xs), max(ys)))
        u["center"] = ((u["bbox"][0] + u["bbox"][2]) / 2, (u["bbox"][1] + u["bbox"][3]) / 2)
        out.append(u)
    return out


def is_number(t):
    """A numeric label (a date such as "May 2020" may also be a title or a
    legend label)."""
    return t["value"] is not None and not t.get("date")


_RULE_AXIS_PT = 0.1       # an axis-aligned rule: ends within 0.1 pt across
_RULE_MIN_PT = 20         # rules 20 pt or more long
_CLIP_SLACK_PT = 0.5      # inside its clip within 0.5 pt
_MINUS_ASPECT = 2.5       # a minus is 2.5 times as long as thick
_MINUS_CELL_PT = 8.0      # minus candidates filed in cells of 8 pt
_MINUS_BEFORE_EMS = 0.5   # a minus ends within 0.5 of a font size before the number
_MINUS_OVERLAP_EMS = 0.1  # or overlaps it by 0.1
_MINUS_MAX_W = 0.9        # a minus is under 0.9 of a font size long
_MINUS_MAX_H = 0.2        # and under 0.2 thick
_MINUS_LO_EMS = 0.1       # its middle 0.1 to 0.55 of a font size above the baseline
_MINUS_HI_EMS = 0.55      # (the highest minus)
_ON_RULE_PT = 0.3         # a dash on a rule's end within 0.3 pt is the rule's
_RULE_ROW_PT = 0.1        # rows of dashes level within 0.1 pt
_DASH_ROW_GAP_PT = 8.0    # dashes of a row 2 to 8 pt apart
_DASH_ALIKE_PT = 0.05     # dashes alike within 0.05 pt


def attach_vector_minus(texts, paths):
    """Some generators (e.g. matplotlib with Type3 fonts) draw the minus sign
    of a tick label as a filled path instead of text.  Find a thin horizontal
    bar just left of a numeric label and make the label negative."""
    bars, uprights, axis_lines = [], set(), []
    for p in paths:
        clip = p.get("clip")
        for a, b in straight_segments(p):
            if abs(a[0] - b[0]) < _RULE_AXIS_PT and abs(a[1] - b[1]) >= _RULE_MIN_PT:
                ly0, ly1 = min(a[1], b[1]), max(a[1], b[1])
                if clip is not None:
                    # only the part in view: the error bars of 2401.16279-023's
                    # log bar chart run off the page (to y = -49419), clipped,
                    # past the minus sign of a "10^-1" in another graph
                    if not clip[0] - _CLIP_SLACK_PT <= a[0] <= clip[2] + _CLIP_SLACK_PT:
                        continue
                    ly0, ly1 = max(ly0, clip[1]), min(ly1, clip[3])
                    if ly1 - ly0 < _RULE_MIN_PT:
                        continue
                axis_lines.append((a[0], ly0, ly1))
        for sp in p["subpaths"]:
            x0, y0, x1, y1 = subpath_bbox(sp)
            w, h = x1 - x0, y1 - y0
            if w > 0 and w > _MINUS_ASPECT * h:
                bars.append((x0, y0, x1, y1))
            elif h > 0 and h > _MINUS_ASPECT * w:
                uprights.add((round((x0 + x1) / 2, 1), round((y0 + y1) / 2, 1)))
    # only dashes that could be a number's minus sign are looked at
    # further (2305.15675v1-015: 34 000 dashes, each compared with every
    # other and every axis line, took four minutes)
    nums = [t for t in texts
            if t["value"] is not None and not t["rotated"] and not t["text"].strip().startswith("-")]
    cell = _MINUS_CELL_PT
    near = {}
    for t in nums:
        s = t["size"] or 1.0
        for gx in range(int((t["bbox"][0] - _MINUS_BEFORE_EMS * s) // cell), int((t["bbox"][0] + _MINUS_OVERLAP_EMS * s) // cell) + 1):
            near.setdefault((gx, int(t["p0"][1] // cell)), []).append(t)
            near.setdefault((gx, int(t["p0"][1] // cell) + 1), []).append(t)

    def may_be_minus(b):
        x0, y0, x1, y1 = b
        for t in near.get((int(x1 // cell), int(((y0 + y1) / 2) // cell)), ()):
            s = t["size"] or 1.0
            if (x1 - x0) < _MINUS_MAX_W * s and (y1 - y0) < _MINUS_MAX_H * s and \
                    t["bbox"][0] - _MINUS_BEFORE_EMS * s <= x1 <= t["bbox"][0] + _MINUS_OVERLAP_EMS * s and \
                    t["p0"][1] + _MINUS_LO_EMS * s <= (y0 + y1) / 2 <= t["p0"][1] + _MINUS_HI_EMS * s:
                return True
        return False
    by_height = {}
    for b in bars:
        by_height.setdefault(round(b[1], 1), []).append(b)
    all_bars = bars
    bars = [b for b in bars if may_be_minus(b)]
    # the cross bar of a '+' marker is no minus sign
    bars = [b for b in bars
            if (round((b[0] + b[2]) / 2, 1), round((b[1] + b[3]) / 2, 1)) not in uprights]
    # nor is a tick mark touching a vertical axis or frame line
    bars = [b for b in bars
            if not any(min(abs(b[0] - lx), abs(b[2] - lx)) <= _ON_RULE_PT and ly0 - _CLIP_SLACK_PT <= b[1] <= ly1 + _CLIP_SLACK_PT
                       for lx, ly0, ly1 in axis_lines)]
    # nor a tick of a colour bar: ggplot marks each value on both edges of
    # the bar, two dashes of one length at one height (Maj-Petr_PhD-077's
    # "1e+06" read as "-1e+06")
    def twinned(b):
        return any(o is not b and abs(o[1] - b[1]) <= _DASH_ALIKE_PT and abs(o[3] - b[3]) <= _DASH_ALIKE_PT and
                   abs((o[2] - o[0]) - (b[2] - b[0])) <= _DASH_ALIKE_PT and
                   2.0 <= abs(o[0] - b[0]) <= _DASH_ROW_GAP_PT
                   for k in (round(b[1] - _RULE_ROW_PT, 1), round(b[1], 1), round(b[1] + _RULE_ROW_PT, 1))
                   for o in by_height.get(k, ()))
    bars = [b for b in bars if not twinned(b)]
    del all_bars
    for t in texts:
        if t["value"] is None or t["rotated"] or t["text"].strip().startswith("-"):
            continue
        s = t["size"] or 1.0
        bx0 = t["bbox"][0]
        base = t["p0"][1]
        for x0, y0, x1, y1 in bars:
            if (x1 - x0) < _MINUS_MAX_W * s and (y1 - y0) < _MINUS_MAX_H * s and \
                    bx0 - _MINUS_BEFORE_EMS * s <= x1 <= bx0 + _MINUS_OVERLAP_EMS * s and \
                    base + _MINUS_LO_EMS * s <= (y0 + y1) / 2 <= base + _MINUS_HI_EMS * s:
                t["value"] = -t["value"]
                t["text"] = "-" + t["text"]
                t["bbox"] = (x0, t["bbox"][1], t["bbox"][2], t["bbox"][3])
                t["center"] = ((x0 + t["bbox"][2]) / 2, t["center"][1])
                t["_minus_x0"] = x0
                break
    _join_vector_minus_exponents(texts)


_EXP_BASE_MAX = 0.9    # an exponent is under 0.9 of the base's size
_EXP_BEFORE_EMS = 0.1  # its minus starts from 0.1 of a font size before the base's end
_EXP_AFTER_EMS = 0.4   # to 0.4 after it


def _join_vector_minus_exponents(texts):
    """'10' and a smaller raised exponent whose minus sign is a drawn bar
    between them (attach_vector_minus made the exponent '-2') are one label,
    10^-2: matplotlib's mathtext draws the minus of 2401.16279-023's
    "10^{-2}" and "10^{-1}" as filled bars, and the gap the bar takes kept
    merge_texts from joining the exponent (both labels read 10).  The bar
    must start within 0.4 of the base's size after the base's end, the
    exponent be smaller than 0.9 of it and raised 0.15 to 0.8 of it above
    its baseline."""
    drop = set()
    for t in texts:
        x0 = t.pop("_minus_x0", None)
        if x0 is None or t["rotated"]:
            continue
        for o in texts:
            if o is t or id(o) in drop or o["rotated"] or o["value"] is None:
                continue
            s = o["size"] or 1.0
            if not o["text"].strip().endswith("10") or t["size"] >= _EXP_BASE_MAX * s:
                continue
            raise_ = t["p0"][1] - o["p0"][1]
            if (o["bbox"][2] - _EXP_BEFORE_EMS * s <= x0 <= o["bbox"][2] + _EXP_AFTER_EMS * s
                    and _SUPER_RAISE_LO * s < raise_ < _SUPER_RAISE_HI * s):
                o["text"] = o["text"].strip() + "^" + t["text"].strip()
                o["value"] = parse_number(o["text"])
                o["p1"] = (t["p1"][0], o["p1"][1])
                o["bbox"] = (o["bbox"][0], o["bbox"][1], max(o["bbox"][2], t["bbox"][2]), o["bbox"][3])
                o["center"] = ((o["bbox"][0] + o["bbox"][2]) / 2, o["center"][1])
                drop.add(id(t))
                break
    if drop:
        texts[:] = [t for t in texts if id(t) not in drop]

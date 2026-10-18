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

from .geometry import bbox_of


_NUMTXT_RE = re.compile(r"^[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?$")


def parse_number(s):
    """Numeric value of a label: plain numbers, 1,000 / $5 / 25%, 10^3 and
    2x10^3, unicode minus signs, '95-style years and dates (as decimal
    years, see parse_date); None if not a number, or not one a float can
    hold (such as 10^602 in body text)."""
    t = (s.strip().replace("\u2212", "-").replace("\u2013", "-")
         .replace("\u2014", "-").replace("\u00a0", "").replace(" ", ""))
    t = t.replace(",", "").replace("$", "").replace("%", "")
    m = re.fullmatch(r"([+-]?[\d.]+)?[x\u00d7\*]?10\^([+-]?\d+)", t)
    if m:  # 10^3  or 2x10^3
        exp = int(m.group(2))
        if abs(exp) > 300:                 # beyond the range of a float
            return None
        try:
            mant = float(m.group(1)) if m.group(1) else 1.0
        except ValueError:                 # e.g. "1.2.3"
            return None
        return mant * 10.0 ** exp
    if _NUMTXT_RE.match(t):
        v = float(t)
        return v if math.isfinite(v) else None
    m = SHORT_YEAR_RE.fullmatch(t)
    if m:  # '95 = 1995, '05 = 2005 (century checked per axis)
        yy = int(m.group(1))
        return float(1900 + yy if yy >= 50 else 2000 + yy)
    return parse_date(s)


_DATES = dateparser.parserinfo()          # month names: Jan, January, Sept, ...
_FULL_MONTHS = [names[-1].lower() for names in _DATES.MONTHS]


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
    if len(w) >= 3:
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
        return (1900 + yy if yy >= 50 else 2000 + yy) + month_index(m.group(1)) / 12.0
    if not any(r.fullmatch(s) for r in _DATE_RES):
        return None
    try:
        d = dateparser.parse(s, default=datetime.datetime(2000, 1, 1))
    except (ValueError, OverflowError):
        return None
    days = calendar.monthrange(d.year, d.month)[1]
    return d.year + (d.month - 1 + (d.day - 1) / days) / 12.0


SHORT_YEAR_RE = re.compile("[\u0027\u2019\u2018\u2032`](\\d\\d)")


def merge_texts(texts):
    """Join text pieces that continue each other on the same baseline."""
    out = []
    for t in texts:
        if out:
            o = out[-1]
            d = math.hypot(t["p0"][0] - o["p1"][0], t["p0"][1] - o["p1"][1])
            if (abs(t["size"] - o["size"]) < 0.05 * max(t["size"], 1e-6) and
                    d < 0.15 * max(t["size"], 1e-6) and t["text"].strip() and
                    o["text"].strip()):
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
            if (t["size"] < 0.9 * o["size"] and 0.15 * o["size"] < raise_ < 0.8 * o["size"]
                    and along < 0.3 * o["size"] and o["text"].strip().endswith("10")
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
        t["rotated"] = not (abs(ang) < 10 or abs(abs(ang) - 180) < 10)
        t["angle"] = ang
        t["value"] = parse_number(t["text"])
        t["date"] = t["value"] is not None and parse_date(t["text"]) is not None
    return out


def is_number(t):
    """A numeric label (a date such as "May 2020" may also be a title or a
    legend label)."""
    return t["value"] is not None and not t.get("date")


def attach_vector_minus(texts, paths):
    """Some generators (e.g. matplotlib with Type3 fonts) draw the minus sign
    of a tick label as a filled path instead of text.  Find a thin horizontal
    bar just left of a numeric label and make the label negative."""
    bars, uprights = [], set()
    for p in paths:
        for sp in p["subpaths"]:
            x0, y0, x1, y1 = bbox_of([sp["start"]] + [q for s in sp["segs"] for q in s[1:]])
            w, h = x1 - x0, y1 - y0
            if w > 0 and w > 2.5 * h:
                bars.append((x0, y0, x1, y1))
            elif h > 0 and h > 2.5 * w:
                uprights.add((round((x0 + x1) / 2, 1), round((y0 + y1) / 2, 1)))
    # the cross bar of a '+' marker is no minus sign
    bars = [b for b in bars
            if (round((b[0] + b[2]) / 2, 1), round((b[1] + b[3]) / 2, 1)) not in uprights]
    for t in texts:
        if t["value"] is None or t["rotated"] or t["text"].strip().startswith("-"):
            continue
        s = t["size"] or 1.0
        bx0 = t["bbox"][0]
        base = t["p0"][1]
        for x0, y0, x1, y1 in bars:
            if (x1 - x0) < 0.9 * s and (y1 - y0) < 0.2 * s and \
                    bx0 - 0.5 * s <= x1 <= bx0 + 0.1 * s and \
                    base + 0.1 * s <= (y0 + y1) / 2 <= base + 0.55 * s:
                t["value"] = -t["value"]
                t["text"] = "-" + t["text"]
                t["bbox"] = (x0, t["bbox"][1], t["bbox"][2], t["bbox"][3])
                t["center"] = ((x0 + t["bbox"][2]) / 2, t["center"][1])
                break

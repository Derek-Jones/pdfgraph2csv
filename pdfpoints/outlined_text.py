"""Reading text that was converted to filled glyph outlines.

Some PDF writers turn every character into a path.  Glyph contours are
grouped into glyphs (outer contour + holes) and words (neighbouring glyphs
of one colour); each glyph is rasterised to a 12x16 grid and compared with
built-in digit templates in each of the four reading directions.  Words
that cannot be read are returned as "blobs" (usable as category labels or
legend labels whose text is unknown).
"""

import bisect
import collections
import math
import re

from .context import PAGE
from .geometry import bbox_of, flatten_subpath, thin_rect_line, to_frame
from .grouping import BoxGrid, DisjointSets
from .occlusion import CoverIndex
from .symbols import classify_subpath
from .text import parse_number


_DIGIT_TEMPLATES = [  # (char, aspect w/h, 12x16 bitmap rows top->bottom as hex)
    # LiberationSans-Regular.ttf
    ("0", 0.684, "1f83fc70e606e07c03c03c03c03c03c03e0760670e3fc1f0"),
    ("1", 0.636, "0e03e0760460060060060060060060060060060060ffffff"),
    ("2", 0.656, "1f83fe606e0700700600600c0380700c0380700600ffffff"),
    ("3", 0.675, "1f83fc606e0600600600e0f80fc006007003e036077fe1f8"),
    ("4", 0.743, "01c03c03c06c0cc0cc18c30c30c60cc0cfff01c00c00c00c"),
    ("5", 0.684, "7fe7fe6006006006007fc79e006007003003c07e0e7fc1f8"),
    ("6", 0.656, "0f83fe706600600c00cfcf8ee07e07e03e036077063fc0f8"),
    ("7", 0.665, "ffffff00600e00c0180380300700600e00c00c00c01c01c0"),
    ("8", 0.665, "1f87be606e07e0760670e1f879e606c03c03c07e077fe1f8"),
    ("9", 0.656, "1f87fc60ee06c07c07c07e0770f3fb00700600660e7fc1f0"),
    # DejaVuSans.ttf
    ("0", 0.670, "0f83fc70e606e07e07c03c03c03c03e07e0760670e3fc0f8"),
    ("1", 0.603, "3f0ff0c700700700700700700700700700700700707fffff"),
    ("2", 0.628, "3f8ffcc0e00700700700600e01c0380e01c0380700ffffff"),
    ("3", 0.639, "7f87fc00e00700700601c1f801e00700700300780effc7f8"),
    ("4", 0.735, "03c03c07c0dc0dc19c31c31c61c41cffffff01c01c01c01c"),
    ("5", 0.637, "7fe7fc6006006007e07fc41e00700700700700780effc7f0"),
    ("6", 0.670, "0fc1fe380700600e00ffcf8ee07e07e03e036077063fc0f8"),
    ("7", 0.648, "ffffff00600e00c01c0180380380300700600e00c01c0180"),
    ("8", 0.665, "1f87fe606e07e0760630c1f879e606e07c03e07e067fe1f8"),
    ("9", 0.670, "1f03fc60ee06c07c07e07e0771f3ff00700600600c7f83f0"),
    # LiberationSerif-Regular.ttf
    ("0", 0.631, "1f830c606606e07e07e07e07e07e07e07e0760660630c1f8"),
    ("1", 0.535, "0601e0e60060060060060060060060060060060060060fff"),
    ("2", 0.608, "7f861c40e00700700600e00c0180300600c0300600ffffff"),
    ("3", 0.619, "7f841c40e00e00e00e01c1f001c006007007807806c0e7f8"),
    ("4", 0.716, "00c01c03c03c04c08c18c10c20c40cc1cfff01c00c00c00c"),
    ("5", 0.613, "7fc7fc40040040040040077c00e007007007807806c0c7f8"),
    ("6", 0.644, "0fe186302600600e00e30ffee06e07e0760760770638e0f8"),
    ("7", 0.628, "ffffff80280400c0080180100300600400c0080180300300"),
    ("8", 0.631, "1f830c60660660660630c1f870e606e07e07e07e0770e1f8"),
    ("9", 0.639, "1f870c606e06e07e07e076073ff0c700700600640c4187f0"),
    # LiberationMono-Regular.ttf
    ("0", 0.706, "1f83fc70e606e07c03c03c63c63c03c03e0760670e3fc1f8"),
    ("1", 0.732, "0700f03f0f70070070070070070070070070070070ffffff"),
    ("2", 0.687, "1f83fe70ee0700700600e01c0380700e0180300600ffffff"),
    ("3", 0.701, "1f83fe70660600600600c0f80fc006007003e036077fe1f8"),
    ("4", 0.758, "01c03c03c06c0cc08c18c30c60c60ce1cfff00c00c00c00c"),
    ("5", 0.711, "7fe7fe6006006006007fc71e007003003003e0760e7fc1f8"),
    ("6", 0.681, "0f83fc706604600c00dfcf8ee07e07e03e0360770e3fc0f8"),
    ("7", 0.677, "ffffff00600e00c0180380300700600e00c00c00c01c01c0"),
    ("8", 0.696, "1f87fc606e06e0660670c1f879e606c03c03e076067fe1f8"),
    ("9", 0.686, "1f83fc60ee06c07c07e07e0770f3fb0c700640660c7fc1f0"),
]


_TGW, _TGH = 12, 16


_NCELLS = _TGW * _TGH

# each template as one integer: cell i (row-major, top row first) is bit
# _NCELLS - 1 - i, so a glyph's agreement with it is a popcount of the XOR
_TEMPLATES = [(ch, asp, int(hx, 16)) for ch, asp, hx in _DIGIT_TEMPLATES]

# number of set bits (int.bit_count is Python 3.10+)
_popcount = int.bit_count if hasattr(int, "bit_count") else (lambda v: bin(v).count("1"))


def _raster(polys, box):
    """Even-odd fill of polygons inside box onto the template grid with 3x3
    supersampling; returns the cells as an integer (cell i, row-major from
    the top row, is bit _NCELLS - 1 - i; set when most samples are inside)."""
    x0, y0, x1, y1 = box
    w, h = max(x1 - x0, 1e-9), max(y1 - y0, 1e-9)
    edges = []
    for poly in polys:
        for a, b in zip(poly, poly[1:] + poly[:1]):
            if a[1] != b[1]:
                edges.append((a, b))
    S = 3
    cov = [0] * (_TGW * _TGH)
    for ry in range(_TGH * S):
        y = y1 - (ry + 0.5) * h / (_TGH * S)       # top row first
        xs = sorted(a[0] + (y - a[1]) * (b[0] - a[0]) / (b[1] - a[1])
                    for a, b in edges if (a[1] <= y < b[1]) or (b[1] <= y < a[1]))
        if not xs:
            continue
        row = (ry // S) * _TGW
        for rx in range(_TGW * S):
            # crossings left of the sample (strictly): inside when odd
            if bisect.bisect_left(xs, x0 + (rx + 0.5) * w / (_TGW * S)) % 2:
                cov[row + rx // S] += 1
    bits = 0
    half = S * S / 2
    for c in cov:
        bits = (bits << 1) | (1 if c > half else 0)
    return bits


def _read_glyph(polys, box, word_box):
    """Classify one glyph (polygons in reading orientation): returns
    (char, quality 0..1)."""
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    H = word_box[3] - word_box[1]
    if w <= 1e-9 or h <= 1e-9 or H <= 1e-9:
        return "?", 0.0
    if h < 0.4 * H:                                # small: '.' or '-'
        mid = (y0 + y1) / 2 - word_box[1]
        if w > 1.5 * h and mid > 0.25 * H:
            return "-", 1.0
        if mid < 0.3 * H and w < 2.0 * h:
            return ".", 1.0
        return "?", 0.0
    asp = w / h
    if asp < 0.45:                                 # only '1' is this narrow
        area = sum(abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(poly, poly[1:] + poly[:1])))
                   for poly in polys) / 2
        if area > 0.85 * w * h:
            return "?", 0.0                        # a solid bar (tick, error bar), not a '1'
        return "1", 0.95
    cells = _raster(polys, box)
    best = ("?", 0.0)
    for ch, tasp, bits in _TEMPLATES:
        agree = (_NCELLS - _popcount(cells ^ bits)) / float(_NCELLS)
        q = agree - 0.5 * abs(asp - tasp)
        if q > best[1]:
            best = (ch, q)
    return best


class _Dash(list):
    """A short thin shape (a polygon) that may be a minus sign; `idx` is
    the drawing step of its path."""

    def __init__(self, poly, idx):
        super().__init__(poly)
        self.idx = idx


def _exponent_minus(word, best, dashes):
    """'10^2' whose exponent's minus sign was drawn as a separate thin dash
    (between the 10 and the exponent, raised to the exponent's height) is
    10^-2.  Returns the (word, reading) pair, corrected if so."""
    rot, q, text, wb = best
    m = re.fullmatch(r"([\d.]*)\^(\d+)", text)
    if not m or q < 0.75:
        return word, best
    H = wb[3] - wb[1]
    boxes = [bbox_of([to_frame(p, rot) for poly in gl["polys"] for p in poly]) for gl in word]
    for d in dashes:
        db = bbox_of([to_frame(p, rot) for p in d])
        cx, cy = (db[0] + db[2]) / 2, (db[1] + db[3]) / 2
        if not (wb[0] < cx < wb[2] and wb[1] + 0.45 * H < cy < wb[3] and db[2] - db[0] < 0.6 * H):
            continue
        left = [b for b in boxes if b[2] <= cx]
        right = [b for b in boxes if b[0] >= cx]
        # the dash sits between the mantissa and the (smaller, raised) exponent
        if left and right and min(b[1] for b in right) > min(b[1] for b in left) + 0.2 * H:
            PAGE.minus_paths.add(d.idx)        # text, not a tick mark
            return word, (rot, q, "%s^-%s" % (m.group(1), m.group(2)), wb)
    return word, best


def _join_split_exponents(readings, read, dashes, page_rot):
    """'10' followed by a small raised number (a superscript whose minus
    sign was drawn as a separate thin dash) is one label 10^n."""
    out = list(readings)
    used = set()
    for i, (word, best) in enumerate(out):
        rot = page_rot if page_rot is not None else best[0]
        text, q, wb = read(word, rot)
        if q < 0.75 or not text.endswith("10") or "^" in text:
            continue
        H = wb[3] - wb[1]
        for j, (w2, _) in enumerate(out):
            if j == i or j in used:
                continue
            t2, q2, eb = read(w2, rot)
            if q2 < 0.75 or not re.fullmatch(r"\d+", t2):
                continue
            h2 = eb[3] - eb[1]
            if not (0.4 * H <= h2 <= 0.85 * H and wb[2] <= eb[0] <= wb[2] + 1.6 * H
                    and (eb[1] + eb[3]) / 2 > wb[1] + 0.6 * H):
                continue
            sign = ""
            for d in dashes:
                db = bbox_of([to_frame(p, rot) for p in d])
                if (wb[2] - 0.1 * H <= db[0] and db[2] <= eb[0] + 0.1 * H and
                        eb[1] - 0.2 * H <= (db[1] + db[3]) / 2 <= eb[3]):
                    sign = "-"
                    PAGE.minus_paths.add(d.idx)
            merged = word + w2
            out[i] = (merged, (rot, min(q, q2), text + "^" + sign + t2,
                               (wb[0], wb[1], eb[2], max(wb[3], eb[3]))))
            used.add(j)
            break
    return [r for k, r in enumerate(out) if k not in used]


def _strip_percent(fr):
    """A trailing '%' drawn as three separate shapes (two small rings and a
    slash): drop it from the glyph list [(polys, bbox)], sorted along the
    line.  Returns (glyphs, found)."""
    if len(fr) < 4:
        return fr, False
    hmax = max(b[3] - b[1] for _, b in fr)
    tail = fr[-3:]
    # (the rings' holes may be counted with the slash, whose box holds them)
    slash = [g for g in tail if g[1][3] - g[1][1] >= 0.8 * hmax]
    rings = [g for g in tail if 0.3 * hmax <= g[1][3] - g[1][1] <= 0.65 * hmax]
    if len(slash) != 1 or len(rings) != 2:
        return fr, False
    sb = slash[0][1]
    (_, r1), (_, r2) = sorted(rings, key=lambda g: g[1][0])
    c1 = ((r1[0] + r1[2]) / 2, (r1[1] + r1[3]) / 2)
    c2 = ((r2[0] + r2[2]) / 2, (r2[1] + r2[3]) / 2)
    # upper ring on the left, lower ring on the right, the slash between
    if c1[1] > c2[1] and sb[0] - 0.3 * hmax <= c1[0] <= sb[2] and \
            sb[0] <= c2[0] <= sb[2] + 0.3 * hmax:
        return fr[:-3], True
    return fr, False


def outlined_text(paths, blobs=None, covers=()):
    """Find words drawn as filled outlines and read the numeric ones.

    Returns (text items like those of the interpreter, set of
    (path idx, subpath no) that belong to text and are not markers).
    Unreadable words are appended to `blobs` (as text items without text),
    and outline parts hidden under a later opaque box (`covers`) are
    ignored."""
    parts, dashes, markerlike, stems = _glyph_parts(paths, covers)
    if not parts:
        return [], set()
    markerlike_keys = {(g[0], g[1]) for g in markerlike}
    words = _words_with_markerlike(_group_words(_group_glyphs(parts + markerlike)),
                                   markerlike_keys)

    def n_real(word):          # glyphs that are not marker-like ('.', 'o')
        return sum(1 for g in word if not set(g["members"]) <= markerlike_keys)
    cache = {}

    def read(word, rot):       # _read_word, each word and direction read once
        key = (tuple(id(g) for g in word), rot)
        got = cache.get(key)
        if got is None:
            got = cache[key] = _read_word(word, rot)
        return got
    readings = []
    for word in words:
        if len(word) > 12:          # far too long for a tick label
            readings.append((word, (0, 0.0, "", (0, 0, 0, 0))))
            continue
        # read the word in each of the four directions, keep the best
        best = None
        for rot in (0, 90, -90, 180):
            text, q, wb = read(word, rot)
            if best is None or q > best[1]:
                best = (rot, q, text, wb)
        readings.append((word, best))
    # short words (one or two glyphs) are ambiguous: use the reading
    # direction that the longer numeric words on the page agree on
    # (marker-like glyphs do not count towards the length: a full stop must
    # not let "0.5" vote where "05" would not)
    votes = collections.Counter(
        rot for word, (rot, q, text, wb) in readings
        if n_real(word) >= 3 and q >= 0.75 and parse_number(text) is not None)
    page_rot = max(votes, key=votes.get) if votes else None
    readings = [_exponent_minus(word, best, dashes) for word, best in readings]
    readings = _join_split_exponents(readings, read, dashes, page_rot)
    texts, used = [], set()
    used.update(_letter_dots(markerlike, stems, {m for word in words for g in word
                                                 for m in g["members"]}))
    for word, best in readings:
        for gl in word:
            used.update(gl["members"])
        if len(word) < 3 and page_rot is not None:
            # a short word is read in the page's direction - unless it reads
            # well as a number in its own direction and that direction is
            # not the page's turned upside down (6 / 9): R writes y labels
            # sideways and x labels upright on one plot
            own_rot, own_q, own_text, _ = best
            keep_own = (own_rot != page_rot and abs(own_rot - page_rot) != 180 and
                        own_q >= 0.75 and parse_number(own_text) is not None)
            if not keep_own:
                text, q, wb = read(word, page_rot)
                best = (page_rot, q, text, wb)
        rot, q, text, wb = best
        if q >= 0.75 and parse_number(text) is not None:
            texts.append(_text_item(word, rot, text, wb))
        elif blobs is not None:
            blobs.extend(_blob_items(word))
    return texts, used


def _words_with_markerlike(words, markerlike_keys):
    """Shapes that look like markers - an 'o' (a circle with a round hole),
    a full stop (a small square) - are characters only inside a word of
    real characters: no bigger than they are, not overlapping another
    glyph (characters of a word never overlap; a run of markers does), and
    within the line of the word's real characters.  A word of marker-like
    shapes alone is markers (stacked open circles, say), not text.
    "No bigger" allows a capital among small letters ('N' of "New")."""
    def size(g):
        return max(g["box"][2] - g["box"][0], g["box"][3] - g["box"][1])

    out = []
    for word in words:
        real = [g for g in word if not set(g["members"]) <= markerlike_keys]
        if not real:
            continue
        big = max(size(g) for g in real)
        rx0 = min(g["box"][0] for g in real)
        ry0 = min(g["box"][1] for g in real)
        rx1 = max(g["box"][2] for g in real)
        ry1 = max(g["box"][3] for g in real)
        slack = 0.5 * big                 # (capitals reach above small letters)
        horizontal = rx1 - rx0 >= ry1 - ry0       # the line the real glyphs form
        # real glyphs that make one letter ('i' and its dot) set no direction
        single = rx1 - rx0 < 1.5 * big and ry1 - ry0 < 1.5 * big
        keep = []
        overlaps_any = _overlap_test(word)
        real_ids = set(id(g) for g in real)
        for g in word:
            if id(g) in real_ids:
                keep.append(g)
                continue
            b = g["box"]
            in_line = (ry0 - slack <= b[1] and b[3] <= ry1 + slack) if horizontal or single \
                else False
            if not horizontal or single:
                in_line = in_line or (rx0 - slack <= b[0] and b[2] <= rx1 + slack)
            if size(g) <= 1.6 * big and in_line and not overlaps_any(g, word):
                keep.append(g)
        out.append(keep)
    return out


def _overlap_test(word):
    """overlaps_any(g, word): does glyph g overlap (by more than a tenth of
    the smaller box) another glyph of its word?  Big words (runs of
    overlapping marker fragments: thousands of shapes) use a grid."""
    def overlap(a, b):
        w = min(a[2], b[2]) - max(a[0], b[0])
        h = min(a[3], b[3]) - max(a[1], b[1])
        if w <= 0 or h <= 0:
            return False
        area = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))
        return w * h > 0.1 * max(area, 1e-12)

    if len(word) <= 64:
        return lambda g, _w: any(o is not g and overlap(g["box"], o["box"]) for o in word)
    sizes = sorted(max(o["box"][2] - o["box"][0], o["box"][3] - o["box"][1]) for o in word)
    grid = BoxGrid(max(sizes[len(sizes) // 2], 0.05))
    for k, o in enumerate(word):
        grid.add(k, o["box"])
    index = {id(o): k for k, o in enumerate(word)}

    def test(g, _w):
        me = index[id(g)]
        return any(k != me and overlap(g["box"], word[k]["box"]) for k in grid.near(g["box"]))
    return test


def _glyph_parts(paths, covers):
    """Contours of filled paths that may be characters:
    [(path idx, subpath no, polygon, bbox, rgb)], the short thin shapes
    that may be minus signs, and the contours of paths made only of
    marker-like shapes (letters such as 'o' and '.' look like markers;
    see _words_with_markerlike)."""
    cover_ix = CoverIndex(covers) if covers else None
    parts = []
    dashes = []            # short thin shapes: tick marks or minus signs
    markerlike = []        # contours of paths made only of marker shapes (or
                           # round letters): text only beside real letters
    stems = []             # thin straight bars: stems of 'i' and 'j' (boxes)
    # colours of marker circles: a single round shape of such a colour is a
    # marker (or its converted outline ring), never a character - characters
    # like 'o' or '0' come with a hole, i.e. two contours
    marker_rgb = set()
    for p in paths:
        if p["fill"] and len(p["subpaths"]) == 1:
            c = classify_subpath(p["subpaths"][0])
            if c and c["shape"] == "circle":
                marker_rgb.add(p["fill_rgb"])
    for p in paths:
        if not p["fill"] or p["stroke"]:
            continue
        subs = p["subpaths"]
        if len(subs) == 1 and p["fill_rgb"] in marker_rgb and _round_blob(subs[0]):
            # a marker disc - or a round letter ('c', 'o', '.') beside other
            # letters: decided by _words_with_markerlike (flattened only if
            # the page has characters at all: see the end)
            if subs[0]["segs"]:
                markerlike.append(("disc", p["idx"], subs[0], p["fill_rgb"]))
            continue
        info = []
        for k, sp in enumerate(subs):
            if sp["segs"]:
                poly = flatten_subpath(sp)
                info.append((k, poly, bbox_of(poly), sp))
        if not info:
            continue
        big = max(max(b[2] - b[0], b[3] - b[1]) for _, _, b, _ in info)
        if big > 30:                               # far larger than a glyph
            continue
        if all(classify_subpath(sp) is not None or thin_rect_line(sp) is not None
               for _, _, _, sp in info):
            if len(info) == 1 and thin_rect_line(info[0][3]) is not None:
                stems.append(info[0][2])
            if len(info) == 1 and thin_rect_line(info[0][3]) is not None and big < 6:
                dashes.append(_Dash(info[0][1], p["idx"]))  # maybe a minus sign
            elif all(classify_subpath(sp) is not None for _, _, _, sp in info):
                # markers - or letters that look like them ('o', '.'): text
                # only if they join a word of real characters
                markerlike.extend((p["idx"], k, poly, b, p["fill_rgb"]) for k, poly, b, _ in info)
            elif len(info) >= 2:
                # marker shapes and thin bars in one path: a letter such as
                # 'i', 'j', '!' (a dot and a stem)
                markerlike.extend((p["idx"], k, poly, b, p["fill_rgb"]) for k, poly, b, _ in info)
                stems.extend(b for _, _, b, sp in info if thin_rect_line(sp) is not None)
            continue                               # markers / lines only
        for k, poly, b, sp in info:
            if cover_ix is not None:
                hid = cover_ix.over((b[0] + b[2]) / 2, (b[1] + b[3]) / 2, p["idx"])
                if hid:                            # painted over: not visible
                    PAGE.hiding_paths.update(hid)
                    continue
            parts.append((p["idx"], k, poly, b, p["fill_rgb"]))
    if not parts:
        return parts, dashes, [], stems           # (outlined_text stops here)
    full = []
    for m in markerlike:
        if m[0] == "disc":
            _, idx, sp, rgb = m
            poly = flatten_subpath(sp)
            b = bbox_of(poly)
            if max(b[2] - b[0], b[3] - b[1]) <= 30:
                full.append((idx, 0, poly, b, rgb))
        else:
            full.append(m)
    markerlike = full
    if parts:
        # tall slender pieces (axis-break wiggles, brackets) are no digits
        # and would glue neighbouring labels into one unreadable word
        hs = sorted(g[3][3] - g[3][1] for g in parts)
        hmed = hs[len(hs) // 2]
        parts = [g for g in parts
                 if not (g[3][3] - g[3][1] > 1.8 * hmed and
                         g[3][3] - g[3][1] > 4 * (g[3][2] - g[3][0]))]
    return parts, dashes, markerlike, stems


def _letter_dots(markerlike, stems, in_words):
    """The dots of 'i' and 'j': a small marker-like shape (a tiny square or
    disc) just beyond one end of a thin bar, centred on it and smaller than
    it.  The bar is set aside as a possible minus sign or tick, so the dot
    finds no character to join; without this it would be reported as a
    marker.  Either end, so that turned text is covered too.  Returns the
    (path idx, subpath no) of the dots."""
    dots = set()
    if not stems:
        return dots
    for idx, k, poly, b, rgb in markerlike:
        if (idx, k) in in_words:
            continue
        w, h = b[2] - b[0], b[3] - b[1]
        sz = max(w, h)
        cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
        for s in stems:
            sw, sh = s[2] - s[0], s[3] - s[1]
            if sh >= sw:                         # vertical bar: dot above or below
                if sh < 1.5 * sz or abs(cx - (s[0] + s[2]) / 2) > 0.6 * sz:
                    continue
                gap = max(b[1] - s[3], s[1] - b[3])
            else:                                # horizontal bar: dot left or right
                if sw < 1.5 * sz or abs(cy - (s[1] + s[3]) / 2) > 0.6 * sz:
                    continue
                gap = max(b[0] - s[2], s[0] - b[2])
            if -0.2 * sz <= gap <= 1.5 * sz:
                dots.add((idx, k))
                break
    return dots


def _round_blob(sp):
    """A single round shape made of curves (a marker disc, not a glyph)."""
    pts = [sp["start"]] + [q for s in sp["segs"] for q in s[1:]]
    x0, y0, x1, y1 = bbox_of(pts)
    w, h = x1 - x0, y1 - y0
    return (w > 0 and h > 0 and min(w, h) / max(w, h) > 0.8 and
            sum(1 for s in sp["segs"] if s[0] == "c") >= 3)


def _group_glyphs(parts):
    """Glyphs = an outer contour plus the contours of the same path that lie
    inside it (holes such as the inside of '0').  Each glyph is a dict with
    its path, box, polygons, members (path idx, subpath no) and colour."""
    parts = sorted(parts, key=lambda g: -((g[3][2] - g[3][0]) * (g[3][3] - g[3][1])))
    glyphs = []
    by_path = {}
    for path_idx, k, poly, b, rgb in parts:
        for gl in by_path.get(path_idx, ()):
            ob = gl["box"]
            if (ob[0] <= b[0] + 1e-6 and ob[1] <= b[1] + 1e-6
                    and b[2] <= ob[2] + 1e-6 and b[3] <= ob[3] + 1e-6):
                gl["polys"].append(poly)
                gl["members"].append((path_idx, k))
                break
        else:
            gl = {"path": path_idx, "box": b, "polys": [poly],
                  "members": [(path_idx, k)], "rgb": rgb}
            glyphs.append(gl)
            by_path.setdefault(path_idx, []).append(gl)
    return glyphs


def _group_words(glyphs):
    """Words = glyphs of one colour closer to each other than 0.45 times
    the bigger glyph's size.

    Pages can hold 100 000+ shapes of very different sizes (clipped marker
    fragments of 0.1 pt beside 7 pt glyphs), so glyphs are filed by size
    class (powers of two), each class in a grid of cells as big as its
    biggest glyph.  Each glyph looks for partners in its own class and the
    bigger ones, within 0.45 times the biggest size of that class (a pair
    joins within reach of its bigger glyph): the cells of a bigger class are
    big, so a lookup touches only a few cells, and small glyphs are never
    scanned cell by cell from a big one.  Each pair is examined once."""
    n = len(glyphs)
    sets = DisjointSets(n)
    parent = sets.parent
    find = sets.find
    boxes = [g["box"] for g in glyphs]
    rgbs = [g["rgb"] for g in glyphs]
    size = [max(b[2] - b[0], b[3] - b[1], 1e-6) for b in boxes]
    klass = [int(math.floor(math.log2(s))) for s in size]
    grids = {}
    for i in range(n):
        k = klass[i]
        grid = grids.get(k)
        if grid is None:
            grid = grids[k] = BoxGrid(2.0 ** (k + 1))
        grid.add(i, boxes[i])
    order = sorted(grids)
    for i in range(n):
        bx0, by0, bx1, by1 = boxes[i]
        si, ki, rgb = size[i], klass[i], rgbs[i]
        for k in order:
            if k < ki:
                continue
            same = k == ki
            for j in grids[k].near(boxes[i], 0.45 * 2.0 ** (k + 1)):
                if (same and j <= i) or rgbs[j] != rgb:
                    continue                  # (a pair in one class: from its first glyph)
                cx0, cy0, cx1, cy1 = boxes[j]
                dx = cx0 - bx1 if cx0 > bx1 else (bx0 - cx1 if bx0 > cx1 else 0.0)
                dy = cy0 - by1 if cy0 > by1 else (by0 - cy1 if by0 > cy1 else 0.0)
                sj = size[j]
                lim = 0.45 * (si if si > sj else sj)
                if dx < lim and dy < lim and math.hypot(dx, dy) < lim:
                    ri, rj = find(i), find(j)
                    if ri != rj:
                        parent[rj] = ri
    return [[glyphs[i] for i in members] for members in sets.groups()]


def _read_word(word, rot):
    """Read a word in the frame turned by `rot` degrees.  Returns (text,
    quality 0..1, word box in that frame).  The quality is 0 when the glyphs
    do not form one line of text in that direction."""
    fr = []
    for gl in word:
        polys = [[to_frame(q, rot) for q in poly] for poly in gl["polys"]]
        fr.append((polys, bbox_of([q for poly in polys for q in poly])))
    fr.sort(key=lambda g: g[1][0])
    fr, pct = _strip_percent(fr)
    if not fr:
        return "", 0.0, (0, 0, 0, 0)

    def box_of(glyphs):
        return bbox_of([q for _, b in glyphs for q in ((b[0], b[1]), (b[2], b[3]))])

    wb = box_of(fr)
    # a trailing group of smaller, raised glyphs is an exponent (10^-1)
    hmax = max(b[3] - b[1] for _, b in fr)
    base = min(b[1] for _, b in fr if b[3] - b[1] >= 0.75 * hmax)
    n_main = len(fr)
    while n_main > 1:
        b = fr[n_main - 1][1]
        if b[3] - b[1] < 0.85 * hmax and (b[1] + b[3]) / 2 > base + 0.6 * hmax:
            n_main -= 1
        else:
            break
    split = n_main < len(fr) and any(fr[k][1][3] - fr[k][1][1] >= 0.4 * hmax
                                     for k in range(n_main, len(fr)))
    # the glyphs must form one line of text in this orientation: the
    # word is not much taller than its tallest glyph, and successive
    # glyphs do not overlap along the line (checked first: a word that is
    # no line here is not worth reading glyph by glyph)
    line_ok = (wb[3] - wb[1]) <= (1.6 if split else 1.25) * hmax and all(
        b2[0] - b1[2] > -0.3 * min(b1[2] - b1[0], b2[2] - b2[0])
        for (_, b1), (_, b2) in zip(fr, fr[1:]))
    if not line_ok:
        return "", 0.0, wb
    if split:
        main, expo = fr[:n_main], fr[n_main:]
        mb, eb = box_of(main), box_of(expo)
        chars = [_read_glyph(polys, b, mb) for polys, b in main]
        echars = [_read_glyph(polys, b, eb) for polys, b in expo]
        text = "".join(c for c, _ in chars) + "^" + "".join(c for c, _ in echars)
        chars = chars + echars
    else:
        chars = [_read_glyph(polys, b, wb) for polys, b in fr]
        text = "".join(c for c, _ in chars)
    qual = min(q for _, q in chars)
    if not any(c not in ".-" for c, _ in chars):
        line_ok = False                    # punctuation alone is no number
    if pct:
        text += "%"
    return text, qual if line_ok else 0.0, wb


def _text_item(word, rot, text, wb):
    """A text item (as made by the interpreter) for a word read in the
    frame turned by `rot`; its points are mapped back to the page."""
    inv = {0: 0, 90: -90, -90: 90, 180: 180}[rot]
    p0 = to_frame((wb[0], wb[1]), inv)
    p1 = to_frame((wb[2], wb[1]), inv)
    top = to_frame((wb[0], wb[3]), inv)
    return {"text": text, "p0": p0, "p1": p1,
            "up": (top[0] - p0[0], top[1] - p0[1]),
            "size": (wb[3] - wb[1]) / 0.7, "idx": min(gl["path"] for gl in word),
            "outlined": True}


def _blob_items(word):
    """Unreadable words as text items without text, usable as category
    labels and legend labels.  Slanted (or merged) words are offered letter
    by letter (flag 'glyph')."""
    gb = [gl["box"] for gl in word]
    hmed = sorted(b[3] - b[1] for b in gb)[len(gb) // 2]
    if hmed < 1.5:
        return []
    idx = min(gl["path"] for gl in word)
    ys = [(b[1] + b[3]) / 2 for b in gb]
    if max(ys) - min(ys) > 1.5 * hmed or len(word) > 60:
        return [{"text": None, "value": None, "rotated": True, "angle": 0.0,
                 "center": ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2),
                 "bbox": b, "centres": [((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)],
                 "size": hmed / 0.7, "idx": idx, "glyph": True}
                for b in gb if b[3] - b[1] >= 0.5 * hmed]
    return [{"text": None, "value": None, "rotated": True, "angle": 0.0,
             "center": (sum((b[0] + b[2]) / 2 for b in gb) / len(gb),
                        sum((b[1] + b[3]) / 2 for b in gb) / len(gb)),
             "bbox": (min(b[0] for b in gb), min(b[1] for b in gb),
                      max(b[2] for b in gb), max(b[3] for b in gb)),
             "centres": [((b[0] + b[2]) / 2, (b[1] + b[3]) / 2) for b in gb],
             "size": hmed / 0.7, "idx": idx}]

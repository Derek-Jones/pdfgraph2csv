"""Data labels: the short text set beside a data point ("55%", a name).

Charts often print a value or a name next to some points; the user asked
for these labels in a column of their own (`label`).  A line of text (the
text items on one baseline, joined where they are less than 0.6 of a font
size apart) is a point's data label when it
  * lies within (or up to one font size around) a graph's plot box;
  * is short: at most 4 words and 40 characters (longer text is a note or
    a title, and a piece of a longer line is a piece of a note);
  * is real text, at least 3 pt and 60% of the size of the axis labels
    (slivers of flattened markers can be read as the glyph '1'), and no
    more than 1.25 times their size (panel numbers and titles are bigger);
  * is none of the graph's axis labels, no legend entry's name (legends
    of line samples and swatches have no marker key to claim their text;
    text just right of a small filled box, level with it, is a swatch's)
    and not inside a bordered or filled note box (a bar is no note box: its
    value is often printed inside it);
  * holds no "=" or ":" (an equation - a trend line's "R² = 0.40", a
    parameter "λ = 0.1" of a legend entry - or a statistic "p: 0.03");
  * comes within 1.5 of its font size (0.8 for a number: values are set
    tight against their points) of a marker (a bar's top, a line's
    corner), and plainly belongs to that one: labels are set level with
    their point beside it, or centred above or below it, so each marker in
    reach is scored by its gap to the text plus how far it is off that
    alignment, and the best must score under 0.6 of the next (else the
    text, in the middle of a point cloud, is left out).
Text nearest a legend key is the key's name, not a data label.  A label
whose winner is the only labelled marker of its kind goes to another
marker within reach of a kind three or more labels belong to
(_consistent).  A line of several pieces with no plain winner (ids
printed inside touching markers run together) is split into its pieces,
each placed on the marker it lies on.  A line placed nowhere joins a label set directly above or
below it (_attach_leftovers).  Lines
of one point's label are joined, top first.
"""

import math
import re

from .context import PAGE
from .geometry import encloses, median, rect_area
from .grouping import BoxGrid
from .nongraphs import axis_labels
from .symbols import symbol_signature

MAX_WORDS, MAX_CHARS = 4, 40
_NUMERIC = re.compile(r"[\d\s.,%x×+\-\u2212()]+")


def _band(b, rect):
    """Whether box b shades a stretch of a plot box across its whole height
    or width (the grey bands of 2204.07073-010), rather than framing a
    note: it spans the box one way and less than half of it the other."""
    x0, y0, x1, y1 = rect
    tol = 0.02 * max(x1 - x0, y1 - y0) + 0.5
    # (the band may run on past the box: over the drawings above a panel)
    across = b[1] <= y0 + tol and b[3] >= y1 - tol and x0 - tol <= b[0] and b[2] <= x1 + tol \
        and b[2] - b[0] < 0.5 * (x1 - x0)
    along = b[0] <= x0 + tol and b[2] >= x1 - tol and y0 - tol <= b[1] and b[3] <= y1 + tol \
        and b[3] - b[1] < 0.5 * (y1 - y0)
    return across or along


def _in_bar(box, s):
    """Whether the centre of a text box lies within bar s (its column,
    between its base and its top)."""
    if s.get("shape") != "bar" or s.get("base") is None:
        return False
    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    if s.get("horizontal"):                # (across is y, along is x)
        lo, hi = sorted((s["base"], s["cx"]))
        return abs(cy - s["cy"]) <= s["size"] / 2 and lo <= cx <= hi
    lo, hi = sorted((s["base"], s["cy"]))
    return abs(cx - s["cx"]) <= s["size"] / 2 and lo <= cy <= hi


def _beyond_foot(box, s, em=0.0):
    """Is a text box no label of bar s: its centre beyond the bar's foot
    (2020.01.30.927558.full-023: bars hanging from 0, the asterisks and
    panel titles above the 0 line), or off the bar's column (across the
    bar, its centre more than half the bar's width and a quarter of a text
    size from the bar's middle: the asterisks beside bars of almost 0)?"""
    if s.get("shape") != "bar" or s.get("base") is None:
        return False
    k = 0 if s.get("horizontal") else 1
    c = (0.5 * (box[0] + box[2]), 0.5 * (box[1] + box[3]))
    across = s["cy"] if k == 0 else s["cx"]
    if abs(c[1 - k] - across) > 0.5 * s["size"] + 0.25 * em:
        return True
    end = s["cx"] if k == 0 else s["cy"]
    foot = s["base"]
    if abs(end - foot) < 1e-6:
        return False
    return c[k] > foot if end < foot else c[k] < foot


def _gap(box, s):
    """The distance between a box and a marker's box (0 if they touch)."""
    half = s["size"] / 2
    x0, y0, x1, y1 = box
    dx = max(x0 - (s["cx"] + half), (s["cx"] - half) - x1, 0.0)
    dy = max(y0 - (s["cy"] + half), (s["cy"] - half) - y1, 0.0)
    return (dx * dx + dy * dy) ** 0.5


def _score(box, s):
    """The gap between a text box and a marker plus the marker's distance
    from the nearer of the text's centre lines: a label beside its point
    is level with it, one above or below is centred on it, and a marker
    off at a diagonal is unlikely to be the text's."""
    x0, y0, x1, y1 = box
    off = min(abs((y0 + y1) / 2 - s["cy"]), abs((x0 + x1) / 2 - s["cx"]))
    return _gap(box, s) + off


def _consistent(got, symbols, unsure):
    """A chart labels the points of one series: a label won by the only
    labelled marker of its kind moves to the best other marker within reach
    of a kind that holds three or more other labels (a label set between a
    dot and a triangle of the labelled series at one x goes to the
    triangle); a label with no plain winner goes to the marker within
    reach of such a kind, if there is one or one plainly best."""
    kinds = {}
    for k in got:
        kinds[symbol_signature(symbols[k])] = kinds.get(symbol_signature(symbols[k]), 0) + len(got[k])
    for ln, rs in unsure:
        fits = [(sc, r) for sc, r in rs if kinds.get(symbol_signature(symbols[r]), 0) >= 3
                and r not in got]
        if len(fits) == 1 or (len(fits) > 1 and fits[0][0] < 0.6 * fits[1][0]):
            got[fits[0][1]] = [ln]
    for k in list(got):
        if kinds[symbol_signature(symbols[k])] != 1 or len(got[k]) != 1:
            continue
        ln = got[k][0]
        alt = [r for r in ln.get("close", ()) if kinds.get(symbol_signature(symbols[r]), 0) >= 3
               and r not in got]
        if alt:
            got[alt[0]] = got.pop(k)


def _after_swatch(ln, boxes):
    """Whether a line starts just right of a small filled box (a legend
    swatch: no more than twice the text's size each way), level with it."""
    em = ln["size"]
    cy = (ln["bbox"][1] + ln["bbox"][3]) / 2
    return any(b[2] - b[0] <= 2 * em and b[3] - b[1] <= 2 * em and
               0 <= ln["bbox"][0] - b[2] <= em and abs((b[1] + b[3]) / 2 - cy) <= 0.5 * em
               for b in boxes)


def _name_parts(names):
    """Legend names and their words (a name drawn as two texts, "λ =" and
    "0.1", leaves pieces that are no labels)."""
    out = set(names)
    for n in names:
        out.update(w for w in n.replace("=", " ").split() if len(w) >= 2)
    return out


_DECIMAL = re.compile(r"[+\-\u2212]?\d*\.\d+")


def _lines(texts, apart=frozenset()):
    """Horizontal text items joined into lines: [{"text", "bbox", "size"}].
    Turned text is kept item by item.  Items whose ids are in `apart` (axis
    labels) join only each other: 2308.04785-006's "0.26" stands 2.7 pt
    after the y label "EST" and was lost with it."""
    flat = sorted((t for t in texts if (t.get("text") or "").strip() and
                   t.get("up", (0, 1))[0] == 0),
                  key=lambda t: t["bbox"][0])
    out = []
    for t in flat:
        em = t.get("size") or 1.0
        # the line this item continues: overlapping it in height (so that
        # subscripts and superscripts join their line) and starting less
        # than 0.6 of the larger size after its end
        ln = None
        for o in reversed(out[-12:]):
            big = max(em, o["size"])
            lo, hi = max(o["bbox"][1], t["bbox"][1]), min(o["bbox"][3], t["bbox"][3])
            # (two decimal numbers side by side are two values:
            # Seongmin-PhD-036's crowded point labels "0.99" and "9.81",
            # 0.25 em apart; whole numbers still join - a row of day counts,
            # ids run together in touching markers)
            if hi - lo > 0 and \
                    -0.3 * big <= t["bbox"][0] - o["bbox"][2] <= 0.6 * big and \
                    (id(t) in apart) == (id(o["items"][-1]) in apart) and \
                    not (_DECIMAL.fullmatch(t["text"].strip()) and
                         _DECIMAL.fullmatch(o["items"][-1]["text"].strip())):
                ln = o
                break
        if ln is not None:
            ln["text"] += " " + t["text"].strip()
            ln["bbox"] = (ln["bbox"][0], min(ln["bbox"][1], t["bbox"][1]),
                          max(ln["bbox"][2], t["bbox"][2]), max(ln["bbox"][3], t["bbox"][3]))
            ln["items"].append(t)
            ln["size"] = max(ln["size"], em)
        else:
            out.append({"text": t["text"].strip(), "bbox": t["bbox"], "size": em,
                        "base": t["p0"][1], "items": [t]})
    out += [{"text": t["text"].strip(), "bbox": t["bbox"], "size": t.get("size") or 1.0,
             "items": [t]} for t in texts
            if (t.get("text") or "").strip() and t.get("up", (0, 1))[0] != 0]
    return out


def _stacked(a, b):
    """Whether line b is set directly under line a as one label with it
    ("FlashAttention," over "paged KV"): same size, left-aligned or centred
    on it, less than 0.6 of their size below it, and short enough together
    to be a label."""
    em = a["size"]
    text = a["text"] + " " + b["text"]
    return (abs(a["size"] - b["size"]) <= 0.05 * em and
            0 <= a["bbox"][1] - b["bbox"][3] < 0.6 * em and
            (abs(a["bbox"][0] - b["bbox"][0]) < 0.5 * em or
             abs((a["bbox"][0] + a["bbox"][2]) - (b["bbox"][0] + b["bbox"][2])) < em) and
            len(text) <= MAX_CHARS and len(text.split()) <= MAX_WORDS)


def _attach_leftovers(got, cands):
    """A candidate line with no marker in its reach joins the label
    line set directly above or below it (the second line of a two-line
    label is often too far from the point).  Each line is placed on its
    own first: two separate labels stacked one over the other ("pidigits
    (1.2MB)" over "flexclust (1MB)") belong to two points."""
    placed = {id(ln): k for k, lns in got.items() for ln in lns}
    for ln in cands:
        if id(ln) in placed or not ln.get("alone"):
            continue
        for k, lns in got.items():
            if any(_stacked(o, ln) or _stacked(ln, o) for o in lns) and \
                    len(" ".join(o["text"] for o in [*lns, ln]).split()) <= MAX_WORDS:
                lns.append(ln)
                placed[id(ln)] = k
                break

def _arrow_label(ln, symbols, marks, legend, got):
    """A label at the free end of an arrow (PAGE.arrows: symbols.
    drop_arrowheads) names the marker just beyond the arrow's tip - within
    8 pt (or three head sizes) of it and 30 degrees of its direction
    (1356058.1356080-007: "-O1" ... "-Os" pointing at the '+' markers of
    GCC's levels).  Sets got[k]; True if the line was so used."""
    arrows = getattr(PAGE, "arrows", None) or []
    x0, y0, x1, y1 = ln["bbox"]
    for tip, (ux, uy), end, size in arrows:
        gap = math.hypot(max(x0 - end[0], end[0] - x1, 0.0), max(y0 - end[1], end[1] - y1, 0.0))
        if gap > 1.0 * ln["size"]:
            continue
        best = None
        for k in marks:
            if k in legend:
                continue
            s = symbols[k]
            dx, dy = s["cx"] - tip[0], s["cy"] - tip[1]
            d = math.hypot(dx, dy)
            if d > max(8.0, 3 * size):
                continue
            if d > 0.5 * s["size"] and (dx * ux + dy * uy) / d < math.cos(math.radians(30)):
                continue
            if best is None or d < best[0]:
                best = (d, k)
        if best:
            got.setdefault(best[1], []).append(ln)
            return True
    return False


_VALUE = re.compile(r"^\s*([-\u2212]?\d+(?:\.(\d+))?)\s*%?\s*$")


def _stated_bar(ln, graphs, symbols, marks, grid):
    """The one bar within 1.5 of the text's size (gap) whose value, read on
    its graph's scale, is the number the text states (to its last decimal,
    or within 0.2% of the axis's range), when no other bar or marker in
    reach states it; else None."""
    m = _VALUE.match(ln["text"])
    if not m:
        return None
    num = float(m.group(1).replace("\u2212", "-"))
    tol0 = 0.5 * 10 ** -len(m.group(2) or "")
    from .graphs import graph_for_symbol
    from .scales import map_value
    reach = 1.5 * ln["size"]
    hits = []
    for k in grid.near(ln["bbox"], reach):
        s = symbols[k]
        if s["shape"] != "bar" or s.get("base") is None or _gap(ln["bbox"], s) > reach:
            continue
        _d, g = graph_for_symbol(graphs, s)
        ax = g["x"] if s.get("horizontal") else g["y"]
        mp = ax.get("map") or {}
        if mp.get("kind") not in ("linear", "log"):
            continue
        try:
            v = map_value(mp, s["cx"] if s.get("horizontal") else s["cy"])
        except (ValueError, ZeroDivisionError, OverflowError):
            continue
        rng = mp.get("range") or 0.0
        if abs(v - num) <= tol0 + 0.002 * rng:
            hits.append(k)
    return hits[0] if len(hits) == 1 else None


def add_data_labels(graphs, symbols, texts, legend, names, boxes, is_marker):
    """Set s["label"] on each symbol that has a data label.  `names` are
    the legend entries' names; `boxes` the note boxes (nongraphs.text_boxes);
    only symbols for which is_marker(s) holds take part (frames and boxes
    classified as big squares would otherwise lie nearest to every text)."""
    if not graphs or not symbols or not texts:
        return
    own = {id(t) for g in graphs for t in axis_labels(g)}
    names = _name_parts(names)
    tick = median((t["size"] for g in graphs for t in axis_labels(g)), 0.0)
    least = max(3.0, 0.6 * tick)
    most = 1.25 * tick if tick else float("inf")
    # note boxes: not bars (a bar's value is often printed inside it) and
    # not square markers (charts print a point's id inside its marker)
    bar_tops = [(s["cx"], s["cy"]) for s in symbols if s["shape"] == "bar" and not s.get("horizontal")]
    # (horizontal bars: their far ends - 2305.15675v1 page 7's segments)
    bar_ends = [(s["cx"], s["cy"]) for s in symbols if s["shape"] == "bar" and s.get("horizontal")]
    # (and heat-map tiles: a cell's value printed in it, 2308.04785-006)
    marker_boxes = [(s["cx"], s["cy"], s["size"]) for s in symbols
                    if s["shape"] in ("square", "tile") and is_marker(s)]
    small_boxes = [b for b in boxes if any(rect_area(b) < 0.5 * rect_area(g["rect"]) for g in graphs)
                   and not any(abs((b[0] + b[2]) / 2 - x) < 0.5 and
                               min(abs(b[3] - y), abs(b[1] - y)) < 0.5 for x, y in bar_tops)
                   and not any(abs((b[1] + b[3]) / 2 - y) < 0.5 and
                               min(abs(b[2] - x), abs(b[0] - x)) < 0.5 for x, y in bar_ends)
                   and not any(abs((b[0] + b[2]) / 2 - x) < 0.5 and abs((b[1] + b[3]) / 2 - y) < 0.5
                               and abs(max(b[2] - b[0], b[3] - b[1]) - sz) < 1.0
                               for x, y, sz in marker_boxes)
                   and not any(_band(b, g["rect"]) for g in graphs)]
    # (graphs' titles are no labels: 2020.01.30.927558.full-030's "E5",
    # inside the top of its panel over a bar)
    from .titles import find_title
    titles = {find_title(g["rect"], texts, symbols) for g in graphs} - {""}
    cands = []
    # (tiny items - specks of text 0.1 pt high - are dropped before lines
    # are made, so that they join nothing)
    lines = [ln for ln in _lines([t for t in texts if (t.get("size") or 0) >= least], own)
             if not _after_swatch(ln, boxes)]
    # labels at the free ends of arrows first: an arrow says which point
    # they name, even when the text is part of a legend name ("-O1" of
    # "GCC -O1,-O2,-O3, -Os") or bigger than tick labels (up to twice
    # their size: 8.7 pt over 5.9 pt there)
    got = {}                               # symbol index -> [lines]
    arrowed = set()
    marks0 = [k for k, s in enumerate(symbols) if is_marker(s)]
    for ln in lines:
        if least <= ln["size"] <= 2 * (most / 1.25) and len(ln["text"]) <= MAX_CHARS and \
                not any(id(t) in own for t in ln["items"]) and \
                _arrow_label(ln, symbols, marks0, legend, got):
            arrowed.add(id(ln))
    lines = [ln for ln in lines if id(ln) not in arrowed]
    for ln in lines:
        txt, em = ln["text"], ln["size"]
        if len(txt) > MAX_CHARS or len(txt.split()) > MAX_WORDS or not least <= em <= most:
            continue
        if any(id(t) in own for t in ln["items"]) or txt in names or "=" in txt or ":" in txt:
            continue
        if txt in titles:
            continue                       # a graph's title ("E5" over its bars)
        if any(encloses(b, ln["bbox"]) for b in small_boxes):
            continue
        cx, cy = (ln["bbox"][0] + ln["bbox"][2]) / 2, (ln["bbox"][1] + ln["bbox"][3]) / 2
        if any(g["rect"][0] - em <= cx <= g["rect"][2] + em and
               g["rect"][1] - em <= cy <= g["rect"][3] + em for g in graphs):
            cands.append(ln)
    marks = marks0
    if not marks:
        return
    if not cands:
        for k, lns in got.items():
            symbols[k]["label"] = " ".join(ln["text"] for ln in lns)
        return
    grid = BoxGrid(max(10.0, *(symbols[k]["size"] for k in marks)))
    for k in marks:
        s = symbols[k]
        h = s["size"] / 2
        grid.add(k, (s["cx"] - h, s["cy"] - h, s["cx"] + h, s["cy"] + h))
    unsure = []                            # (line, markers in reach) with no plain winner
    queue = [ln for ln in cands if id(ln) not in arrowed]
    while queue:
        ln = queue.pop(0)
        # each piece of the line centred on a marker of its own: values
        # printed in neighbouring cells (2308.04785-006's correlation
        # matrices: "0.40 0.31 0.56" across three squares) - split at once,
        # though one marker would win the whole line
        if not ln.get("piece") and len(ln["items"]) > 1:
            on = []
            for t in ln["items"]:
                tc = ((t["bbox"][0] + t["bbox"][2]) / 2, (t["bbox"][1] + t["bbox"][3]) / 2)
                hit = [k for k in grid.near((tc[0], tc[1], tc[0], tc[1]), 0.0)
                       if abs(symbols[k]["cx"] - tc[0]) <= symbols[k]["size"] / 2
                       and abs(symbols[k]["cy"] - tc[1]) <= symbols[k]["size"] / 2]
                on.append(min(hit, key=lambda k: math.hypot(symbols[k]["cx"] - tc[0],
                                                            symbols[k]["cy"] - tc[1])) if hit else None)
            if None not in on and len(set(on)) == len(on):
                queue[:0] = [{"text": t["text"].strip(), "bbox": t["bbox"], "size": ln["size"],
                              "items": [t], "piece": True} for t in ln["items"]]
                continue
        # (a value is set tight against its point; a name may stand off)
        reach = (0.8 if _NUMERIC.fullmatch(ln["text"]) else 1.5) * ln["size"]
        if ln.get("piece"):
            reach = 0.0                    # (a piece must lie on its marker)
        near = [k for k in grid.near(ln["bbox"], reach) if _gap(ln["bbox"], symbols[k]) <= reach]
        # (and a bar it is printed inside, however far its end: the long
        # segments of 2305.15675v1 page 7's horizontal stacked bars)
        if not ln.get("piece"):
            near += [k for k in marks if k not in near and _in_bar(ln["bbox"], symbols[k])]
        # a bar's value printed beside it, moved off its column clear of
        # its neighbours' labels (3832783.3834484-004: "14.31%" over the
        # gap between two bars, "2.88%" beyond reach of its own): the one
        # bar within 1.5 sizes whose value it states is its bar
        if not ln.get("piece"):
            k = _stated_bar(ln, graphs, symbols, marks, grid)
            if k is not None:
                if k not in legend:
                    got.setdefault(k, []).append(ln)
                continue
        if not near:
            ln["alone"] = True             # (may still be a second line: _attach_leftovers)
            continue
        # best score per spot (coincident markers - a point drawn twice,
        # a legend key on its sample - count as one spot)
        spots = {}
        for k in near:
            if _beyond_foot(ln["bbox"], symbols[k], ln["size"]):
                continue
            key = (round(symbols[k]["cx"], 1), round(symbols[k]["cy"], 1))
            if ln.get("piece"):
                # (an id printed in a marker is centred on it)
                b, m = ln["bbox"], symbols[k]
                sc = (math.hypot((b[0] + b[2]) / 2 - m["cx"], (b[1] + b[3]) / 2 - m["cy"]), k)
            else:
                sc = (_score(ln["bbox"], symbols[k]), k)
            if key not in spots or sc < spots[key]:
                spots[key] = sc
        ranked = sorted(spots.values())
        if not ranked:
            continue                       # (only bars it lies beyond the foot of)
        # a point marker within reach wins over bars: a chart of bars with
        # labelled points over them labels the points (Seongmin-PhD-036's
        # ratios 5.86 and 8.03, printed over bar tops beside their points)
        # (squares and rectangles may be short bars: VaskeBeaman2006-003)
        def point_mark(k):
            return symbols[k]["shape"] not in ("bar", "square", "rectangle", "tile")
        if any(point_mark(r[1]) and r[1] not in legend for r in ranked):
            ranked = [r for r in ranked if point_mark(r[1])]
        # a value printed inside a bar (a segment of a stacked bar) is that
        # bar's, whatever the neighbouring segments' tops
        inside = [r for r in ranked if _in_bar(ln["bbox"], symbols[r[1]])]
        if len(inside) == 1:
            ranked = inside
        if len(ranked) > 1 and ranked[0][0] >= 0.6 * ranked[1][0]:
            if len(ln["items"]) > 1:
                # ids printed in markers that touch run together into one
                # line ("4168 7640 1157"): each piece on its own marker
                queue[:0] = [{"text": t["text"].strip(), "bbox": t["bbox"], "size": ln["size"],
                              "items": [t], "piece": True} for t in ln["items"]]
                continue
            # (a lone value printed in a marker - an id in touching big
            # markers, 3368089.3409714-004 - is that marker's, nearest
            # centre first, as the pieces of a joined line are)
            b = ln["bbox"]
            tc = ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)
            on = [r for _, r in ranked if r not in legend and symbols[r]["shape"] != "bar" and
                  abs(symbols[r]["cx"] - tc[0]) <= symbols[r]["size"] / 2 and
                  abs(symbols[r]["cy"] - tc[1]) <= symbols[r]["size"] / 2]
            if len(ln["items"]) == 1 and on:
                k = min(on, key=lambda r: math.hypot(symbols[r]["cx"] - tc[0], symbols[r]["cy"] - tc[1]))
                got.setdefault(k, []).append(ln)
                continue
            unsure.append((ln, [(sc, r) for sc, r in ranked if r not in legend]))
            continue                       # no plain winner (yet)
        k = ranked[0][1]
        if k in legend:
            continue                       # a legend key's name
        got.setdefault(k, []).append(ln)
        # the other markers within reach, best first
        ln["close"] = [r for _, r in ranked[1:]]
    _consistent(got, symbols, unsure)
    _attach_leftovers(got, cands)
    for k, lns in got.items():
        lns.sort(key=lambda ln: (-ln["bbox"][3], ln["bbox"][0]))
        symbols[k]["label"] = " ".join(ln["text"] for ln in lns)

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
    lo, hi = sorted((s["base"], s["cy"]))
    return abs(cx - s["cx"]) <= s["size"] / 2 and lo <= cy <= hi


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
        if len(fits) == 1 or len(fits) > 1 and fits[0][0] < 0.6 * fits[1][0]:
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
            if hi - lo > 0 and \
                    -0.3 * big <= t["bbox"][0] - o["bbox"][2] <= 0.6 * big and \
                    (id(t) in apart) == (id(o["items"][-1]) in apart):
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
                    len(" ".join(o["text"] for o in lns + [ln]).split()) <= MAX_WORDS:
                lns.append(ln)
                placed[id(ln)] = k
                break

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
    bar_tops = [(s["cx"], s["cy"]) for s in symbols if s["shape"] == "bar"]
    marker_boxes = [(s["cx"], s["cy"], s["size"]) for s in symbols
                    if s["shape"] == "square" and is_marker(s)]
    small_boxes = [b for b in boxes if any(rect_area(b) < 0.5 * rect_area(g["rect"]) for g in graphs)
                   and not any(abs((b[0] + b[2]) / 2 - x) < 0.5 and
                               min(abs(b[3] - y), abs(b[1] - y)) < 0.5 for x, y in bar_tops)
                   and not any(abs((b[0] + b[2]) / 2 - x) < 0.5 and abs((b[1] + b[3]) / 2 - y) < 0.5
                               and abs(max(b[2] - b[0], b[3] - b[1]) - sz) < 1.0
                               for x, y, sz in marker_boxes)
                   and not any(_band(b, g["rect"]) for g in graphs)]
    cands = []
    # (tiny items - specks of text 0.1 pt high - are dropped before lines
    # are made, so that they join nothing)
    lines = [ln for ln in _lines([t for t in texts if (t.get("size") or 0) >= least], own)
             if not _after_swatch(ln, boxes)]
    for ln in lines:
        txt, em = ln["text"], ln["size"]
        if len(txt) > MAX_CHARS or len(txt.split()) > MAX_WORDS or not least <= em <= most:
            continue
        if any(id(t) in own for t in ln["items"]) or txt in names or "=" in txt or ":" in txt:
            continue
        if any(encloses(b, ln["bbox"]) for b in small_boxes):
            continue
        cx, cy = (ln["bbox"][0] + ln["bbox"][2]) / 2, (ln["bbox"][1] + ln["bbox"][3]) / 2
        if any(g["rect"][0] - em <= cx <= g["rect"][2] + em and
               g["rect"][1] - em <= cy <= g["rect"][3] + em for g in graphs):
            cands.append(ln)
    marks = [k for k, s in enumerate(symbols) if is_marker(s)]
    if not cands or not marks:
        return
    grid = BoxGrid(max(10.0, max(symbols[k]["size"] for k in marks)))
    for k in marks:
        s = symbols[k]
        h = s["size"] / 2
        grid.add(k, (s["cx"] - h, s["cy"] - h, s["cx"] + h, s["cy"] + h))
    got = {}                               # symbol index -> [lines]
    unsure = []                            # (line, markers in reach) with no plain winner
    queue = list(cands)
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
        if not near:
            ln["alone"] = True             # (may still be a second line: _attach_leftovers)
            continue
        # best score per spot (coincident markers - a point drawn twice,
        # a legend key on its sample - count as one spot)
        spots = {}
        for k in near:
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

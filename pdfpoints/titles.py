"""Graph titles and figure captions, for the -meta file.

A title is the text centred above a plot (with continuation lines), or for
want of one a sub-caption below it such as "(a) ..." or "Fig. 3 ...".  A
caption is the paragraph starting "Fig. N" / "Figure N" below the figure.
Titles also tell which way a graph is turned (graphs.graph_rotation).  Much
of the code here keeps other text from passing for a title: running
headers, axis titles of the graph above, legend headings, subscripts and
the later lines of another graph's caption.
"""

import re

from .context import PAGE
from .geometry import encloses
from .text import is_number


def find_title(rect, texts, symbols, with_size=False):
    title, size = _find_title(rect, texts, symbols)
    return (title, size) if with_size else title


def _continues_caption(t, texts, depth=12):
    """Is `t` a continuation line of a paragraph that starts with a figure
    caption ("Figure 3: ...") on the lines just above it?"""
    s = t["size"] or 1.0
    line = t
    for _ in range(depth):
        up = None
        for o in texts:
            if o is line or o["rotated"] or abs(o["size"] - s) > 0.1 * s or not o["text"].strip():
                continue
            gap = o["bbox"][1] - line["bbox"][3]
            if -0.1 * s <= gap <= 0.8 * s and o["bbox"][0] < line["bbox"][2] and \
                    line["bbox"][0] < o["bbox"][2]:
                if up is None or gap < up[0]:
                    up = (gap, o)
        if up is None:
            return False
        line = up[1]
        if _CAPTION_RE.match(line["text"].strip()) and \
                re.match(r"(?i)fig(ure|\.)", line["text"].strip()):
            return True
    return False


def _running_headers(texts):
    """Ids of the texts of a running header (footer): the topmost
    (bottommost) line of the page's text, spanning the text block from its
    left margin to its right one ("Copy-and-Patch ... for R" at the left,
    "VMIL '25, October ..., Singapore" at the right)."""
    flat = [t for t in texts if not t["rotated"] and t["text"].strip()]
    if len(flat) < 3:
        return set()
    tx0 = min(t["bbox"][0] for t in flat)
    tx1 = max(t["bbox"][2] for t in flat)
    width = tx1 - tx0
    if width <= 0:
        return set()
    out = set()
    for edge in (max(flat, key=lambda t: t["bbox"][3]), min(flat, key=lambda t: t["bbox"][1])):
        s = max(edge["size"], 1e-6)
        line = [t for t in flat if abs(t["p0"][1] - edge["p0"][1]) < 0.3 * s]
        if min(t["bbox"][0] for t in line) <= tx0 + 0.05 * width and \
                max(t["bbox"][2] for t in line) >= tx1 - 0.05 * width and \
                max(o["bbox"][0] - t["bbox"][2] for t in line for o in line) > 0.25 * width:
            out.update(id(t) for t in line)
    return out


def _find_title(rect, texts, symbols):
    """Text centred above a plot, alone on its line (so legend headings such
    as "Post-TOF  [key] FALSE [key] TRUE" are not mistaken for titles), and
    not a running header of the page."""
    x0, y0, x1, y1 = rect
    w, h = x1 - x0, y1 - y0
    best = None
    headers = _running_headers(texts)
    frame = PAGE.chart_frames.get(tuple(rect))
    for t in texts:
        txt = t["text"].strip()
        if not txt or is_number(t) or t["rotated"] or id(t) in headers:
            continue
        if frame and not encloses(frame, t["bbox"], 1):
            continue                  # outside the box drawn round the chart
        cx = (t["bbox"][0] + t["bbox"][2]) / 2
        def under(o, zb):
            # a line between the labels above and t (that graph's own axis
            # title: "# of duplicate files" over "Python",
            # Maj-Petr_PhD-077)
            return o is not t and o["text"].strip() and not o["rotated"] and \
                o["bbox"][0] < t["bbox"][2] and t["bbox"][0] < o["bbox"][2] and \
                t["bbox"][3] <= o["bbox"][1] + 0.1 and o["bbox"][3] <= zb + 0.1 * t["size"]
        # (text inside this graph's box is not the axis title of the
        # graph above: 2020.01.30.927558.full-030's "E5" ... "E8")
        if t["bbox"][1] >= rect[3] - 0.15 * t["size"] and any(zx0 <= cx <= zx1 and zx1 - zx0 > 0 and
               -0.2 * t["size"] <= zb - t["bbox"][3] <= 2.5 * t["size"] and
               zr != tuple(rect) and not any(under(o, zb) for o in texts)
               for zx0, zx1, zb, zr in PAGE.xlabel_zones):
            continue                  # the axis title of the graph above ("Hours")
            # (zones are told apart by their graph, not by their width: the
            # "x" under the upper of two same-width panels of ESEUR-intro
            # page 16 was the lower panel's title)
        if t["size"] < 0.85 * PAGE.label_size:
            continue            # sub/superscripts and small print are no titles
        if any(o["size"] > 1.15 * t["size"] and not o["rotated"] and
               0 <= t["bbox"][0] - o["bbox"][2] < 0.3 * o["size"] and
               abs(o["center"][1] - t["center"][1]) < 0.6 * o["size"] for o in texts):
            continue            # a subscript, e.g. the "DS" of "V_DS"
        bx0, by0, bx1, by1 = t["bbox"]
        gap = by0 - y1
        # centred over the plot, or starting at its left edge (within a
        # tenth of its width: VaskeBeaman2006-Lessonslearned-003's
        # left-aligned "Figure 1e. ..." titles), and not past its right edge
        # (a figure label only: "(GB/s = ...)" set at the left of
        # Memory_systems_cacheDRAMdisk-051's PERL chart is a note)
        left = abs(bx0 - x0) <= 0.1 * w and bx1 <= x1 + 0.1 * w and bool(_FIGURE_RE.match(txt))
        # (a title's box may dip into the plot by its descent: the line
        # ends of 2020.01.30.927558.full-023's y axes reach 1.2 pt into
        # "IIAB")
        # (or by up to 1.2 text sizes when nothing plotted under it reaches
        # up to it: 2020.01.30.927558.full-030's "E1" ... "E8" inside the
        # top of their panels, over the bars)
        # (centred within 5% of the width: ThomasBockPhD-073's note
        # "Goodness of fit: ..." in the plot's top, 6% off, is no title)
        inside_top = -1.2 * t["size"] <= gap < -0.15 * t["size"] and \
            abs(t["center"][0] - (x0 + x1) / 2) <= 0.05 * w and not any(
            bx0 - 0.5 * sy["size"] <= sy["cx"] <= bx1 + 0.5 * sy["size"] and
            y0 <= sy["cy"] <= y1 and sy["cy"] >= by0 for sy in symbols)
        if not (-0.15 * t["size"] <= gap <= min(0.35 * h, 4 * t["size"]) or inside_top) or \
                (abs(t["center"][0] - (x0 + x1) / 2) > 0.15 * w and not left):
            continue
        # (unless it stands within a font size of this graph and at least
        # four times as far from the one above: VaskeBeaman2006-Lessons-
        # learned-003's "Figure 1c. Number of Anglers ..." titles, 2 pt over
        # their graphs and 25 pt under those above)
        if _CAPTION_RE.match(txt) and any(
                r != rect and r[1] >= by1 and r[1] - by1 < 0.5 * (r[3] - r[1]) and
                not (gap <= t["size"] and 4 * gap <= r[1] - by1) and
                min(r[2], x1) - max(r[0], x0) > 0 for r in PAGE.graph_rects):
            continue            # sub-captions go below: this is the graph above's
        if _continues_caption(t, texts):
            continue            # a later line of the caption of a graph above
        s = t["size"] or 1.0
        def over_other_graph(o):
            return any(r != rect and abs(o["center"][0] - (r[0] + r[2]) / 2) < 0.15 * (r[2] - r[0])
                       and 0 <= o["bbox"][1] - r[3] <= 4 * o["size"] for r in PAGE.graph_rects)
        # legend headings share their line with legend keys (drawn right
        # next to the text) and key labels; titles stand alone
        # (a neighbour less than half a size off is the next word of the
        # title: Word sets "Individual" and "results" apart,
        # 2020.01.30.927558.full-048)
        crowded = any(
            o is not t and o["size"] >= 0.85 * s and abs(o["p0"][1] - t["p0"][1]) < 0.5 * s and
            0.5 * s <= max(o["bbox"][0] - bx1, bx0 - o["bbox"][2]) < 3 * s and not over_other_graph(o)
            for o in texts) or any(
            abs(sy["cy"] - t["center"][1]) < s and abs(sy["idx"] - t["idx"]) <= 100 and
            0 <= max(sy["cx"] - bx1, bx0 - sy["cx"]) < 3 * s and sy["shape"] != "bar"
            for sy in symbols)       # (a bar's top beside a title inside the plot is no key: -030's E5)
        if crowded:
            continue
        # (words over the next panel are not on its line: histogram's
        # "(s: 107.1 p: 0.00)" ends just before "f4")
        # (but a word that follows others, a word space apart, on a line
        # opening a sub-caption is part of that caption: broken-axes's
        # "a) LLVM", ThomasBockPhD-073's "(a) QEMU (message-based, ...)",
        # under the graphs above)
        line, head = [t], t
        while True:
            prev = [o for o in texts if o not in line and abs(o["p0"][1] - t["p0"][1]) < 0.5 * s and
                    0 <= head["bbox"][0] - o["bbox"][2] < 0.5 * s and o["bbox"][0] >= x0 - 0.1 * w]
            if not prev:
                break
            head = max(prev, key=lambda o: o["bbox"][2])
            line.append(head)
        lead = " ".join(o["text"].strip() for o in reversed(line[1:]))
        if lead and _CAPTION_RE.match(lead + " " + txt):
            continue
        key = (-round(s, 1), gap)          # biggest font first, then closest
        if best is None or key < best[0]:
            best = (key, txt, s, t, lead)
    if best:
        # a title may continue on further lines just below the first one
        title, s = best[1], best[2]
        line = best[3]
        # (the words before it on its line, a word space apart, open the
        # title: ThomasBockPhD-073's "QEMU" before "(message-based, ...)")
        lead = best[4]
        # subscripts / superscripts directly after the text (e.g. "f" + "4";
        # one starting exactly at the text's end may lie a rounding error
        # before it: ArianeWuerbach-Phd-219's "rho" + "11" in a turned frame)
        for o in sorted(texts, key=lambda o: o["bbox"][0]):
            if o is not line and o["size"] < 0.85 * s and \
                    -0.05 * s <= o["bbox"][0] - line["bbox"][2] < 0.3 * s and \
                    abs(o["center"][1] - line["center"][1]) < 0.6 * s:
                title += o["text"].strip()
        title += _rest_of_line(line, texts, s)
        if lead:
            title = lead + " " + title
        # ... or start on a line just above it ("Vth" over "(s: 6.9 p: 0.03)")
        top = best[3]
        for _ in range(3):
            prv = None
            for t in texts:
                if t is top or t["rotated"] or abs(t["size"] - s) > 0.05 * s or \
                        not t["text"].strip() or is_number(t):
                    continue
                gap = t["bbox"][1] - top["bbox"][3]
                if 0 <= gap <= 0.8 * s and abs(t["center"][0] - (x0 + x1) / 2) <= 0.15 * w and \
                        not _CAPTION_RE.match(t["text"].strip()):
                    if prv is None or gap < prv[0]:
                        prv = (gap, t)
            if prv is None:
                break
            top = prv[1]
            title = top["text"].strip() + " " + title
        while True:
            nxt = None
            for t in texts:
                if t is line or t["rotated"] or abs(t["size"] - s) > 0.05 * s:
                    continue
                gap = line["bbox"][1] - t["bbox"][3]
                if 0 <= gap <= 0.8 * s and abs(t["center"][0] - line["center"][0]) <= 0.25 * w \
                        and t["text"].strip() and t["value"] is None:
                    if nxt is None or gap < nxt[0]:
                        nxt = (gap, t)
            if nxt is None:
                break
            line = nxt[1]
            title += " " + line["text"].strip()
        return title, s
    # no title above: use a sub-caption below the plot such as
    # "(a). log(Effort) against log(Size)" or "Fig. 3 ..."
    for t in texts:
        txt = t["text"].strip()
        if t["rotated"] or not _CAPTION_RE.match(txt):
            continue
        gap = y0 - t["bbox"][3]
        # (a sub-caption starts its line: "(B) Model comparison ..." in the
        # middle of a line of 2020.01.30.927558.full-026's figure caption,
        # text just before it, is part of that caption)
        sz = t["size"] or 1.0
        if not re.match(r"(?i)fig(ure|\.)", txt) and (any(
                o is not t and o["text"].strip() and not o["rotated"] and
                abs(o["center"][1] - t["center"][1]) < 0.5 * sz and
                0 <= t["bbox"][0] - o["bbox"][2] <= sz for o in texts) or _continues_caption(t, texts)):
            continue                # (figure captions may stand side by side: 3485513-020)
        if 0 <= gap <= 0.8 * h and abs(t["center"][0] - (x0 + x1) / 2) <= 0.25 * w:
            if any(r != tuple(rect) and 0 <= t["bbox"][1] - r[3] < min(gap, 2 * t["size"]) and
                   r[0] - 6 * t["size"] <= t["bbox"][0] and t["bbox"][2] <= r[0] + 2 * t["size"]
                   for r in map(tuple, PAGE.graph_rects)):
                continue        # the panel label at the top left corner of the graph below
            if best is None or gap < best[0]:
                best = (gap, txt, t["size"], t)
    if not best:
        return "", 0.0
    return best[1] + _rest_of_line(best[3], texts, best[2] or 1.0), best[2]


def _rest_of_line(line, texts, s):
    """The words drawn as separate texts further along the line of `line`
    (" LLVM" after "a)"), each starting within 0.6 em of the one before;
    "" if none."""
    out = ""
    end = line["bbox"][2]
    for o in sorted(texts, key=lambda o: o["bbox"][0]):
        if o is not line and not o["rotated"] and abs(o["size"] - s) <= 0.1 * s and \
                abs(o["p0"][1] - line["p0"][1]) < 0.2 * s and \
                0 <= o["bbox"][0] - end < 0.6 * s and o["text"].strip():
            out += " " + o["text"].strip()
            end = o["bbox"][2]
    return out


# (an appendix figure's letter too: "Figure B.3", PsychologyToPhylogeny-
# AnalysisCultEvo-170)
_CAPTION_RE = re.compile(r"^(\(?[a-zA-Z]\)|Fig(ure|\.)?\s*(?:[A-Z]\.?)?\d)")


# -- figure captions ----------------------------------------------------------

# "Fig. 5.", "Figure 3:", "FIGURE 12 -", "Fig 2", "Figure S3", "Figure 4.2",
# "Figure 3-6" (chapter and figure), "Figure B.3" (an appendix's),
# "Figure 1.1.2" (horowitz2014-004: three levels)
# (small-caps fonts may map the label to lower case: "figure 2.")
_FIGURE_RE = re.compile(r"^\s*(?:Fig(?:ure)?|FIG(?:URE)?|fig(?:ure)?)\.?\s*((?:[A-Z]\.?)?\d+(?:[.\-–]\d+)*[a-z]?)"
                        r"\s*(?:[.:|–—-]\s*)?(.*)$", re.S)


def text_lines(texts):
    """The page's horizontal text as lines: items sharing a baseline are
    joined left to right, but not across a gap of more than one em (the
    gap between two columns of a page).  Each line: {text, bbox, size, y},
    where size is that of most of its text and y its baseline."""
    items = sorted((t for t in texts if not t["rotated"] and t["text"].strip()),
                   key=lambda t: -t["p0"][1])
    rows, cur = [], []
    for t in items:
        if cur and abs(cur[0]["p0"][1] - t["p0"][1]) > 0.3 * max(cur[0]["size"], 1e-6):
            rows.append(cur)
            cur = []
        cur.append(t)
    if cur:
        rows.append(cur)
    lines = []
    for row in rows:
        row.sort(key=lambda t: t["bbox"][0])
        line = None
        for t in row:
            s = max(t["size"], 1e-6)
            # (the line's largest size kept as it grows: a max over all its
            # items made a line of many items quadratic)
            if line is not None and t["bbox"][0] - line["bbox"][2] <= 1.0 * max(s, line["big"]):
                gap = t["bbox"][0] - line["bbox"][2]
                line["text"] += (" " if gap > 0.15 * s and not line["text"].endswith(" ")
                                 else "") + t["text"].strip()
                b = line["bbox"]
                line["bbox"] = (b[0], min(b[1], t["bbox"][1]), max(b[2], t["bbox"][2]),
                                max(b[3], t["bbox"][3]))
                line["sizes"].append((len(t["text"].strip()), t["size"]))
                line["big"] = max(line["big"], t["size"])
                continue
            line = {"text": t["text"].strip(), "bbox": tuple(t["bbox"]), "y": t["p0"][1],
                    "sizes": [(len(t["text"].strip()), t["size"])], "big": t["size"]}
            lines.append(line)
    for line in lines:
        # the size of most of the line's text (a word in another font, such
        # as a monospaced name, may be set larger)
        weight = {}
        line.pop("big")
        for n, sz in line.pop("sizes"):
            weight[round(sz, 1)] = weight.get(round(sz, 1), 0) + n
        line["size"] = max(weight, key=lambda sz: (weight[sz], -sz))
    return lines


def _caption_head(ln, m, lines):
    """The first line of a caption.  A label set apart from its text ("Figure
    1." in bold, a wide space, then the caption) forms a line of its own;
    when nothing follows the number, the text further along the same
    baseline is joined to it."""
    head = dict(ln, parts=[ln])
    if m.group(2).strip():
        return head
    s = max(ln["size"], 1e-6)
    for o in sorted(lines, key=lambda o: o["bbox"][0]):
        if o is not ln and abs(o["y"] - ln["y"]) < 0.3 * s and \
                0 <= o["bbox"][0] - head["bbox"][2] <= 4 * s:
            head["text"] += " " + o["text"]
            b = head["bbox"]
            head["bbox"] = (b[0], min(b[1], o["bbox"][1]), max(b[2], o["bbox"][2]),
                            max(b[3], o["bbox"][3]))
            head["parts"].append(o)
    return head


def find_figure_caption(rect, lines, graph_rects):
    """(figure number, caption text) of the figure a graph belongs to: the
    nearest caption paragraph starting "Fig. N" / "Figure N" below the
    graph and across its width.  Other graphs of the same figure may lie in
    between (the caption goes below the whole figure), so the distance
    allowed grows by the height of each graph across the way.  ("", "")
    if none."""
    x0, y0, x1, y1 = rect
    h = y1 - y0
    best = None
    for ln in lines:
        m = _FIGURE_RE.match(ln["text"])
        if not m or m.group(2)[:1] in (")", "]", ",", ";"):
            continue                           # none, or a reference: "(see Fig. 2)."
        ln = _caption_head(ln, m, lines)
        bx0, by0_, bx1, by1 = ln["bbox"]
        gap = y0 - by1
        if bx1 <= x0 or bx0 >= x1:
            continue                           # not across the graph's width
        if any(r != rect and 0 <= by0_ - r[3] <= ln["size"] and 4 * (by0_ - r[3]) <= gap and
               min(r[2], bx1) - max(r[0], bx0) >= 0.5 * min(r[2] - r[0], bx1 - bx0)
               for r in graph_rects):
            continue                           # the title of a graph below it
            # (VaskeBeaman2006-Lessonslearned-003: "Figure 1c. ..." over
            # Figure 1c, no caption of 1a above it)
        between = sum(r[3] - r[1] for r in graph_rects
                      if r != rect and r[3] <= y0 + 1 and r[1] >= by1 - 1 and
                      r[2] > bx0 and r[0] < bx1)
        if not (-0.5 * ln["size"] <= gap <= max(2.0 * h, 150.0) + 1.5 * between):
            continue
        if best is None or gap < best[0]:
            best = (gap, ln, m)
    if best is None:
        return "", ""
    _, first, m = best
    s = max(first["size"], 1e-6)
    parts = [_FIGURE_RE.match(first["text"]).group(2).strip()]
    prev = first
    spacing = None
    # the following lines of the paragraph: same size, same column, one
    # line spacing further down (the first step sets the spacing: single
    # or double spaced); a line ending well short of the column's right
    # edge ends the paragraph
    for _ in range(40):
        if prev["bbox"][2] < first["bbox"][2] - 3 * s and prev is not first:
            break
        nxt = None
        for ln in lines:
            if ln is prev or ln in first["parts"] or abs(ln["size"] - first["size"]) > 0.15 * s:
                continue
            dy = prev["y"] - ln["y"]
            ok = 0.8 * spacing < dy < 1.2 * spacing if spacing else 0.5 * s < dy < 2.6 * s
            # the next line starts where the caption starts, ends where it
            # ends (justified, also with a hanging indent under the text
            # after "Figure 3.3:"), or is centred under it (a centred
            # caption): not a line of the right-hand column below a short
            # centred caption
            starts = abs(ln["bbox"][0] - first["bbox"][0]) <= 2 * s or \
                (abs(ln["bbox"][0] - prev["bbox"][0]) <= 2 * s and prev is not first) or \
                abs(ln["bbox"][2] - first["bbox"][2]) <= 2 * s
            centred = abs((ln["bbox"][0] + ln["bbox"][2]) / 2 -
                          (first["bbox"][0] + first["bbox"][2]) / 2) <= 2 * s
            if ok and ln["bbox"][0] < first["bbox"][2] and \
                    ln["bbox"][2] > first["bbox"][0] and \
                    ln["bbox"][0] >= first["bbox"][0] - 2 * s and (starts or centred):
                if nxt is None or dy < nxt[0]:
                    nxt = (dy, ln)
        if nxt is None or _FIGURE_RE.match(nxt[1]["text"]):
            break
        prev = nxt[1]
        spacing = spacing or nxt[0]
        parts.append(prev["text"].strip())
    caption = ""
    for p in parts:
        if caption.endswith("-") and p[:1].islower():
            caption = caption[:-1] + p         # a word hyphenated at the line end
        else:
            caption += (" " if caption else "") + p
    return m.group(1), caption

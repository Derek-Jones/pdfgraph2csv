"""Graph titles: the text centred above a plot (with continuation lines),
or a sub-caption below it such as "(a) ..." or "Fig. 3 ...".
"""

import re

from .context import PAGE
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


def _find_title(rect, texts, symbols):
    """Text centred above a plot, alone on its line (so legend headings such
    as "Post-TOF  [key] FALSE [key] TRUE" are not mistaken for titles)."""
    x0, y0, x1, y1 = rect
    w, h = x1 - x0, y1 - y0
    best = None
    for t in texts:
        txt = t["text"].strip()
        if not txt or is_number(t) or t["rotated"]:
            continue
        if t["size"] < 0.85 * PAGE.label_size:
            continue            # sub/superscripts and small print are no titles
        if any(o["size"] > 1.15 * t["size"] and not o["rotated"] and
               0 <= t["bbox"][0] - o["bbox"][2] < 0.3 * o["size"] and
               abs(o["center"][1] - t["center"][1]) < 0.6 * o["size"] for o in texts):
            continue            # a subscript, e.g. the "DS" of "V_DS"
        bx0, by0, bx1, by1 = t["bbox"]
        gap = by0 - y1
        if not (0 <= gap <= min(0.35 * h, 4 * t["size"])) or \
                abs(t["center"][0] - (x0 + x1) / 2) > 0.15 * w:
            continue
        if _CAPTION_RE.match(txt) and any(
                r != rect and r[1] >= by1 and r[1] - by1 < 0.5 * (r[3] - r[1]) and
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
        crowded = any(
            o is not t and o["size"] >= 0.85 * s and abs(o["p0"][1] - t["p0"][1]) < 0.5 * s and
            0 <= max(o["bbox"][0] - bx1, bx0 - o["bbox"][2]) < 3 * s and not over_other_graph(o)
            for o in texts) or any(
            abs(sy["cy"] - t["center"][1]) < s and abs(sy["idx"] - t["idx"]) <= 100 and
            0 <= max(sy["cx"] - bx1, bx0 - sy["cx"]) < 3 * s for sy in symbols)
        if crowded:
            continue
        key = (-round(s, 1), gap)          # biggest font first, then closest
        if best is None or key < best[0]:
            best = (key, txt, s, t)
    if best:
        # a title may continue on further lines just below the first one
        title, s = best[1], best[2]
        line = best[3]
        # subscripts / superscripts directly after the text (e.g. "f" + "4")
        for o in sorted(texts, key=lambda o: o["bbox"][0]):
            if o is not line and o["size"] < 0.85 * s and \
                    0 <= o["bbox"][0] - line["bbox"][2] < 0.3 * s and \
                    abs(o["center"][1] - line["center"][1]) < 0.6 * s:
                title += o["text"].strip()
        # words of the same line drawn as separate texts ("a)" + "LLVM")
        end = line["bbox"][2]
        for o in sorted(texts, key=lambda o: o["bbox"][0]):
            if o is not line and not o["rotated"] and abs(o["size"] - s) <= 0.1 * s and \
                    abs(o["p0"][1] - line["p0"][1]) < 0.2 * s and \
                    0 <= o["bbox"][0] - end < 0.6 * s and o["text"].strip():
                title += " " + o["text"].strip()
                end = o["bbox"][2]
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
        if 0 <= gap <= 0.8 * h and abs(t["center"][0] - (x0 + x1) / 2) <= 0.25 * w:
            if best is None or gap < best[0]:
                best = (gap, txt, t["size"], t)
    if not best:
        return "", 0.0
    # the rest of the caption's line: "a)" + "LLVM"
    title, s, line = best[1], best[2] or 1.0, best[3]
    end = line["bbox"][2]
    for o in sorted(texts, key=lambda o: o["bbox"][0]):
        if o is not line and not o["rotated"] and abs(o["size"] - s) <= 0.1 * s and \
                abs(o["p0"][1] - line["p0"][1]) < 0.2 * s and \
                0 <= o["bbox"][0] - end < 0.6 * s and o["text"].strip():
            title += " " + o["text"].strip()
            end = o["bbox"][2]
    return title, best[2]


_CAPTION_RE = re.compile(r"^(\(?[a-zA-Z]\)|Fig(ure|\.)?\s*\d)")

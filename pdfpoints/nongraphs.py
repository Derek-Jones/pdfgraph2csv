"""Rejecting 'graphs' that are not graphs.

The axis finder looks for lines with evenly spaced marks and numbers or
names beside them.  A ruled table (rules, column headings, row names), a
page of mathematics (rules above and below shaded boxes, bracket glyphs,
numbers in the prose) or a table of numbers ruled with thin rectangles
can pass that test.  A graph, as the user defined it, holds two axes, tick
marks or lines with their labels, and small symbols for the data points,
with at most a few words of text (legends, notes, point labels).  These
tests reject a candidate whose plot area holds what a table or a text page
holds instead: running prose, text in most cells of a grid, or a grid of
numbers.
"""

import re
import sys

from .context import SETTINGS
from .geometry import box_of, encloses, fmt_rect, median, overlap_area, rect_area
from .text import WORD_RE

# a number in a table cell: digits may come in groups split by thin spaces
# (0.918 6), as some journals set them
# (regression tables too: significance marks after a number, "-.895**",
# and standard errors in brackets, "(.177)": w21074-035)
_CELL_NUM = re.compile(r"^(?:[+-]?(\d[\d ]*)?\.?\d[\d ]*%?[*\u2020\u2021]*|"
                       r"[(\[][+-]?(\d[\d ]*)?\.?\d[\d ]*%?[)\]][*\u2020\u2021]*)$")


def axis_labels(g):
    """The text items labelling a graph's x and y axes."""
    return [t for k in ("x", "y") for _, t in g[k].get("labels", ())]


def texts_inside(g, texts):
    """The text items centred inside a graph's plot box, other than its own
    axis labels (which may sit just inside the box)."""
    own = {id(t) for t in axis_labels(g)}
    x0, y0, x1, y1 = g["rect"]
    return [t for t in texts if id(t) not in own
            and x0 <= t["center"][0] <= x1 and y0 <= t["center"][1] <= y1]


def text_boxes(paths):
    """Axis-aligned rectangles that may enclose text: filled boxes and
    closed outlines (call-outs with a border, notes on a coloured ground).
    Boxes under 3 pt across are rules or markers, not boxes."""
    out = []
    for p in paths:
        for sp in p["subpaths"]:
            b = box_of(sp)
            if b is None or not (p["fill"] or sp.get("closed") or len(sp["segs"]) == 4):
                continue        # (an open 4-point outline is no box: 3 sides)
            if min(b[2] - b[0], b[3] - b[1]) >= 3:
                out.append(b)
    return out


def prose_inside(g, texts, boxes=()):
    """The words (of three letters or more) of running text inside a graph's
    plot box, its own axis labels apart.  The text items on one baseline
    are joined into lines, and only lines of three words or more count:
    the names beside points, legend entries and short notes are shorter.
    Text enclosed by a border or a filled box smaller than half the plot box
    does not count either: the user asked for notes describing the data
    (ITRS charts) to be allowed however long they are.  Nor does turned or
    slanted text: running text is set level (the page itself is read
    turned when its text is), while category names may stand at a slant
    over their bars (Memory_systems_cacheDRAMdisk-051's PERL chart: 48
    names such as "1 x 8-bit x 100 Mhz" at 45 degrees inside the plot)."""
    half = 0.5 * rect_area(g["rect"])
    notes = [b for b in boxes if rect_area(b) < half]
    items = sorted((t for t in texts_inside(g, texts) if t["text"].strip() and not t.get("rotated")
                    and not any(encloses(b, t["bbox"]) for b in notes)),
                   key=lambda t: (-round(t["p0"][1], 1), t["p0"][0]))
    lines = []           # [baseline y, right end, text]
    for t in items:
        size = t.get("size") or 1.0
        # (only recent lines can continue: items are sorted top to bottom)
        for ln in lines[-8:]:
            if abs(ln[0] - t["p0"][1]) <= 0.3 * size and -0.5 * size <= t["p0"][0] - ln[1] <= 1.5 * size:
                ln[1] = max(ln[1], t["p1"][0])
                ln[2] += " " + t["text"]
                break
        else:
            lines.append([t["p0"][1], t["p1"][0], t["text"]])
    return sum(len(WORD_RE.findall(ln[2])) for ln in lines if len(ln[2].split()) >= 3)


def numeric_grid(g, texts):
    """Whether the plot area holds a table of numbers: at least 3 columns
    and 3 rows that each line up 3 or more numbers, with 9 or more numbers
    in both a column and a row.  Point labels are scattered, a bar's value
    sits alone above it and stacked-bar segment labels do not line up across
    bars, so no graph's numbers make such a grid.  Axis labels well inside
    the box count as cells: a graph's tick labels lie outside its plot box,
    while a column of a table can pass for an axis's labels (a table's
    rules pass for axes).  Only real text counts: at least 3 pt and 60% of
    the axis labels' size (slivers of flattened markers can be read as the
    glyph '1')."""
    least = max(3.0, 0.6 * median((t["size"] for t in axis_labels(g)), 0.0))
    x0, y0, x1, y1 = g["rect"]
    inner = [t for t in axis_labels(g)
             if x0 + 0.5 * t["size"] < t["center"][0] < x1 - 0.5 * t["size"] and
             y0 + 0.5 * t["size"] < t["center"][1] < y1 - 0.5 * t["size"]]
    nums = [t for t in texts_inside(g, texts) + inner
            if t["size"] >= least and _CELL_NUM.match((t.get("text") or "").strip())]
    if len(nums) < 9:
        return False

    def lines(pos):
        # numbers sharing a position (half a font size apart at most)
        out = []
        for t in sorted(nums, key=pos):
            if out and abs(pos(t) - out[-1][0]) <= 0.5 * t["size"]:
                out[-1][1].append(t)
            else:
                out.append([pos(t), [t]])
        return [ts for _, ts in out if len(ts) >= 3]
    cols = lines(lambda t: t["center"][0])        # centred in a column
    rows = lines(lambda t: t["bbox"][1])          # on one baseline
    if len(cols) < 3 or len(rows) < 3:
        return False
    held = {id(t) for ts in cols for t in ts} & {id(t) for ts in rows for t in ts}
    return len(held) >= 9


def _text_in_cells(g, texts):
    """For a graph with a category axis each way: (cells holding text,
    number of cells), a cell being a row category by a column category."""
    mx, my = g["x"]["map"], g["y"]["map"]
    xr, yr = ({"x": 0, "y": 1}[g[k]["orient"]] for k in ("x", "y"))
    xt = [p for p, _ in mx["ticks"]]
    yt = [p for p, _ in my["ticks"]]
    cells = set()
    for t in texts_inside(g, texts):
        c = t["center"]
        cells.add((min(range(len(xt)), key=lambda i: abs(xt[i] - c[xr])),
                   min(range(len(yt)), key=lambda j: abs(yt[j] - c[yr]))))
    return len(cells), len(xt) * len(yt)


def _cell_numbers_boxed(g, texts, paths):
    """Whether the numbers in the plot are cell values of an annotated
    heatmap or correlation matrix: at least 80% of them (9 or more) are
    each centred (within 0.3 of a cell) in a filled rectangle that is not
    white, no wider than 1.5 times and no narrower than half the median of
    those rectangles, and at least as tall as the number.  A table's
    numbers stand on its page, not each in its own coloured cell
    (2308.04785-006: seaborn correlation matrices, a coloured square with
    its coefficient at each crossing of the category grid).  Rectangles
    are filed in a grid: plots can hold thousands."""
    x0, y0, x1, y1 = g["rect"]
    nums = [t for t in texts_inside(g, texts) if _CELL_NUM.match((t.get("text") or "").strip())]
    if len(nums) < 9:
        return False
    cells = {}
    for p in paths:
        if not p["fill"] or not p.get("fill_rgb") or min(p["fill_rgb"]) > 0.97:
            continue
        for sp in p["subpaths"]:
            r = box_of(sp)
            if r is None or not (x0 - 1 <= r[0] and r[2] <= x1 + 1 and y0 - 1 <= r[1] and r[3] <= y1 + 1):
                continue
            if r[2] - r[0] > 0.5 * (x1 - x0):
                continue
            cells.setdefault((int((r[0] + r[2]) / 20), int((r[1] + r[3]) / 20)), []).append(r)
    held, widths = 0, []
    for t in nums:
        cx, cy = t["center"]
        best = None
        for i in (-1, 0, 1):
            for j in (-1, 0, 1):
                for r in cells.get((int(cx / 10) + i, int(cy / 10) + j), ()):
                    w, h = r[2] - r[0], r[3] - r[1]
                    if (abs((r[0] + r[2]) / 2 - cx) <= 0.3 * w and abs((r[1] + r[3]) / 2 - cy) <= 0.3 * h
                            and h >= t["size"] * 0.7):
                        best = r
        if best is not None:
            held += 1
            widths.append(best[2] - best[0])
    if held < 9 or held < 0.8 * len(nums):
        return False
    mw = median(widths)
    return all(0.5 * mw <= w <= 1.5 * mw for w in widths)


def ruled_tables(paths):
    """Boxes of ruled tables: five or more rules of one extent (ends within
    1 pt), parallel, one under another (or side by side); the box spans the
    rules.  State_IT_Project_Management_in_UK-056's table has 24 rules
    across its full width, its column rules cut cell by cell.  A rule is
    drawn unbroken: pieces join only where they touch (within 0.5 pt), so
    the frames and grid lines of charts side by side, lined up, make no
    rules across them; and the table is closed by a border, rules across
    the whole box at both ends of its rules (3276496-020's three Excel
    scatter plots of one size have frame sides and grid lines of one
    height)."""
    from .axes import _page_segments
    _, segs, _ = _page_segments(paths)
    rules = {}
    for orient in ("h", "v"):
        by_pos = {}
        for lo, hi, pos in segs[orient]:
            by_pos.setdefault(round(pos, 1), []).append((lo, hi))
        rules[orient] = []
        for pos, pieces in by_pos.items():
            pieces.sort()
            cur = list(pieces[0])
            for lo, hi in pieces[1:]:
                if lo <= cur[1] + 0.5:
                    cur[1] = max(cur[1], hi)
                else:
                    rules[orient].append((cur[0], cur[1], pos))
                    cur = [lo, hi]
            rules[orient].append((cur[0], cur[1], pos))

    def spans(orient, lo, hi, at):
        """A rule across lo..hi (within 1 pt) at position at (within 1 pt)?"""
        return any(abs(p - at) <= 1.0 and a <= lo + 1.0 and b >= hi - 1.0
                   for a, b, p in rules[orient])
    out = []
    for orient, other in (("h", "v"), ("v", "h")):
        groups = []
        for lo, hi, pos in rules[orient]:
            if hi - lo <= 20:
                continue        # (no table rule; a trace plot's thousands of
                                # short strokes made this loop slow)
            for g in groups:
                if abs(g[0] - lo) <= 1.0 and abs(g[1] - hi) <= 1.0:
                    g[2].append(pos)
                    break
            else:
                groups.append([lo, hi, [pos]])
        for lo, hi, ps in groups:
            if len(ps) < 5 or hi - lo <= 20:
                continue
            a, b = min(ps), max(ps)
            # closed by a border: rules across the whole box at both ends
            # (charts of one size side by side are not)
            if not (spans(other, a, b, lo) and spans(other, a, b, hi)):
                continue
            out.append((lo, a, hi, b) if orient == "h" else (a, lo, b, hi))
    return out


def _across_tables(rect, tables):
    """Does `rect` lie 70% or more within the boxes `tables`, which overlap
    it and together are twice its size or more?"""
    a = rect_area(rect)
    if a <= 0:
        return False
    hit = [t for t in tables if overlap_area(rect, t) > 0]
    inside = sum(overlap_area(rect, t) for t in hit)
    return bool(hit) and inside >= 0.7 * a and sum(rect_area(t) for t in hit) >= 2 * a


def _one_name(m):
    """Do all the labels of a category axis name the same category?
    Categories differ; the same word at every tick is a heading repeated
    in the columns or tables of a page (roache_fundamentals_2009-193: "R"
    of the headings "R actual" and "R theory" across two tables, "actual"
    of the two "R actual" headings one above the other)."""
    names = {str(lab).strip().lower() for _, lab in m.get("ticks", ())}
    return len(m.get("ticks", ())) >= 2 and len(names) == 1


def _names_inside(g):
    """Do most (80%) of the names of one of graph g's category axes - three
    or more - stand inside its plot box, more than half their size in from
    the edge their axis faces?  A chart's category names stand outside its
    box; a table's column of entries, the rule beside it taken for an axis,
    stands within the table (no.ntnu_inspera_146721987_149459097-031: the
    entries of the second column of a LaTeX table with filled cells, its
    headings taken for x categories)."""
    x0, y0, x1, y1 = g["rect"]
    for k in ("x", "y"):
        labs = [t for _, t in g[k].get("labels") or ()]
        if len(labs) < 3:
            continue
        def inside(t):
            s = 0.5 * (t.get("size") or 1.0)
            if k == "y":
                return t["bbox"][0] > x0 + s and t["bbox"][2] < x1 - s
            return t["bbox"][1] > y0 + s and t["bbox"][3] < y1 - s
        if sum(1 for t in labs if inside(t)) >= 0.8 * len(labs):
            return True
    return False


def drop_tables(graphs, texts, debug=False, boxes=(), paths=()):
    """The graphs that are graphs.  Dropped:
    - a 'plot' holding more words of running text than --max-words
      (default 20): a text page whose rules and numbers passed for axes;
      real graphs hold a few words at most (legends, notes);
    - a plot holding a grid of numbers (numeric_grid): a table whose rules
      and row names passed for axes;
    - a graph with a category axis each way whose cells hold text in at
      least half of them, or one of whose axes names one category at every
      tick (_one_name), or whose names stand inside its box (_names_inside):
      a ruled table (its column headings and row names are the
      categories).  A chart with categories both ways, such as a
      dot matrix, holds markers in its cells, not text;
    - a graph lying inside a ruled table (ruled_tables) twice its size or
      more, whose box holds a grid of numbers: a few rows of the table
      taken for a plot
      (State_IT_Project_Management_in_UK-056: one row of a 24-rule table,
      its cell values read as categories);
    - a graph lying 70% or more within ruled tables of numbers twice its
      size or more together: a column of cells running through tables one
      above another (w21074-035: one column of two regression tables, its
      x categories two words of the note below)."""
    out = []
    tables = None
    for g in graphs:
        why = None
        mx, my = g["x"]["map"], g["y"]["map"]
        if tables is None:
            tables = [t for t in ruled_tables(paths) if numeric_grid(dict(g, rect=t), texts)] \
                if paths else []
        x0, y0, x1, y1 = g["rect"]
        # (a slice of a table at most half its size: a plot's own grid
        # lines make a "table" of its own box - 2308.04785-006's correlation
        # matrices, an Excel scatter's grid)
        if any(t[0] - 1 <= x0 and x1 <= t[2] + 1 and t[1] - 1 <= y0 and y1 <= t[3] + 1 and
               rect_area(g["rect"]) <= 0.5 * rect_area(t) for t in tables) and \
                not _cell_numbers_boxed(g, texts, paths):
            why = "lies in a ruled table of numbers"
        elif _across_tables(g["rect"], tables):
            why = "lies across ruled tables of numbers"
        elif prose_inside(g, texts, boxes) > SETTINGS.max_words:
            why = "holds running text: no graph"
        elif numeric_grid(g, texts) and not _cell_numbers_boxed(g, texts, paths):
            why = "holds a grid of numbers: a table"
        elif mx and my and mx["kind"] == "nominal" and my["kind"] == "nominal":
            held, n = _text_in_cells(g, texts)
            if n >= 4 and held >= 0.5 * n:
                why = "is a table: text in %d of its %d cells" % (held, n)
            elif _one_name(mx) or _one_name(my):
                why = "is a table: a category axis naming one category over and over"
            elif _names_inside(g):
                why = "is a table: a category axis's names stand inside its box"
        if why is None:
            out.append(g)
        elif debug:
            print("[debug] graph rect %s %s" % (fmt_rect(g["rect"]), why), file=sys.stderr)
    return out

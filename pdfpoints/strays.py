"""Marks that look like data-point markers but are not.

symbols.find_symbols accepts any small closed shape, glyph or crossing of
strokes that has the form of a marker.  On real pages many such shapes
belong to something else, and once the page's graphs are known they can be
told apart by where they sit:
- sample markers in a caption or the body text ("Binomial(20, 1/2) (o o o)"),
  bullets, and full stops drawn as shapes after formulas;
- the '+' that tick marks crossing the axis line make where the axes meet;
- the dashes of a dashed border round a note, drawn as small squares;
- the little squares filling the joints of a table ruled with thin filled
  rectangles.
"""

import collections
import math

from .geometry import bbox_of, box_of, encloses, inside_rect, median, rect_area, rect_distance, vertices
from .grouping import DisjointSets, PointGrid
from .text import WORD_RE


def drop_symbols_in_prose(symbols, texts, graphs):
    """A marker drawn in a line of running text outside every graph is no
    data point and no legend key.  It counts as in the line when there is
    text on both sides of it on its baseline, within 0.75 of a font size,
    in a line of three words or more (of three letters or more: a legend
    row "o Group A o Group B" has fewer) that reaches beyond the page's
    graphs by more than 15% of their width (a legend row stays within
    them), and when it is no bigger than the text (a legend key's box is).
    A run of such markers close together counts as one (text left of the
    first and right of the last).  A dot under 0.3 of the font size just
    after text, on a line within a font size of it, needs no words around
    it: a full stop drawn as a shape after a formula's superscript.
    Symbols with a clipping box belong to the graph they were clipped to."""
    if not symbols or not texts:
        return symbols
    lines = _text_lines(texts)
    if not lines:
        return symbols
    outside = sorted((s for s in symbols if not s.get("clip")
                      and not any(rect_distance(g["rect"], s["cx"], s["cy"]) == 0 for g in graphs)),
                     key=lambda s: s["cx"])
    # runs of markers along one baseline, left to right
    runs = []
    for s in outside:
        for r in reversed(runs[-50:]):
            q = r[-1]
            if abs(q["cy"] - s["cy"]) <= 0.3 * max(s["size"], q["size"]) and \
                    s["cx"] - q["cx"] <= 3 * max(s["size"], q["size"]) + 2:
                r.append(s)
                break
        else:
            runs.append([s])
    prose = lines
    if graphs:
        gx0 = min(g["rect"][0] for g in graphs)
        gx1 = max(g["rect"][2] for g in graphs)
        reach = 0.15 * (gx1 - gx0)
        prose = [ln for ln in lines if ln[2][0][0] < gx0 - reach or ln[2][-1][1] > gx1 + reach]
    drop = set()
    for run in runs:
        x0 = min(s["cx"] - s["size"] / 2 for s in run)
        x1 = max(s["cx"] + s["size"] / 2 for s in run)
        cy = sum(s["cy"] for s in run) / len(run)
        size = max(s["size"] for s in run)
        if any(_in_line(ln, x0, x1, cy, size) for ln in prose) or \
                any(_after_text(ln, x0, cy, size) for ln in lines):
            drop.update(id(s) for s in run)
    return [s for s in symbols if id(s) not in drop]


def _text_lines(texts):
    """Lines of horizontal text: (baseline, font size, the items' x spans,
    whether the line has three words or more)."""
    rows = collections.defaultdict(list)
    for t in texts:
        if t.get("up", (0, 1))[0] != 0 or not t["text"].strip():
            continue
        rows[round(t["p0"][1])].append(t)
    out = []
    for items in rows.values():
        items.sort(key=lambda t: t["p0"][0])
        size = median(t.get("size") or 1.0 for t in items)
        prose = len(WORD_RE.findall(" ".join(t["text"] for t in items))) >= 3
        out.append((items[0]["p0"][1], size, [(t["p0"][0], t["p1"][0]) for t in items], prose))
    return out


def _after_text(ln, x0, cy, msize):
    """A tiny mark (under 0.3 of the font size) just after text on a line
    within a font size of it (a full stop after a superscript)."""
    base, size, spans, _ = ln
    if msize >= 0.3 * size or not base - size <= cy <= base + size:
        return False
    return any(x0 - 0.75 * size <= e <= x0 + 0.1 * size for _, e in spans)


def _in_line(ln, x0, x1, cy, msize):
    """A mark spanning x0..x1 set in line `ln`: text ends just left of it
    and starts just right of it."""
    base, size, spans, prose = ln
    if msize > size or not (prose or msize < 0.3 * size):
        return False        # (a mark in a line of text is no bigger than the text)
    if not base - 0.3 * size <= cy <= base + 0.9 * size:
        return False
    left = any(x0 - 0.75 * size <= e <= x0 + 0.1 * size for _, e in spans)
    right = any(x1 - 0.1 * size <= b <= x1 + 0.75 * size for b, _ in spans)
    return left and right


def drop_corner_ticks(symbols, graphs):
    """Ticks drawn across the axis line (seen with Excel) meet where the
    axes meet: the first x tick and the first y tick there make a '+' one
    or two tick lengths across.  Such a plus, on a tick of each axis at the
    corner where the axis lines cross, is not a data point; nor is a plus
    of tick size near another corner of the plot box, where ticks mirrored
    on the top and right edges cross."""
    corners = []
    edges = []              # (corner x, corner y, tick length) of other corners
    for g in graphs:
        ax = {a.get("orient"): a for a in (g.get("x"), g.get("y")) if a}
        if set(ax) != {"x", "y"} or ax["x"].get("pos") is None or ax["y"].get("pos") is None:
            continue
        cx, cy = ax["y"]["pos"], ax["x"]["pos"]
        L = max(ax["x"].get("tick_len") or 0, ax["y"].get("tick_len") or 0)
        tol = max(0.5, 0.15 * L)
        if any(abs(t - cx) <= tol for t in ax["x"].get("tick_pos", ())) and \
                any(abs(t - cy) <= tol for t in ax["y"].get("tick_pos", ())):
            corners.append((cx, cy, L, tol))
        # ticks mirrored on the top and right edges cross near the plot
        # box's other corners too (the last minor ticks of each edge): a plus
        # whose arms run in from both edges of that corner
        if L > 0:
            x0, y0, x1, y1 = g["rect"]
            edges.extend((qx, qy, L) for qx, qy in ((x0, y1), (x1, y1), (x1, y0)))
    if not corners and not edges:
        return symbols

    def reaches(s, qx, qy, L):
        h = s["size"] / 2
        return 0.7 * L <= s["size"] <= 2.2 * L and \
            min(abs(s["cx"] - h - qx), abs(s["cx"] + h - qx)) <= 0.3 and \
            min(abs(s["cy"] - h - qy), abs(s["cy"] + h - qy)) <= 0.3
    return [s for s in symbols if not (
        s["shape"] == "plus" and (any(
            abs(s["cx"] - cx) <= tol and abs(s["cy"] - cy) <= tol and 0.7 * L <= s["size"] <= 2.2 * L
            for cx, cy, L, tol in corners) or any(reaches(s, *e) for e in edges)))]


def drop_box_dashes(symbols, texts, boxes, graphs):
    """A dashed border round a note drawn as a row of small filled squares
    (ITRS charts): four or more squares of one size on an edge of a box
    that encloses text, and is smaller than a quarter of the largest graph,
    are its dashes.  A marker alone on a frame's edge is a data point.
    Dashes are small beside their box: under a quarter of its shorter side
    (2308.04785-006: each cell of a correlation matrix is a filled square
    round its number, and its neighbours, as big as it, are no dashes)."""
    if not boxes or not texts or not graphs:
        return symbols
    big = max(rect_area(g["rect"]) for g in graphs)
    notes = [b for b in boxes if rect_area(b) <= 0.25 * big        # (else a plot frame)
             and any(encloses(b, t["bbox"]) for t in texts if t["text"].strip())]
    if not notes:
        return symbols
    edges = collections.defaultdict(list)       # (box, side, size) -> squares on it
    for s in symbols:
        if s["shape"] not in ("square", "rectangle"):
            continue
        tol = 0.75 * s["size"] + 0.5
        for bi, (x0, y0, x1, y1) in enumerate(notes):
            if s["size"] >= 0.25 * min(x1 - x0, y1 - y0):
                continue
            if not inside_rect(notes[bi], s["cx"], s["cy"], tol):
                continue
            for side, d in (("l", abs(s["cx"] - x0)), ("r", abs(s["cx"] - x1)),
                            ("b", abs(s["cy"] - y0)), ("t", abs(s["cy"] - y1))):
                if d <= tol:
                    edges[(bi, side, round(s["size"], 1))].append(id(s))
    dashes = {i for ids in edges.values() if len(ids) >= 4 for i in ids}
    return [s for s in symbols if id(s) not in dashes]


def drop_rule_joints(symbols, paths):
    """A table ruled with thin filled rectangles often fills the joint where
    two rules meet with a separate square as wide as the rules (564-010).
    A filled square no wider than 1.5 pt, flush against the end of a filled
    rule of its own thickness, is such a joint, not a data point."""
    rules = []          # (x0, y0, x1, y1, thickness, horizontal)
    for p in paths:
        if not p["fill"]:
            continue
        for sp in p["subpaths"]:
            b = box_of(sp)
            if b is None:
                continue
            w, h = b[2] - b[0], b[3] - b[1]
            t = min(w, h)
            if 0 < t <= 1.5 and max(w, h) >= 3 * t:
                rules.append((*b, t, w > h))
    if not rules:
        return symbols

    def joint(s):
        if s["shape"] not in ("square", "rectangle") or not s.get("filled", True) or s["size"] > 1.5:
            return False
        half, tol = s["size"] / 2, 0.15 * s["size"] + 0.05
        for x0, y0, x1, y1, t, horiz in rules:
            if abs(t - s["size"]) > tol:
                continue
            if horiz:
                # a horizontal rule starting or ending at the square's side
                if abs((y0 + y1) / 2 - s["cy"]) <= tol and (
                        abs(x0 - (s["cx"] + half)) <= tol or abs(x1 - (s["cx"] - half)) <= tol):
                    return True
            elif abs((x0 + x1) / 2 - s["cx"]) <= tol and (
                    abs(y0 - (s["cy"] + half)) <= tol or abs(y1 - (s["cy"] - half)) <= tol):
                return True
        return False
    return [s for s in symbols if not joint(s)]


def drop_foreign_crowds(symbols, graphs):
    """Markers of a drawing laid over a plot are not its data: in a graph
    whose markers are clipped to its box (10 or more), 100 or more symbols
    in the box clipped otherwise, over twice as many as its own, are
    dropped (the stippled hare and lynx drawn across plot a of
    song2025rigorous-002, clipped to the whole figure).  Outside a plot
    box, a crowd (100 or more symbols, over twice as many as inside) is
    dropped only when its sizes vary like a stippled drawing's (under 80%
    of them within 25% of the median size: the drawings of panel b in
    song2025rigorous-002; those over three times the median size, legend
    keys, stay); markers of one size stay, as the user wants
    the nodes of the networks drawn above 2204.07073-010's bars, read
    through the bars' axes."""
    if not symbols or not graphs:
        return symbols
    drop = _foreign_crowds(symbols, graphs) | _stippled_outside(symbols, graphs)
    return [s for s in symbols if id(s) not in drop] if drop else symbols


def _stippled_outside(symbols, graphs):
    """Ids of the symbols of crowds of mixed sizes outside a plot box (see
    drop_foreign_crowds)."""
    from .graphs import clip_graph, graph_for_symbol
    outside = collections.defaultdict(list)
    inside = collections.Counter()
    for s in symbols:
        d, g = graph_for_symbol(graphs, s)
        if d > 0 and clip_graph(graphs, s) is None:
            outside[id(g)].append(s)
        else:
            inside[id(g)] += 1
    drop = set()
    for gid, outs in outside.items():
        if len(outs) < 100 or len(outs) <= 2 * inside[gid]:
            continue
        m = median(s["size"] for s in outs)
        if sum(abs(s["size"] - m) <= 0.25 * m for s in outs) < 0.8 * len(outs):
            # (bigger ones, over three times the median, are legend keys)
            drop.update(id(s) for s in outs if s["size"] <= 3 * m)
    return drop


def _foreign_crowds(symbols, graphs):
    """Ids of the markers of a drawing laid over a plot: in a graph whose
    markers are clipped to its box (10 or more), 100 or more symbols in the
    box clipped otherwise, over twice as many as its own, are not its data
    (the stippled hare and lynx drawn across plot a of
    song2025rigorous-002, clipped to the whole figure)."""
    from .graphs import clip_graph, graph_for_symbol
    own = collections.Counter()
    other = collections.defaultdict(list)
    for s in symbols:
        g = clip_graph(graphs, s)
        if g is not None:
            own[id(g)] += 1
            continue
        d, g = graph_for_symbol(graphs, s)
        if d <= 0 and s.get("clip"):
            other[id(g)].append(s)
    drop = set()
    for gid, outs in other.items():
        if own[gid] >= 10 and len(outs) >= 100 and len(outs) > 2 * own[gid]:
            drop.update(id(s) for s in outs)
    return drop


def drop_plot_backgrounds(symbols, graphs):
    """A filled square spanning 90% or more of a graph's plot box both ways
    is the plot's background, not a marker.  matplotlib fills each axes
    with a white rectangle; in a figure of two panels side by side
    (mpl-line-errorbars) that rectangle is nearly square, so it passed for
    a 200 pt marker, and a graph with a marker reports no line vertices:
    the page gave no points at all.  (Too large to be reported anyway: the
    size limit on markers is applied only when rows are written.)"""
    def background(s):
        if s["shape"] not in ("square", "rectangle") or not s.get("filled"):
            return False
        for g in graphs:
            x0, y0, x1, y1 = g["rect"]
            if (s["size"] >= 0.9 * (x1 - x0) and s["size"] >= 0.9 * (y1 - y0)
                    and x0 <= s["cx"] <= x1 and y0 <= s["cy"] <= y1):
                return True
        return False
    return [s for s in symbols if not background(s)]


def pattern_dash_paths(paths):
    """The dashes of a patterned line drawn as small filled quadrilaterals
    are no markers: logpaper5Rediscoveries-007 (Acrobat Distiller from
    PScript5) draws its dotted D-Pareto curve as 52 small pieces turned
    along the curve - rectangles 0.78 x 1.5 pt, rhombi of 1.07 pt sides,
    longer parallelograms - so that they read as squares, diamonds and
    rectangles.  A colour's fill-only four-sided pieces in the drawing (no
    larger than 2 pt: MollickMooresLawIEEE-009's diamonds, 2.9 to 3.5 pt
    with corners on a coarse grid, vary in shape too; not only those taken
    for markers) form runs: pieces within 6 pt of one another, not in a
    crowd of more than 12 in 6 pt square.  A run is dashes when four or
    more of it stand on one level line (a legend's line sample), or when it
    has eight or more pieces of three or more different shapes (side
    lengths to 0.1 pt and the direction of the longer side to 10 degrees:
    markers of a series are drawn alike, and two series of one colour make
    two shapes), two in five of them or more oblong (sides 1.6 : 1 or more;
    a network's nodes, squares at all angles, are not: none of
    2204.07073-010's 60 000).  A piece within 8 pt of a run's dash (a dot
    left over at its end) is a dash too.  Returns the paths' idx."""
    pieces = {}                       # colour -> [(cx, path idx, shape)]
    for p in paths:
        if not p["fill"] or p["stroke"]:
            continue
        # (a path of many pieces - a whole dotted line in one path,
        # cheyette2024limited-011 - counts only as a straight run of dots:
        # Excel draws all the markers of a series in one path)
        many = len(p["subpaths"]) > 1
        for sp in p["subpaths"]:
            if len(sp["segs"]) not in (3, 4) or any(g[0] != "l" for g in sp["segs"]):
                if many:
                    break
                continue
            q = ([sp["start"]] + [g[-1] for g in sp["segs"]])[:4]
            xs = [v[0] for v in q]
            ys = [v[1] for v in q]
            if max(max(xs) - min(xs), max(ys) - min(ys)) > 2.0:
                continue
            e = [(q[(i + 1) % 4][0] - q[i][0], q[(i + 1) % 4][1] - q[i][1]) for i in range(4)]
            ln = [math.hypot(*v) for v in e]
            k = 0 if ln[0] >= ln[1] else 1
            ang = round(math.degrees(math.atan2(e[k][1], e[k][0])) % 180 / 10) % 18
            shape = (round(min(ln[0], ln[1]), 1), round(max(ln[0], ln[1]), 1), ang)
            slender = max(ln[0], ln[1]) >= 1.6 * max(1e-9, min(ln[0], ln[1]))
            pieces.setdefault(p["fill_rgb"], []).append(
                (sum(xs) / 4, p["idx"], shape, sum(ys) / 4, slender, many))

    def line_like(run):
        # a line sample: four or more pieces on one level line (a legend's
        # dotted sample, its pieces alike)
        if len(run) >= 4 and max(x[3] for x in run) - min(x[3] for x in run) <= 0.5:
            return True
        if straight_dots(run):
            return True
        # dashes are mostly oblong (73% of logpaper5Rediscoveries-007's,
        # turned along the curve); scattered nodes of a network are squares
        # at all angles (none of 2204.07073-010's 60 000 is oblong)
        if len(run) < 8 or len({x[2] for x in run}) < 3:
            return False
        return sum(1 for x in run if x[4]) >= 0.4 * len(run)

    def straight_dots(run):
        # a dotted straight line in any direction (cheyette2024limited-011's
        # diagonal y = x: 107 squares of 0.5 pt sides, 2.07 pt apart): eight
        # or more alike pieces on one line (within 0.2 pt), close together
        # (the usual gap at most 5 sides) and evenly spaced (four in five
        # gaps within 25% of the usual one, or twice it: a dot hidden under
        # a marker)
        if len(run) < 8 or len({x[2] for x in run}) > 2:
            return False
        pts = [(x[0], x[3]) for x in run]
        mx = sum(p[0] for p in pts) / len(pts)
        my = sum(p[1] for p in pts) / len(pts)
        sxx = sum((p[0] - mx) ** 2 for p in pts)
        syy = sum((p[1] - my) ** 2 for p in pts)
        sxy = sum((p[0] - mx) * (p[1] - my) for p in pts)
        ang = 0.5 * math.atan2(2 * sxy, sxx - syy)
        ux, uy = math.cos(ang), math.sin(ang)
        if any(abs(-(p[0] - mx) * uy + (p[1] - my) * ux) > 0.2 for p in pts):
            return False
        along = sorted((p[0] - mx) * ux + (p[1] - my) * uy for p in pts)
        gaps = [b - a for a, b in zip(along, along[1:])]
        g = median(gaps)
        size = max(run[0][2][1], 0.1)
        if g <= 0 or g > 5 * size:
            return False
        even = sum(1 for d in gaps if abs(d - g) <= 0.25 * g or abs(d - 2 * g) <= 0.25 * g)
        return even >= 0.8 * len(gaps)

    drop = set()
    for rgb, ps in list(pieces.items()):
        # a path of many pieces is judged on its own: a straight dotted line
        by_path = {}
        for x in ps:
            if x[5]:
                by_path.setdefault(x[1], []).append(x)
        for idx, run in by_path.items():
            if straight_dots(sorted(run)):
                drop.add(idx)
        pieces[rgb] = [x for x in ps if not x[5]]
    for ps in pieces.values():
        # pieces within 6 pt of one another make one run (a legend's dotted
        # sample is a run apart from the curve it crosses in x)
        sets = DisjointSets(len(ps))
        cells = {}
        for i, x in enumerate(ps):
            cells.setdefault((int(x[0] // 6), int(x[3] // 6)), []).append(i)
        for (cx, cy), idxs in cells.items():
            if len(idxs) > 12:
                continue                  # crowded: no dotted line (network nodes)
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for j in cells.get((cx + dx, cy + dy), ()):
                        for i in idxs:
                            if i < j and math.hypot(ps[i][0] - ps[j][0], ps[i][3] - ps[j][3]) <= 6.0:
                                sets.union(j, i)
        mine = set()
        for group in sets.groups():
            run = sorted(ps[i] for i in group)
            if line_like(run):
                mine.update(x[1] for x in run)
        if mine:
            # (the run's pieces filed in cells of 8 pt: every piece against
            # every one of a long run took tens of seconds)
            near = PointGrid(8.0)
            for y in ps:
                if y[1] in mine:
                    near.add(y, y[0], y[3])
            for x in ps:
                if x[1] not in mine and any(math.hypot(x[0] - y[0], x[3] - y[3]) <= 8.0
                                            for y in near.near(x[0], x[3])):
                    mine.add(x[1])
        drop |= mine
    return drop


def drop_pattern_dashes(symbols, paths):
    """Symbols drawn by the dashes of a patterned line (pattern_dash_paths)
    are no markers."""
    drop = pattern_dash_paths(paths)
    return [s for s in symbols if s["idx"] not in drop]


def add_dash_markers(symbols, paths, graphs):
    """Thin filled rectangles as markers: Excel's dash marker ("-"), a
    small oblong 3.1 x 0.8 pt in logpaper5Rediscoveries-007, with an error
    bar through each.  Oblongs are otherwise no markers (boxes, bars,
    rules, pieces of lines), so a set must show them to be: five or more
    filled axis-aligned rectangles of one size (within 0.2 pt) and colour,
    no larger than 6 pt, longer than wide (aspect under 0.85; squares are
    markers already), centred inside one graph's box and not touching one
    another, nor dashes of a patterned line (pattern_dash_paths: the
    dotted curves' flat dashes are oblongs of one size too), in a graph
    with no other markers, none standing on the graph's bottom edge (bars:
    S1383762124002030's narrow bars are oblongs of one size too).  They are
    added as rectangles marked as markers (rows keep them)."""
    have = {s["idx"] for s in symbols} | pattern_dash_paths(paths)
    cand = []
    for p in paths:
        if not p["fill"] or p["idx"] in have or len(p["subpaths"]) != 1:
            continue
        sp = p["subpaths"][0]
        if len(sp["segs"]) not in (3, 4) or any(g[0] != "l" for g in sp["segs"]):
            continue
        q = ([sp["start"]] + [g[-1] for g in sp["segs"]])[:4]
        if len(q) < 4:
            continue
        if not all(abs(a[0] - b[0]) < 1e-3 or abs(a[1] - b[1]) < 1e-3 for a, b in zip(q, q[1:] + q[:1])):
            continue
        xs = [v[0] for v in q]
        ys = [v[1] for v in q]
        w, h = max(xs) - min(xs), max(ys) - min(ys)
        if min(w, h) <= 0 or max(w, h) > 6.0 or min(w, h) / max(w, h) >= 0.85:
            continue
        cand.append((round(w / 0.2), round(h / 0.2), p["fill_rgb"],
                     (min(xs), min(ys), max(xs), max(ys)), p))
    groups = {}
    for c in cand:
        groups.setdefault(c[:3], []).append(c)
    out = list(symbols)
    for g in graphs:
        x0, y0, x1, y1 = g["rect"]
        if any(x0 <= s["cx"] <= x1 and y0 <= s["cy"] <= y1 for s in symbols
               if s["shape"] != "rectangle"):
            continue                      # the graph has markers of its own
        for cs in groups.values():
            mine = [c for c in cs if x0 <= (c[3][0] + c[3][2]) / 2 <= x1 and y0 <= (c[3][1] + c[3][3]) / 2 <= y1]
            if len(mine) < 5 or any(abs(c[3][1] - y0) <= 0.5 for c in mine):
                continue
            boxes = [c[3] for c in mine]
            loose = [c for c in mine if not any(
                b is not c[3] and b[0] <= c[3][2] + 0.1 and c[3][0] <= b[2] + 0.1 and
                b[1] <= c[3][3] + 0.1 and c[3][1] <= b[3] + 0.1 for b in boxes)]
            if len(loose) < 5:
                continue
            for _, _, rgb, b, p in loose:
                out.append({"shape": "rectangle", "cx": (b[0] + b[2]) / 2, "cy": (b[1] + b[3]) / 2,
                            "size": max(b[2] - b[0], b[3] - b[1]), "filled": True, "rgb": rgb,
                            "idx": p["idx"], "clip": p.get("clip"), "res": p.get("res"),
                            "tool": p.get("tool"), "marker": True})
    return out


def mark_legend_frames(symbols, paths, graphs):
    """A legend's keys go to one graph together: the one nearest the
    legend's frame, not each the graph nearest itself.  3576042-018
    (matplotlib, six panels in three rows) puts each legend, framed, under
    its graph's x axis label; the frame's lower row of keys lies nearer
    the top of the graph below.  A symbol outside every graph gets
    "frame", the box of the smallest closed path holding it (no larger
    than a third of the nearest graph, and holding no graph) that holds two
    or more such symbols."""
    from .graphs import _graphs_at
    if not graphs:
        return symbols
    out = [s for s in symbols if not _graphs_at(graphs, s["cx"], s["cy"])]
    if len(out) < 2:
        return symbols
    gmax = max(rect_area(g["rect"]) for g in graphs)
    boxes = []
    for p in paths:
        for sp in p["subpaths"]:
            if not sp["closed"] and not p["fill"]:
                continue
            if len(sp["segs"]) < 3:
                continue
            b = bbox_of(vertices(sp))
            w, h = b[2] - b[0], b[3] - b[1]
            if w < 5 or h < 3 or w * h > gmax / 3:
                continue
            if any(rect_distance(b, (g["rect"][0] + g["rect"][2]) / 2, (g["rect"][1] + g["rect"][3]) / 2) == 0
                   for g in graphs):
                continue
            boxes.append(b)
    if not boxes:
        return symbols
    held = {}          # box -> how many symbols it holds (counted once per box)
    for s in out:
        if s.get("idx") is None:
            continue
        holding = [b for b in boxes if b[0] < s["cx"] < b[2] and b[1] < s["cy"] < b[3]
                   and not (b[2] - b[0] < 3 * s.get("size", 0) + 1)]
        if not holding:
            continue
        b = min(holding, key=lambda b: (b[2] - b[0]) * (b[3] - b[1]))
        key = tuple(b)
        if key not in held:
            held[key] = sum(1 for o in out if b[0] < o["cx"] < b[2] and b[1] < o["cy"] < b[3])
        if held[key] >= 2:
            s["frame"] = b
    return symbols


def fill_circles_under_dots(symbols, texts):
    """An open circle with a "\u25cf" character of its colour centred on it
    is a filled circle: Seongmin-PhD-044 (cairo) draws each ggplot outlier
    as a stroked circle and a black-circle glyph of the plot's font over it.
    The glyph's centre: the middle of its advance, half its up vector up
    (within 0.3 of the circle's size)."""
    dots = []
    for t in texts:
        if t["text"].strip() != "\u25cf" or not t.get("up"):
            continue
        (x0, y0), (x1, y1), (ux, uy) = t["p0"], t["p1"], t["up"]
        dots.append(((x0 + x1) / 2 + 0.5 * ux, (y0 + y1) / 2 + 0.5 * uy, t.get("rgb")))
    if not dots:
        return symbols
    grid = {}
    for k, (x, y, _) in enumerate(dots):
        grid.setdefault((int(x // 5), int(y // 5)), []).append(k)
    for s in symbols:
        if s["shape"] != "circle" or s["filled"]:
            continue
        tol = 0.3 * max(s.get("size", 0.0), 1.0)
        gx, gy = int(s["cx"] // 5), int(s["cy"] // 5)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for k in grid.get((gx + dx, gy + dy), ()):
                    x, y, rgb = dots[k]
                    if abs(x - s["cx"]) <= tol and abs(y - s["cy"]) <= tol and \
                            (rgb is None or s["rgb"] is None or
                             max(abs(a - b) for a, b in zip(rgb, s["rgb"])) <= 0.05):
                        s["filled"] = True
    return symbols


def merge_crossed_squares(symbols):
    """An open square and a plus of one colour and centre (within a tenth
    of the square's size; sizes within 15%) are one marker, the square with
    a plus in it (R's pch 12): wp_21_1036-019's "6 weeks from 18 weeks".
    Reported as "square-plus" (open)."""
    plus = {}
    for k, s in enumerate(symbols):
        if s["shape"] == "plus":
            plus.setdefault((round(s["cx"]), round(s["cy"])), []).append(k)
    if not plus:
        return symbols
    gone = set()
    for s in symbols:
        if s["shape"] != "square" or s["filled"]:
            continue
        size = s.get("size", 0.0)
        cx, cy = round(s["cx"]), round(s["cy"])
        for key in ((cx + i, cy + j) for i in (-1, 0, 1) for j in (-1, 0, 1)):
            hit = next((k for k in plus.get(key, ()) if k not in gone and
                        symbols[k]["rgb"] == s["rgb"] and
                        abs(symbols[k]["cx"] - s["cx"]) <= 0.1 * size and
                        abs(symbols[k]["cy"] - s["cy"]) <= 0.1 * size and
                        abs(symbols[k].get("size", 0.0) - size) <= 0.15 * size), None)
            if hit is not None:
                gone.add(hit)
                s["shape"] = "square-plus"
                break
    return [s for k, s in enumerate(symbols) if k not in gone]

"""Labels of groups of bars: a second row of labels along the x axis.

A bar chart may label its x axis twice (Memory_systems_cacheDRAMdisk-051):
the axis ticks carry one label each (the system bandwidth, 0.8 ... 25.6),
while each group of bars between them carries a name of its own (its
channel configuration, "1 chan x 1 byte", slanted under the axis labels in
the GCC and BZIP charts; "1 x 8-bit x 100 Mhz", slanted above the bars
inside the PERL chart).  Each bar is given its group's name ("x_group").
"""

from .geometry import median

# the end of a slanted label that points at its group: 0.35 em up from the
# baseline (as for slanted category labels, labels._label_anchor)
_UP = 0.35


def bar_groups(bars):
    """Bars side by side in groups: [(left edge, right edge, [bars])], left
    to right.  Bars whose centres lie closer than twice a bar's width (and
    than 1.5 times the usual spacing between neighbours) belong together;
    stacked segments share their bar's centre."""
    if not bars:
        return []
    w = median(b["size"] for b in bars)
    xs = sorted({round(b["cx"], 2) for b in bars})
    gaps = [b - a for a, b in zip(xs, xs[1:])]
    if not gaps:
        return []
    cut = max(2.0 * w, 1.5 * median(gaps))
    runs, cur = [], [xs[0]]
    for x in xs[1:]:
        if x - cur[-1] > cut:
            runs.append(cur)
            cur = [x]
        else:
            cur.append(x)
    runs.append(cur)
    out = []
    for r in runs:
        lo, hi = r[0] - w / 2, r[-1] + w / 2
        out.append((lo, hi, [b for b in bars if lo - 0.01 <= b["cx"] <= hi + 0.01]))
    return out


def _anchor(t, below):
    """Where along x a label points at its group: the middle of a level
    label; for a slanted or turned one, the middle of the end nearest the
    bars (its upper end under the axis, its lower end above the bars)."""
    if not t.get("rotated"):
        return t["center"][0]
    up = t.get("up") or (0.0, 0.0)
    ends = [(p[0] + _UP * up[0], p[1] + _UP * up[1]) for p in (t["p0"], t["p1"])]
    end = max(ends, key=lambda e: e[1]) if below else min(ends, key=lambda e: e[1])
    return end[0]


def label_bar_groups(g, bars, texts):
    """Name the groups of bars of graph g from a row of labels along its x
    axis that are not the axis's own labels: three or more texts (words,
    not bare numbers) of one kind - all level, or all slanted alike (within
    30 degrees) - each pointing at a different group of two or more bars,
    either under the plot (within 8 label sizes of its bottom) or inside it
    (where the tallest bars of a group may reach past its name).  Sets b["x_group"] on the bars of each named group.
    Returns the number of groups named."""
    groups = [gr for gr in bar_groups(bars) if len({round(b["cx"], 2) for b in gr[2]}) >= 2]
    if len(groups) < 3:
        return 0
    x0, y0, x1, y1 = g["rect"]
    own = {id(tx) for a in ("x", "y") for _, tx in g[a].get("labels", ())}
    size = median([tx.get("size") or 1.0 for a in ("x", "y") for _, tx in g[a].get("labels", ())]
                  or [1.0])
    spacing = min(b[0] - a[1] for a, b in zip(groups, groups[1:]))
    cands = []
    for t in texts:
        s = (t.get("text") or "").strip()
        if not s or id(t) in own or len(s) > 40 or t.get("value") is not None or \
                not any(ch.isalpha() for ch in s):
            continue
        ts = t.get("size") or 1.0
        if ts > 1.5 * size:
            continue                                   # titles
        cy = t["center"][1]
        below = cy < y0
        if below and cy < y0 - 8 * size:
            continue
        if not below and (cy > y1 or t["bbox"][1] < min(b["base"] for b in bars if "base" in b)):
            continue
        a = _anchor(t, below)
        if not x0 - ts <= a <= x1 + ts:
            continue
        ang = abs(t.get("angle", 0.0)) % 180 if t.get("rotated") else 0.0
        cands.append((a, below, ang, t))
    best = []
    for side in (True, False):
        for kind in ("level", "slanted"):
            row = [c for c in cands if c[1] == side and (c[2] == 0.0) == (kind == "level")]
            if kind == "slanted" and row:
                ma = median(c[2] for c in row)
                row = [c for c in row if abs(c[2] - ma) <= 30]
            if len(row) > len(best):
                best = row
    if len(best) < 3:
        return 0
    # each label to the nearest group (by its anchor's distance from the
    # group's span), greedily, nearest first; within half the gap between
    # groups (or a label size)
    reach = max(0.5 * spacing, size)
    pairs = []
    for a, _below, _ang, t in best:
        for k, (lo, hi, _bs) in enumerate(groups):
            d = max(lo - a, a - hi, 0.0)
            if d <= reach:
                pairs.append((d, k, id(t), t))
    pairs.sort(key=lambda p: (p[0], p[1]))
    used_g, used_t, got = set(), set(), {}
    for d, k, tid, t in pairs:
        if k in used_g or tid in used_t:
            continue
        used_g.add(k)
        used_t.add(tid)
        got[k] = t
    if len(got) < 3 or len(got) < 0.6 * len(best):
        return 0
    for k, t in got.items():
        name = " ".join(t["text"].split())
        for b in groups[k][2]:
            b["x_group"] = name
    return len(got)


def group_categories(g, bars):
    """On a category x axis whose labels each stand for a set of groups of
    bars (Memory_systems_cacheDRAMdisk-051: a bandwidth centred under the
    one to eight channel configurations that give it), a group belongs to
    one category as a whole: between two neighbouring category labels the
    sets part at the widest gap between groups (a bar of the first group of
    a set may lie nearer the previous label than its own).  Sets
    b["x_category"] (and its place along the axis, b["x_rank"]) on every
    bar of such groups.  Only when there are more
    groups (of two or more bars) than categories."""
    m = g["x"]["map"]
    if m.get("kind") != "nominal":
        return
    ticks = sorted(m["ticks"])
    groups = [gr for gr in bar_groups(bars) if len({round(b["cx"], 2) for b in gr[2]}) >= 2]
    if len(ticks) < 2 or len(groups) <= len(ticks):
        return
    cuts = []
    for (ca, _), (cb, _) in zip(ticks, ticks[1:]):
        # gaps between consecutive groups lying between the two labels
        gaps = [(b[0] - a[1], (a[1] + b[0]) / 2) for a, b in zip(groups, groups[1:])
                if ca <= (a[1] + b[0]) / 2 <= cb and a[0] <= cb and b[1] >= ca]
        cuts.append(max(gaps)[1] if gaps else (ca + cb) / 2)
    for lo, hi, bs in groups:
        c = (lo + hi) / 2
        k = sum(1 for x in cuts if x < c)
        for b in bs:
            b["x_category"] = ticks[k][1]
            b["x_rank"] = k


__all__ = ["bar_groups", "group_categories", "label_bar_groups"]

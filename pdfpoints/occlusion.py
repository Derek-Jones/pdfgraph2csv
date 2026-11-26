"""What is hidden: text and glyph outlines painted over by a later opaque
rectangle or image.  Authors "edit" labels by covering them with a white
box and writing new text on top (Excel graphs whose values beyond an axis
break were changed this way); reading the covered text as well would give
two labels at one tick, or labels the reader never sees.
"""

import math

from .context import PAGE
from .geometry import rect_of


def cover_rects(paths, images):
    """Opaque rectangles and images: [(bbox, drawing step)].  Images drawn
    with a mask (a translucent watermark) are not in `images`: they hide
    nothing.  Boxes under 0.5 pt across are rules, not covers.  A box hides
    only what lies within its clipping box (2305.15675v1-015: the bars of a
    log-scale histogram run down to y = -13 826, clipped to the plot, over
    the x tick labels below it)."""
    covers = [(b, i) for b, i in images]
    for p in paths:
        if p["fill"] and p.get("opaque", True):
            for sp in p["subpaths"]:
                b = rect_of(sp)
                # (and within its form's box: 3832783.3834484-004's white
                # page boxes, each in a form showing one chart of three)
                for clip in (p.get("clip"), p.get("form_box")):
                    if b and clip:
                        b = (max(b[0], clip[0]), max(b[1], clip[1]), min(b[2], clip[2]), min(b[3], clip[3]))
                if b and b[2] - b[0] > 0.5 and b[3] - b[1] > 0.5:
                    covers.append((b, p["idx"]))
    return covers


class CoverIndex:
    """Which covers (painted after drawing step `idx`) hold a point: a grid
    of 20 pt cells, since a page may hold thousands of glyphs and boxes."""
    MAX_CELLS = 10000                 # bigger covers are checked one by one

    def __init__(self, covers, cell=20.0):
        self.cell, self.grid, self.big = cell, {}, []
        for b, i in covers:
            nx = int(b[2] // cell) - int(b[0] // cell) + 1
            ny = int(b[3] // cell) - int(b[1] // cell) + 1
            if nx * ny > self.MAX_CELLS:  # e.g. a degenerate box 10^9 points wide
                self.big.append((b, i))
                continue
            for gx in range(int(b[0] // cell), int(b[2] // cell) + 1):
                for gy in range(int(b[1] // cell), int(b[3] // cell) + 1):
                    self.grid.setdefault((gx, gy), []).append((b, i))

    def over(self, x, y, idx):
        cands = self.grid.get((int(x // self.cell), int(y // self.cell)), ())
        return [i for b, i in (list(cands) + self.big if self.big else cands)
                if i > idx and b[0] <= x <= b[2] and b[1] <= y <= b[3]]


def drop_hidden_glyphs(texts, covers):
    """Remove glyphs painted over by a later cover (see cover_rects).  The
    covers that hide text are noted in PAGE.hiding_paths: they are boxes,
    not square markers.  A text partly hidden keeps its visible runs of
    glyphs, split into words."""
    if not covers:
        return texts
    last = max(i for _, i in covers)
    ix = CoverIndex(covers)
    out = []
    for t in texts:
        if t["idx"] > last:
            out.append(t)
            continue
        ux, uy = t["up"]
        keep = []
        for _c, a, e in t["glyphs"]:
            cx = (a[0] + e[0]) / 2 + 0.5 * ux
            cy = (a[1] + e[1]) / 2 + 0.5 * uy
            hid = ix.over(cx, cy, t["idx"])
            PAGE.hiding_paths.update(hid)
            keep.append(not hid)
        if all(keep):
            out.append(t)
            continue
        # rebuild the visible runs of glyphs as separate texts
        runs, cur = [], []
        for g, k in zip(t["glyphs"], keep):
            if k:
                cur.append(g)
            elif cur:
                runs.append(cur)
                cur = []
        if cur:
            runs.append(cur)
        em = t["size"] or 1.0
        for run in runs:
            # split at word gaps too: the remains of a list of labels
            words, w = [], [run[0]]
            for g0, g1 in zip(run, run[1:]):
                if math.hypot(g1[1][0] - g0[2][0], g1[1][1] - g0[2][1]) > 0.15 * em:
                    words.append(w)
                    w = []
                w.append(g1)
            words.append(w)
            for w in words:
                txt = "".join(c for c, _, _ in w).strip()
                if txt:
                    out.append(dict(t, text=txt, p0=w[0][1], p1=w[-1][2], glyphs=w))
    return out


def drop_hidden_paths(paths):
    """Remove the paths of a drawing placed several times, each time
    through a window: forms with the same content but different boxes,
    each showing a part of it.  A path of such a form lying wholly outside
    the form's box (by more than 0.5 pt) is not seen.  3832783.3834484-004
    places one drawing of three Excel charts in three forms, each form's
    box showing one chart; read whole, each chart came three times,
    shifted, and no graph was found.  Paths of other forms outside their
    boxes stay: marks clipped out of view are reported (plus-symbols-log-
    axes, ESEUR-intro)."""
    from .geometry import subpath_bbox
    boxes = {}
    for p in paths:
        if p.get("form_key") and p.get("form_box"):
            boxes.setdefault(p["form_key"], set()).add(tuple(round(v, 1) for v in p["form_box"]))
    windowed = {k for k, v in boxes.items() if len(v) >= 2}
    if not windowed:
        return paths
    out = []
    for p in paths:
        f = p.get("form_box")
        if p.get("form_key") in windowed and f and p["subpaths"]:
            bb = [subpath_bbox(sp) for sp in p["subpaths"]]
            b = [min(v[0] for v in bb), min(v[1] for v in bb), max(v[2] for v in bb), max(v[3] for v in bb)]
            if b[0] > f[2] + 0.5 or b[2] < f[0] - 0.5 or b[1] > f[3] + 0.5 or b[3] < f[1] - 0.5:
                continue
        out.append(p)
    return out

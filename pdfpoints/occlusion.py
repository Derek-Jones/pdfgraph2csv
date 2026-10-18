"""What is hidden: text and glyph outlines painted over by a later opaque
rectangle or image (labels "edited" by covering them with a white box).
"""

import math

from .context import PAGE
from .geometry import rect_of


def cover_rects(paths, images):
    """Opaque rectangles and images: [(bbox, drawing step)]."""
    covers = [(b, i) for b, i in images]
    for p in paths:
        if p["fill"] and p.get("opaque", True):
            for sp in p["subpaths"]:
                b = rect_of(sp)
                if b and b[2] - b[0] > 0.5 and b[3] - b[1] > 0.5:
                    covers.append((b, p["idx"]))
    return covers


class CoverIndex:
    """Which covers (painted after drawing step `idx`) hold a point."""
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


def drop_hidden_glyphs(texts, paths, images):
    """Remove glyphs painted over by a later opaque rectangle or image.
    Labels are sometimes 'edited' by covering them with a white box and
    writing new text on top (e.g. the values beyond an axis break)."""
    covers = cover_rects(paths, images)
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
        for c, a, e in t["glyphs"]:
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

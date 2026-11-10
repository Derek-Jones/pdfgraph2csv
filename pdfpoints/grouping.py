"""Grouping helpers: disjoint sets (union-find), used to gather glyph
outlines into words and stroke pieces into crosses, and a uniform grid of
boxes for finding the neighbours of a shape among many (pages can hold
hundreds of thousands of shapes)."""

import math


class DisjointSets:
    """Union-find over the items 0..n-1."""

    def __init__(self, n):
        self.parent = list(range(n))

    def find(self, i):
        """The representative of i's set (with path halving)."""
        parent = self.parent
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(self, i, j):
        """Merge the sets of i and j (j's set joins i's)."""
        self.parent[self.find(j)] = self.find(i)

    def groups(self):
        """The sets as lists of items, in order of their first item."""
        out = {}
        for i in range(len(self.parent)):
            out.setdefault(self.find(i), []).append(i)
        return list(out.values())


class BoxGrid:
    """Boxes (x0, y0, x1, y1) filed in square cells of side `cell`, so that
    the boxes near a point or box are found without looking at all of
    them.  A box is filed in every cell it touches."""

    def __init__(self, cell):
        self.cell = max(cell, 1e-6)
        self.cells = {}

    def _span(self, x0, y0, x1, y1):
        c = self.cell
        return (range(int(math.floor(x0 / c)), int(math.floor(x1 / c)) + 1),
                range(int(math.floor(y0 / c)), int(math.floor(y1 / c)) + 1))

    def add(self, item, box):
        xs, ys = self._span(*box)
        cells = self.cells
        for gx in xs:
            for gy in ys:
                cells.setdefault((gx, gy), []).append(item)

    def near(self, box, reach=0.0):
        """The items filed in the cells that `box` grown by `reach` touches
        (a superset of those within `reach`; each item once)."""
        xs, ys = self._span(box[0] - reach, box[1] - reach, box[2] + reach, box[3] + reach)
        cells = self.cells
        out = set()
        if len(xs) * len(ys) > len(cells):
            # a big area over a sparse grid: walk the occupied cells instead
            x0, x1, y0, y1 = xs.start, xs.stop, ys.start, ys.stop
            for (gx, gy), got in cells.items():
                if x0 <= gx < x1 and y0 <= gy < y1:
                    out.update(got)
            return out
        for gx in xs:
            for gy in ys:
                got = cells.get((gx, gy))
                if got:
                    out.update(got)
        return out

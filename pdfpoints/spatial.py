"""Spatial indexes and grouping, shared by every step.

Pages can hold hundreds of thousands of shapes, and a step that compares
every shape with every other takes minutes (ESEUR-slowpages, 2602.03839v2-
029, gopinath2014mutations-004, BehavioralNetworkScience-319: each was
fixed with an index of its own).  The standard indexes here:

  SortedIndex   items sorted by one coordinate: those whose key lies in a
                range (bisection), in key order, ties in the items' order
  PointGrid     items at points filed in square cells: those in the cells
                around a point
  BoxGrid       boxes filed in every cell they touch: those near a box
  DisjointSets  union-find, to gather pieces into groups
  PageIndex     the indexes of one page, each built once on first use and
                shared by the steps that need it (page.index)

Callers test the exact condition themselves: an index gives a superset.
"""

import bisect
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
        return (range(math.floor(x0 / c), math.floor(x1 / c) + 1),
                range(math.floor(y0 / c), math.floor(y1 / c) + 1))

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


class PointGrid:
    """Items at points filed in square cells of side `cell`: near(x, y)
    gives those in the cells around (x, y) - the 3 x 3 block, or more
    rings of cells - cell by cell, column by column (dx outer, dy inner),
    each cell in the order its items were filed.  Callers check the exact
    distance themselves."""

    def __init__(self, cell):
        self.cell = cell
        self.cells = {}

    def key(self, x, y):
        c = self.cell
        return int(x // c), int(y // c)

    def add(self, item, x, y):
        self.cells.setdefault(self.key(x, y), []).append(item)

    def near(self, x, y, rings=1):
        gx, gy = self.key(x, y)
        cells = self.cells
        for dx in range(-rings, rings + 1):
            for dy in range(-rings, rings + 1):
                got = cells.get((gx + dx, gy + dy))
                if got:
                    yield from got


class SortedIndex:
    """`items` sorted by `key(item)` (a stable sort: items with equal keys
    keep their order).  `between(lo, hi)` gives, in that order, the items
    whose key k has lo <= k <= hi (lo < k with lo_open, k < hi with
    hi_open)."""

    __slots__ = ("keys", "items")

    def __init__(self, items, key):
        pairs = sorted(((key(it), n) for n, it in enumerate(items)), key=lambda p: p[0])
        items = list(items)
        self.keys = [k for k, _ in pairs]
        self.items = [items[n] for _, n in pairs]

    def __len__(self):
        return len(self.items)

    def span(self, lo, hi, lo_open=False, hi_open=False):
        """(start, stop): the positions in `items` of the keys in the range."""
        a = (bisect.bisect_right if lo_open else bisect.bisect_left)(self.keys, lo)
        b = (bisect.bisect_left if hi_open else bisect.bisect_right)(self.keys, hi)
        return a, b

    def between(self, lo, hi, lo_open=False, hi_open=False):
        a, b = self.span(lo, hi, lo_open, hi_open)
        return self.items[a:b]


class PageIndex:
    """The spatial indexes of one page (page.index), each built once, on
    first use, and shared by the steps that need it.  An index is named
    and built from a collection (the page's paths, its texts, a list of
    symbols); it is rebuilt when asked for a different collection (a new
    list, or one whose length changed), so that a step never sees an
    index of a list it no longer uses."""

    def __init__(self, page):
        self.page = page
        self._built = {}                 # name -> (collection, its length, index)

    def get(self, name, source, build):
        """The index `name` of `source`, made by `build()` when not yet made
        for this very collection."""
        got = self._built.get(name)
        if got is not None and got[0] is source and got[1] == len(source):
            return got[2]
        index = build()
        self._built[name] = (source, len(source), index)
        return index

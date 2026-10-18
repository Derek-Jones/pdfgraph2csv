"""Grouping helper: disjoint sets (union-find), used to gather glyph
outlines into words and stroke pieces into crosses."""


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

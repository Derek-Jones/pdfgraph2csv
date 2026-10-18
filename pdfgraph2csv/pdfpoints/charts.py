"""Charts without markers: bars of bar charts / histograms and the
vertices of data lines (solid or dashed) of line charts.
"""

import math

from .geometry import axis_aligned, bbox_of, line_intersection


def find_bars(graph, paths):
    """Bars of a bar chart: filled axis-aligned rectangles standing on the
    graph's baseline (its x axis line, or the line of value 0).  Each bar is
    one data point at the middle of its top edge."""
    x0, y0, x1, y1 = graph["rect"]
    w, h = x1 - x0, y1 - y0
    bases = [y0]
    if graph["y"]["map"]["kind"] == "linear" and graph["y"]["map"]["a"]:
        yz = -graph["y"]["map"]["b"] / graph["y"]["map"]["a"]      # where value 0 is
        if y0 < yz < y1:
            bases.append(yz)
    tol = max(0.75, 0.005 * h)
    bars = []
    seen = set()
    for p in paths:
        if not p["fill"]:
            continue
        for sp in p["subpaths"]:
            if any(s[0] != "l" for s in sp["segs"]) or len(sp["segs"]) not in (3, 4):
                continue
            pts = [sp["start"]] + [s[1] for s in sp["segs"]]
            bx0, by0, bx1, by1 = bbox_of(pts)
            bw, bh = bx1 - bx0, by1 - by0
            if not all(abs(a[0] - b[0]) < 1e-3 or abs(a[1] - b[1]) < 1e-3
                       for a, b in zip(pts, pts[1:] + pts[:1])):
                continue                     # not an axis-aligned rectangle
            if bw <= 0.3 or bw > 0.25 * w or bh <= 0 or bx0 < x0 - tol or bx1 > x1 + tol:
                continue
            for base in bases:
                if abs(by0 - base) <= tol and by1 <= y1 + tol:
                    top = by1
                elif abs(by1 - base) <= tol and by0 >= y0 - tol and base != y0:
                    top = by0                # a bar going down from zero
                else:
                    continue
                key = (round(bx0, 2), round(bx1, 2), round(top, 2))
                if key in seen:
                    continue                 # fill and outline of one bar
                seen.add(key)
                bars.append({"shape": "bar", "cx": (bx0 + bx1) / 2, "cy": top, "size": bw,
                             "filled": True, "rgb": p["fill_rgb"], "idx": p["idx"]})
                break
    return bars


def find_line_series(graph, paths, keep_out=()):
    """Data lines of a line chart without markers.  Returns a list of
    series, each {"points": [(x, y), ...], "rgb", "style", "idx"}:
      * stroked polylines: their corners (pieces that continue each other
        are joined first);
      * dashed lines drawn as many small filled dashes: the dashes are
        chained and each corner is recovered where the dash direction
        changes.
    Axis-parallel straight lines (grid, axes, frames) are not data lines."""
    x0, y0, x1, y1 = graph["rect"]
    w, h = x1 - x0, y1 - y0
    tol = max(1.0, 0.01 * max(w, h))

    def inside(q):
        return x0 - tol <= q[0] <= x1 + tol and y0 - tol <= q[1] <= y1 + tol

    pieces = []                    # stroked polylines
    for p in paths:
        if not p["stroke"] or p["fill"] or p["idx"] in keep_out:
            continue
        for sp in p["subpaths"]:
            if sp["closed"] or not sp["segs"] or any(s[0] != "l" for s in sp["segs"]):
                continue
            pts = [sp["start"]] + [s[1] for s in sp["segs"]]
            if not all(inside(q) for q in pts):
                continue
            if len(pts) == 2 and axis_aligned(pts[0], pts[1]):
                continue           # grid lines, ticks, axes
            if all(axis_aligned(a, b) for a, b in zip(pts, pts[1:])):
                continue
            pieces.append({"pts": pts, "rgb": p["stroke_rgb"], "style": ("solid", round(p.get("lw", 0), 2)),
                           "idx": p["idx"]})
    # join pieces that continue each other (same colour, touching ends)
    series = []
    for pc in sorted(pieces, key=lambda pc: pc["idx"]):
        for s in series:
            if s["rgb"] == pc["rgb"] and s["style"] == pc["style"]:
                if math.hypot(s["pts"][-1][0] - pc["pts"][0][0], s["pts"][-1][1] - pc["pts"][0][1]) < 0.05:
                    s["pts"] += pc["pts"][1:]
                    break
                if math.hypot(pc["pts"][-1][0] - s["pts"][0][0], pc["pts"][-1][1] - s["pts"][0][1]) < 0.05:
                    s["pts"] = pc["pts"][:-1] + s["pts"]
                    break
        else:
            series.append({"pts": list(pc["pts"]), "rgb": pc["rgb"], "style": pc["style"],
                           "idx": pc["idx"]})
    # dashes drawn as small filled quadrilaterals
    dashes = {}
    for p in paths:
        if not p["fill"] or p["stroke"] or p["idx"] in keep_out:
            continue
        for sp in p["subpaths"]:
            if len(sp["segs"]) not in (3, 4) or any(s[0] != "l" for s in sp["segs"]):
                continue
            q = [sp["start"]] + [s[1] for s in sp["segs"]][:3]
            if not all(inside(v) for v in q):
                continue
            e = [math.hypot(q[(i + 1) % 4][0] - q[i][0], q[(i + 1) % 4][1] - q[i][1]) for i in range(4)]
            longs = max(e[0], e[1]), min(e[0], e[1])
            if longs[1] <= 0 or longs[0] / longs[1] < 2.5 or longs[0] > 0.1 * max(w, h):
                continue
            if e[0] >= e[1]:     # short sides are 1-2 and 3-0
                a = ((q[1][0] + q[2][0]) / 2, (q[1][1] + q[2][1]) / 2)
                b = ((q[3][0] + q[0][0]) / 2, (q[3][1] + q[0][1]) / 2)
            else:
                a = ((q[0][0] + q[1][0]) / 2, (q[0][1] + q[1][1]) / 2)
                b = ((q[2][0] + q[3][0]) / 2, (q[2][1] + q[3][1]) / 2)
            if axis_aligned(a, b) and abs(a[1] - b[1]) < 1e-3 and False:
                continue
            dashes.setdefault(p["fill_rgb"], []).append((min(a, b), max(a, b), p["idx"]))
    for rgb, ds in dashes.items():
        if len(ds) < 6:
            continue
        ds.sort()
        # gaps between dashes are short; the chain must run left to right
        gaps = sorted(ds[i + 1][0][0] - ds[i][1][0] for i in range(len(ds) - 1))
        if not gaps or gaps[len(gaps) // 2] > 0.05 * w:
            continue
        pts = [ds[0][0]]
        for (a1, b1, _), (a2, b2, _) in zip(ds, ds[1:]):
            d1 = (b1[0] - a1[0], b1[1] - a1[1])
            d2 = (b2[0] - a2[0], b2[1] - a2[1])
            ang = abs(math.atan2(d1[0] * d2[1] - d1[1] * d2[0], d1[0] * d2[0] + d1[1] * d2[1]))
            if ang > math.radians(2):
                v = line_intersection(a1, d1, a2, d2)
                if v and b1[0] - 0.1 <= v[0] <= a2[0] + 0.1:
                    pts.append(v)              # corner in the gap
                elif v and a1[0] <= v[0] <= b1[0]:
                    pts.append(v)              # corner inside a dash
        pts.append(ds[-1][1])
        # on a dense labelled x axis (dates, categories) every series has its
        # corners at the label positions: read the dashed line there, as
        # gentle bends between dashes are easy to miss
        xs_lab = sorted(t for t, _ in graph["x"].get("ticks", ()))
        if graph["x"]["map"]["kind"] != "log" and len(xs_lab) >= 6:
            chain = []
            for a, b, _ in ds:
                chain += [a, b]
            samp = []
            reach = 0.5 * min(b - a for a, b in zip(xs_lab, xs_lab[1:]))
            for xv in xs_lab:
                # a dash pattern may stop short of the line's last corner
                if not (chain[0][0] - reach <= xv <= chain[-1][0] + reach):
                    continue
                for (u, v) in zip(chain, chain[1:]):
                    if u[0] - 1e-9 <= xv <= v[0] + 1e-9 or (xv < chain[0][0] and u is chain[0]) \
                            or (xv > chain[-1][0] and v is chain[-1]):
                        f = 0.0 if v[0] == u[0] else (xv - u[0]) / (v[0] - u[0])
                        samp.append((xv, u[1] + f * (v[1] - u[1])))
                        break
            if len(samp) >= len(pts) - 1:
                pts = samp
        series.append({"pts": pts, "rgb": rgb, "style": ("dashed",), "idx": min(d[2] for d in ds)})
    out = []
    for s in series:
        pts = []
        for q in s["pts"]:
            if not pts or math.hypot(q[0] - pts[-1][0], q[1] - pts[-1][1]) > 0.05:
                pts.append(q)
        if len(pts) >= 3:
            out.append(dict(s, points=pts))
    return out

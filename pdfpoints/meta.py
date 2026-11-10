"""Records of the -meta file: one per graph."""

from .scales import map_value


def graph_meta(pno, graphs, rows):
    """One record per graph for the --meta file: page and graph number,
    title, figure number and caption, the number of data points reported,
    and the values at the lowest and highest labelled tick of each axis."""
    counts = {}
    for r in rows:
        counts[r["graph"]] = counts.get(r["graph"], 0) + 1
    out = []
    for g in graphs:
        m = {"page": pno, "graph": g["no"], "title": g["title"],
             "figure": g.get("figure", ""), "caption": g.get("caption", ""),
             "tool": g.get("tool", ""), "tool_guess": g.get("tool_guess", ""),
             "points": counts.get(g["no"], 0)}
        for k in ("x", "y"):
            m[k + "_tick_min"], m[k + "_tick_max"] = tick_range(g[k])
        k2 = "y2" if "y2" in g else "x2" if "x2" in g else None
        m["axis2"] = ("%s %s" % (k2[0], g["twin"]["sides"][1])) if k2 and g.get("twin") else ""
        m["axis2_tick_min"], m["axis2_tick_max"] = tick_range(g[k2]) if k2 else ("", "")
        out.append(m)
    return out


def tick_range(axis):
    """The values of an axis's lowest and highest labelled ticks (for a
    category axis the first and last category along it), with the axis
    multiplier (e.g. x10^-9) applied.  ("", "") if unknown."""
    m = axis.get("map")
    if not m:
        return "", ""
    if m["kind"] == "nominal":
        pos = sorted(m["ticks"], key=lambda tv: tv[0])
        return (pos[0][1], pos[-1][1]) if pos else ("", "")
    scale = 10.0 ** axis.get("multiplier", 0)
    ticks = [(c, v) for c, v in axis.get("ticks", ())
             if isinstance(v, (int, float)) and not isinstance(v, bool)]
    if not ticks:
        return "", ""
    vals = [v * scale for _, v in ticks]
    if m.get("n", len(ticks)) < len(ticks):
        # the fit set a misread label aside (e.g. "0.5" for -0.5): such a
        # tick's value comes from the mapping, rounded to the decimals of
        # the labels that fit
        mapped = [map_value(m, c) for c, _ in ticks]
        rng = m.get("range") or 1.0
        good = [abs(mv - v * scale) <= 0.02 * abs(rng) * scale for mv, v in zip(mapped, (v for _, v in ticks))]
        places = max((len(repr(float(v)).split(".")[1].rstrip("0")) for (c, v), ok in zip(ticks, good)
                      if ok and "e" not in repr(float(v))), default=6)
        vals = [v if ok else round(mv, min(places, 10))
                for v, mv, ok in zip(vals, mapped, good)]
    return min(vals), max(vals)

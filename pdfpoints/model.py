"""The records that pass between the steps, and the keys each may carry.

Paths, texts, symbols, axes and graphs are plain dicts (fast to make by
the hundred thousand, and cheap to copy with a change: dict(s, size=...)).
The TypedDicts below say which keys each kind of record may hold and what
they mean, for readers and for static checkers; they change nothing at run
time.  Every key is optional (total=False): steps add keys as they learn
more, and only the first few of each kind are always present.

With the environment variable PDFPOINTS_CHECK_MODEL set, the pipeline
checks the records at the boundaries between its steps (check_records)
and stops on a key that is not declared here: a misspelt key ("cy" for
"cx" is no typo, but "centre" for "center" is) would otherwise be read as
missing and give a wrong answer without an error.  The regression suite
is run once this way whenever a key is added.
"""

import os
from typing import Any, TypedDict


class Subpath(TypedDict, total=False):
    """One subpath of a painted path, in page coordinates."""
    start: tuple            # (x, y) of its first point
    segs: list              # [("l", (x, y)) | ("c", (x1, y1), (x2, y2), (x3, y3)), ...]
    closed: bool            # closed with h (or by being filled)
    _cls: Any               # memo: classify_subpath's result (symbols.py)
    _flat: Any              # memo: the subpath's vertices with curves flattened
    _thin: Any              # memo: thin_rect_line's result (a stroke drawn as an outline)


class Path(TypedDict, total=False):
    """A painted path (interpreter.py), in drawing order."""
    idx: int                # drawing step (shared numbering with texts and images)
    subpaths: list          # [Subpath]
    fill: bool
    stroke: bool
    fill_rgb: tuple         # (r, g, b), 0..1
    stroke_rgb: tuple
    opaque: bool            # fill alpha >= 0.99 (can hide what is under it)
    clip: tuple             # (x0, y0, x1, y1) of the clipping path's box, or None
    res: float              # coordinate resolution in page points (digits written)
    scale: float            # page points per unit of the drawing's own space
    style: tuple            # (dash kind, line width) of a stroke
    tool: str               # the program recorded for the form or document that drew it
    form_box: tuple         # /BBox of the form drawing it, in page coordinates
    form_key: str           # hash of the form's content (a form drawn through several windows)
    rebuilt: str            # made by the normalisation stage ("strip disc": a fan of triangles)
    painted: str            # "fill and stroke": two paths of one outline joined (normalise.py)


class Text(TypedDict, total=False):
    """A text item: a run of glyphs set together (interpreter.py), merged
    into words and labels (text.merge_texts), or read from outlines
    (outlined_text.py; a text of None is an unread outlined word)."""
    text: str
    value: float            # its number (text.parse_number), or None
    idx: int                # drawing step
    p0: tuple               # baseline start and end, page coordinates
    p1: tuple
    up: tuple               # the text's up direction, one font size long
    size: float             # font size in page points
    bbox: tuple             # (x0, y0, x1, y1)
    center: tuple           # middle of bbox
    rotated: bool           # not upright
    angle: float            # baseline angle, degrees
    font: str               # base font name
    rgb: tuple
    clip: tuple
    form_box: tuple
    glyphs: list            # [(char, start, end)] along the baseline (occlusion.py)
    date: bool              # the value was read as a date (decimal year)
    outlined: bool          # read from glyph outlines


class Symbol(TypedDict, total=False):
    """A mark that may be a data point: a marker, bar, line vertex, tile
    of a heat map, box-plot part ... (symbols.py, charts.py and others)."""
    shape: str              # circle, square, triangle ..., bar, stem, line, tile, area, errorbar, box-*
    cx: float               # the point, page coordinates
    cy: float
    size: float             # diameter / mean side (rows: --sizesymbol)
    w: float                # width and height of a bar, tile or face
    h: float
    filled: bool
    rgb: tuple              # the colour reported
    outline: bool           # an unfilled stroked rectangle taken for a bar (charts.py)
    paint_rgb: tuple        # fill colour of a filled-and-stroked marker
    outline_rgb: tuple      # its outline colour
    idx: int                # drawing step of its path
    last: int               # drawing step of its last piece (line series)
    clip: tuple             # clipping box: which graph it belongs to
    res: float              # coordinate resolution (Path.res)
    scale: float            # Path.scale
    tool: str               # Path.tool
    image: bool             # a small picture used as a marker
    picture: bool           # a heat-map cell read from a picture (colourbar.py)
    marker: bool            # a dash marker (thin rectangle) rather than a bar
    patch: bool             # a bar-legend swatch
    frame: tuple            # the legend frame round it (strays.mark_legend_frames)
    face_of: bool           # the face of a two-part marker (symbols.py)
    ring: bool              # an open circle drawn as a ring
    turned: bool            # a shape turned 45 degrees (a diamond's square)
    rebuilt: bool           # put together from fragments (fragments.py)
    confidence: float       # how sure the rebuilt circle is (rows: confidence column)
    horizontal: bool        # a horizontal bar
    base: float             # a bar's foot (the end opposite its value)
    base_y: float           # the foot of a stacked area band
    vbar: tuple             # (low, high) of a lone capped error bar
    label: str              # its data label (datalabels.py)
    value: float            # its colour-bar value (colourbar.py)
    x_group: str            # the group label of a bar (grouplabels.py)
    x_category: str         # its category in a group of categories
    x_rank: int             # its place in that group


class Axis(TypedDict, total=False):
    """An axis: tick marks, their labels and the map from page position to
    value (axes.py)."""
    orient: str             # "x" (ticks along x) or "y"
    pos: float              # position of the axis line across
    lo: float               # extent along
    hi: float
    ticks: list             # tick positions along
    tick_pos: list          # tick positions of the labelled ticks
    tick_len: float
    tick_unc: float         # uncertainty of the tick positions
    labels: list            # [(tick position, Text)]
    map: dict               # page position -> value: {"kind": linear | log | nominal | ..., ...}
    has_line: bool          # an axis line runs along the ticks
    inside: bool            # the ticks point into the plot
    label_ticks: bool       # ticks found from the labels alone
    low_labels: bool        # labels set below the plot for an axis on a zero line
    label_angle: float      # the labels' angle, degrees
    from_labels: bool       # placed by its labels
    multiplier: float       # a "x 10^3" written by the axis
    number_categories: bool # categories named by numbers
    shared: bool            # the scale of a labelled axis beside it in a row of panels (graphs.share_row_scales)


class Graph(TypedDict, total=False):
    """A graph: a pair of axes and the box they span (graphs.py), described
    for the meta file (pipeline.describe_graphs)."""
    rect: tuple             # the plot box (x0, y0, x1, y1)
    x: Axis
    y: Axis
    x2: Axis                # a second scale on the other side
    y2: Axis
    no: Any                 # graph number (renumbered; "" when it gives no rows)
    rot: int                # 0, 90, -90 or 180: the graph is turned
    title: str
    figure: str
    caption: str
    tool: str               # the program recorded as drawing it
    tool_guess: str         # styles.guess_tool
    paper: tuple            # the background box it is drawn on
    bg: int                 # drawing step of its plot background (-1: none)
    twin: dict              # a scale on both sides: {"axis", "sides", "titles"}
    twin_map: dict          # series name -> the scale it is read against
    twin_unsure: bool
    value_name: str         # the colour-bar column's name (--heatmap)


_DECLARED = {"path": set(Path.__annotations__), "subpath": set(Subpath.__annotations__),
             "text": set(Text.__annotations__), "symbol": set(Symbol.__annotations__),
             "axis": set(Axis.__annotations__), "graph": set(Graph.__annotations__)}

CHECKING = bool(os.environ.get("PDFPOINTS_CHECK_MODEL"))


def check_records(kind, records, where):
    """With PDFPOINTS_CHECK_MODEL set: raise on a key of a `kind` record
    ("path", "text", "symbol", ...) that is not declared above."""
    if not CHECKING:
        return
    known = _DECLARED[kind]
    for r in records:
        extra = set(r) - known
        if extra:
            raise KeyError("%s: %s record with undeclared keys %s" % (where, kind, sorted(extra)))

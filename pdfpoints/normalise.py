"""The normalisation stage: the drawing rewritten into one standard form.

The same thing is drawn many ways: a disc as Bezier arcs, a 20-gon, a fan
of thin triangles or the fragments of flattened transparency; a label as
text, as text in a Type 3 font, or as filled glyph outlines; a minus sign
as U+2212, a hyphen, a soft hyphen, an unnamed glyph or a drawn bar; a
drawing placed through several windows, or covered by an opaque box.
Between the interpreter (which records what is drawn) and the analysis
(which finds axes, graphs and data points), this stage rewrites those
variants into one form, so that the analysis meets each thing one way:

  text as it is seen      texts clipped out of view, drawn twice over or
                          painted over are dropped; paths outside their
                          form's window likewise
  discs                   fans of thin triangles become one filled circle
  axis-break wiggles      known before any glyph is read (they are none)
  outlined text           filled glyph outlines read as text items
                          (numbers by shape; unread words kept as blobs)
  fill and stroke         a shape filled and then stroked as two paths
                          becomes one path painted both ways
  words                   glyph runs merged into words and labels
  minus signs             drawn bars before numbers become their minus

Each step is a named `Normaliser` (the list NORMALISERS, in order), run on
a `Drawing`: the interpreter's record plus what the steps produce.  With
--debug (or PDFPOINTS_RULE_STATS) the tracer of rules.py reports, per
step, how many paths and texts it removed and added.

A new way of drawing something already handled is a new normaliser here,
not a change in the analysis.  (Steps that need the graphs - fragmented
circles of flattened transparency, which need the plot boxes to tell
round letters from markers - stay in the symbol rules of pipeline.py.)
"""

from .fragments import strip_discs_as_paths
from .occlusion import cover_rects, drop_clipped_texts, drop_hidden_glyphs, drop_hidden_paths
from .outlined_text import outlined_text
from .scales import find_break_marks
from .symbols import classify_subpath
from .text import attach_vector_minus, billions_not_bytes, drop_repeated_texts, merge_texts


class Drawing:
    """What the normalisers work on: the interpreter `it` (its paths and
    raw texts, rewritten in place), the page model, the boxes that hide
    what is under them (`covers`), and what the steps produce: `words`
    (the page's texts as read), `outlined` (texts read from outlines),
    `text_parts` (outline parts that are text), `read_parts` (those read
    as text) and `blobs` (unread outlined words)."""

    def __init__(self, it, page):
        self.it = it
        self.page = page
        self.covers = cover_rects(it.paths, it.images)
        self.words = None
        self.outlined = []
        self.text_parts = set()
        self.read_parts = set()
        self.blobs = []


class Normaliser:
    """One step of the normalisation stage: `run(drawing)` rewrites the
    drawing in place; `why` says what it does."""

    __slots__ = ("name", "run", "why")

    def __init__(self, name, run, why):
        self.name = name
        self.run = run
        self.why = why

    def __repr__(self):
        return "Normaliser(%r)" % self.name


def _drop_clipped_texts(d):
    d.it.texts = drop_clipped_texts(d.it.texts)


def _drop_repeated_texts(d):
    d.it.texts = drop_repeated_texts(d.it.texts)


def _drop_hidden_glyphs(d):
    d.it.texts = drop_hidden_glyphs(d.it.texts, d.covers, page=d.page)


def _drop_hidden_paths(d):
    d.it.paths = drop_hidden_paths(d.it.paths)


def _strip_discs(d):
    d.it.paths = strip_discs_as_paths(d.it.paths)


def _break_marks(d):
    d.page.break_marks = find_break_marks(d.it.paths)


def _outlined_text(d):
    d.outlined, d.text_parts = outlined_text(d.it.paths, d.blobs, d.covers, d.read_parts, page=d.page)
    # (parts of unread "words": a marker drawn as filled strokes may be
    # grouped as one - 1356058.1356080-007's 'x' of four filled half-arms)
    d.page.blob_parts = d.text_parts - d.read_parts


def fill_stroke_pairs(paths, text_parts=frozenset()):
    """A shape filled, then stroked as a separate path of the very same
    outline (or stroked, then filled), drawn one right after the other, is
    one path painted both ways, when it is a marker shape (_marker_outline):
    in the first one's place (drawing step),
    with the filled one's outline, fill and stroke colours both
    (no.ntnu_inspera_146721987_149459097-037 draws each of its 11 700
    markers so; Excel does too).  Parts read as text are left alone.
    Returns the paths."""
    out = []
    i, n = 0, len(paths)
    while i < n:
        a = paths[i]
        if i + 1 < n:
            b = paths[i + 1]
            if (b["idx"] == a["idx"] + 1 and a["fill"] != b["fill"] and a["stroke"] != b["stroke"]
                    and a["fill"] != a["stroke"] and _same_outline(a, b) and _marker_outline(a)
                    and not any((p["idx"], k) in text_parts for p in (a, b) for k in range(len(p["subpaths"])))):
                f, st = (a, b) if a["fill"] else (b, a)
                out.append(dict(f, idx=a["idx"], stroke=True, stroke_rgb=st["stroke_rgb"],
                                style=st.get("style"), painted="fill and stroke"))
                i += 2
                continue
        out.append(a)
        i += 1
    return out


_MARKER_MAX_PT = 20          # only marker-sized shapes (bars and frames are left as drawn)


def _marker_outline(p):
    """Is path p one closed marker shape, at most 20 pt (a circle, square,
    triangle, diamond ...: classify_subpath)?  A bar, a frame or a tick's
    rectangle filled and stroked apart is left as drawn: the analysis of
    axes and bars reads such pairs as they are (S1383762124002030-p6-7)."""
    if len(p["subpaths"]) != 1:
        return False
    c = classify_subpath(p["subpaths"][0])
    return c is not None and c["shape"] not in ("rectangle",) and c["size"] <= _MARKER_MAX_PT


def _same_outline(a, b):
    """Do paths a and b have the very same subpaths (not counting results
    cached on them)?"""
    return len(a["subpaths"]) == len(b["subpaths"]) and all(
        p["start"] == q["start"] and p["segs"] == q["segs"] and p["closed"] == q["closed"]
        for p, q in zip(a["subpaths"], b["subpaths"]))


def _fill_stroke(d):
    d.it.paths = fill_stroke_pairs(d.it.paths, d.text_parts)


def _words(d):
    d.words = merge_texts(d.it.texts) + merge_texts(d.outlined)


def _billions(d):
    billions_not_bytes(d.words)


def _vector_minus(d):
    attach_vector_minus(d.words, d.it.paths)


NORMALISERS = [
    Normaliser("drop_clipped_texts", _drop_clipped_texts,
               "text whose middle is outside its clipping box or form is not seen"),
    Normaliser("drop_repeated_texts", _drop_repeated_texts,
               "text drawn again in the same place is one text"),
    Normaliser("drop_hidden_glyphs", _drop_hidden_glyphs,
               "glyphs painted over by a later opaque box are not seen"),
    Normaliser("drop_hidden_paths", _drop_hidden_paths,
               "paths of a form drawn through several windows, outside the window they are drawn in"),
    Normaliser("strip_discs", _strip_discs,
               "a fan of thin triangles filling a disc is one filled circle"),
    Normaliser("break_marks", _break_marks,
               "axis-break wiggles, known before glyphs are read (they are none)"),
    Normaliser("outlined_text", _outlined_text,
               "filled glyph outlines read as text: numbers by shape, other words kept unread"),
    Normaliser("fill_stroke", _fill_stroke,
               "a shape filled, then stroked as a separate path of the same outline, is one path"),
    Normaliser("words", _words, "glyph runs merged into words and labels"),
    Normaliser("billions", _billions, "'2.00B' among millions is billions, not bytes"),
    Normaliser("vector_minus", _vector_minus, "a drawn bar just before a number is its minus sign"),
]


def normalise_page(it, page, tracer=None):
    """Run NORMALISERS on the interpreter's record of a page.  Returns the
    Drawing (its words, text_parts and blobs for the analysis)."""
    d = Drawing(it, page)
    for step in NORMALISERS:
        if tracer is not None and tracer.active:
            before = (list(d.it.paths), list(d.it.texts), list(d.words or ()))
            step.run(d)
            tracer.note_drawing(step, before, (d.it.paths, d.it.texts, d.words or ()))
        else:
            step.run(d)
    return d

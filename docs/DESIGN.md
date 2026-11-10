# How pdfgraph2csv works

`pdfgraph2csv.py` is a thin command-line wrapper; the work is done by the
`pdfpoints` package next to it.  It uses four packages:

* **pikepdf** opens the file (`document.py`): qpdf repairs damaged files,
  decrypts and decodes streams; streams that cannot be decoded are emptied
  with a warning; the cleaned file is handed, in memory, to pdfminer.six.
* Content streams are tokenized by `tokenizer.py`, one operator at a time
  (much faster than pdfminer.six's parser, and unlike qpdf's
  `parse_content_stream` it does not hold a whole stream as objects in
  memory: a 92 MB stream of 2.3 million operators needed 2.5 GB that way).
  Path coordinates come out as floats and are appended to the current path
  directly.  Content with inline images goes to qpdf's tokenizer, and
  pdfminer.six's parser is the last fallback.
* **pdfminer.six** interprets the pages (`interpreter.py`): its
  `PDFPageInterpreter` keeps the matrix,
  q/Q stack, text state, fonts and resources.  `ContentInterpreter`
  overrides the painting, clipping, colour, ExtGState, text-showing and
  XObject operators to record what plot extraction needs (pdfminer ignores
  clipping and opacity, and starts Form XObjects with a fresh graphics
  state).
* **fontTools** maps glyph names in /Differences to Unicode (Adobe Glyph
  List) in `fonts.py`.
* **python-dateutil** reads month names and date labels in `text.py`.

## Pipeline (one page at a time)

`pipeline.extract_page()` runs these steps, each in its own function:

| Step | Function (module) | Result |
|---|---|---|
| 0. Open the file | `Document` (document) | decrypted, repaired file parsed by pdfminer |
| 1. Draw the page | `Interpreter.run_page` (interpreter) | painted paths, text items, Dingbats markers, image boxes — all in page coordinates and drawing order |
| 2. Read the text | `read_page_text` (pipeline) → `drop_hidden_glyphs` (occlusion), `outlined_text` (outlined_text), `merge_texts`, `attach_vector_minus` (text) | labels and words, including text drawn as outlines; text painted over by white boxes removed |
| 3. Find the graphs | `find_page_graphs` (pipeline) → `find_axes` (axes), `resolve_shared_labels`, `apply_axis_multipliers` (labels), `build_graphs`, `add_panel_graphs` (graphs) | axes with value mappings, paired into plot boxes |
| 4. Find the markers | `find_page_symbols` (pipeline) → `find_symbols` (symbols), `rebuild_fragmented_circles` (fragments) | visible marker symbols |
| 5. Describe graphs | `describe_graphs` (pipeline) → `graph_rotation` (graphs), `find_title`, `find_figure_caption` (titles) | number, title, figure number and caption, 90° turns |
| 6. Bars and lines | `add_bars_and_lines` (pipeline) → `find_bars`, `find_line_series` (charts) | data points of charts without markers |
| 7. Legends | `find_page_legend`, `SeriesNamer` (legend) | series name of every point |
| 7a. Error bars (`--errbars`) | `find_error_bars` (errbars) | each marker's bar ends, page coordinates |
| 8. Rows | `make_rows` (rows) → `map_value` (scales), `error_bar_values`, `value_digits` (rows), `twin_view` (twin) | the CSV rows |
| 9. Meta records | `graph_meta` (meta) → `tick_range` (meta) | one record per graph for the -meta file |

## Modules and their dependencies

Lower layers never import higher ones (there are no import cycles):

```
opening the file    document                                    (pikepdf, pdfminer.six)
drawing             tokenizer  fonts  →  interpreter            (pdfminer.six, fontTools)
text                occlusion  text  →  outlined_text           (python-dateutil in text)
axes                scales  →  labels  →  axes
graphs              titles  →  graphs
marks               symbols  fragments  charts  errbars
naming              legend
output              twin  tools  styles  →  rows  meta
top                 pipeline  →  cli  →  pdfgraph2csv.py
shared              geometry  grouping  colours  context
```

## The records passed between steps

Plain dicts are used throughout (they are cheap and print well in a
debugger).  Coordinates are PDF page points (1/72 inch, y upwards).

**Path** (`Interpreter.paths`)
: `subpaths` — list of `{start, segs, closed}` where `segs` holds
  `("l", p)` and `("c", p1, p2, p3)`; `fill`, `stroke` (bool);
  `fill_rgb`, `stroke_rgb`; `opaque` (fill opacity ≥ 0.99); `clip`
  (clipping box or None); `idx` (drawing step).

**Text item** (`Interpreter.texts`, then `merge_texts`)
: `text`; `p0`, `p1` (baseline start/end); `up` (vector to the top of
  the glyphs); `size`; `idx`; `glyphs` — `(char, start, end)` per glyph.
  After `merge_texts`: `bbox`, `center`, `angle`, `rotated`, `value`
  (number or None).  Outlined words add `outlined: True`; unreadable
  outlined words ("blobs") have `text: None` and `centres` of their glyphs.

**Symbol** (`find_symbols`, `find_bars`, line vertices)
: `shape` (circle, square, triangle, diamond, polygon, plus, cross,
  asterisk, rectangle, bar, line, …); `cx`, `cy` (centre); `size`;
  `filled`; `rgb`; `idx`; `clip` (the clipping box it was drawn with, which
  decides its graph; markers outside the axis ranges are still reported).

**Axis** (`find_axes`)
: `orient` ("x"/"y"); `lo`, `hi` (extent along the axis); `pos` (position
  of the axis line); `has_line`; `ticks` (tick, value) pairs; `labels`
  ((tick, value), text item); `map` (see below); `tick_len`; `inside`
  (side on which the plot box lies).

**Mapping** (`axis["map"]`, used by `scales.map_value`)
: `kind` is `linear` (value = a·c + b), `log` (log10 value = a·c + b),
  `piecewise` (two linear pieces either side of `cut`: `a, b` and
  `a2, b2`) or `nominal` (`ticks`: (position, label) — nearest label wins).
  `n` labels were fitted with largest relative error `resid`.

Shared axes: `build_graphs` lets a graph use the labelled axis of another
graph in its column (row) only when `borrows_axis` finds the graph's own
axis line with ticks at the same places (`PAGE.bare_axes`, recorded by
`axes_from_group` for tick rows that got no labels), or, without ticks, a
dark axis line spanning the labelled axis (`PAGE.dark_lines`).

**Graph** (`build_graphs`)
: `x`, `y` (axes); `rect` (plot box); later `no`, `title`, `figure`, `caption`, `rot`, `bg`
  (drawing step of its background box, for insets).

## Page state

`context.PAGE` holds what several steps need to know about the current
page (graph boxes, typical label size, category-label candidates, wiggle
marks, boxes that hide text).  It is reset at the start of each page.
`context.SETTINGS` holds command-line settings that change how markers are
read.

## Tolerances

Most decisions compare distances with the font size of nearby text or the
size of the marker or tick concerned (e.g. a legend label must start
within 3 font sizes of its key), so they work at any scale.  Absolute values in points
are used only for things that are fixed in practice, such as the 0.5 pt
slack allowed around a clipping box.

## Error bars (--errbars)

`errbars.find_error_bars` collects straight stroke segments (and strokes
converted to thin filled rectangles) that are nearly vertical or horizontal
(within 0.3 pt or a tenth of their length: Excel's halves lean slightly),
indexed by position in 0.5 pt buckets.  For each marker it gathers the
pieces on its centre line (within max(0.15 × size, 0.3 pt)), chains pieces
that continue each other end to end (Excel's two halves) but not ones that
overlap (bars of other points at the same x), and keeps a chain that
touches the marker, reaches beyond it, does not span 90% of the plot (grid
lines, axes) and is not wholly outside the plot box (ticks).  A chain
touched by several markers goes to the one at which a piece starts or ends,
else to the one nearest its middle.  The result is
`{symbol index: {"v": (low, high) | None, "h": ...}}` in page coordinates;
`rows.error_bar_values` maps the ends through the graph's axes (swapping
directions in turned graphs) into `x_low, x_high, y_low, y_high`.

## Background grids

`axes.background_grid` serves plots with neither tick marks nor axis lines:
the edges of a light background rectangle crossed by grid lines, or of a
background tiled from light blocks (whose thin gaps become grid lines), are
added as axis lines, and the ordinary grid-lines-as-ticks fallback does the
rest.

## Two scales (twin.py)

`graphs.merge_twin_axes` joins the two graphs that a left and a right y
axis over one x axis (or a bottom and a top x axis beside one y axis) make
into one with `y2` (`x2`).  `twin.twin_axes` collects each series of
such a graph (by legend name, or colour when unnamed) and
`twin.assign_twin_axes` places it on one scale from its legend label
("right axis"), the axis titles that name it, or the colour of an axis's
labels (text items carry `rgb`); `twin.twin_view` then maps its points
through that scale and `make_rows` records the side in `axis`.  Frame sides
with labels at the corners become axes in `axes._frame_side_axes`.

## Speed on pages with many points

Pages hold up to 470 000 markers and 50 000 outline fragments; every step
that compares shapes with each other uses an index, and work that several
steps need is done once:

* **Glyph words** (`outlined_text._group_words`): glyphs filed by size
  class (powers of two) in grids (`grouping.BoxGrid`) of cells as big as
  the class; each glyph looks only in its own and bigger classes (a pair
  joins within the bigger glyph's reach), each pair once, union-find.
  `BoxGrid.near` walks the occupied cells instead when a query would touch
  more cells than there are.
* **Reading words**: the one-line test (box geometry only) comes before
  rasterising any glyph; readings are cached per word and direction (the
  split-exponent pass re-read every word for every other word); digit
  templates are integers compared by popcount; round marker discs are
  flattened as possible letters only when the page has real glyphs.
* **Per-subpath results** (`geometry.memoized`): flattening,
  `classify_subpath` and `thin_rect_line` are stored on the subpath dict
  under "_flat", "_cls", "_thin"; `symbols.as_closed` makes a copy without
  them.
* **Graphs** (`graphs._cache_for`): the graph of each clipping box and a
  grid of graph boxes, kept for the page's list of graphs and dropped by
  `pipeline.forget_page`; `tools.PathsByX` hands each graph the paths in
  its column (`graph_tool`, `guess_tool`).
* **Legends**: line samples in a grid by height and x cell; texts sorted
  once.  **Crossing strokes**: identical strokes (stacks of duplicate
  points) merged before the neighbour search; strokes filed by length class
  (factors of 1.2: partners differ by under 20%), cells 0.15 × the class's
  longest stroke, only neighbouring classes searched.  **Highlight boxes**: cells holding only the marker's own
  colour skipped.  **Ticks**: groups bucketed by their low end; labels
  matched to ticks by bisection; "away from any tick" by bisection.
* `doubled_outlines` compares the raw numbers before rounding them.

Every one of these keeps the output identical (checked on the whole
regression suite and byte for byte on the large files).

## The meta file (-meta)

`meta.graph_meta` makes one record per graph after its points are
mapped: page, graph number, title, figure number and caption
(`titles.find_figure_caption`: the nearest "Fig. N" / "Figure N" paragraph
below the graph and across its width; other graphs of the same figure may
lie in between; the paragraph is followed down the column at the spacing of
its first two lines), the program that drew it (`tool`, see below), the number of points output for the graph, and the
values of the lowest and highest labelled ticks of each axis
(`meta.tick_range`, with any ×10^n axis multiplier applied).
`extract()` returns these in `info["meta"]`; `cli.write_meta` writes them.

## Where a marker's data point is

A marker's data point is the middle of its bounding box, except:

* an equilateral triangle (box aspect about 0.87): its centroid, the
  convention of R (apex r above the point, base r/2 below); a triangle
  filling a square box, as matplotlib draws it, keeps the middle of the box;
* a regular polygon or star: its centre of symmetry (the mean of its
  vertices), which for a pentagon or a star is not the middle of the box;
* ZapfDingbats circles: (0.396, 0.347) em from the glyph origin (R).

`tests/make_random_symbols_pdf.py` draws 1000 random points with each kind
of marker by the drawing program's convention; the regression cases require
every point within the 3-decimal precision of the PDF's coordinates.  Means
of a circle's arc ends or of the strokes' crossing point were tried instead
of the middle of the box: they gained nothing on these files and made
schumpeter-001 (supplied reference values) and symbols-on-axes (values on a
known grid) slightly worse, so the box middle stays.

## How many digits are written

`tokenizer.coordinate_decimals` reads how many decimals a content stream's
numbers are written with (the 95th percentile, so one odd number does not
count); the interpreter turns that into a resolution in page units for each
path and Dingbats glyph (`res`: one unit of the last decimal, scaled by the
transformation matrix).  `rows.value_digits` carries it through the axis
mapping (|a| for a linear axis; |v| ln 10 |a| for a log axis) and writes each
x/y value down to that resolution plus one guard digit, so that rounding the
output adds at most a tenth of the coordinates' own rounding; never fewer
than 6 digits.  `--digits N` fixes the number instead.  For the random test
plots this puts every point within the rounding of the PDF's coordinates:
0.000125 data units with 3 decimals, 1.25e-8 with 10 significant digits.

## The tool that drew a graph (meta file)

`tools.py` names the program from what the PDF records.  pdfTeX keeps an
embedded graphic's own document information in its Form XObject
(/PTEX.InfoDict: Creator, Producer); an XObject may also carry XMP metadata
(xmp:CreatorTool).  The interpreter gives each path and Dingbats marker the
tool of the innermost embedded graphic that drew it (`form_tool`), and
`tools.graph_tool` takes the most common one among the paths inside a
graph's box.  Creator is preferred; Producer is used when it only adds a
version ("R" + "R 4.0.2") or when Creator is empty.  Programs that only
convert or print to PDF (Ghostscript, Distiller, PScript5, PDF libraries,
cairo, ...) are never reported.  Failing that, the document's own
Creator/Producer is used, but only when it names a plotting program (a PDF
written by R or matplotlib): the Creator of a LaTeX or Word document says
nothing about the program that drew a chart in it.

## Guessing the tool from the drawing style (meta file)

`styles.guess_tool` scores, for each program, the signs found among the
paths, texts and Dingbats markers in and around a graph: default palettes
(counted only when they make up at least a fifth of the graph's colours,
matching exactly before matching within 2 units per channel), fonts
(Calibri, DejaVu, Helvetica), ZapfDingbats circles, round caps and joins
with 2-3 decimals (R's pdf() device), graphics states A1, A2, ... and marker
drawings M0, M1, ... (matplotlib), axes in #262626 (MATLAB), filled diamonds
with an Office palette (Excel).  The interpreter records each path's style
as a shared tuple (line width, cap, join, decimals, Form XObject name,
ExtGState name).  The best program is reported when it scores at least 2.5
and leads the next by at least 1; otherwise the guess is empty.

On the test files the guess agrees with the recorded tool for every graph
whose tool is recorded (R 19 graphs, "S graphics" 2 as R, matplotlib 21,
MATLAB 4, Visio-pasted Excel charts 10 as Excel); figures saved by Adobe
Illustrator are guessed as R or left empty.  The rules were written from
these files, so fresh matplotlib plots in other styles (default, classic,
ggplot imitation, seaborn darkgrid; scatter, line and bar charts) were used
as a check: all six were guessed as matplotlib (a seventh, seaborn's
"white" style, has no tick marks and is not found as a graph at all).

# How pdf_points works

`pdf_points.py` is a thin command-line wrapper; the work is done by the
`pdfpoints` package next to it.  It uses four packages:

* **pikepdf** opens the file (`document.py`) and tokenizes the content
  streams (`interpreter.py`, much faster than pdfminer.six's parser): qpdf repairs damaged files,
  decrypts and decodes streams; streams that cannot be decoded are emptied
  with a warning; the cleaned file is handed, in memory, to pdfminer.six.
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
| 5. Describe graphs | `describe_graphs` (pipeline) → `graph_rotation` (graphs), `find_title` (titles) | number, title, 90° turns |
| 6. Bars and lines | `add_bars_and_lines` (pipeline) → `find_bars`, `find_line_series` (charts) | data points of charts without markers |
| 7. Legends | `find_page_legend`, `SeriesNamer` (legend) | series name of every point |
| 8. Rows | `make_rows` (pipeline) → `map_value` (scales) | the CSV rows |

## Modules and their dependencies

Lower layers never import higher ones (there are no import cycles):

```
opening the file    document                                    (pikepdf, pdfminer.six)
drawing             fonts  →  interpreter                       (pdfminer.six, fontTools)
text                occlusion  text  →  outlined_text           (python-dateutil in text)
axes                scales  →  labels  →  axes
graphs              titles  →  graphs
marks               symbols  fragments  charts
naming              legend
top                 pipeline  →  cli  →  pdf_points.py
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

**Graph** (`build_graphs`)
: `x`, `y` (axes); `rect` (plot box); later `no`, `title`, `rot`, `bg`
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

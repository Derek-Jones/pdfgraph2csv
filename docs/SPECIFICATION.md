# pdfgraph2csv — specification for a new implementation

This document specifies a program that extracts the data values of the
points plotted in graphs drawn as vector graphics in PDF files. It is
written for a coding agent building a new version from scratch. It records
what the program must do, the rules that were found to work, the problems
met while building the current version, and how to test the result.

The current implementation (Python, package `pdfpoints`, about 7,000 lines)
is a working reference: where this document gives a rule with numbers, those
numbers come from it and are known to pass the regression corpus. Where it
says *should*, a better method is welcome if the corpus still passes.

Contents

1. Purpose and scope
2. Deliverables
3. Command-line interface
4. Output files
5. Processing pipeline
6. Opening the file
7. Executing the drawing operators
8. Text
9. Axes
10. Graphs
11. Marker symbols
12. Bars and lines
13. Legends and series names
14. Titles and figure captions
15. The program that drew a graph
16. Number precision
17. Robustness and performance
18. Problems met while building the current version
19. Regression testing
20. Acceptance criteria
21. Appendices

---

## 1. Purpose and scope

Given a PDF file, find every graph (x and y axes with numbered or labelled
tick marks) drawn with vector graphics, find the data points drawn in it
(marker symbols, or bar tops / line vertices when there are no markers),
and write the data coordinates of every point as CSV.

**In scope**

* Scatter plots, line plots with markers, bar charts, histograms, line
  charts without markers, box plots (their outlier markers).
* Any number of graphs per page and per file; multi-page files.
* Graphs embedded in documents (LaTeX `\includegraphics`, Word, InDesign),
  graphs that are the whole file (written by R, matplotlib, ...).
* Linear, logarithmic, category (nominal), date/month and broken axes.
* Graphs turned by 90 degrees on the page.
* Text drawn as fonts or as filled glyph outlines.
* Encrypted and damaged files that qpdf can repair.

**Out of scope**

* Raster graphs (JPEG/PNG images) — ignored.
* 3-dimensional graphs — not required; must not hang or crash (a file with
  two 3-D cubes must finish in about a second and report no graphs).
* Pie charts, maps, contour/heat maps.

**Guiding principles** (they came from the user's instructions and from
experience):

* Every detected data point is reported, duplicates included, graph by
  graph and in increasing order of x within a graph (the user asked for
  this order). Points whose values lie beyond the visible axis range (clipped
  out of view) are still reported.
* No output at all when there are no points (no CSV header, no output file).
* One bad page or one bad stream must not lose the rest of the file.
* The coordinates must be as accurate as the PDF's own numbers allow
  (section 16).
* Decisions are made relative to the size of the things involved (font
  size, marker size, tick length), not absolute distances, so that the same
  rules work at any scale.

## 2. Deliverables

```
pdfgraph2csv/
  pdfgraph2csv.py          command-line wrapper (run this); puts its own
                           directory on sys.path and calls the package's main()
  <package>/               the implementation, one module per step (section 5)
  requirements.txt         pikepdf>=8, pdfminer.six>=20231228, fonttools>=4,
                           python-dateutil>=2.8
  README.md                user documentation (owned by the user: do not
                           rewrite it; only correct statements your changes
                           make false, and say which)
  docs/DESIGN.md           pipeline, modules, record formats, rules
  docs/PACKAGES.md         packages that could replace hand-written parts
  tests/run_tests.sh       the regression runner: bash only (section 19)
  tests/make_*.py          Python generators of the synthetic test PDFs
  tests/data/              test PDFs, expected CSVs, true-value CSVs
```

* Language: Python 3.9+. The user asked for these packages to be used:
  **pikepdf** (qpdf: open, repair, decrypt, decode), **pdfminer.six**
  (content-stream interpreter, fonts, CMaps, standard-14 metrics),
  **fontTools** (Adobe Glyph List for glyph names), **python-dateutil**
  (month names, dates). Nothing else at run time. (Pillow and matplotlib
  may be used by test generators only.)
* The package must be importable: `from <package> import extract;
  rows = extract("plot.pdf")` returns a list of dicts, one per point, and
  `python3 -m <package> plot.pdf` works.
* Code: one major component per module, every module and function with a
  docstring saying what it does and why; lower layers never import higher
  ones.
* Deliver the program as a `.tgz` that unpacks to a `pdfgraph2csv/`
  directory, and verify the regression suite passes from a fresh unpack.

## 3. Command-line interface

```
python3 pdfgraph2csv.py FILE.pdf [options]
```

| Option | Meaning |
|---|---|
| `-o FILE`, `--output FILE` | write the points CSV to FILE (default stdout). The file is created only when points are found. |
| `-meta FILE`, `--meta FILE` | also write the per-graph meta CSV (section 4.2); created only when graphs are found. Both the single-dash and double-dash spellings must work. |
| `--pages LIST` | comma-separated page numbers (1-based). Graph numbers still count from the first graph of the selected pages. |
| `--inside-only` | report only symbols inside the plot rectangle (drops legend keys). |
| `--exclude-legend` | do not report the marker symbols of legend keys. |
| `--glyph-centre {marker,bbox}` | data point of a ZapfDingbats marker: R's convention (0.396, 0.347) em (default) or the glyph's box centre. |
| `--max-symbol-frac F` | largest marker size as a fraction of the plot's smaller side (default 0.1). |
| `--rotation` | add a `rotation` column (0, 90, -90, 180). |
| `--digits N` | fixed number of significant digits (1..17) for numbers; default: as many as the PDF's precision justifies (section 16). |
| `--internal` | add `pdf_x`, `pdf_y` columns (marker centre in page coordinates). |
| `--errbars` | add `x_low,x_high,y_low,y_high` columns: the ends of each point's error bars (section 12.1). |
| `--password PW` | user or owner password of an encrypted file. |
| `--debug` | print axis candidates, graph boxes, titles, legends to stderr. |

**Exit status**: 0 on success (including "no graphs found"); 1 on a fatal
error (message `error: ...` on stderr); 2 for usage errors.

**Messages** (stderr; exact wording is tested):

| Situation | Message |
|---|---|
| no graph found | `warning: No vector graphics found` |
| graphs found, no points | `warning: graphs found, but no data points in them` |
| not a PDF | `error: not a PDF file` |
| beyond repair | `error: the file is damaged beyond repair (<qpdf reason>)` |
| encrypted, no/empty password fails | `error: the file is encrypted and needs a password (use --password)` |
| wrong password | `error: the password is not correct for this file` |
| corrupt stream skipped | `warning: a corrupt <Filter> stream was skipped (<qpdf reason>)` e.g. `ASCII85Decode` |
| a page failed (a bug) | `warning: page N could not be analysed (<ExceptionType>: <message>)` |
| huge content | `note: page N has M MB of drawing instructions; this may take a minute or two` (when the page's content exceeds 15 MB) |
| flattened markers rebuilt | `warning: markers were flattened into fragments; N circles rebuilt from their outlines ...` |

Each warning is printed once. Output piped into `head` must not produce a
traceback (handle BrokenPipeError).

## 4. Output files

### 4.1 Points CSV

Columns, in this order:

```
page,graph,symbol,series,legend_key,x_coord,y_coord,color,color_hex
```
plus `axis` when a graph has two scales, plus
`x_coord_low,x_coord_high,y_coord_low,y_coord_high` when an axis takes its
tick positions from its label centres, plus `x_low,x_high,y_low,y_high`
with `--errbars` (before `rotation`), plus `rotation` with `--rotation`,
plus `pdf_x,pdf_y` with `--internal`.

* `page` — 1-based page number.
* `graph` — graph number, counted through the whole document in reading
  order: pages in order; on a page, rows of graphs top to bottom (graphs
  whose vertical extents mostly overlap share a row), left to right within
  a row.
* `symbol` — `filled-` or `open-` + shape for closed shapes (`circle`,
  `square`, `triangle`, `diamond`, `thin-diamond`, `polygon`, `rectangle`), or `plus`,
  `cross`, `asterisk`, `bar`, `line`.
* `series` — series name from a legend (section 13), else empty.
* `legend_key` — 1 if this symbol is itself a legend key, else 0.
* `x_coord`, `y_coord` — data values (section 16 for formatting). Category
  axes give the category label (unreadable outlined labels: `#1`, `#2`,
  ... in axis order). Month axes give year + month/12 (month 0..11).
* `color` — nearest CSS colour name; `color_hex` — `#rrggbb`.
* `axis` — only when some graph of the document has a scale on both sides
  (section 10.1): `left` / `right` (`bottom` / `top` for two x scales), the
  scale the point's value was read against; empty for graphs with one.
* `x_coord_low`, `x_coord_high`, `y_coord_low`, `y_coord_high` — only when
  some axis of the output has no tick marks and its label centres stand in
  for them (the user asked for these): the range the value may really lie
  in, as an error bar.  The page position is moved by the axis's
  uncertainty each way and mapped through the axis (asymmetric on a log
  axis).  The uncertainty is 0.1 of the labels' font size (programs centre
  a label on its cap height, its em box or its ink) plus the largest
  distance of a label centre from the fitted scale.  Empty for an axis
  with tick marks or grid lines, and for category axes.
* The graph title is **not** a column (the user asked for it to be
  removed).
* Rows are grouped by graph (in graph-number order within a page) and
  sorted by increasing x within each graph; a category axis gives the
  order of its categories along the axis, and rows with the same x keep
  their drawing order (stable sort). CSV uses `\n` line endings.
* No points: write nothing (no header) and do not create the `-o` file.

### 4.2 Meta CSV (`-meta FILE`)

One row per graph found (also graphs with no points):

```
page,graph,title,figure,caption,tool,tool_guess,points,x_tick_min,x_tick_max,y_tick_min,y_tick_max
```

* `title` — section 14.1; empty if none.
* `figure` — the figure number from a caption "Fig. 5" / "Figure 3.2" /
  "FIGURE 12" / "Figure S3"; empty if none.
* `caption` — the caption text without the "Fig. N." label (section 14.2).
* `tool` — the program recorded in the PDF as having drawn the graph
  (section 15.1); empty if not recorded.
* `tool_guess` — best guess from the drawing style (section 15.2); empty
  when no program stands out. Independent of `tool`.
* `points` — number of rows written for this graph.
* `x_tick_min` ... `y_tick_max` — the values of the lowest and highest
  labelled ticks (with any ×10^n axis multiplier applied); for a category
  axis the first and last category along it.
* `axis2`, `axis2_tick_min`, `axis2_tick_max` — only when some graph has a
  second scale (section 10.1): which (`y right`, `x top`) and its lowest
  and highest labelled ticks; empty for graphs with one scale per axis.
* Not created when no graph is found.

## 5. Processing pipeline

Process the file page by page. For each page, run these steps; wrap the
whole page in an exception handler that records the page warning and moves
on (unless `--debug`, which re-raises).

| Step | Result |
|---|---|
| 0. Open the file | decrypted, repaired document (section 6) |
| 1. Execute the page | painted paths, text items, Dingbats markers, image boxes — page coordinates, drawing order (section 7) |
| 2. Read the text | labels and words, including text drawn as outlines; text hidden under later opaque boxes removed (section 8) |
| 3. Find axes and graphs | axes with value mappings, paired into plot boxes (sections 9, 10) |
| 4. Find markers | marker symbols (section 11) |
| 5. Describe graphs | number, title, figure, caption, rotation, tool, tool guess |
| 6. Bars and lines | points of graphs without markers (section 12) |
| 7. Legends | series name of every point (section 13) |
| 8. Rows | map every point through its graph's axes; meta records |

Suggested modules (lower layers first; no import cycles):

```
opening the file    document
drawing             tokenizer  fonts  ->  interpreter
text                occlusion  text  ->  outlined_text
axes                scales  ->  labels  ->  axes
graphs              titles  ->  graphs
marks               symbols  fragments  charts
naming              legend
tools               tools  styles
top                 pipeline  ->  cli  ->  pdfgraph2csv.py
shared              geometry  grouping(union-find)  colours  context(page state)
```

Records are plain dicts. Page state shared by several steps (graph boxes,
typical label size, category-label candidates, wiggle marks, boxes that hide
text, paths that are minus signs) lives in one object reset at the start of
every page.

## 6. Opening the file

1. Reject data that does not contain `%PDF` in its first 1024 bytes:
   "not a PDF file".
2. Open with pikepdf from memory. On a password error: if a password was
   given, retry with the empty password (the given one may be an owner
   password of a file anyone may open), else report "needs a password".
   Other qpdf errors: "damaged beyond repair (reason)", where the reason is
   qpdf's message without the in-memory stream name.
3. Decode every stream once whose filters qpdf can decode (Flate, LZW,
   ASCII85, ASCIIHex, RunLength; not image codecs). If decoding fails:
   for a plain Flate stream without DecodeParms, keep the part that does
   decompress (`zlib.decompressobj().decompress(raw)`); otherwise replace
   the stream by an empty one and warn, giving qpdf's own warning text as
   the reason.
4. Save the repaired, decrypted file to memory and parse it with
   pdfminer.six (PDFDocument, PDFPage, PDFResourceManager with caching).
   "no pages found (damaged file?)" if there are none.
5. Read the document-level tool (section 15.1) while the pikepdf object is
   open.
6. Silence pdfminer's logging; the program reports what matters itself.

Encryption to support: RC4 40/128, AES-128, AES-256 (R5, R6), user and
owner passwords.

## 7. Executing the drawing operators

Use pdfminer.six's `PDFPageInterpreter` for the matrix, q/Q stack, text
state, fonts and resources, subclassed to record what plot extraction
needs. Page coordinates are the PDF's user space (do not apply /Rotate or
the media box offset).

### 7.1 Tokenizing — critical for performance and memory

pdfminer's own parser is far too slow for big streams (a 69 MB stream of
2.9 million operators took many minutes), and qpdf's
`parse_content_stream` holds the whole stream as objects (a 92 MB stream of
2.3 million operators needed **2.5 GB** for that list alone; the process was
killed). Write a **streaming tokenizer** that yields one
`(operator, operands)` pair at a time:

* A fast path matches, with one regular expression, optional whitespace,
  numbers each followed by whitespace, and an operator (not `true`, `false`
  or `null`), ending at a delimiter or end of data. For the path operators
  `m l c v y`, convert the numbers with `map(float, ...)` and mark the list
  (e.g. a `list` subclass) so the interpreter can append the segment to the
  current path directly without per-operand checks.
* A general path handles names (with `#xx` escapes), literal strings
  (nesting, `\n \r \t \b \f \( \) \\`, octal `\ddd`, line continuations,
  CR/CRLF → LF), hex strings (odd length padded with 0), arrays,
  dictionaries, `true/false/null`, comments; stray closing brackets are
  ignored; an operator inside an unclosed array/dict ends it.
* Numbers: integers as `int`, reals as `float` (as pdfminer gives them).
* Streams containing inline images (`BI ... ID ... EI`) go to qpdf's
  tokenizer; if qpdf rejects the content, fall back to pdfminer's parser.
* Validate the tokenizer against qpdf on every content stream of the test
  corpus: operators and operands must be identical.
* Target: about 7–10 s for a 92 MB stream; memory independent of size.

### 7.2 Operators

* An operator whose handler raises is skipped; one malformed operator must
  not lose the page. Cache the handler lookup per (class, operator).
* **Paths**: on painting operators record the path (if filled or stroked)
  as subpaths in page coordinates: `{start, segs: [("l", p) | ("c", p1, p2,
  p3)], closed}` (subpaths without segments - a bare move-to, which
  Inkscape writes after every shape - are dropped: they draw nothing, and
  their zero-size box on a marker's edge passed for a hole that made the
  marker a letter), `v`/`y` expanded, a segment after `h` starting a new
  subpath at the current point; plus `fill`, `stroke`, `fill_rgb`,
  `stroke_rgb`, `opaque` (fill opacity /ca ≥ 0.99), `clip` (current clipping
  box), `idx` (drawing step), `res` (section 16), `tool` (section 15.1),
  `style` (section 15.2; share equal tuples to save memory).
* **Clipping** (pdfminer ignores it): `W`/`W*` makes the next painted (or
  `n`) path a clip; intersect its bounding box with the current clip; save
  and restore with q/Q.
* **Colour**: colour operators take all operands given (not a fixed count).
  Convert gray, RGB, CMYK, ICCBased (by /N), CalRGB, Lab, CalGray and
  Indexed (base space + lookup table) to RGB; patterns, Separation, DeviceN
  are unknown (None).
* **ExtGState**: record /ca (fill opacity) and the resource name used.
* **Text**: position every glyph (Tc, Tw, Tz, rise, TJ adjustments, the
  text and line matrices). Split a string into separate text items wherever
  the visible gap between consecutive glyphs exceeds the font size, so that
  several labels packed into one TJ with wide spacing come apart (e.g.
  Distiller's `[(-)6404(1)83(13)-55(57)]TJ`). Inside a piece, a space
  character or a gap wider than 0.15 em becomes one space. Each text item:
  `text`, `p0`/`p1` (baseline ends), `up` (vector to the top of the glyphs),
  `size`, `font` (name without subset prefix; Type 3 fonts from /BaseFont
  or /Name), `glyphs` [(char, start, end)], `idx`. An undefined font shows no
  text.
* **ZapfDingbats markers**: glyph codes 59 `;` (a27 cross), 108 `l` (a71
  circle), 110 `n` (a73 square), 115/116 (a76/a77 triangles), 117 (a78
  diamond) are recorded as marker symbols, not text: centre at (0.396,
  0.347) em from the glyph origin (R's pdf() convention; `--glyph-centre
  bbox` uses the glyph box centre), size from the AFM box, filled for render
  modes 0/2/4/6, open for 1/5; invisible modes 3/7 ignored.
* **Fonts**: Unicode from ToUnicode, else /Differences glyph names via the
  Adobe Glyph List (fontTools), else fixes for TeX symbol fonts and dashes,
  else the base encoding; ligatures spelt out (fi, fl, ffi, ...). Standard-14
  fonts used without /Widths (and aliases such as Arial, TimesNewRoman) are
  measured with the Adobe metrics.
* **Glyph names that are no character names**: Type 3 copies of TrueType
  fonts (matplotlib 3.3) name each glyph after its glyph number,
  "uni00000013", which the Adobe Glyph List reads as U+0000 U+0013. A name
  (or a base-encoding entry) that gives control characters is ignored, and
  the code keeps its standard meaning (printable ASCII 32-126: code 48 is
  "0").
* **Fonts without a map to Unicode**: for a two-byte (CID) font whose code
  neither ToUnicode nor pdfminer explains, read the embedded font program
  (FontFile2, FontFile3/OpenType, bare CFF; the descendant's for Type 0):
  code → glyph through /CIDToGIDMap (identity when absent) → character from
  the program's Unicode cmap tables (reversed, smallest code point) or its
  glyph names through the Adobe Glyph List ("zero", "uni0036"; a suffix
  such as ".numr" dropped). A Type 0 font that was taken for a one-byte
  font (no /Subtype) shows its strings as byte pairs 00 xx: when all the
  high bytes are zero and the font program is a CID one, read them as
  two-byte codes, with widths from the descendant's /W and /DW. Control
  characters left over are dropped, never output: an unreadable label is
  no label.
* **Form XObjects**: run with their own matrix and resources, **inheriting
  the caller's graphics state** (pdfminer starts them afresh, which loses
  colours). Guard against a form drawing itself (track stream ids) and limit
  nesting depth (25).
* **Images**: record their page box and drawing step (they may hide text
  drawn earlier).

## 8. Text

### 8.1 Hidden text

Labels are sometimes "edited" by painting a white box over them and writing
new text on top (e.g. the values beyond an axis break). Remove glyphs (and
glyph outlines) that a later opaque rectangle or image covers. Use a grid
index of cover boxes — but **cap the number of cells per box** (e.g. 10,000)
and test bigger boxes one by one: a degenerate box 3×10^9 points across once
made the index try to create 6×10^15 cells (an apparent infinite loop).

### 8.2 Words and numbers

* Merge text pieces that continue each other on the same baseline (same
  size within 5%, gap < 0.15 em; < 0.45 em either side of a "×", which
  mathtext spaces: matplotlib's log-axis labels "3×10^1" come as "3", "×",
  "10" and a raised "1"). A small raised number directly after
  "10" is a superscript exponent: "10" + "3" → "10^3".
  Small capitals ("FULL" set as "F" + smaller "ULL"): an all-capital piece
  of 0.6-0.85 of the size touching (< 0.15 em) a capital joins it; the
  item keeps the bigger size.
* Each merged item gets `bbox`, `center`, `angle`, `rotated`, `value`.
* `parse_number`: plain numbers, `1,000`, `$5`, `25%`, `10^3`, `2x10^3`,
  `2×10^3`, Unicode minus (U+2212), '95-style years, dates (decimal year),
  and numbers with a unit or scale suffix: byte sizes in SI units (`B`,
  `kB`, `MB`, `GB`, `TB`, `PB` = 10^3n; the value is in bytes) and binary
  units (`KiB`, `MiB`, `GiB`, `TiB` = 1024^n), thousands and millions
  (`10k`, `10K`, `2M`: ggplot2's label_number(scale_cut)), factors (`1.5x`,
  `1.5×` = 1.5), and durations - a number and a unit of time, the value
  in seconds (`ns`, `µs`, `ms`, `s`/`sec`/`second`, `min`/`minute`,
  `h`/`hr`/`hour`, `d`/`day`, `w`/`wk`/`week`, `mo`/`month` = 365.25/12
  days, `y`/`yr`/`year` = 365.25 days, plurals too, lower case; a bare `m`
  is not taken): a log time axis labelled 1 s, 15 s, 1 min ... 64 h (the
  user asked for these). Not other letters ("5G", "3D" stay words).
  Return None for values a float cannot hold or exponents above 300 (body
  text "2^2000 ≈ 10^602" once raised OverflowError) and for non-finite
  values.
* Dates: only unambiguous forms — a month name with a year ("Mar 2010",
  "15 March 2010", "Jan-10") or a full ISO date; value year + month/12 (+
  fraction of the month). "2010-11" stays unparsed (a range).
* `month_index`: "Jan", "January", "Sept", "jan.", "Janu" → 0..11 (python-
  dateutil's month names).
* A thin horizontal filled bar just left of a numeric label is a minus sign
  drawn as a path (matplotlib with Type 3 fonts): make the label negative.
  Not a bar that touches a vertical line 20 pt or longer (including the
  closing edge of a rectangle): that is a tick on its axis or frame, with
  the label beside it.

### 8.3 Text drawn as outlines

Some PDF writers convert every character into a filled path. Then:

* Glyph = an outer contour plus the contours of the same path inside it
  (holes). Word = glyphs of one colour closer than about half a glyph
  (spatial grid: pages can hold 100,000+ shapes).
* Read each glyph by rasterising it (even-odd fill, 3×3 supersampling) to a
  12×16 grid and comparing it with built-in digit templates (Liberation
  Sans/Serif/Mono and DejaVu Sans renderings of 0–9, each with its ink aspect
  ratio), in each of the four reading directions; keep the direction where
  the word reads as one line with the best quality.
* A trailing "%" drawn as three shapes (two small rings and a slash) is
  recognised and dropped. "10" followed by a small raised number is 10^n;
  an exponent's minus sign drawn as a separate thin dash makes it 10^-n.
  Such dashes must **not** be taken for tick marks (record them as minus
  paths and exclude them from tick detection).
* **Labels run into a nearby word**: big glyphs reach far (a sideways
  axis title in 8 pt letters joins a y label "0.50" 3.5 pt away; a y label
  and an x label touching at the corner, "10^-4" and "10^-4"). A word of up
  to 40 glyphs that reads as no number is regrouped with a tighter reach
  (0.25 of the bigger glyph) and its pieces of 2-12 glyphs read; the split
  is kept only if a piece reads as a number (words of letters stay whole:
  category labels), and a single glyph never becomes a label this way (a
  round marker fragment reads as "0").
* Words that cannot be read are kept as "blobs" (text items with
  `text=None` and their glyph centres): usable as category labels (numbered
  #1, #2, ...) and as legend labels with an unknown name.
* Glyph outlines are never marker symbols; return the set of (path, subpath)
  that are text.
* **Letters that look like markers**: an 'o' (a circle with a round hole),
  'c', 's' or 'e' (closed round outlines), a full stop (a small square or
  disc), a capital 'N' or 'x' (symmetric polygons), and 'i'/'j' (a dot and a
  stem in one path). Paths made only of marker shapes (or of marker shapes
  and thin bars, or single round outlines in a marker colour) are offered
  to word grouping as *marker-like*; one becomes text only when it joins a
  word that has real characters, is at most 1.6 × their size (a capital
  among small letters), overlaps no other glyph (characters never overlap;
  a run of markers does) and lies within the line of the real characters
  (slack half a character; any direction when the real characters are a
  single letter). A word of marker-like shapes alone is markers. The dot of
  an 'i' or 'j' whose stem was set aside as a thin bar is text when it sits
  just beyond one end of the bar, centred on it and smaller than it.
  Marker-like shapes never count towards the word length that decides
  which words vote for the page's reading direction (a full stop must not
  let "0.5" vote where "05" would not).
* **Reading direction of short words**: a word of one or two glyphs is read
  in the page's direction (the vote of long numeric words) unless it reads
  well as a number in its own direction and that is not the page's turned
  by 180° (6 against 9): R writes y labels sideways and x labels upright.

## 9. Axes

### 9.1 Tick marks

* Collect axis-aligned straight segments of stroked paths; also thin filled
  axis-aligned shapes (strokes converted to outlines, with butt, round or
  square ends) except minus-sign dashes. Merge collinear pieces into lines.
* Horizontal short open segments are candidate ticks of a y axis; vertical
  ones of an x axis.
* Group parallel segments with identical extent (lo, hi within
  max(0.05, min(0.1·L, 1)) pt); a group needs ≥ 2 distinct positions.
  A group whose length exceeds a quarter of its span is a set of **grid
  lines**: used only when an axis has no real ticks (plots without tick
  marks), and then only grid lines that start on the axis line. A group of
  long segments is a row of grid lines when they are longer than a quarter
  of the group's span or than three times their median spacing (one row
  of grid lines may run through several side-by-side panels, making the
  span large). When no
  axis line is found at either end of the grid lines (ggplot2's
  theme_minimal draws only major and minor grid lines: no ticks, no axis
  lines), or the line across them is not at their ends (the lowest minor
  grid line of the other direction, a few points in), the grid's own low
  end is the axis line: (first grid line, last grid line, low end).
  Grid lines without labels (minor ones, a line at a mean) are harmless:
  the fit uses only labelled positions.
* One group of identical ticks may belong to several axes (side-by-side
  panels): split it by the axis lines its ticks touch (an axis line must be
  at least 3 tick lengths long and span at least half the ticks). Keep the
  closest line for each set of ticks.
* An axis line may be an edge of a stroked rectangle.
* **Background grids** (no tick marks, no axis lines: seaborn's darkgrid,
  ggplot2's grey theme). A filled axis-aligned rectangle in a light, not
  white, colour (every component ≥ 0.75), at least 40 pt each way, with
  two or more lines running right across it (white grid lines), gives
  its four edges as axis lines; the grid lines then stand in for ticks
  (they start on those lines). A background tiled with ≥ 4 blocks of one
  light colour covering ≥ 80% of their union, separated by thin gaps
  (≤ 8 pt and ≤ 15% of the blocks beside them), gives a grid line through
  the middle of each gap, across the whole union, and the union's edges as
  axis lines.
* A tick may be drawn as a tiny closed rectangle that is stroked (and maybe
  also filled), as InDesign does (0.3 × 1.5 pt): a thin rectangle up to
  12 pt long counts as its centre line, and its edges are not lines (the
  tips of a row of such ticks would join into a false axis line). The same
  tick filled and then outlined gives two copies: positions closer than
  0.05 pt are one tick.
* **Labels at the frame corners**: boxed plots often put the first and last
  labels at the ends of the axis line without a tick there. When the ticks
  are evenly spaced (within 2%) and an end of the axis line lies one
  spacing (within 3%) beyond the outer tick, try that end as a tick too;
  keep it only if more labels then fit, and (unless the ticks alone fit
  fewer than 3) the fit is no worse than 3 × its residual + 1e-4 — an axis
  starting before its first value puts a label near the line's end that is
  not at it. Not for pieces of a frame line split at lattice panel borders.
* **Frame sides as axes**: a frame side starting at the end of a found axis
  (a right-hand scale) may have only one tick of its own, its other labels
  sitting at the corners. Try it with its two ends plus the ticks touching
  it as tick positions; it needs ≥ 3 fitting numeric labels, and when it
  fails it is not recorded as a bare axis (section 10).
* **Labels as ticks**: an axis line with no ticks at all (Excel's category
  axis of a line chart: labels 1, 101, ... 1001; ggplot2 with axis.ticks
  blank: 0.00 ... 1.00, or only 4, 8, 12 on a 1..15 axis). Tried for that
  frame side, and then for every line of 30 pt or more that carries no
  axis, or only one fitted with two labels (the frame's side lines taken
  for two "ticks"): a row of at least three numbers beside it, not labels
  of another axis, within its span, at most 2 label sizes away, on one
  side, one baseline (x) or one edge (y), evenly spaced (within 5%) with
  values in equal steps, gives the tick positions: the label centres. A
  horizontal label is centred by its advance width: for a label drawn as
  outlines (only the ink box known) the advance box is estimated from
  Helvetica / Arial digit metrics ("1" has its ink well right of its
  middle; uncorrected, 4 / 8 / 12 put every point 0.03 too high). Label
  positions are less exact than ticks: vertical centring differs between
  programs.
* A long frame line shared by a column of lattice panels is split at the
  perpendicular panel borders that cross it away from any tick.

### 9.2 Labels

* Pair each tick with the numeric label just beyond it: centred on the tick
  within min(0.8 × font size, half the tick spacing) (1.5 × size for oblique
  labels, which point at their tick with the end nearest the axis); its gap
  beyond the tick end between −0.5 and 5 font sizes. Greedy matching, best
  centred and closest first; each label and tick used once.
* Try labels beyond the outer tick end and (for inward ticks, as Excel draws
  them) beyond the axis line on the other side; keep whichever pairs more
  labels.
* A numeric string covering two or more ticks ("510 20") is cut into digit
  groups centred on the ticks.
* A tick label belongs to one axis only: resolve labels reached by mirrored
  tick rows or neighbouring panels to the nearest axis line; drop axes left
  with too few labels.
* Month names on an axis read as 0..11; year numbers written beyond them
  (one per run of months) give year + month/12.
* '95-style years next to full years: give each the century that keeps the
  labels in axis order.
* "×10^n" (often just "10^n", the × being a symbol glyph or a drawing)
  written at the end of an axis scales its values.

### 9.3 Value mapping

* Least squares fit `value = a·c + b`, or `log10(value) = a·c + b` when the
  labels are successive powers of ten or the log fit is ten times better.
* Accept a fit when every label lies within 2% of the value range of the
  line; otherwise drop the worst label (a misread or misassigned one) and
  refit while more than half the labels remain. Record `n` labels used and
  the largest relative residual `resid`.
* For axes with an axis line only, if that fails, try dropping each single
  label: accept when the others fit within 0.2% and the dropped label lies
  at least 10% off their line (a wrong label pulls the least-squares line
  towards itself, so the label farthest from it can be a right one: "0.5
  0.0 0.5 1.0", where the first should read −0.5, lost the 0.0). Not for
  axes without a line (some subset of stray numbers nearly always fits) and
  not for labels that only roughly follow a scale (a category axis of sizes
  250, 180, 130, 100, 70).
* The meta file's tick range uses the read label values, but a label the
  fit set aside gets the mapped value, rounded to the decimals of the
  labels that fit.
* Without an axis line, demand at least 3 labels (short parallel strokes of
  '+' markers easily pass for ticks).
* **Broken axes**: when the labels form two linear runs with the same scale
  and a jump in value, and a wiggle mark (short open curved strokes) crosses
  the axis between them, map piecewise with a cut at the wiggle. A single
  label beyond the break continues the scale.
* **Category axes**: when there are no numbers (or only two stray "numbers"
  on a row of ≥ 6 ticks), use words at the ticks — or midway between ticks
  as Excel draws them — as categories; a point gets the nearest category
  (binary search over sorted positions; first in axis order on a tie).
  Category labels that are all month names make a date axis after all.
  At least 3 categories, except two readable words, one in each gap
  between three ticks on an axis line (an Excel bar chart of "Yes" and
  "No").
* Category labels beside grid lines (no axis line: ggplot2's
  theme_minimal) lie outside the grid lines' span; their distance is
  measured from the nearer end of the grid lines.
* A category label's position along the axis: the centre of upright
  (90°) text and of horizontal text; the end nearest the axis for slanted
  text.
* Major and minor ticks on one axis line may both match labels: keep one
  axis per line — the one matching the most labels, then the longer ticks,
  then the better fit.
* `map_value`: values closer to zero than the fit's own error
  (min(max(2·resid, 1e-9), 2e-6) × range) are 0. A log value that
  overflows becomes inf.

## 10. Graphs

* Pair x and y axes whose lines meet at a corner: for each x axis the y
  axis closest to forming a corner, and vice versa, within 8% of the longer
  axis. Axes with lines are preferred to those without. An axis shared by
  side-by-side panels takes part in several graphs. Plot box = (x.lo, y.lo,
  x.hi, y.hi). Only the first gap (the axis line to the end of the other
  axis) must be within 8%; the second may be loose (an axis set off from
  the end of the other), up to half the length of the graph's own axis.
* **Crossing axes**: axes may cross inside the plot, with their ticks and
  labels in its body (spines through the origin; Excel's log axes crossing
  at 1). An x and a y axis line, both with lines, that found no corner
  pair when each runs across the other between 5% and 95% of its length
  and their lengths are within a factor of 3; the pair crossing nearest
  the middles wins. Plot box = (x.lo, y.lo, x.hi, y.hi) as for a corner.
  Other lines round the plot (grid lines at the ends of an axis, a frame
  round the chart) carry no labels and are not axes.
* **Shared axes**: graphs stacked one above the other often carry the x
  labels under the lowest graph only (side-by-side graphs: the y labels
  left of the first). A graph whose axis line has ticks but no labels then
  uses the labelled axis of its column (row) — the pairing above with a
  second gap of more than half its axis length — only if its own axis line
  lies at the end of its other axis (within the corner tolerance), overlaps
  the labelled axis, and has the same number of ticks at the same places
  (within max(0.5 pt, 0.5% of the axis length)). Rows of only two "ticks"
  are the frame's side lines and are ignored. A graph with no ticks of its
  own needs a dark axis line at that end spanning the labelled axis (a line
  of any shade when the labelled axis has no ticks either: ggplot2 facets
  in grey frames). "That end" is the end facing the labelled axis (a left
  axis serves the panels to its right through their left sides). An axis
  beyond the end of another, with its labels in the gap between them, is
  the axis of the plot on the far side and pairs with neither as a corner
  nor as a shared axis. The
  unlabelled tick rows (`bare axes`) and the merged dark lines are kept in
  the page state for this test. Without the test, a graph whose own x axis
  could not be read borrowed the x axis of whatever graph stood below it
  (an Excel bar chart of "Yes"/"No" got the categories of the chart above).
* **Two scales** (section 10.1): a left and a right y axis over one x
  axis are first paired as two graphs with the same plot box.
* **Small multiples** (lattice/facet plots): only outer panels carry labels;
  every framed rectangle spanned by a column's x axis and a row's y axis is
  a graph sharing those scales (216 panels on one page in the corpus).
* **Insets**: a graph whose opaque background box was painted over another
  graph; a symbol belongs to the innermost graph painted before it.
* **Assigning symbols**: a symbol belongs to the graph whose box its clipping
  box matches (overlap ≥ 90% of the graph box, clip area ≤ 1.5× graph
  area); else the innermost graph containing it painted before it; else the
  nearest graph. A symbol outside that graph's box whose clipping box
  overlaps the box by less than 10% of the clipping box's area was drawn
  in a plot area that is not a graph found (its axes were unreadable or
  not shared): it is not reported (legend keys excepted).
* **Turned graphs**: a graph is turned (90, −90, 180) when the tick labels of
  both axes read in the same non-horizontal direction and the title found in
  the turned frame is at least as large as any found in the page frame. Its
  data x values come from the axis running down the page and y from the one
  running across.

### 10.1 Graphs with a scale on both sides

Two graphs sharing one x axis whose y axes span the same stretch (within
2%) at opposite ends of it (each within 2% of an end, more than 80% of the
x axis apart) are one graph with two y scales: the left axis stays `y`, the
right one becomes `y2` (likewise two x scales `x`, `x2` beside one y axis;
in turned graphs the second scale follows its axis). Each series (a legend
name; unnamed series by colour) is read against one scale, decided by, in
order:

1. its legend label: "left", "LHS", "(L)", "primary" → first; "right",
   "RHS", "(R)", "secondary", "axis 2", "y2" → second ("bottom"/"top" for
   x scales);
2. the axis titles: the text beside each axis beyond its tick labels
   (within 40 pt, along the axis), lower-cased with punctuation dropped,
   containing the series name as whole words in one title but not the
   other ("SRAM area (µm²)" / "CGP/M1 pitch (µm)" place SRAM left, CGP and
   M1 pitch right);
3. colour: tick labels or title drawn in the series' colour on one side
   only (text items carry their fill colour; black is ignored);
4. otherwise the first (left/bottom) scale, with a warning naming the
   series (only series that are output).

The graph is reported once; its rows carry `axis` (section 4.1), and the
meta file the second scale's range.

## 11. Marker symbols

### 11.1 Closed shapes

Classify each closed subpath (closed by `h`, or ending within 2% of its
size from its start; a filled subpath counts as closed):

* **Circle**: ≥ 3 Bézier curves, ≤ 1 line, box aspect > 0.85 (4, 8 or more
  arcs). Two half-circle arcs (GraphPad Prism) also make a circle: their
  control points stand 4/3 of the radius off the diameter, so the box (and
  the centre and size) come from the flattened curve, which must be round
  (every flattened point within 6% of the radius from the centre). Also an outline ring drawn as one contour (outer circle, short
  line inwards, inner circle back) — an open circle whose stroke was
  converted to a fill.
* **Polygons** (no curves): count distinct vertices (merging those closer
  than 1% of the size, dropping a closing duplicate):
  3 → triangle; 4 axis-aligned edges → square (aspect > 0.85) or rectangle
  (0.5–0.85, reported only as legend keys); 4 corners at the middles of the
  box sides (within 8% of the box's width / height) → diamond (aspect >
  0.85) or thin-diamond (0.5–0.85, matplotlib's `'d'`; elongation ≤ 2.2); 5–12 vertices, aspect > 0.7,
  mapping onto themselves when turned by 360/k (k = 2..8) → polygon
  (pentagons, hexagons, stars, filled plus signs; letters such as 'v', 'A'
  do not).
* Reject long thin shapes: elongation (√ of the ratio of principal second
  moments) > 1.8 for triangles, diamonds and polygons (dashes of dashed
  lines converted to outlines).
* In a filled path with several contours, a contour inside a larger one is
  a hole. A marker's hole repeats its shape around the same centre (open
  marker drawn as an outline); any other hole means a letter. A filled path
  of ≥ 3 outer contours of which fewer than half are marker shapes is a word
  of outlined letters. **Find holes with a grid index** (a containing box
  covers the contained box's centre), not by comparing all pairs.

### 11.2 Where the data point is

| Shape | Data point |
|---|---|
| circle, square, diamond, rectangle, plus, cross, asterisk | middle of the bounding box |
| triangle with box aspect 0.8–0.93 (equilateral: R's pch 2, 6, 17, 24, 25) | centroid (mean of the 3 vertices): R draws the apex r above the point and the base r/2 below |
| triangle filling a square box (matplotlib "^") | middle of the box |
| regular polygon, star | mean of the vertices (centre of symmetry; for a pentagon or star not the middle of the box) |
| ZapfDingbats glyph | (0.396, 0.347) em from the glyph origin |

Tried and rejected: the mean of a circle's arc ends, and the crossing point
of a plus sign's strokes. They gave no gain on synthetic plots and made two
files with known true values slightly worse.

### 11.3 Crossing strokes (+, ×, *)

* Strokes of one symbol need not be drawn together (R draws all vertical
  bars of all '+' markers first, then all horizontal bars). Match globally:
  strokes of the same colour and similar length (within 20%) whose
  midpoints coincide (within 0.15 × the shorter length) form a group
  (spatial hash on midpoints; union-find).
* Inside a group, bucket by direction (within 10°, wrapping at 180°). Two
  directions at least 25° apart → plus (axis-aligned) or cross (diagonal);
  three or more → asterisk. Form symbols from one stroke of each direction
  in drawing order; coincident symbols give several strokes per direction
  and are all reported.
* An asterisk whose diagonal rays are longer than its straight ones comes
  out as a plus and a cross (lengths differ by √2, beyond the 20%): a plus
  and a cross of one colour around the same centre (within 5% of the size),
  drawn one right after the other, with sizes within a factor of 2, are one
  asterisk.

### 11.4 Duplicates and things that are not data points

* **Fill + outline**: a filled shape directly followed by a stroke of the
  same outline (or vice versa) is one point (Excel), reported as filled.
  Only directly consecutive pairs; genuinely repeated points are kept.
* **Doubled outlines**: some converters (Acrobat Distiller) write every
  marker outline twice in a row. Form runs of identical consecutive marker
  outlines (followed across painting operations); when ≥ 90% of outlines
  are in runs of even length, a run of L outlines is L/2 points. (Compare
  start points first and only build the rounded geometry when they agree —
  rounding every coordinate of 460,000 outlines was a major cost.)
* **Highlight boxes**: an open square or circle drawn round a smaller marker
  of another colour is not a data point. Index candidates **by colour** so
  that stacks of thousands of same-colour markers are never compared.
  Boxes are a style of their own: drop them only when every marker of that
  style (shape, colour, size) surrounds another marker. Means drawn over
  the per-generator markers of the same row coincide with them only now
  and then, and stay.
* Symbols whose path is a hiding box (section 8.1) are dropped.
* **Outline rings**: a marker's outline drawn as a filled ring right after
  its filled body (stroke converted to an outline) comes out as an open
  circle round a filled one - same colour and centre, 1-2× its size,
  painted within two steps after it: the ring is dropped.
* **Dots hidden in a line**: a filled circle at most 1.3 × the width of a
  line of its colour that passes within a quarter of the line width of its
  centre cannot be seen (points at the vertices of a model curve): dropped.
* Glyph outlines that are text are never markers.

### 11.5 Flattened markers

A converter may flatten overlapping semi-transparent markers into many
clipped fragments. Rebuild circles by fitting circles to the fragments' arcs
(circumcircle of three points on each arc), merge centres closer than 8% of
the radius, and count stacked points from the colour of overlapping layers.

* Arcs of subpaths that run far beyond their circle (more than 5 radii: the
  round joins of a thick line drawn as an outline) are no marker evidence.
* Whole markers on the same page (a graph that was not flattened) stay: a
  centre where a found circle sits whose arcs all come from that circle's
  own paths is not rebuilt, and those circles are kept. Fragment symbols
  are dropped only near a rebuilt centre.
* One ladder of shades per hue (several series in different colours; the
  rebuilt circle takes the colour of one marker of its hue alone). Its
  first rung is the shade with the most arcs (the darkest aside); lighter
  shades are other things (an error bar's own colour where it meets a
  marker). A shade counts as a stack only if it is what n layers of the
  marker colour give (one layer of alpha a over white: 1 - a(1 - m); n
  layers: 1 - (1 - m)(1 - (1 - a)^n), the darkest shade taken as m): a
  semi-transparent error bar across a marker darkens a strip of it to a
  shade no stack of markers gives, and that strip is not a stack.
Warn: "markers were flattened into fragments; N circles rebuilt from their
outlines". Cap grid cells per fragment box (degenerate boxes).

### 11.6 Which symbols are reported

For each symbol, find its graph (section 10) and:

* rectangles only as legend keys;
* drop symbols farther than half the graph's larger side from it, unless
  they are legend keys or were clipped to that graph (**markers beyond the
  axis ranges, clipped out of view, are reported**, in the graph they were
  clipped to);
* drop shapes larger than max(max-frac × the graph's smaller side,
  min(3.5 pt, 0.4 × the smaller side)) — small multiples have tiny panels;
* apply `--inside-only` and `--exclude-legend`.

## 12. Bars and lines

For graphs without marker symbols:

* **Bars**: filled axis-aligned rectangles standing on the graph's baseline
  (the x axis line or the line of value 0); one point per bar at the middle
  of its top edge, symbol `bar`. A bar's middle (not the whole bar) must be
  within the box: on a category axis the box ends at the outer categories'
  centres. Bars hanging down from the lowest line when it is not 0 (ratios
  plotted from 1x: speedups below 1) count when as wide as the standing
  bars (within 5%) and no deeper than a quarter of the plot. Short bars
  that look like squares are bars too, when every square of the graph is
  one of the bars or the bars outnumber the other squares (legend keys in
  the bar colours) three to one; the other squares stay.
* **Lines** (no bars either): the vertices of data lines, symbol `line`:
  stroked polylines (pieces that continue each other joined first) and
  dashed lines drawn as many small filled dashes (chained; a vertex where
  the direction changes). Axis-parallel straight lines (grid, axes, frames)
  are not data lines. A line legend (a short line sample in the series'
  style with a label to its right) names the series.

### 12.1 Error bars (`--errbars`)

An error bar is a straight line through a marker's centre along a page
axis, reaching beyond the marker. The four columns `x_low, x_high, y_low,
y_high` give its ends as data values, written with the digits of `x_coord`
/ `y_coord`; both cells of a direction are empty when the point has no bar
in that direction (also for zero errors, which programs draw as nothing or
as a line hidden by the marker). A point with a bar on one side only gets
its own value for the other side.

* **Finding the bars.** Candidate pieces are the straight `l` segments of
  open stroked subpaths (closed ones are marker outlines and boxes) and
  strokes converted to thin filled rectangles, that are within 0.3 pt (or a
  tenth of their length) of vertical or horizontal. Excel rounds its
  coordinates, so its bars lean slightly: (433.14, 303.6) to (433.38,
  306.96); an exact axis-alignment test misses most of them. A piece's
  position is the mean of its two ends.
* For each marker (not bars or line vertices) and each page direction,
  take the pieces whose position is within max(0.15 x marker size, 0.3 pt)
  of the marker's centre line, skipping pieces wholly outside the plot box
  (+/- 0.5 pt: tick marks). Chain pieces that continue each other end to end
  (gap <= max(0.3 pt, 0.1 x size)): matplotlib draws a bar as one segment,
  Excel as two halves that start at the marker's centre. Overlapping pieces
  are not chained (they are the bars of different points at the same x);
  a piece drawn twice is one piece.
* A chain is not a bar if it spans 90% or more of the plot (grid line,
  axis, frame), does not come within 0.6 x size of the marker's centre, or
  reaches no further than 0.55 x size beyond the centre on either side
  (the strokes of a '+'). A side that reaches beyond gives that end; the
  other side ends at the point.
* **Ownership.** Points at the same x share a centre line, so a chain may
  touch several markers. It belongs to the marker at which one of its
  interior knots lies (Excel's halves meet at their marker), else to the
  marker nearest its middle (a bar drawn in one piece). Each marker takes
  at most one chain per direction.
* **Values.** Map the bar's ends through the graph's axes (a log axis gives
  asymmetric values for symmetric page lengths, as it should); low/high are
  the smaller/larger mapped value. In a graph turned by 90 degrees a
  vertical page bar gives the x range. Category axes give no values. Caps
  (the short strokes across the ends) are not needed and are ignored.

## 13. Legends and series names

* A legend key is a marker (or line sample) with a non-numeric label just
  to its right on the same line (gap −0.2 … 3 font sizes, measured from the
  end of the line sample the marker sits on; vertical offset ≤ 0.6 font
  size). Use binary search over labels and over line samples sorted by
  height (boxplots have hundreds of short horizontal lines; comparing every
  marker with every line was quadratic).
* Subscripts/superscripts continuing the label are appended, and so are
  following words set as separate pieces (same size and baseline, gap ≤
  0.4 em, not a number, no marker in between - the legend's frame box is
  no marker): "FULL" + "higher", "λ" + "=0.01".
* A key drawn several times at one place (ggplot2 draws the glyph of each
  point layer in the key box) is reported once.
* Line samples include short horizontal strokes converted to thin filled
  rectangles (Inkscape/cairo convert every stroke).
* A single key whose label cannot be read (outlined) is accepted when a
  line sample of the same legend lines up with it (left edges within one
  key size, one to three key sizes above or below), as in SPSS's "marker
  series + fitted line" legend.
* A key stands apart on its line: markers with neighbours just left and
  right of them along a dense data curve are not keys.
* Keys line up (stacked or side by side); when a page has an aligned
  legend, unaligned candidates are dropped.
* Text outside the graph holding the marker (body text beside a data point
  at the plot's edge) is not a label.
* In-graph legends with unreadable outlined names: keys when at least three,
  all different markers, of similar size, are stacked in a column with
  regular spacing. Their series name is left blank.
* Colour swatches labelled 1, 2, 3, ... in a column (runs of consecutive
  numbers): a numbered legend.
* Turned graphs: look for keys in the turned frame too.
* **Naming**: each point gets, in order of preference: the name of its line
  (line charts), the label of a key with the same marker (shape, filled,
  colour) in its graph, a colour swatch of its colour in its graph, or a
  figure legend outside all graphs matched by marker or by colour (within
  0.03 per channel; only if unambiguous). Cache by (colour, signature).

## 14. Titles and figure captions

### 14.1 Title (meta file, `--debug`; not in the points CSV)

* Text centred above the plot (within 15% of its width), gap ≤ min(0.35 ×
  height, 4 font sizes), at least 0.85 × the typical label size, not a
  number, alone on its line (legend headings share their line with keys and
  labels), not a sub-caption belonging to the graph above, not a later line
  of a caption above, not a running header or footer (the topmost /
  bottommost line of the page's text, running from the left margin to the
  right one with a wide gap: "Paper title ...   Conference '25, ..."; side-
  by-side graph titles do not reach both margins), not the axis title of
  another graph (text within that graph's width, at most 2.5 text sizes
  below its x tick labels: "Hours" under the panel above), not outside
  the box drawn round the chart (Excel's chart area: the smallest
  rectangle holding the plot box with at least 2 pt to spare, at most 1.6×
  its width and 2× its height; body text above it is no title). Prefer the
  biggest font, then the closest. Add
  continuation lines below and lines just above, words of the same line
  drawn as separate texts, and sub/superscripts.
* Failing that, a sub-caption below the plot ("(a) ...", "(b). ...",
  "Fig. 3 ..."); but not the graph's own figure caption (a title starting
  with "Fig."/"Figure" and the caption's number), which is in `caption`.
  Not a panel label standing at the top left corner of the graph below it
  (within 2 text sizes above it, ending at most 2 sizes right of its left
  edge): "(c)" above panel (c) is not the title of the panel above.

### 14.2 Figure number and caption

* Build text lines: items sharing a baseline joined left to right, **not**
  across a gap of more than one em (the gap between page columns). A line's
  size is the size of most of its text (a monospaced word may be set larger
  and must not change the line's size).
* Caption head: a line starting `Fig.`/`Figure`/`FIG.`/`FIGURE` + number
  (`5`, `3.2`, `S3`, `4a`). Reject in-text references: the text after the
  number starts with `)`, `]`, `,` or `;` (e.g. "(see Fig. 2).").
* When nothing follows the number ("Figure 1." in bold, a wide space, then
  the caption text), join the text further along the same baseline (within
  4 em).
* Choose the nearest caption head below the graph that overlaps its width.
  Other graphs of the same figure may lie in between (the caption goes below
  the whole figure): allow a gap of max(2 × graph height, 150 pt) plus 1.5 ×
  the heights of graphs across the way.
* Follow the paragraph down the column: same size (within 15%), in the same
  column, one line spacing further down — the first step sets the spacing
  (captions may be double spaced), later steps must match it within 20%; a
  line ending well short of the column's right edge ends the paragraph;
  stop at another caption head; at most 40 lines. A next line must start
  where the caption (or the line before) starts, end at the caption's right
  edge (justified text, also with a hanging indent under the text after
  "Figure 3.3:"), or be centred under it: the first line of the right-hand
  column below a short centred caption is none of these. Join a word
  hyphenated at a line end.
* Output the number and the text without the label.

## 15. The program that drew a graph

### 15.1 Recorded tool (`tool`)

* pdfTeX keeps an embedded PDF graphic's own document information in its
  Form XObject (`/PTEX.InfoDict`: Creator, Producer). A Form XObject may also
  carry XMP metadata (`xmp:CreatorTool`).
* Give each path and Dingbats marker the tool of the **innermost** embedded
  graphic that drew it (a knitr figure is a pdfTeX PDF wrapping an R plot:
  report R). A graph's tool is the most common tool among the paths inside
  its box (5% margin).
* Name choice: Creator, unless Producer extends it ("R" + "R 4.0.2" →
  "R 4.0.2"); Producer when Creator is empty; then CreatorTool. Tidy: drop
  surrounding parentheses, a trailing web address, backslash escapes left in
  by the writer (`\(R2017b\)`), MATLAB's "Operating System: ..." suffix;
  collapse spaces. Decode UTF-16 strings.
* Never report converters: Ghostscript, Acrobat Distiller, PScript5.dll,
  AdobePS, PDFium, Quartz PDFContext, "Print to PDF", cairo, PDF libraries,
  PDFlib, iText, ps2pdf/epstopdf/dvipdf, printer drivers. "Acrobat PDFMaker
  ... for Excel" → "Microsoft Excel".
* Fallback: the document's own Creator/Producer/XMP, **only if it names a
  plotting program** (R, matplotlib, gnuplot, MATLAB, Octave, Excel,
  Origin, Mathematica, Stata, SAS, SPSS, Prism, SigmaPlot, Igor, Grace,
  Veusz, Plotly, Bokeh, Maple, JMP, Minitab, Tableau, Julia, S-PLUS,
  Statistica, gretl, EViews, KaleidaGraph, Scilab, LabVIEW, ...). The
  Creator of a LaTeX or Word document says nothing about a chart inside it.

### 15.2 Guess from the drawing style (`tool_guess`)

Record for each path a style tuple: (line width in page units, line cap,
line join, decimals of the stream's numbers, Form XObject resource name,
ExtGState resource name). Score each program from the paths, texts and
Dingbats markers in and around the graph (10% margin horizontally, 15%
vertically):

| Program | Signs (score) |
|---|---|
| R | ZapfDingbats circles (+3); ≥ 80% of strokes with round cap and join and ≤ 3 decimals (+2); R 4 palette, R 3 green3/gray, rainbow(8) (#FFBF00, #80FF00, ...) |
| R (ggplot2) | R's evidence plus #EBEBEB grid and the hue palette (#F8766D, #00BFC4, #7CAE00, #C77CFF, ...) |
| R (lattice) | R's evidence plus #FFE5CC strips, #0080FF points |
| matplotlib | ≥ 80% of ExtGState names A1, A2, ... (+3); Form names M0, M1, ... (+2); DejaVu fonts (+2); tab10 palette |
| MATLAB | #262626 axes and labels (+1.5); line colours #0072BD, #D95319, #EDB120, ... |
| Excel | Calibri (+2), Arial with other Excel evidence (+1); Office palettes 2003 (#000080, #FF00FF), 2007–10 (#4F81BD, #C0504D, gridlines #868686), 2013+ (#5B9BD5, #4472C4, #ED7D31, #D9D9D9, #595959); ≥ 3 filled diamonds with Excel evidence (+1) |
| gnuplot, Mathematica, Stata | default palettes (Appendix C) |

* A palette scores 1 + the number of its distinct colours present (max 3),
  only if its colours make up ≥ 20% of the graph's non-common colours (one
  colour of a rainbow that happens to match proves nothing). Common colours
  (black, white, primaries, greys) never count.
* Match colours exactly first; only when no palette has the colour exactly,
  match within 2 units per channel (converters shift colours: #EDB120 →
  #EDB021).
* Helvetica adds 0.5 to R or MATLAB when they already score.
* Report the best program if it scores ≥ 2.5 and leads the next by ≥ 1
  (R and its packages don't compete with each other); else empty.
* Results to expect on the corpus: agreement with the recorded tool for
  every graph whose tool is recorded; fresh matplotlib plots in default,
  classic, 'ggplot' imitation and seaborn styles all → matplotlib. Validate
  the rules on plots not used to write them.

## 16. Number precision

* Read how many decimals a stream's numbers are written with: the 95th
  percentile over the numbers of the first 2 MB (one odd number must not
  count), capped at 12.
* Each path and Dingbats marker gets a resolution in page units:
  10^−decimals × √|det(CTM)| (for glyphs the text rendering matrix).
* Through the axis mapping: linear rv = |a| × res (max of both pieces when
  piecewise); log rv = |v| × ln 10 × |a| × res.
* Significant digits = floor(log10|v|) − floor(log10 rv) + 2 (the digits the
  coordinates resolve plus one guard digit, so rounding the output adds at
  most a tenth of the coordinates' own rounding), at least 6, at most 15.
  Unknown resolution, 0, non-finite → 6. Category values are labels.
* `--digits N` writes every number with N significant digits instead.
* Other numbers (pdf_x, pdf_y, meta tick values) use `%g` unless `--digits`.
* Expected accuracy on synthetic plots with axes 0–100 over 400 pt
  (section 19.4): coordinates written with 3 decimals → maximum error
  1.25e-4 data units (exactly the PDF's rounding); with 10 significant
  digits → 1.25e-8. The extraction itself must add nothing measurable.

## 17. Robustness and performance

Requirements, all from real files:

| Case | Requirement |
|---|---|
| 69 MB content stream, 2.9 million operators, 200,000 markers | finishes in well under a minute, every marker found |
| 92 MB Form XObject, 2.3 million operators, 472,000 outlier circles | whole 11-page file < 60 s; peak memory < 2 GB (it was > 10 min and killed at 3.9 GB) |
| degenerate box ±1.5×10^9 pt | no hang (cap grid cells per box) |
| "10^602" in body text | no crash, no number |
| corrupt Flate / ASCII85 streams | page still read; warning |
| 3-D graphs | finish in about a second, "No vector graphics found" |
| any exception in one page | other pages still processed; warning |

Rules that follow:

* No algorithm may be quadratic in the number of markers, paths or text
  items on a page. Use spatial grids (with a cap on cells per item and a
  list for oversized items), sorting + binary search, caches keyed by
  (colour, signature), dictionaries by colour.
* Shapes of very different sizes (0.1 pt clipped-marker fragments beside
  7 pt glyphs): one grid sized by the median makes big shapes scan
  thousands of cells, and one sized for the big ones crowds the small ones.
  File them by size class (powers of two), cells as big as the class, and
  search from each shape only its own and the bigger classes, within the
  reach of the class's biggest shape. Classes of 8× were tried: their cells
  are too coarse for small shapes in dense clusters.
* Stacks of identical items (duplicate points: 30 strokes on one spot)
  join each other without comparison; compare one representative each.
* A grid's cell must suit every item that searches it. Crossing strokes
  pair only when their lengths are within 20%: file them by length class
  (factors of 1.2), cells 0.15 × the class's longest stroke, and search
  the two classes either side. One grid with cells sized by the median
  stroke turned a page of 441 000 strokes of 0.01 pt (curves drawn point
  by point) into 10^8 cell visits per long stroke: it ran for hours.
* Do expensive work only when its result can be used: a word that fails
  the one-line box test is not rasterised; marker discs are flattened as
  possible letters only when the page has letter-like outlines at all.
* Work out pure per-subpath results (flattening, marker classification,
  thin-stroke test) once and keep them on the subpath; a modified copy
  must not inherit them. A separate dictionary keyed by id costs more
  than it saves when a result is asked for only once.
* Cache what depends only on a clipping box (its graph), not per symbol
  (a per-symbol cache cost more than recomputing).
* Do not keep large intermediate lists of objects when a stream can be
  processed incrementally.
* Profile with a 92 MB-stream page: about 15 s to execute, about 20 s for
  all the analysis after it. Reference times of this version (one core):
  200 000 markers 32 s, 472 000 markers 35 s, 50 000 outline fragments
  19 s, 14 900 markers 3.3 s, 216 small-multiple panels 1.6 s.

## 18. Problems met while building the current version

Each of these cost time; a new implementation should avoid them from the
start.

1. **Slow tokenizing**: pdfminer's parser took many minutes on a 69 MB
   stream. Then qpdf's tokenizer was fast but its object list took 2.5 GB.
   Solution: the streaming tokenizer (7.1).
2. **Quadratic steps on huge plots**: highlight-box search (stacked
   markers in one grid cell), legend line samples (every marker × every
   line), hole detection (all contour pairs), category mapping (min over
   all ticks per point), figure-legend matching, re-classifying every
   subpath twice. Each was fixed with an index or cache.
3. **Grid indexes and degenerate boxes**: a 3×10^9-pt box made a cover
   index loop for ever. Cap cells per box everywhere a grid is used.
4. **Overflow**: "2^2000 ≈ 10^602" raised OverflowError; parse such
   strings as non-numbers.
5. **Exponent minus dashes** of outlined "10^-2" labels were taken for tick
   marks; exclude them from tick detection.
6. **In-graph legend false positives**: require ≥ 3 keys, distinct
   signatures, similar sizes and regular spacing in a column.
7. **Markers beyond the axis ranges** (clipped out of view) were first
   dropped; the user requires them reported. Assign them to the graph they
   were clipped to.
8. **Empty output**: with no points, print no header and create no `-o`
   file; the "no graph" warning text is "No vector graphics found".
9. **Marker centres**: R's equilateral triangles were 0.21 data units off
   (box middle instead of centroid); pentagons/stars 0.06–0.07; asterisks
   with unequal rays reported twice. Measure against synthetic plots with
   known values (19.4) rather than guessing.
10. **Output precision**: 6 significant digits added up to 5e-5 error,
    4,000 times the precision of 10-digit coordinates. Choose digits from
    the coordinates' precision (16). Guard digit needed to reach the bound.
11. **Accuracy experiments can mislead**: averaging a circle's arc ends
    looked better in theory but was worse on files with known truth; the
    synthetic plots' marker radius (2.5 pt) shared the centre's rounding, so
    averaging could not help. Check every "improvement" against real files
    with known values (supplied reference, values on a known grid).
12. **Measurement precision**: true-value files written with 10 significant
    digits added 5e-9 error to the measurement; write them with full
    precision (`repr`). A hand-made reference rounded to 6 digits (2010.67 for
    2010 + 8/12) made a correct program fail.
13. **Captions**: labels set apart from their text ("Figure 1." then a wide
    space), double-spaced captions, monospaced words set larger, in-text
    references ("Fig. 2).") and figures whose caption lies below several
    stacked graphs each needed a rule (14.2).
14. **Tool metadata**: document-level Creator is usually LaTeX/Word; embedded
    graphics' info names converters as often as plotting programs; MATLAB
    strings carry escapes and an OS suffix (15.1).
15. **Style guessing**: a rainbow plot accidentally matched an Office
    palette; tolerant colour matching made R's rainbow #FFBF00 look like
    Excel's #FFC000. Hence the share threshold and exact-before-near
    matching (15.2).
16. **Version-dependent tests**: a test that read the tool of a matplotlib
    file broke when the generator re-created the file with a newer
    matplotlib. Tests must not depend on versions of tools that generators
    use.
17. **Shell quoting in the test runner**: an apostrophe ("R's") in a case
    name broke the bash script; a heredoc inside a here-document ended it
    early. Keep case names free of `'` and generate edits from files.
18. **Empty subpaths**: an Inkscape-converted SPSS plot wrote a bare
    move-to after every shape. Kept as subpaths, they made every one of its
    496 markers look like a letter with a hole, and only the legend key and
    two text glyphs were reported. Drop segment-less subpaths.
19. **Letters as markers**: with all text outlined, 'o', 'c', full stops,
    'i' dots and a capital 'N' were reported as markers (in captions, axis
    titles and legends), and a stray 'N' in a bar chart even stopped its bars
    from being looked for. Fixing it took care: including marker-like
    shapes in words also absorbed a diagonal run of overlapping diamond
    markers and changed the page's reading direction vote. Hence the
    overlap, in-line and vote rules (8.3).
20. **Pixel-snapped plots**: the SPSS plot's renderer placed markers and
    ticks on a 0.43 pt grid, so points are off by up to 0.06 x units
    (all points of one x value share the same offset). That rounding happened
    before the PDF was written and cannot be undone; the extracted points
    reproduce the legend's regression line to within 0.8% in slope and 1.2%
    in intercept.

21. **Slanted error bars**: Excel draws each error bar as two halves from
    the marker's centre to the centre of its cap, and its coordinate
    rounding moves one end by a quarter of a point, so the halves lean by
    up to 4 degrees. An exact horizontal/vertical test found bars on only a
    few of the 30 points; accept segments within 0.3 pt or a tenth of their
    length.
22. **A label taken for a multiplier**: matplotlib's log-axis minor labels
    "3×10^1" were not joined (mathtext spaces the "×"), so a lone "10^1"
    stood beside the neighbouring panel's x axis and was applied to it as a
    "×10^1" multiplier: every x value came out ten times too big, and the
    log axis itself got no labels at all.
23. **Circles of two arcs**: GraphPad Prism draws each marker with two
    half-circle Béziers; the box of their control points is 4/3 taller
    than wide, so none of the 140 markers was taken for a circle.
24. **Shared axes by accident**: stacked graphs with one row of x labels
    worked because the pairing never checked the second gap; but that also
    let any graph whose axis was unreadable take the scale of the graph
    below it, which had put wrong category names on a two-bar chart in
    the corpus for a long time. Sharing now has to be justified by the
    graph's own ticks (section 10).
25. **Ticks as outlined boxes**: InDesign draws each tick as a 0.3 × 1.5 pt
    rectangle, filled and stroked; closed stroked subpaths were never
    ticks, and once they were, the stroked copy duplicated every position
    and the box tops joined into false axis lines.
26. **Corner labels**: in a boxed plot whose end labels (1990, 2020; 0.01,
    1) sit at the frame corners without ticks, the year labels came as one
    string "1990 1995 2000" that could not be cut at the ticks, and the
    right scale had a single tick. Trying the line ends as ticks fixed
    both — but on a lattice frame split at panel borders it turned every
    piece into a two-label axis, and on an axis starting before 0 it put
    0 at the line's start: hence the fit-quality test.
27. **A tick taken for a minus sign**: an inward tick just left of the
    right-hand label "0.1" made it −0.1. The frame's right edge was the
    rectangle's implicit closing segment, so a check of `l` segments only
    missed it.
28. **Small-caps captions** read "figure 2." in lower case.
29. **No ticks, no axis lines**: a seaborn darkgrid plot has white grid
    lines on a grey rectangle and nothing else; grid lines stand in for
    ticks only when they start on an axis line, so the grey rectangle's
    edges must serve as axis lines. Its thin diamonds ('d', aspect 0.6)
    were no shape at all, and its caption became the graph title.
30. **Speed with many points** (refactoring round): outline fragments of
    clipped markers took 68 s, mostly in grouping glyphs into words (a grid
    sized by the median glyph) and testing marker-like glyphs against all
    others of their word (words of 16 000 fragments); a per-symbol graph
    cache and a per-id subpath cache each turned out slower than the work
    they saved and were replaced (section 17).
31. **Grid lines only**: ggplot2's theme_minimal has neither ticks nor axis
    lines. Grid lines stood in for ticks only when an axis line was found
    at their ends; one panel's grid happened to start on the other
    direction's lowest minor grid line and worked, its neighbour's did not
    (2.2 pt off, the tolerance being 2.1 pt) and lost its x axis. Upright
    category labels were anchored at the end of their baseline, 2.4 pt off
    centre, so the "between ticks" layout fitted better and every bar got
    its neighbour's name. Labels "10kB" ... "1MB" and "1.26x" were words.
32. **A page that never finished**: an R plot drawing its curves as 441 000
    one-segment strokes (and 9 999 tiny circles) beside long axes; the
    crossing-stroke grid of problem 30 had cells sized by the median
    stroke (0.002 pt), so each long stroke scanned some 10^8 cells. With
    length classes the page takes 18 s.
33. **Control characters as coordinates**: the axis labels of matplotlib
    3.3.3 graphs in 2305.15675v1, in Type 3 copies of Arial without ToUnicode
    whose /Differences name glyphs by glyph number ("uni00000019" for code
    54, "6"), came out as NUL 0x19 ..., and were then used as category
    names for both axes. The codes themselves are ASCII. (A first fix,
    written without the PDF, read the embedded program of CID fonts and
    dropped control characters: it removed the labels, and with them the
    graphs of four pages.)
34. **Grid lines through three panels**: matplotlib panels with grid lines
    for ticks, three in a row with the same height: their vertical grid
    lines made one group spanning all three, 83 pt lines against a 461 pt
    span, so not "grid lines" but ticks too long for any axis line - no
    graph at all. Then the lower panels took the upper panels' axis title
    "Hours" as their title, and the centred one-line caption took on the
    first line of the right-hand column below it. A caption continues only
    with a line that starts where it (or the line before) starts, ends at
    its right edge, or is centred under it.
35. **Two panels sharing project names**: ggplot2 panels without ticks or
    axis lines, a light grey block over the positive half of each panel.
    The project names were measured from the implicit axis line and
    sometimes fell inside the grid span; the mean markers (open circles,
    larger) that happened to surround a triangle or square of the same row
    were taken for highlight boxes (pexpect, portalocker lost their means);
    "FULL higher" came as "F", "ULL" and "higher" and was named "F"; the
    open-symbol keys appeared twice, one per point layer.
36. **Axes crossing in the middle**: three Excel scatter plots with log
    axes (0.1, 1, 10) crossing at 1; the axis lines meet halfway along each
    other, not at a corner, so no graph was found ("No vector graphics
    found").
37. **Labels without ticks**: an Excel line chart of 1061 loops, the x axis
    labelled 1, 101, ... 1001 with no tick marks, the y axis a log scale
    whose only "ticks" are the axis line at 1 and a grid line at 10. Only
    the y axis was found; then the body text above the chart's box became
    its title.
38. **No ticks anywhere**: ggplot2 panels with axis.ticks blank - five
    graphs, labels at the four corners and between, no tick marks. Nothing
    was found. Then: the y label "0.50" ran into the sideways axis title
    (a 14-glyph word, unread); the markers, flattened with semi-transparent
    error bars into pieces of blended colours, were counted as stacks of
    up to four (all colours of all three series on one ladder; the strip
    under each error bar read as a second layer), and the whole markers of
    the two lower graphs were counted four times as the darkest shade; each
    lower marker was found twice (body and outline ring) and the model
    curves' vertex dots counted as points; the facets without labels took
    the scale of the panel to their right; "(c)" became the title of the
    facet above it.

## 19. Regression testing

### 19.1 Runner (`tests/run_tests.sh`, bash only)

The user requires the main test script to be bash (no Python runner); it
needs only bash ≥ 3.2 (macOS), awk, grep, sort, diff, cmp, and `timeout` if
available (600 s per run). Options: `-v` (one line per case with its run
time), `-k TEXT` (case-insensitive substring of the case name),
`--update` (rewrite expected CSVs from the program, reporting created /
unchanged / UPDATED; hand-made references are kept), `--generate`
(re-create the synthetic PDFs with the Python generators, skipping the
matplotlib one if matplotlib is missing, then run the cases), `-h`.
`$PYTHON` chooses the interpreter (default python3). Exit status 0 when all
selected cases pass; "no cases selected" → 1. Summary: "N cases: P passed,
F failed (Ts)" and the names of failures.

Cases are listed in the script itself, one call each:

```
t 'name' --pdf FILE [options] [-- program arguments]
  --expect CSV      CSV the program must reproduce
  --tol N           largest absolute difference in numeric columns (default 1e-6)
  --cols a,b,...    compare only these columns (default: all of CSV)
  --keep            hand-made reference: never overwritten by --update
  --exit N          required exit status (default 0)
  --stderr TEXT     a message stderr must contain (repeatable)
  --out FILE        write with -o to a temporary FILE (must not be created
                    when there are no points; stdout must then be empty)
  --counts 'graph symbol=N|...'   points per graph and symbol (big outputs)
  --meta CSV        also write -meta and compare; "--meta -": none created
```

Without `--expect` or `--counts` stdout must be empty. Comparison: same
rows in the same order; text columns identical; numeric columns within the
tolerance; at most 10 differences listed, then "... and N more". The CSV
parser must handle RFC 4180 quoting (a fast path when a line has no quote).
Check that the checker catches every kind of difference by mutating
expected files in a copy.

### 19.2 Generators (Python, in `tests/`, writing into `tests/data`)

* `make_line_plus_pdf.py` (standard library): a plot of filled circles and
  plus signs drawn as R draws them (all vertical bars first), duplicates, a
  legend, exact known values; also turned clockwise and counter-clockwise
  (must give identical values); document information as R's pdf() writes it
  (Creator "R", Producer "R 4.3.1").
* `make_date_axis_pdf.py` (standard library): date tick labels ("Jan
  2010" ...), labels and title in a font with /Differences glyph names
  including the /fi ligature; full-precision reference values.
* `make_random_symbols_pdf.py` (standard library): see 19.4.
* `make_synthetic_pdfs.py` (matplotlib): two-panel log plot, multi-page
  markers.
* `make_digit_templates.py` (Pillow + fonts): prints the digit templates
  embedded in the outlined-text reader.
* Generators must be deterministic (fixed seeds); re-running the standard-
  library ones must reproduce the committed files byte for byte.

### 19.3 Corpus (real files; keep them)

| File | What it exercises |
|---|---|
| schumpeter-001 | ggplot2 plot in a LaTeX Form XObject; Bézier circles; legend; supplied reference CSV (tolerance 0.001) |
| rofpc-19 | four log-log graphs in one stream; ZapfDingbats circles; titles; figure caption below stacked graphs |
| mpl-two-panels-log, mpl-multipage-markers | matplotlib; panels; marker XObjects; duplicates; vector minus signs; `--pages`, `--internal` |
| effort-fig2-excel-diamonds | Excel via Distiller; ~3000 diamonds of four lines; inward ticks; several labels in one TJ; sub-caption titles |
| swed-bank | 9 pages; Excel scatter plots in separate forms; fill+outline diamonds; bar charts with category axes; captions set apart from their labels |
| Schalken_PhD-057 | R graphs mixing Dingbats circles and crosses; legend series |
| King_PhD-214 | graph turned 90° clockwise; no tick marks (grid lines); Times-Roman without widths; labels in one TJ |
| ssrn-4204819-016 | 1870 grey circles; turned anticlockwise; log-log; all text and lines outlined |
| 2304_10304v3-005 | matplotlib histogram markers via /M0; 10^n labels with superscripts; minor ticks |
| Estimatingcomputerdepreciationauctiondata-001 | every outline written twice (Distiller); clipped markers |
| broken-axes | Excel graphs with axis breaks and labels edited by white boxes |
| grid-line-axes | axes from grid lines; outlined labels including '%'; breaks with one label beyond |
| symbols-on-axes | '+' markers on the axes; colour-swatch legend |
| log-inset | log axis with unlabelled minor ticks; ×10^-9 multiplier; insets; MATLAB |
| nominal-axis | outlined category names (#1..#35) |
| short-years | '95-style years; nominal axis with log y axis |
| lattice-panels | 216 panels on one page; merged tick labels '510 20'; figure legend |
| month-axis | month names with years beneath; solid and dashed line series |
| histogram | 16 small histograms; short bars that look like squares |
| frame-corner-axes | body text beside a graph is no legend |
| plus-symbols-log-axes | ~7700 '+' markers as separate strokes; numbered legend; clipped markers reported |
| 1209.1411v2-013 | outlined labels with exponent minus dashes; points beyond the axes; in-graph legend with unreadable names |
| 2510.19281v2-013 | SPSS scatter converted by Inkscape: empty subpath after every shape; all text outlined (Bézier 0s, letters that look like markers); legend key beside a line sample converted to a thin rectangle |
| log-clipped-markers | circles flattened into clipped fragments |
| mpl-errorbars | `--errbars`: matplotlib bars in one piece, asymmetric x and y errors, zero errors, two points at one x, log y panel with "3×10^1" labels; compared with the known values (tolerance 1e-6) |
| Rescaling_reliability_bounds_new_opprof-002 | `--errbars`: Excel bars as two slightly slanted halves with caps; dense stacks of points; log-log |
| number-sense-across-the-lifespan-004 | GraphPad Prism: two stacked graphs sharing the x axis (labels under the lower one only); circles of two Bézier arcs, filled then stroked; interdecile bars (`--errbars`) |
| mpl-shared-axes | matplotlib sharex (stacked) and sharey (side by side); a stacked panel with other, unlabelled ticks takes no scale and its markers are not reported |
| 2017_End-of-Moores-Law-004 | two y scales: SRAM left, CGP and M1 pitch right (by the axis titles); InDesign ticks as tiny outlined boxes; end labels at the frame corners; one-tick right scale; small-caps caption |
| mpl-twin-axes | matplotlib twinx: the scale of each series from the axis titles, from legend labels "(left axis)" / "(right axis)", and from tick label colours (no legend) |
| 2205.01842-004 | seaborn darkgrid: no ticks or axis lines, white grid lines on grey; thin diamonds; the caption is not the title |
| mpl-background-grid | darkgrid with thin diamonds; a plot area tiled with grey blocks whose white gaps are the only tick positions; known values (tolerance 1e-6) |
| 2308.04748-008 | six matplotlib panels on light blue, grid lines through three panels in a row; sub-captions as titles; a centred caption above two-column text |
| mpl-crossing-axes | spines through the origin (four quadrants); log axes crossing at 1 with grid lines at the y ends and a frame round the figure; known values (tolerance 1e-6) |
| 3276496-020 | three Excel scatter plots, log axes 0.1 ... 10 crossing at 1 in the middle of the plot, grid lines at the y ends, frames |
| mpl-label-ticks | x labels without ticks (1, 101, ... 1001), log y with grid lines at 1 and 10 only, body text above the chart box |
| 3276496-014 | Excel line chart: category x axis without ticks (1 ... 1001), log y axis from two grid lines; body text above the chart box |
| mpl-no-ticks | no tick marks: label centres as positions (0.00 ... 1.00; 4, 8, 12), a facet sharing its left neighbour's y axis, dots hidden in a line |
| cheyette2024limited-008 | five ggplot2 panels without ticks; facets sharing a y axis in grey frames; flattened markers with transparent error bars; whole markers with outline rings; model-curve dots |
| 2610.20068v1-009 | two ggplot2 panels sharing project-name categories, a grey block over the positive side, grid lines only; means over per-generator markers; small-capital two-word legend labels; keys drawn once per layer |
| 2305.15675v1-p7-13 | pages 7 and 13 of 2305.15675v1: Type 3 Arial whose glyph names spell glyph numbers; four histograms, a grouped bar chart with category labels |
| mpl-font-type42, mpl-font-no-unicode, mpl-font-no-subtype | the same matplotlib graph with TrueType text, then with the text's codes made glyph numbers and every map to Unicode removed (no ToUnicode, no cmap table), once with the Type 0 font's /Subtype removed too: all three must give the same CSV |
| 61676858-74 | R curves of 441 000 one-segment strokes beside long axes (once ran for hours); 9 999 tiny circles per graph |
| 3759548.3763370-007 | ggplot2 theme_minimal (major and minor grid lines only): two log-log scatter plots (one labelled 10kB ... 1MB) and a bar chart of speedups from 1x (labels 1x ... 2.5x, bars below 1x, 57 upright category labels); running header |
| 2001.10488v4-56 | 69 MB stream (counts only) |
| 2001.10488v4-121 | 3-D cubes and a degenerate box: no graph, fast |
| S1383762124002030 | 92 MB form on page 9 (counts only); two-column journal pages 6–7 with captions (points and meta) |
| overflow-exponent | "10^602" in body text |
| encrypted*, enc-* | RC4-40/128, AES-128/256, user password |
| bad-stream, damaged, not-a-pdf, no-graph, many-shapes, zero-width-glyph, doubtful-axes | clean failures and "no graph" |

### 19.4 Accuracy tests with known values

`make_random_symbols_pdf.py` draws, for each marker kind, 1000 points with
x and y uniform on [0, 100] (fixed seed per kind), axes 0–100 with ticks
every 20, 4 pt per data unit; every marker drawn by its program's
convention. Two files per kind: coordinates with 3 decimals
(`random-<kind>.pdf`) and with 10 significant digits (`random10-<kind>.pdf`);
true values with full precision and the expected symbol name in
`random-<kind>.reference.csv`. Kinds: circle (4 Béziers, filled), open
circle, circle of 8 Béziers in a Form XObject placed with `cm ... Do`,
Dingbats a71 circle, diamond of four lines (`m l l l l S`), filled diamond,
diamond filled then stroked, square (`re f`), open square, R up and down
triangles (equilateral), matplotlib triangle, pentagon, hexagon, star, plus
(all verticals first), cross, R asterisk (equal rays), asterisk with longer
diagonals. Cases require every point, in order, with the right symbol name,
within 1.3e-4 (3 decimals) and 1.3e-8 (10 digits).

### 19.5 Working practice

* After any change in output, run `--update` and verify every changed
  expected file: for formatting-only changes, check each new value rounds
  to the old one; otherwise judge against known truths before accepting.
* Keep timing in mind: the whole suite runs in about 3–4 minutes.
* Run the suite from a fresh unpack of the delivered archive.

## 20. Acceptance criteria

1. All regression cases pass from a fresh unpack, including `--generate`.
2. The accuracy cases of 19.4 pass with default options.
3. The performance cases of section 17 meet their limits.
4. The tokenizer reproduces qpdf's operators and operands on every content
   stream of the corpus.
5. Messages, exit codes and "no output" behaviour exactly as in section 3.
6. Meta file columns and semantics as in section 4.2; `tool_guess` agrees
   with the recorded tool on every corpus graph that records one.

## 21. Appendices

### A. ZapfDingbats marker glyphs (code: shape, AFM box)

```
59  (;)  a27  plus      (35, 0, 725, 692)
108 (l)  a71  circle    (35, -14, 757, 708)
110 (n)  a73  square    (35, 0, 726, 691)
115 (s)  a76  triangle  (35, 0, 858, 705)
116 (t)  a77  triangle  (35, -14, 858, 692)
117 (u)  a78  diamond   (35, -14, 754, 705)
data point: (0.396, 0.347) em from the glyph origin (R's pdf() device)
```

### B. Marker conventions used by the random-symbol generator

* R triangle (pch 2/17): TRC0 = √(4π/(3√3)), TRC1 = TRC0·√3/2, TRC2 =
  TRC0/2; with xc chosen for a 2r-tall triangle: apex (x, y + TRC0·xc),
  base corners (x ± TRC1·xc, y − TRC2·xc).
* matplotlib "^": (0, 1), (−1, −1), (1, −1) scaled by r about the point.
* R asterisk (pch 8): cross from (−xc, −xc) to (xc, xc), plus with arms
  √2·xc.
* Bézier circle constant 0.5522847498; 8-arc circle control length
  (4/3)·tan(π/16)·r.

### C. Default palettes (lower-case hex)

```
ggplot2   f8766d 00bfc4 7cae00 c77cff 00ba38 619cff e76bf3 a3a500 00bf7d 00b0f6 ebebeb
lattice   ffe5cc 0080ff ccffff
R         df536b 61d04f 2297e6 28e2e5 cd0bbc f5c710 00cd00 bebebe
          rainbow(8): ffbf00 80ff00 00ff40 0040ff 8000ff ff00bf
matplotlib 1f77b4 ff7f0e 2ca02c d62728 9467bd 8c564b e377c2 7f7f7f bcbd22 17becf
MATLAB    262626 0072bd d95319 edb120 7e2f8e 77ac30 4dbeee a2142f
Excel     000080 4f81bd c0504d 9bbb59 8064a2 4bacc6 f79646 5b9bd5 4472c4 ed7d31
          a5a5a5 ffc000 70ad47 868686 d9d9d9 595959 9999ff 993366 ffffcc
gnuplot   9400d3 009e73 56b4e9 e69f00 f0e442 0072b2 e51e10
Mathematica 5e81b5 e19c24 8fb032 eb6235 8778b3 c56e1a 5d9ec7
Stata     1a476f 90353b 55752f e37e00 6e8e84 c10534 938dd2 eaf2f3
common (never evidence): 000000 ffffff ff0000 00ff00 0000ff 808080 c0c0c0
```

### D. Packages that could replace hand-written parts

See docs/PACKAGES.md of the current version: e.g. Tesseract (pytesseract)
for outlined text including letters, which would recover category and
legend names now numbered or left blank.

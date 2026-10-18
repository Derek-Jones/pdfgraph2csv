# pdf_points.py

A program to extract the x/y coordinates of data points, displayed as symbols within a graph, drawn using vector graphics within a pdf file.  Graphs represented using raster graphics (e.g., jpeg and png formats) are ignored.

The program is still new and under active development.

The following command will send the x/y coordinates of any detected data points within any graphs contained in ``interesting.pdf`` to standard output:

``python3 pdf_points.py interesting.pdf``

an output file can be specified:

    python3 pdf_points.py interesting.pdf -o interesting.csv

By default the message ``warning: No vector graphics found`` is output when no data points are detected.

`python3 pdf_points.py --help` lists the options.

The program is written in python and needs python 3.9+

    pip install -r requirements.txt     # pikepdf, pdfminer.six, fonttools, python-dateutil

A myriad of different ways are used to display symbols denoting data values, e.g., instruction to output a circle, or four instructions that output the four (sometimes eight) bezier curves forming the quadrants of a circle.

If no x/y coordinates are output, it's possible that the technique used to support them is not yet supported.  The first thing to do is check whether it's possible to [extract the graph](https://github.com/pdfcpu/pdfcpu) as a known raster image format.  If no image can be extracted, the the process involves extracting the page containing the graph, then [uncompressing the pdf, and looking at the sequences of internal pdf instructions](https://shape-of-code.com/2025/07/27/a-process-to-find-and-extract-data-points-from-graphs-in-pdf-files/).

| Package | Used for |
|---|---|
| pikepdf (qpdf) | opening the file: repairing damaged files, decryption (RC4, AES-128/256), decoding streams |
| pdfminer.six | the content-stream interpreter, resources, fonts and CMaps, standard-14 font metrics |
| fontTools | glyph names → Unicode (Adobe Glyph List) for fonts with /Differences |
| python-dateutil | month names and date tick labels ("Mar 2010", "2010-03-15", "Jan-10") |

## Layout

    pdf_points.py        command-line wrapper (run this)
    pdfpoints/           the package that does the work, one module per step:
      document.py                                      opening the file
      fonts.py interpreter.py                          drawing a page
      occlusion.py text.py outlined_text.py            the page's text
      axes.py labels.py scales.py                      ticks, labels, value mappings
      graphs.py titles.py                              plot boxes, panels, insets, titles
      symbols.py fragments.py charts.py                markers, bars, line vertices
      legend.py                                        legend keys and series names
      pipeline.py cli.py                               putting it together
      geometry.py grouping.py colours.py context.py    shared helpers and page state
    docs/DESIGN.md       the pipeline, module dependencies and record formats
    docs/PACKAGES.md     packages that could replace hand-written parts
    tests/               regression suite

`pdfpoints/__init__.py` describes the method in detail.  From Python:

    from pdfpoints import extract
    rows = extract("plot.pdf")          # list of dicts, one per point

or, from this directory, `python3 -m pdfpoints plot.pdf`.

## Regression tests

    python3 tests/run_tests.py            # all cases (exit status 0 = pass)
    python3 tests/run_tests.py -v         # one line per case
    python3 tests/run_tests.py -k rofpc   # cases whose name contains "rofpc"

Output columns: page, graph, symbol, series, legend_key, x_coord, y_coord, color, color_hex.
When no data points are found nothing is written (not even the header line),
and an output file named with `-o` is not created.

Each case in `tests/cases.json` runs `pdf_points.py` on a PDF in `tests/data`
and compares the result with the expected CSV: same rows in the same order,
identical text columns, numeric columns within the case's tolerance.

| Input PDF | What it exercises |
|---|---|
| schumpeter-001.pdf | ggplot2 plot in a LaTeX Form XObject; Bezier circles; legend keys |
| rofpc-19.pdf | four log-log graphs in one stream; ZapfDingbats glyph circles; graph titles |
| mpl-two-panels-log.pdf | matplotlib; side-by-side panels; power-of-ten log axis; marker XObjects; duplicate point |
| effort-fig2-excel-diamonds.pdf | Word/Excel via Acrobat Distiller; 3 graphs, ~3000 diamonds drawn as four lines; inward ticks; several labels in one TJ with wide character spacing; sub-captions below the plots as titles |
| swed-bank.pdf | 9-page LaTeX paper; four Excel scatter plots on page 6 in separate embedded forms; each diamond drawn as fill + outline (counted once); bar charts with category axes (High/Medium/Low, between-tick Excel labels) on page 4. Refitting the extracted points reproduces Excel's printed R² values exactly. `--pages 6` has its own expected file (graph numbers start at 1 there) |
| Schalken_PhD-057.pdf | two R graphs, each mixing ZapfDingbats circles (a71) and crosses (a27); legend gives the `series` column. All markers are anchored at the a71 centre: the integer-valued data confirm it |
| synthetic-line-plus.pdf | made by `tests/make_line_plus_pdf.py`: plus signs drawn as two strokes with all vertical bars first, duplicated points, legend; exact known values |
| King_PhD-214.pdf | graph turned 90° clockwise (y axis across the top, x axis down the left); no tick marks, grid lines act as ticks; Times-Roman labels without width table, all in one TJ; two-line title |
| synthetic-date-axis.pdf | made by `tests/make_date_axis_pdf.py`: x tick labels are dates ("Jan 2010" ... "Jan 2011", python-dateutil); labels and title use glyph names from /Differences, including the /fi ligature (fontTools); exact known values in the hand-made reference |
| synthetic-rotated-cw.pdf, synthetic-rotated-ccw.pdf | the synthetic plot turned both ways; must equal `synthetic-line-plus.csv` exactly |
| ssrn-4204819-016.pdf | 1870 light-grey filled circles; graph turned 90° anticlockwise (y axis along the bottom, x axis up the right); log-log; every line and every label converted to filled outlines, so tick labels are read from glyph shapes. The points reproduce the empirical 1−F(x) steps k/N to 0.2% |
| 2304_10304v3-005.pdf | matplotlib histogram on log-log axes; each marker drawn by the Form XObject /M0 (filled circle of 8 Béziers); labels 10^n with superscript exponents; log minor ticks. The 334 counts are integers summing to 108,745 as the caption says; the "1 month"/"1 year" lines map to 30 and 365 days |
| Estimatingcomputerdepreciationauctiondata-001.pdf | two scatter plots (Desktops, Notebooks) via DVIPSONE + Distiller; every circle outline written twice in a row, runs of 4/6/8 for coincident points; each marker clipped separately. Desktops: 876 points = 706 used + 170 new at age 0, exactly as the paper states |
| mpl-multipage-markers.pdf | two pages; open circles, diamonds, x; minus signs drawn as paths; `--pages`, `--internal` |
| broken-axes.pdf | four Excel graphs whose x and/or y axes are broken by wiggle lines; the labels beyond each break were edited by painting white boxes over the old ones. Points on both sides of a break are mapped (piecewise axis) |
| grid-line-axes.pdf | six graphs without tick marks (grid lines act as ticks); every label is outlined text, including '%'; x axes broken with a single label (4091, 3893) beyond the wiggle; legend names unreadable (keys flagged, series blank) |
| symbols-on-axes.pdf | three graphs; '+' markers lying on the axes; month-resolution x positions; legend of colour swatches |
| log-inset.pdf | log y axis whose decades are the ends of runs of unlabelled minor ticks; ×10^-9 axis multiplier; two inset graphs inside the lower graph |
| nominal-axis.pdf | category x axis: each point gets the label of the nearest tick; the outlined names cannot be read and are numbered #1..#35 |
| short-years.pdf | '95-style year labels; nominal feature-size axis with a log y axis; line-sample legend keys with subscripts |
| lattice-panels.pdf | 216 panels on one page; merged tick-label strings ('510 20') split at the ticks; ring markers; figure-wide legend |
| month-axis.pdf | month names at the ticks with years beneath (x = year + month/12); solid and dashed line series without markers |
| histogram.pdf | 16 small histograms; short bars that look like squares are read as bars |
| frame-corner-axes.pdf | '+' markers; body text beside a graph must not become a legend label; captions below as titles |
| plus-symbols-log-axes.pdf | six panels, ~7700 '+' markers drawn as separate strokes; legend of swatches numbered 1..8; markers beyond the axis ranges (clipped out of view) are reported, in the graph they were clipped to |
| 1209.1411v2-013.pdf | four log-log graphs; labels drawn as outlines whose exponent minus signs are separate dashes (which must not pass for tick marks); points beyond the axis values reported; legend inside a graph with unreadable names |
| 2001.10488v4-56.pdf | two scatter plots of 100 000 points each: a 69 MB content stream with 2.9 million operators (tokenized by qpdf); only the point counts are checked |
| overflow-exponent.pdf | body text with '2^2000 ≈ 10^602' (a superscript joined to its base): a number too big for a float is no number; no graph, no crash |
| log-clipped-markers.pdf | circles flattened into clipped fragments; rebuilt from their arcs, with stacking counts from the alpha layers |
| encrypted*.pdf, enc-*.pdf, bad-stream.pdf | RC4-40/128, AES-128/256 (R2-R6), user password (`--password secret`), all decrypted by pikepdf; corrupt ASCII85 and Flate streams skipped with qpdf's reason as the warning |
| damaged.pdf (beyond qpdf's repair), not-a-pdf.pdf, no-graph.pdf, many-shapes.pdf, zero-width-glyph.pdf, doubtful-axes.pdf | must fail cleanly or report that no graph was found (cases with `"expected": null` check only the exit status and the message) |

`schumpeter-001.reference.csv` is the reference supplied with the PDF
(compared with tolerance 0.001 and never overwritten).  The other expected
CSVs were produced by the program; for the matplotlib files they equal the
plotted values exactly.

### Adding a case

1. Copy the PDF into `tests/data/`.
2. Add an entry to `tests/cases.json` (`pdf`, `args`, `expected`, `tolerance`;
   optionally `exit_code` and `stderr_contains`).
3. `python3 tests/run_tests.py --update -k "<case name>"` to write the expected CSV.
4. Check that CSV by hand before trusting it; then it is a regression baseline.

After an intended change in the program's output, run `--update` and review
the changed CSVs (e.g. with `git diff`) before accepting them.

`tests/make_digit_templates.py` regenerates the digit templates embedded in
`pdfpoints/outlined_text.py` (needs Pillow and the Liberation/DejaVu fonts,
which the program itself does not use).
`tests/make_date_axis_pdf.py` writes the synthetic date-axis case and its
reference CSV.

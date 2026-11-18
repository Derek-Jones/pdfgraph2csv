# Regression tests

Run from the top directory of the package:

    tests/run_tests.sh                    # all cases (exit status 0 = pass)
    tests/run_tests.sh -v                 # one line per case
    tests/run_tests.sh -k rofpc           # cases whose name contains "rofpc"

Each case listed at the end of `tests/run_tests.sh` (a bash script; set `PYTHON`
to choose the interpreter) runs `pdfgraph2csv.py` on a PDF in `tests/data`
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
| 2510.19281v2-013.pdf | SPSS scatter plot converted by Inkscape: a bare move-to after every shape, all text outlined (labels with Bézier-drawn 0s, letters 'o' and full stops that look like markers), legend key beside a line sample converted to a thin filled rectangle; 496 points |
| 2001.10488v4-56.pdf | two scatter plots of 100 000 points each: a 69 MB content stream with 2.9 million operators (tokenized by qpdf); only the point counts are checked |
| overflow-exponent.pdf | body text with '2^2000 ≈ 10^602' (a superscript joined to its base): a number too big for a float is no number; no graph, no crash |
| mpl-errorbars.pdf | made by `tests/make_synthetic_pdfs.py`: matplotlib error bars (`--errbars`) with asymmetric x and y errors, zero errors and two points at one x, and a log y panel labelled 3×10^1 ...; compared with the known values |
| mpl-line-errorbars.pdf | made by `tests/make_synthetic_pdfs.py`: capped error bars (`--errbars`) on the vertices of two lines without markers, one of them zero, with grey drop lines ending at the lower caps; a second panel whose bars have no caps (not reported); the two panels' white backgrounds are nearly square (no markers); compared with the known values |
| Rescaling_reliability_bounds_new_opprof-002.pdf | Excel error bars (`--errbars`) drawn as two slightly slanted halves from each marker's centre, with caps; dense stacks of points on log-log axes |
| MollickMooresLawIEEE-009.pdf | two Excel scatter plots (via Distiller): filled diamonds whose corners sit on a coarse grid, outlines stroked as four separate edges (crossing edges of overlapping diamonds are no '+' or 'x'), a fitted curve of small filled slivers running through diamonds (not an outlined word), a y label misprinted 0.4 for 0.2, ticks crossing at the axes corner (no '+') |
| horowitz2014-004.pdf | eight graphs on one page, one an inset with its own axes inside another; y labels with SI units (300 mW, 0.18 um, 500 MHz; "MHz"/"GHz" drawn as outlines, the prefix step found where the values fall from 500 to 1); tick labels in subsets whose glyphs are named s0 ... s9 (read by their outlines); 1x, 2x, 5x, 10x at equal spacing (a log axis fitted to its powers of ten); points coloured along a colour bar named by the shapes of the legend keys; a legend's range dash in a font that is not embedded |
| 0307278v2-003.pdf | two log-log panels with their tick marks repeated on the opposite axes: the right y axis repeats the left one's scale (body text beside it is no set of labels), so there is one scale; each circle is a white fill, a pattern fill and a black outline (one point); the mirrored minor ticks crossing at the top-right corner are no '+' |
| 3368089.3409714-004.pdf | ggplot2 scatter whose 14 points are big discs, squares and pentagons (larger than the usual marker size limit, accepted because they look like the legend keys), each with the subject's id printed inside it (`label`); ids in touching markers run together and are split; the points match the paper's table |
| 2609.00744v2-025.pdf | log y axis labelled 10^-9, 10^-7, ..., 10^3 (exponents in steps of 2) whose minus signs are set from a symbol font, apart from their digits; three points labelled with names, one on two lines, in the `label` column |
| 2014_JPL-State_of_SW_Jun-29-031.pdf | Excel for Mac line chart whose markers are small images (gradient-filled diamonds, squares and triangles with soft masks, each over a faint shadow image): marker shapes are read from the masks and series from the line through each marker; the values printed beside the points (55%, 46%, ...) are reported in the `label` column; a Calibri subset maps the space to "$" and the "ti" ligature to "8" (repaired) |
| 120875-008.pdf | R line chart without tick marks under a translucent watermark image (which hides nothing): y label centres stand in for the ticks (with `y_coord_low`/`y_coord_high`), and the centres of three unreadable outlined category labels (one on two lines) give the x positions; the label centres sit 0.15 em off the ticks, within the error bound |
| ITRS_2011ExecSum-028.pdf, ITRS_2011ExecSum-031.pdf | charts with notes in bordered boxes (yellow, blue) inside the plot: boxed text is not counted against `--max-words`; dashed borders drawn as rows of small squares are no points |
| prob-book-057.pdf | two binomial probability functions in a textbook page: open circles drawn as stroked 20-gons, filled circles as fans of thin triangles; markers inside the caption's text, the dots of "X1 + ··· + Xn" and a full stop drawn as a shape are no data points; the 42 values match Binomial(20, 1/2) and Binomial(20, 1/5) to 0.0005 |
| 2206.11102v2-018.pdf | beeswarm plot with venue categories on y (points spread around each category line only to be seen), circles drawn as ellipses (the figure was scaled unequally), `--integer x` for participant counts drawn with jitter; workshop median 26 and mean 33.1, as the paper states |
| 2204.07073-010.pdf | x axis labelled at 1939, 1949, 1965, 1977, 1991 with points at and near them: stacked bars with their percentages printed inside, node-link diagrams of tiny markers above the bars (reported, with y values read through the bars' axis; their nodes are squares turned at each network's own angle), line graphs over grey bands (not bars) and an inset whose coloured legend samples are not an axis |
| 2610.30307v1-003.pdf | a log time axis labelled 1 min, 1 hour, 1 day: read in minutes (the smallest unit of its labels), with "1 day" placed at 8 hours (a day of work) as the ticks show |
| 2610.30307v1-011.pdf | a log time axis labelled 1 s, 15 s, 1 min ... 64 h (durations, read in seconds) with vertical error bars, a point highlighted by a white circle over its dot; a second graph of model names with horizontal error bars (`--errbars`) |
| song2025rigorous-002.pdf | `--sizesymbol`: each marker's size in the `symbol_size` column (filled circles 1.36 and 1.43 pt across, triangles 1.8 pt); stippled drawings of a hare and a lynx over a plot (hundreds of dots of many sizes) are not data; two stacked panels with their own y axis lines share the x axis of the lower one |
| 2017_End-of-Moores-Law-002.pdf | log y axis labelled 1E-21 ... 1E-03 (programming notation) with no tick marks: the label centres stand in for them, and `x_coord_low` ... `y_coord_high` give the range each value may lie in; legend keys filled white with coloured outlines name open and outlined markers |
| LogicProbPragSyllogistic_Reasoning-013.pdf | three ggplot2 facets traced from a bitmap: 31 000 staircase slivers of error bars and dotted lines (not read as digits or markers), labels and legend drawn as outlines, axes with only the ticks 0 and 1 (y labels on the left facet only, shared), panel borders as filled outlines, points as a coloured disc inside a black ring; 576 points per facet |
| number-sense-across-the-lifespan-004.pdf | GraphPad Prism: two stacked graphs share one x axis, labelled under the lower graph only; circles drawn as two Bézier arcs; interdecile bars (`--errbars`) |
| mpl-shared-axes.pdf | made by `tests/make_synthetic_pdfs.py`: matplotlib panels sharing the x axis (stacked) or the y axis (side by side); a stacked panel with other, unlabelled ticks must not take the scale of the one below |
| 2017_End-of-Moores-Law-004.pdf | a left and a right y scale: SRAM read on the left, CGP and M1 pitch on the right (from the axis titles), reported in an `axis` column; ticks drawn as tiny outlined boxes, end labels at the frame corners |
| mpl-twin-axes.pdf | made by `tests/make_synthetic_pdfs.py`: matplotlib twinx graphs whose series' scales are told by the axis titles, by legend labels "(right axis)", or by tick label colours |
| 2205.01842-004.pdf | seaborn darkgrid: no tick marks or axis lines, the white grid lines on the grey background give the tick positions; thin diamond markers |
| mpl-background-grid.pdf | made by `tests/make_synthetic_pdfs.py`: a darkgrid plot, and a plot area tiled with grey blocks whose white gaps are the only tick positions; compared with the known values |
| 3759548.3763370-007.pdf | ggplot2 with grid lines only (no ticks or axis lines): two log-log scatter plots, one with sizes 10kB ... 1MB, and a bar chart of speedups (1x ... 2.5x) with bars below 1x |
| 61676858-74.pdf | R curves drawn as 441 000 one-segment strokes, 9 999 tiny circles per graph: once ran for hours, now about 20 s |
| 2308.04748-008.pdf | six matplotlib panels on light blue backgrounds, grid lines standing in for ticks running through three panels in a row |
| mpl-crossing-axes.pdf | made by `tests/make_synthetic_pdfs.py`: axes crossing inside the plot (through the origin; log axes crossing at 1), compared with the known values |
| 3276496-020.pdf | three Excel scatter plots with log axes crossing at 1 in the middle of the plot |
| mpl-label-ticks.pdf | made by `tests/make_synthetic_pdfs.py`: x labels without tick marks, log y axis with two grid lines, body text above the chart's box; compared with the known values |
| 3276496-014.pdf | Excel line chart of 1061 loops: x labels 1 ... 1001 without tick marks, log y axis with lines at 1 and 10 only |
| mpl-no-ticks.pdf | made by `tests/make_synthetic_pdfs.py`: axes without any tick marks, labels alone giving the positions; compared with the known values |
| cheyette2024limited-008.pdf | five ggplot2 panels without tick marks (three facets sharing a y axis, two line-and-point graphs); markers flattened with transparent error bars |
| 2610.20068v1-009.pdf | two ggplot2 panels close together sharing project-name categories, a grey block shading the positive side |
| MSR23_Anisha-003.pdf | two R box plots placed by LaTeX after PDFTron rewrote them: text in Type 0 fonts whose /Encoding is an embedded one-byte Identity CMap, y labels written vertically; 33 751 ZapfDingbats outliers, most clipped far above the plots, all output (none taken for legend keys) |
| 2305.15675v1-p7-13.pdf | pages 7 and 13 of 2305.15675v1: labels in Type 3 Arial whose glyph names spell glyph numbers (once output as control characters) |
| mpl-font-type42.pdf, mpl-font-no-unicode.pdf, mpl-font-no-subtype.pdf | made by `tests/make_synthetic_pdfs.py`: one graph with TrueType text, then copies whose font has no map to Unicode (and one whose Type 0 font lost its /Subtype); all must read alike |
| log-clipped-markers.pdf | circles flattened into clipped fragments; rebuilt from their arcs, with stacking counts from the alpha layers |
| random-*.pdf, random10-*.pdf | made by `tests/make_random_symbols_pdf.py`: 1000 points drawn uniformly from [0, 100]², one file per marker kind (circles of 4 or 8 Béziers, Dingbats circles, diamonds of four lines, squares, R's equilateral and matplotlib's triangles, pentagons, hexagons, stars, plus, cross, asterisks); the true values are in `random-*.reference.csv`, and every point must come out within the precision of the PDF's coordinates: written with 3 decimals in random-*.pdf (0.000125 data units), with 10 significant digits in random10-*.pdf (1.25e-8) |
| encrypted*.pdf, enc-*.pdf, bad-stream.pdf | RC4-40/128, AES-128/256 (R2-R6), user password (`--password secret`), all decrypted by pikepdf; corrupt ASCII85 and Flate streams skipped with qpdf's reason as the warning |
| 3297663.3310314-005.pdf | four ruled tables with shaded cells: their headings and row names look like two category axes, but text fills the cells, so they are no graphs |
| Main_causes_of_missing_errors_testing-006.pdf | a 3 × 3 table of percentages: its rules look like axes, one of its columns like y tick labels and words of its caption like categories, but a grid of numbers (axis labels inside the box counted) is no graph |
| 564-010.pdf | a table of numbers ruled with thin filled rectangles: its rules, row names (t14 ... t28) and the squares at the rule joints look like axes, tick labels and points, but a grid of numbers is no graph |
| prob-book-038.pdf | a page of mathematics: shaded definition boxes ruled above and below, bracket glyphs drawn as outlines and numbers in the prose look like axes, but a box full of running text is no graph |
| jordan-teh-026.pdf | four MATLAB stem plots (Dirichlet process draws) of 100, 100, 100 and 99 atoms: each atom a vertical stroke rising from the x axis, its mass on a 0 to 0.5 y axis; atoms of almost no mass drawn as strokes of no length or as 0.43 pt dots on the axis; stems of one length standing on the axis like tick marks (they must not make axes); a blue density curve (not reported: the stems are the data) |
| cumulative-evol-hollywood-film-crews-007.pdf | a journal figure of three panels in a row (Acrobat Distiller), each a log-scale scatter of 1000 films (years 1910 to 2010, crew sizes 3 to 3000) with semi-transparent grey points over blue bands and a pink band; the axes, grid and tick labels are outlined glyphs drawn up to four times over in the same place; 19 MB of drawing instructions (about a minute) |
| 2401.16279-023.pdf | a journal page (pdfTeX, matplotlib figures): two scatter plots of DRAM currents whose log y axes label one tick only (10^2), with minor ticks at 2 to 9 times each power of ten; the lower one has a log x axis labelled 10^-2 ... 10^4, the minus signs drawn as filled bars; above them a log bar chart whose error bars run off the page, clipped (its bars are not found: 0 points) |
| sarroRE15-008.pdf | a journal page (pdfTeX) of eight R box plots, eight boxes each (categories NM ... SM): grey boxes with outlines, thick medians, dashed whiskers with caps, boxes of no height (just a median line) and boxes without whiskers; outlier circles drawn in an embedded ZapfDingbatsITC subset that gives the circle code 33, stroked (open circles) |
| 2308.04785-006.pdf | a journal page (pdfTeX, seaborn figures) with two correlation matrices: 19 category labels on each axis, 91 and 95 coloured squares at crossings of the category grid, each with its coefficient printed in it (symmetric, 1.00 on the diagonal); neighbouring values close enough to run together; colour bars as images |
| 3485513-020.pdf | a journal page (pdfTeX, Google Sheets figures) with three charts side by side, no frames, no x tick marks: two bar charts of rounded bars with soft shadows (the tallest above the top grid line) and between them a dot chart of 6 series over 30 benchmark names slanted 60 degrees ("2mm", "3mm" among them); the right bar chart is the average of the dot chart |
| Korotayev_Doomsday_preprint-005.pdf | an Excel scatter plot (Word, macOS Quartz) with decimal commas: x axis 4,0 ... 0,0 (billions of years, falling to the right), log y axis 1,E-10 ... 1,E-01 on the right; 19 points, 11 of them near 0; the fitted equation y = 1,886x^-1,010 printed in the plot |
| Statistical_Test_Coverage_for_Linux.pdf | 14-page IEEE paper (pdfTeX, modified by iText) with R graphs whose labels are glyph outlines: page 6 an accumulation curve of 149 points with uncapped vertical confidence bars; page 7 a scatter of 103 open circles; page 8 six estimates with 95% intervals as horizontal grey boxes without whiskers (one of no width), category names drawn as letter outlines; page 10 a log-log CDF of 238 open circles labelled in e-notation (1e+00 ... 1e+06, 5e-04 ... 5e-01) beside a curve of 10 points; page 11 two curves of 576 points (blue solid, red dotted) with a legend of black keys; circles of a diagram and dots in the other column |
| logpaper5Rediscoveries-007.pdf | two Excel charts (PScript5, Acrobat Distiller 6): left, 37 dash markers (filled rectangles 3.1 x 0.8 pt) with vertical error bars on a log y axis (0.01 ... 100), a solid and a dotted fitted curve, the dotted one drawn as small filled pieces turned along it; right, three lines (dashed, solid, dotted) on a percent log axis with their own legend (Year 1 ... 3); the dotted Year 3 line is not extracted |
| 3576042-018.pdf | six matplotlib line charts (Fig. 5, Recall Rate@k, k = 1 ... 10), all text drawn as outlines; six series per chart (circle, square, x, plus, thin diamond, triangle) and a framed two-row legend just below each x axis; legend names are outlined letters and are not read, so series are unnamed |
| damaged.pdf (beyond qpdf's repair), not-a-pdf.pdf, no-graph.pdf, many-shapes.pdf, zero-width-glyph.pdf, doubtful-axes.pdf | must fail cleanly or report that no graph was found (cases without `--expect` check only the exit status and the message) |

`schumpeter-001.reference.csv` is the reference supplied with the PDF
(compared with tolerance 0.001 and never overwritten).  The other expected
CSVs were produced by the program; for the matplotlib files they equal the
plotted values to within 5e-7 (relative), the error of the axis mapping fitted
to the tick marks, which matplotlib writes with 5 decimals.

## Adding a case

1. Copy the PDF into `tests/data/`.
2. Add a `t` call at the end of `tests/run_tests.sh` (`--pdf`, `--expect`,
   optionally `--tol`, `--exit`, `--stderr`, `--counts`; the comment at the
   top of the script lists them all).
3. `tests/run_tests.sh --update -k "<case name>"` to write the expected CSV.
4. Check that CSV by hand before trusting it; then it is a regression baseline.

After an intended change in the program's output, run `--update` and review
the changed CSVs (e.g. with `git diff`) before accepting them.

Cases with `--meta` also compare the `-meta` file with an expected CSV
(`*.meta.csv` in `tests/data`).

The synthetic test PDFs are made by Python programs in `tests/`;
`tests/run_tests.sh --generate` re-creates them and then runs the cases:

    make_line_plus_pdf.py    synthetic-line-plus.pdf, synthetic-rotated-*.pdf
    make_date_axis_pdf.py    synthetic-date-axis.pdf and its reference CSV
    make_random_symbols_pdf.py  random-*.pdf, random10-*.pdf: 1000 random points per marker kind, with their true values
    make_synthetic_pdfs.py   mpl-*.pdf (needs matplotlib)

`tests/make_digit_templates.py` prints the digit templates embedded in
`pdfpoints/outlined_text.py` (needs Pillow and the Liberation/DejaVu fonts,
which the program itself does not use).

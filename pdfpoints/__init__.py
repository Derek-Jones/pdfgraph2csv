"""
pdfgraph2csv.py - extract the data coordinates of marker symbols (circles,
squares, triangles, diamonds, crosses, ...) drawn as vector graphics in the
plots of a PDF file.

How it works
------------
1.  The PDF is opened with pikepdf (qpdf), which repairs damaged files,
    decrypts them and decodes their streams, and is then interpreted with
    pdfminer.six (with tokenizer.py reading the content streams): its
    content-stream interpreter (extended here to record paths, colours,
    clipping, opacity and glyph-by-glyph text) tracks the
    current transformation matrix, the graphics-state stack, the text state
    and Form XObjects (which is how LaTeX embeds plots made by R,
    matplotlib, etc.).  All geometry is therefore converted to page
    coordinates.  Glyph names are read with the Adobe Glyph List from
    fontTools, and dates and month names with python-dateutil.
2.  Axes are found from their tick marks: groups of short, parallel,
    identical-length line segments, one end of which touches a long axis
    line (which may also be an edge of a stroked rectangle).  Ticks of
    identical shape that touch different axis lines are split into separate
    axes, so any number of graphs may be drawn in one stream.
3.  Each tick is paired with the closest numeric text label beyond the
    tick or, for inward-pointing ticks (Excel), on the other side of the
    axis line.  Text is positioned glyph by glyph, so several labels
    written in one text instruction with wide character spacing are
    separated; a least-squares fit of label value against tick position
    gives the mapping from page coordinates to data values.  An
    axis is logarithmic when the labels fit log10(value) much better than
    value (e.g. 0.01 0.02 0.05 0.1 ...) or are successive powers of ten
    (labels such as "10^3" are understood, including a superscript
    exponent drawn as separate text).  When major and minor ticks on one
    axis line both match the labels, the major (longer) ticks are used.
    Plots without tick marks are handled too: grid lines that start on the
    axis line then stand in for the ticks.  Some PDF writers convert all
    strokes and text to filled outlines: thin filled shapes then act as
    lines, and tick labels drawn as glyph outlines are read by comparing
    each glyph with built-in digit templates (any of the four reading
    directions).  Standard-14 fonts used without
    width tables (e.g. Times-Roman) are measured with the Adobe metrics.
4.  An x axis and a y axis whose lines meet at a corner form a graph.
    A graph turned by 90 degrees (y axis across the top or bottom of the
    page, x axis down the side) is recognised from its tick labels, which
    then read vertically on both axes, and from its title in the turned
    frame; its data x values are then read from the axis running down the
    page and its y values from the axis running across (--rotation adds
    the detected angle as a column).
    Graphs are numbered through the document (top to bottom, left to right
    on each page).  The title centred above a graph (or, failing that, a
    sub-caption below it such as "(a). ..." or "Fig. 2 ...") is found too: it
    helps to recognise turned graphs, and --debug shows it, but it is not
    part of the output.
5.  Marker symbols are recognised in two forms:
      * vector paths: small closed shapes - filled or outlined circles made
        of Bezier curves (4, 8 or more segments; also when the marker is a
        Form XObject such as matplotlib's /M0 drawn at each point with Do),
        squares, triangles, polygons, and diamonds drawn as four lines,
        with or without an explicit close-path - and short
        crossing strokes (+, x, asterisk).  Compact shapes only: dashes of
        a dashed line, letters and the outline rings of converted strokes
        are not markers;
      * font glyphs: the ZapfDingbats marker characters, e.g. the black
        circle "l" (a71) used by R's pdf() device and the cross ";" (a27).
        The text render mode (Tr) tells filled (0, 2) from open (1) markers.
    Strokes of plus/cross symbols are matched globally by their common
    midpoint, so they may be drawn in any order (e.g. all vertical bars
    first, then all horizontal bars).
    Legend keys (a marker with a label just to its right) give every point
    with the same marker and colour a series name; within one graph points
    may use any mix of symbols.
    A marker drawn as a fill immediately followed by a stroke of the same
    outline (Excel) counts once, and so does a marker outline that a
    converter wrote twice in a row (Acrobat Distiller): when nearly all runs
    of identical outlines on a page have even length, a run of L outlines
    is L/2 data points.  The centre of each symbol is mapped
    through the axes of the graph it is in.  Every symbol is reported,
    duplicates included, in drawing order.  Multi-page files are handled
    page by page; graphs are numbered through the whole document.

Special axes and graphs
-----------------------
  * Category (nominal) axes: words at the ticks, or midway between ticks as
    Excel draws them; a point gets the label of the nearest category (names
    drawn as unreadable outlines are numbered #1, #2, ...).  Month names
    count 0..11; with year numbers beneath them x = year + month/12.  '95
    style labels are years (century fixed per axis).  "x10^n" written at the
    end of an axis scales it.
  * Broken axes: when the labels form two linear runs with the same scale
    and a jump in value, and a wiggle line crosses the axis between them,
    the axis is mapped piecewise (cut at the wiggle), so points on both sides
    are reported.  A single label beyond the break continues the scale.
    Labels that were painted over (a white box with new text on top) are
    ignored in favour of the visible ones.
  * Lattice / small-multiple panels sharing long frame lines, inset graphs
    (assigned by drawing order), bar charts and histograms (one point per
    bar top) and line charts without markers (one point per vertex).
  * All detected markers are reported, also those whose values lie beyond
    the axis ranges (often clipped out of view by the plot); a marker
    belongs to the graph it was clipped to.  Markers flattened into clipped
    fragments are rebuilt from their arcs.
  * Encrypted files (RC4, AES-128, AES-256) open with an empty or given
    (--password) user password; corrupt streams are skipped with a warning.

Usage
-----
    python3 pdfgraph2csv.py plot.pdf                # CSV to stdout
    python3 pdfgraph2csv.py plot.pdf -o points.csv
    python3 pdfgraph2csv.py plot.pdf --inside-only  # drop legend keys etc.
    python3 pdfgraph2csv.py plot.pdf --internal     # add page x/y columns
    python3 pdfgraph2csv.py plot.pdf --debug        # axis info on stderr

Output columns: page,graph,symbol,series,legend_key,
                x_coord,y_coord,color,color_hex

Package layout (in pipeline order)
----------------------------------
    document                                opening the file (pikepdf -> pdfminer.six)
    fonts, interpreter                      executing a page's drawing operators
    occlusion, text, outlined_text          the page's text, as it is seen
    axes, labels, scales                    tick marks, tick labels, value mappings
    graphs, titles                          plot boxes, panels, insets, titles
    symbols, fragments, charts              markers, rebuilt markers, bars, lines
    legend                                  legend keys and series names
    pipeline, cli                           putting it together; command line
    geometry, colours, context              shared helpers and page state
"""

from .pipeline import extract  # noqa: F401

__all__ = ["extract"]

# Layout

    pdfgraph2csv.py        command-line wrapper (run this)
    pdfpoints/           the package that does the work, one module per step:
      document.py                                      opening the file
      fonts.py interpreter.py                          drawing a page
      occlusion.py text.py outlined_text.py            the page's text
      axes.py labels.py scales.py                      ticks, labels, value mappings
      graphs.py titles.py twin.py                      plot boxes, panels, insets, titles, two scales
      symbols.py fragments.py charts.py errbars.py     markers, bars, line vertices, error bars
      image_marks.py datalabels.py                     markers drawn as images, text printed beside points
      nongraphs.py strays.py                           tables and text taken for graphs, shapes taken for markers
      legend.py                                        legend keys and series names
      pipeline.py rows.py meta.py tools.py styles.py   putting it together: points, -meta records, tools
      cli.py                                           the command line
      geometry.py grouping.py colours.py context.py    shared helpers and page state
    docs/DESIGN.md       the pipeline, module dependencies and record formats
    docs/PACKAGES.md     packages that could replace hand-written parts
    tests/               regression suite (tests/README.md)

`pdfpoints/__init__.py` describes the method in detail.  From Python:

    from pdfpoints import extract
    rows = extract("plot.pdf")          # list of dicts, one per point

or, from this directory, `python3 -m pdfpoints plot.pdf`.

Output columns: page, graph, symbol, series, legend_key, x_coord, y_coord, color, color_hex
(plus label, the text printed beside a point, when some point has one; axis,
`left` or `right`, when a graph has a scale on both sides; confidence, 0 to 1,
when some point was reconstructed from flattened marker fragments, empty for
markers drawn whole; and x_group, after x_coord, when the x axis has a second
row of labels naming groups of bars: the name of each bar's group).
When no data points are found nothing is written (not even the header line),
and an output file named with `-o` is not created.

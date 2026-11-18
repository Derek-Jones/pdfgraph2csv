# pdfgraph2csv

Extract the x/y coordinates of data points, displayed as symbols within a graph that is drawn using vector graphics, from within a pdf file.  Graphs represented using raster graphics (e.g., jpeg and png formats) are ignored.

The following command sends the x/y coordinates of any detected data points within any graphs contained in ``interesting.pdf`` to standard output:

``python3 pdfgraph2csv.py interesting.pdf``

an output file can be specified:

    python3 pdfgraph2csv.py interesting.pdf -o interesting.csv

By default the message ``warning: No vector graphics found`` is output when no data points are detected.

To check which graphs are in raster format use the [pdfcpu tool](https://github.com/pdfcpu/pdfcpu).  The following command will extract most rasther images contained in `interesting.pdf` and write them in the appropriate image format to the directory `im_dir`:

    pdfcpu extract -m image interesting.pdf im_dir

If no images are extracted, then the process involves extracting the page containing the graph, then [uncompressing the pdf, and looking at the sequences of internal pdf instructions](https://shape-of-code.com/2025/07/27/a-process-to-find-and-extract-data-points-from-graphs-in-pdf-files/).

`python3 pdfgraph2csv.py --help` lists the options.  x/y values are written with as many significant digits as the precision of the PDF's own coordinates justifies, plus one (at least 6): a plot whose coordinates have 3 decimals gives about 6 or 7 digits, one written with 10 significant digits about 10; `--digits N` fixes the number of digits instead.

The program is written in python and needs python 3.9+

    pip install -r requirements.txt     # pikepdf, pdfminer.six, fonttools, python-dateutil

a file describing each graph found can generated:

    python3 pdfgraph2csv.py interesting.pdf -o interesting.csv -meta interesting-meta.csv

with the columns page, graph, title, figure (number), caption, tool (the program that drew the graph, when the PDF records it: e.g. `R 4.0.2`, `Matplotlib v3.7.2`, `MATLAB ... (R2017b)`, `Adobe Illustrator CS5`; taken from the information an embedded graphic keeps about its own file, or from the document information when the PDF is itself a plot; programs that only convert to PDF, such as Ghostscript, Acrobat Distiller or a printer driver, are not reported), tool_guess (a best guess from the drawing style, independent of the recorded tool: `R`, `R (ggplot2)`, `R (lattice)`, `matplotlib`, `MATLAB`, `Excel`, `gnuplot`, `Mathematica` or `Stata`, from default colours, fonts, line caps and joins, the decimals of the coordinates and the names given to marker drawings and graphics states; empty when no program stands out; see `pdfpoints/styles.py`), points (the number of data points output for the graph), x_tick_min, x_tick_max, y_tick_min, y_tick_max (the values of the lowest and highest labelled ticks of each axis; for a category axis, the first and last category); and, when some graph has a scale on both sides, axis2, axis2_tick_min, axis2_tick_max (which second scale, e.g. `y right`, and its lowest and highest labelled ticks).  Title, figure and caption are empty when none is found; a caption is the paragraph starting "Fig. N" or "Figure N" below the graph, shared by all the graphs of that figure.  The file is only created when graphs are found.

A myriad of different ways are used to display symbols denoting data values, e.g., instruction to output a circle, or four instructions that output the four (sometimes eight) bezier curves forming the quadrants of a circle.

| Package | Used for |
|---|---|
| pikepdf (qpdf) | opening the file: repairing damaged files, decryption (RC4, AES-128/256), decoding streams |
| pdfminer.six | the content-stream interpreter, resources, fonts and CMaps, standard-14 font metrics |
| fontTools | glyph names → Unicode (Adobe Glyph List) for fonts with /Differences |
| python-dateutil | month names and date tick labels ("Mar 2010", "2010-03-15", "Jan-10") |

## Layout

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
(plus label, the text printed beside a point, when some point has one; and axis,
`left` or `right`, when a graph has a scale on both sides).
When no data points are found nothing is written (not even the header line),
and an output file named with `-o` is not created.

## Regression tests

See [tests/README.md](tests/README.md): how to run the suite, what each test
PDF exercises, and how to add a case.

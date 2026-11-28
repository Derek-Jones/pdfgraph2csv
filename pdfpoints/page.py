"""The page model: everything known about the page being analysed.

One `Page` is made for each page by pipeline.extract_page and passed, as
the keyword argument `page`, to every step that reads or adds a fact about
the page as a whole.  (These facts were once module-level state, reset per
page, that steps read without saying so: which step depended on which was
invisible - outlined_text's reading of specks as text decided, through
`blob_parts`, which shapes symbols.find_symbols kept.)

Each field says which step sets it and which steps read it.  The drawn
content (the interpreter's paths, texts, ...) is reached through
`page.drawn`; `page.index` holds the spatial indexes of that content,
built once on first use (spatial.PageIndex).
"""

from .spatial import PageIndex


class Page:
    """Facts about one page, set and read by the steps of the pipeline."""

    def __init__(self, number):
        # page number in the document, from 1 (progress and debug messages)
        self.number = number

        # -- set by pipeline.extract_page ------------------------------------
        # the interpreter that drew the page (paths, texts, glyph_symbols,
        # colour_strips, pictures, images, image_marks), once drawn
        self.drawn = None
        # degrees the page's content was turned to be read upright
        # (pipeline.page_turn), and the map from that frame back to PDF page
        # points; read by rows.make_rows
        self.turn = 0
        self.unturn = None

        # -- set while reading the page's text (pipeline.read_page_text) -----
        # bboxes of small curved strokes, axis-break wiggles
        # (scales.find_break_marks); read by scales.piecewise_axis
        self.break_marks = []
        # drawing steps of boxes painted over text (occlusion.drop_hidden_glyphs,
        # outlined_text._glyph_parts); read by pipeline.find_page_symbols
        self.hiding_paths = set()
        # drawing steps of dashes that are the minus signs of labels
        # (outlined_text); read by axes._page_segments (no tick marks)
        self.minus_paths = set()
        # outline parts of unread outlined "words" (outlined_text); read by
        # symbols.find_symbols (a filled stroke may still be a marker's arm)
        self.blob_parts = frozenset()
        # non-numeric label candidates: short texts and unread words; read
        # by axes (category axes, titles), labels.nominal_axis
        self.nominal_labels = []
        # ids of the small numbers joined as subscripts to the words before
        # them in nominal_labels ("N" + "2": text.join_subscripts); read by
        # axes.find_axes (no tick numbers)
        self.subscripts = set()

        # -- set by axes.find_axes -------------------------------------------
        # axis lines with ticks but no labels: {orient, pos, lo, hi, tick_pos};
        # read by axes and graphs (shared and borrowed axes, open panels)
        self.bare_axes = []
        # merged dark, and any-shade, horizontal and vertical lines
        # ([(lo, hi, pos)], [(lo, hi, pos)]); read by graphs
        self.dark_lines = ([], [])
        self.all_lines = ([], [])

        # -- set by pipeline.find_page_graphs --------------------------------
        # rectangles of all graphs found on the page; read by legend, titles,
        # pipeline (captions, rebuilt circles)
        self.graph_rects = []
        # (x0, x1, bottom of the x tick labels, graph rect) of each graph;
        # read by titles._find_title
        self.xlabel_zones = []
        # the typical tick-label font size; read by titles._find_title
        self.label_size = 0.0
        # graph rect -> the box drawn round the whole chart
        # (graphs.set_graph_backgrounds); read by titles._find_title
        self.chart_frames = {}

        # -- set by pipeline.find_page_symbols -------------------------------
        # arrows pointing from labels at points (symbols.drop_arrowheads);
        # read by datalabels
        self.arrows = []

        # spatial indexes of the drawn content, built on first use
        self.index = PageIndex(self)

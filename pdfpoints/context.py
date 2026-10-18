"""Shared state: command-line settings and facts about the page being
analysed (graph boxes, typical label size, ...) that several steps need.
`PAGE` is reset by the pipeline at the start of every page.
"""


class Settings:
    """Options that change how markers are read (set from the command line)."""
    glyph_centre = "marker"       # "marker" or "bbox", see DINGBAT_ANCHOR


class PageState:
    """Facts about the page being analysed that several steps consult.
    Reset at the start of every page by extract()."""

    def __init__(self):
        self.reset()

    def reset(self):
        """Forget everything about the previous page."""
        self.nominal_labels = []  # non-numeric label candidates (category axes)
        self.break_marks = []     # bboxes of small curved strokes (axis-break wiggles)
        self.hiding_paths = set() # drawing steps of boxes painted over text
        self.graph_rects = []     # rectangles of all graphs found on the page
        self.label_size = 0.0     # typical tick-label font size on the page


SETTINGS = Settings()


PAGE = PageState()

"""Command-line settings that change how markers are read.  (Facts about
the page being analysed live in the page model: page.Page.)"""


class Settings:
    """Options that change how markers are read (set from the command line)."""
    glyph_centre = "marker"       # "marker" or "bbox", see DINGBAT_ANCHOR
    max_words = 20                # --max-words: running text allowed in a graph


SETTINGS = Settings()

#!/usr/bin/env python3
"""pdfgraph2csv.py - extract the data coordinates of marker symbols drawn as
vector graphics in the plots of a PDF file.

This script is a thin wrapper around the `pdfpoints` package next to it;
see pdfpoints/__init__.py for how the extraction works.

    python3 pdfgraph2csv.py plot.pdf -o points.csv
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pdfpoints.cli import main  # noqa: E402

if __name__ == "__main__":
    main()

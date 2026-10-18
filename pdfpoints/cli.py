"""Command-line interface: argument parsing and CSV output.
"""

import argparse
import csv
import sys

from . import __doc__ as package_doc
from .context import SETTINGS
from .pipeline import extract


def main():
    """Parse the command line, run the extraction and write the CSV."""
    ap = argparse.ArgumentParser(description=package_doc.split("\n\n")[0])
    ap.add_argument("pdf", help="input PDF file")
    ap.add_argument("-o", "--output", help="output CSV file (default: stdout)")
    ap.add_argument("--pages", help="comma separated page numbers, e.g. 1,3")
    ap.add_argument("--inside-only", action="store_true",
                    help="only report symbols inside the axis rectangle (drops legend keys)")
    ap.add_argument("--glyph-centre", choices=("marker", "bbox"), default="marker",
                    help="data point of a ZapfDingbats marker glyph: the plotting "
                         "convention (0.396, 0.347) em (default) or the centre of "
                         "the glyph's bounding box")
    ap.add_argument("--exclude-legend", action="store_true",
                    help="do not report the marker symbols of legend keys")
    ap.add_argument("--max-symbol-frac", type=float, default=0.1,
                    help="largest symbol size as a fraction of the plot area's "
                         "smaller side (default 0.1)")
    ap.add_argument("--rotation", action="store_true",
                    help="add a column with the rotation of each point's graph "
                         "(0, 90, -90 or 180 degrees)")
    ap.add_argument("--internal", action="store_true",
                    help="also output the symbol centres in PDF page coordinates")
    ap.add_argument("--password", default="",
                    help="password of an encrypted PDF (user or owner password)")
    ap.add_argument("--debug", action="store_true", help="print axis detection details")
    args = ap.parse_args()
    pages = {int(p) for p in args.pages.split(",")} if args.pages else None
    SETTINGS.glyph_centre = args.glyph_centre
    info = {}
    try:
        rows = extract(args.pdf, pages, args.inside_only, args.max_symbol_frac, args.debug,
                       args.exclude_legend, args.password.encode("utf-8"), info)
    except (OSError, ValueError) as e:
        sys.exit("error: %s" % e)
    for wmsg in info.get("warnings", []):
        print("warning: %s" % wmsg, file=sys.stderr)
    cols = ["page", "graph", "graph_title", "symbol", "series", "legend_key",
            "x_coord", "y_coord", "color", "color_hex"]
    if args.rotation:
        cols.append("rotation")
    if args.internal:
        cols += ["pdf_x", "pdf_y"]
    out = open(args.output, "w", newline="") if args.output else sys.stdout
    w = csv.writer(out, lineterminator="\n")
    try:
        w.writerow(cols)
        for r in rows:
            w.writerow(["%g" % r[c] if isinstance(r[c], float) else r[c] for c in cols])
        out.flush()
    except BrokenPipeError:          # e.g. output piped into "head"
        sys.stderr.close()
        sys.exit(0)
    if args.output:
        out.close()
    if not rows:
        print("warning: %s" % ("no graphs with numbered axes found" if not info.get("graphs")
                               else "graphs found, but no data points in them"), file=sys.stderr)

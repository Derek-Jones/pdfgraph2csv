"""Command-line interface: argument parsing and CSV output.
"""

import argparse
import contextlib
import csv
import math
import sys

from .context import SETTINGS
from .pipeline import extract


# The --help text, as README.md gives it (tests/run_tests.sh checks that the
# two agree): written out rather than laid out by argparse, whose layout
# depends on the Python version and the terminal's width.
HELP = """\
usage: pdfgraph2csv.py [--debug] [--digits N] [--errbars] [--exclude-legend] [--glyph-centre {marker,bbox}] [-h]
                   [--inside-only] [--integer AXIS] [--internal] [--max-symbol-frac MAX_SYMBOL_FRAC] [--max-words N]
                   [-meta FILE] [--meta-only] [-o OUTPUT] [--pages PAGES] [--password PASSWORD] [--rotation]
                   [--sizesymbol]
                   pdf

positional arguments:
   pdf                  input PDF file

options:
  --debug               print axis detection details
  --digits N            significant digits in numbers written (default: as many as the precision of the PDF's coordinates justifies, at least 6)
  --errbars             output the ends of each point's error bars
  --exclude-legend      do not report the marker symbols of legend keys
  --glyph-centre {marker,bbox} data point of a ZapfDingbats marker glyph: the plotting convention (0.396, 0.347) em (default) or the centre of the glyph's bounding box
  -h, --help            show this help message and exit
  --inside-only         only report symbols inside the axis rectangle
  --integer AXIS        round axis values (x or y; may be given twice) to whole numbers
  --internal            output the symbol centres in PDF page coordinates
  --max-symbol-frac MAX_SYMBOL_FRAC maximum symbol size as a fraction of the plot area's smaller side (default 0.1)
  --max-words N         maximum words of running text (i.e., lines of three or more words; words of three letters or more; default 20)
  -meta FILE, --meta FILE  write graph meta data
  --meta-only           only write the -meta file (no csv of data point values is generated)
  -o OUTPUT, --output OUTPUT  write to file OUTPUT (default: stdout)
  --pages PAGES         comma separated page numbers, e.g. 1,3
  --password PASSWORD   password of an encrypted PDF (user or owner password)
  --rotation            output the rotation of each point's graph (0, 90, -90 or 180 degrees)
  --sizesymbol          output the size of each point's marker in PDF points (1/72 inch) - the diameter of a circle, the average edge length of a box (other shapes: the mean of their bounding box's width and height)
"""


class _Parser(argparse.ArgumentParser):
    """argparse with the --help text of README.md."""

    def format_help(self):
        return HELP

    def format_usage(self):
        return HELP[:HELP.index("\n\n") + 1]


def main():
    """Parse the command line, run the extraction and write the CSV."""
    ap = _Parser(prog="pdfgraph2csv.py")
    ap.add_argument("pdf", help="input PDF file")
    ap.add_argument("-o", "--output", help="write to file OUTPUT (default: stdout)")
    ap.add_argument("-meta", "--meta", metavar="FILE", help="write graph meta data")
    ap.add_argument("--meta-only", action="store_true",
                    help="only write the -meta file (no csv of data point values is generated)")
    ap.add_argument("--pages", help="comma separated page numbers, e.g. 1,3")
    ap.add_argument("--inside-only", action="store_true",
                    help="only report symbols inside the axis rectangle")
    ap.add_argument("--glyph-centre", choices=("marker", "bbox"), default="marker",
                    help="data point of a ZapfDingbats marker glyph: the plotting convention "
                         "(0.396, 0.347) em (default) or the centre of the glyph's bounding box")
    ap.add_argument("--exclude-legend", action="store_true",
                    help="do not report the marker symbols of legend keys")
    ap.add_argument("--max-symbol-frac", type=float, default=0.1,
                    help="maximum symbol size as a fraction of the plot area's smaller side "
                         "(default 0.1)")
    ap.add_argument("--errbars", action="store_true",
                    help="output the ends of each point's error bars")
    ap.add_argument("--rotation", action="store_true",
                    help="output the rotation of each point's graph (0, 90, -90 or 180 degrees)")
    ap.add_argument("--sizesymbol", action="store_true",
                    help="output the size of each point's marker in PDF points (1/72 inch) - the "
                         "diameter of a circle, the average edge length of a box (other shapes: "
                         "the mean of their bounding box's width and height)")
    ap.add_argument("--digits", type=int, default=None, metavar="N",
                    help="significant digits in numbers written (default: as many as the "
                         "precision of the PDF's coordinates justifies, at least 6)")
    ap.add_argument("--max-words", type=int, default=20, metavar="N",
                    help="maximum words of running text (i.e., lines of three or more words; "
                         "words of three letters or more; default 20)")
    ap.add_argument("--integer", action="append", choices=("x", "y"), default=[],
                    metavar="AXIS",
                    help="round axis values (x or y; may be given twice) to whole numbers")
    ap.add_argument("--internal", action="store_true",
                    help="output the symbol centres in PDF page coordinates")
    ap.add_argument("--password", default="",
                    help="password of an encrypted PDF (user or owner password)")
    ap.add_argument("--debug", action="store_true", help="print axis detection details")
    args = ap.parse_args()
    if args.digits is not None and not 1 <= args.digits <= 17:
        ap.error("--digits must be between 1 and 17")
    if args.max_words < 0:
        ap.error("--max-words must be 0 or more")
    if args.meta_only and not args.meta:
        ap.error("--meta-only needs -meta FILE")
    if args.meta_only and args.output:
        ap.error("--meta-only writes no data points: -o cannot be given with it")
    num = "%%.%dg" % args.digits if args.digits else "%g"
    pages = {int(p) for p in args.pages.split(",")} if args.pages else None
    SETTINGS.glyph_centre = args.glyph_centre
    SETTINGS.max_words = args.max_words
    info = {}
    try:
        rows = extract(args.pdf, pages, args.inside_only, args.max_symbol_frac, args.debug,
                       args.exclude_legend, args.password.encode("utf-8"), info,
                       errbars=args.errbars)
    except (OSError, ValueError) as e:
        sys.exit("error: %s" % e)
    for wmsg in info.get("warnings", []):
        print("warning: %s" % wmsg, file=sys.stderr)
    for axis in set(args.integer):
        round_values(rows, axis + "_coord")
    if args.meta and info.get("meta"):
        write_meta(args.meta, info["meta"], num)
    if args.meta_only:
        if not info.get("graphs"):
            print("warning: No vector graphics found", file=sys.stderr)
        return
    cols = ["page", "graph", "symbol", "series", "legend_key",
            "x_coord", "y_coord", "color", "color_hex"]
    if any(r.get("symbol") == "tile" for r in rows):
        # heat maps: the value of each tile's colour on the colour bar
        cols.insert(cols.index("y_coord") + 1, "value")
    if any(r.get("x_group") for r in rows):
        # a second row of x labels: the name of each bar's group of bars
        cols.insert(cols.index("x_coord") + 1, "x_group")
    if any(r.get("label") for r in rows):
        # text printed beside points (values, names): the data labels
        cols.append("label")
    if any(r.get("axis") for r in rows):
        # a graph with a scale on both sides: which one each value is read against
        cols.append("axis")
    if any(r.get("confidence", "") != "" for r in rows):
        # some points reconstructed (flattened markers rebuilt): how sure each is
        cols.append("confidence")
    if args.rotation:
        cols.append("rotation")
    if args.sizesymbol:
        cols.append("symbol_size")
    if any(r.get("x_coord_low") != "" or r.get("y_coord_low") != "" for r in rows):
        # an axis without tick marks, its label centres taken as ticks: the
        # range each value may really lie in
        cols += ["x_coord_low", "x_coord_high", "y_coord_low", "y_coord_high"]
    if args.errbars:
        cols += ["x_low", "x_high", "y_low", "y_high"]
    if args.internal:
        cols += ["pdf_x", "pdf_y"]
    if not rows:
        # no points: no output at all - not even the header, and no -o file
        print("warning: %s" % ("No vector graphics found" if not info.get("graphs")
                               else "graphs found, but no data points in them"), file=sys.stderr)
        return
    with (open(args.output, "w", newline="") if args.output
          else contextlib.nullcontext(sys.stdout)) as out:
        w = csv.writer(out, lineterminator="\n")
        try:
            w.writerow(cols)
            for r in rows:
                w.writerow([cell(r, c, num, args.digits) for c in cols])
            out.flush()
        except BrokenPipeError:          # e.g. output piped into "head"
            sys.stderr.close()
            sys.exit(0)


def round_values(rows, col):
    """--integer: a column's numeric values rounded to whole numbers (category
    labels are left alone)."""
    for r in rows:
        v = r.get(col)
        if isinstance(v, float) and math.isfinite(v):
            r[col] = round(v)


# columns holding data values: written with the digits the PDF's precision
# justifies for that axis (x_digits / y_digits, see rows.value_digits)
VALUE_COLUMNS = {"x_coord", "y_coord", "x_low", "x_high", "y_low", "y_high",
                 "x_coord_low", "x_coord_high", "y_coord_low", "y_coord_high"}


def cell(row, col, num, digits):
    """One CSV cell: a data value with the digits its precision justifies
    (unless --digits fixes them), other numbers with `num`."""
    v = row[col]
    if not isinstance(v, float):
        return v
    if digits is None and col in VALUE_COLUMNS:
        return "%%.%dg" % row.get(col[0] + "_digits", 6) % v
    return num % v


META_COLUMNS = ["page", "graph", "title", "figure", "caption", "tool", "tool_guess", "points",
                "x_tick_min", "x_tick_max", "y_tick_min", "y_tick_max"]
# graphs with a second scale (right y axis, top x axis): which, and its range
META_TWIN = ["axis2", "axis2_tick_min", "axis2_tick_max"]


def write_meta(path, records, num="%g"):
    """The --meta file: one row per graph."""
    try:
        with open(path, "w", newline="") as f:
            w = csv.writer(f, lineterminator="\n")
            cols = META_COLUMNS + (META_TWIN if any(r.get("axis2") for r in records) else []) + \
                (["value_name"] if any(r.get("value_name") for r in records) else [])
            w.writerow(cols)
            for r in records:
                w.writerow([num % r[c] if isinstance(r[c], float) else r[c]
                            for c in cols])
    except OSError as e:
        sys.exit("error: %s" % e)

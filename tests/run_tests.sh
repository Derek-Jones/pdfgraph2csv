#!/usr/bin/env bash
#
# Regression tests for pdfgraph2csv.py.
#
# Every case (listed at the end of this file) runs pdfgraph2csv.py, as a
# separate process exactly as a user would, on a PDF in tests/data and
# checks what it does:
#
#   * the CSV it writes against an expected CSV in tests/data: the same
#     number of rows in the same order, text columns (page, graph, symbol,
#     colour, ...) identical, numeric columns equal within a tolerance;
#   * or, for outputs too big to keep, the number of points per
#     "graph symbol";
#   * or, for a case without expected output, that nothing at all is
#     written to stdout (not even the CSV header);
#   * its exit status and the messages it must write to stderr;
#   * with -o, that the output file is created only when there are points;
#   * with --meta, the per-graph meta file (written with -meta) against an
#     expected CSV, or that none is created.
#
# Usage
#   tests/run_tests.sh               run all cases
#   tests/run_tests.sh -v            one line per case (with its run time)
#   tests/run_tests.sh -k rofpc      only cases whose name contains "rofpc"
#   tests/run_tests.sh --update      regenerate the expected CSVs from the
#                                    current program (after an intended
#                                    change; review the differences)
#   tests/run_tests.sh --generate    first re-create the synthetic test PDFs
#                                    with the Python generators, then run
#                                    the cases
#
# The test PDFs that were made by program are re-created by these Python
# scripts in tests/ (they write into tests/data):
#   make_line_plus_pdf.py    synthetic-line-plus.pdf, synthetic-rotated-*.pdf
#   make_date_axis_pdf.py    synthetic-date-axis.pdf and its reference CSV
#   make_random_symbols_pdf.py  random-<symbol>.pdf: 1000 uniform random
#                            points drawn with each kind of marker, and
#                            their true values
#   make_synthetic_pdfs.py   mpl-*.pdf (needs matplotlib)
# All but the last need only the standard library.  make_digit_templates.py
# prints the digit templates embedded in pdfpoints/outlined_text.py (needs
# Pillow and the Liberation and DejaVu fonts).
#
# The Python interpreter is taken from $PYTHON (default python3).  Needs
# only bash (3.2 or later) and the standard tools awk, grep, sort, diff, cmp.
# Exit status is 0 when every case passes, 1 otherwise.
#
# A case is one call of t:
#
#   t 'name' --pdf FILE [options] [-- program arguments]
#
#   --expect CSV     the CSV the program must reproduce
#   --tol N          largest absolute difference allowed in numeric columns
#                    (default 1e-6)
#   --cols a,b,...   compare only these columns (default: all columns of CSV)
#   --keep           a hand-made reference: never overwritten by --update
#   --exit N         the exit status the program must give (default 0)
#   --stderr TEXT    a message stderr must contain (may be repeated)
#   --out FILE       write the CSV with -o to a temporary FILE (which must
#                    not be created when no points are found)
#   --counts 'graph symbol=N|...'
#                    number of points per graph and symbol (instead of CSV)
#   --meta CSV       also write the meta file (-meta) and compare it with
#                    CSV; "--meta -": no meta file may be created
#
# Without --expect or --counts the program must write nothing to stdout.

HERE=$(cd "$(dirname "$0")" && pwd)
DATA=$HERE/data
PROGRAM=$(cd "$HERE/.." && pwd)/pdfgraph2csv.py
PYTHON=${PYTHON:-python3}
MAX_REPORTED=10                      # differences listed per failing case
TIME_LIMIT=600                       # seconds per run (when timeout exists)

verbose=0
update=0
generate=0
filter=
while [ $# -gt 0 ]; do
    case $1 in
        -v|--verbose) verbose=1 ;;
        -k) shift; filter=$1 ;;
        --update) update=1 ;;
        --generate) generate=1 ;;
        -h|--help) sed -n '2,/^$/s/^# \{0,1\}//p' "$0"; exit 0 ;;
        *) echo "usage: $0 [-v] [-k TEXT] [--update] [--generate]" >&2; exit 2 ;;
    esac
    shift
done

TMP=$(mktemp -d "${TMPDIR:-/tmp}/pdfgraph2csv-tests.XXXXXX") || exit 2
trap 'rm -rf "$TMP"' EXIT

if command -v timeout >/dev/null 2>&1; then
    TIMEOUT="timeout $TIME_LIMIT"
else
    TIMEOUT=
fi

passed=0
failed=0
failed_names=

# --generate: re-create the synthetic PDFs before running the cases
if [ "$generate" -eq 1 ]; then
    for gen in make_line_plus_pdf.py make_date_axis_pdf.py make_random_symbols_pdf.py \
               make_synthetic_pdfs.py; do
        if [ "$gen" = make_synthetic_pdfs.py ] && ! "$PYTHON" -c "import matplotlib" 2>/dev/null; then
            echo "skipped   $gen (matplotlib is not installed)"
            continue
        fi
        if "$PYTHON" "$HERE/$gen" >"$TMP/gen.log" 2>&1; then
            echo "generated $gen"
        else
            echo "FAILED    $gen:"; sed 's/^/      /' "$TMP/gen.log"; exit 1
        fi
    done
    echo
fi

# -- awk helpers ---------------------------------------------------------------

# csvsplit(line, fields): split one CSV line (RFC 4180 quoting) into
# fields[1..n]; returns n.
AWK_CSV='
function csvsplit(s, f,    n, i, c, q, cur, L) {
    sub(/\r$/, "", s)
    if (index(s, "\"") == 0)
        return split(s, f, ",")
    n = 0; cur = ""; q = 0; L = length(s)
    for (i = 1; i <= L; i++) {
        c = substr(s, i, 1)
        if (q) {
            if (c == "\"") {
                if (substr(s, i + 1, 1) == "\"") { cur = cur "\""; i++ }
                else q = 0
            } else cur = cur c
        } else if (c == "\"") q = 1
        else if (c == ",") { f[++n] = cur; cur = "" }
        else cur = cur c
    }
    f[++n] = cur
    return n
}
function isnum(s) {
    return s ~ /^[ \t]*[-+]?([0-9]+\.?[0-9]*|\.[0-9]+)([eE][-+]?[0-9]+)?[ \t]*$/
}
'

# compare_csv ACTUAL EXPECTED TOL COLS: print the differences (none = pass)
compare_csv() {
    awk -v tol="$3" -v cols="$4" -v max="$MAX_REPORTED" "$AWK_CSV"'
    FNR == 1 { file++; n = csvsplit($0, h)
               for (i = 1; i <= n; i++) {
                   if (file == 1) { ahdr[h[i]] = i } else { ecol[i] = h[i] }
               }
               if (file == 2) necol = n
               next }
    /^\r?$/ { next }                               # blank lines are no rows
    file == 1 { an = csvsplit($0, f); arows++
                for (i = 1; i <= an; i++) A[arows, i] = f[i]
                alen[arows] = an; next }
    { en = csvsplit($0, f); erows++
      for (i = 1; i <= en; i++) E[erows, ecol[i]] = f[i]
      for (i = en + 1; i <= necol; i++) E[erows, ecol[i]] = "<none>" }
    function report(msg) { nd++; if (nd <= max) print msg }
    END {
        tol += 0
        if (cols != "") nc = split(cols, C, ",")
        else if (erows > 0) { nc = necol; for (i = 1; i <= nc; i++) C[i] = ecol[i] }
        if (arows > 0 && erows > 0) {
            miss = ""
            for (k = 1; k <= nc; k++) if (!(C[k] in ahdr)) miss = miss (miss == "" ? "" : ", ") C[k]
            if (miss != "") { print "output lacks column(s): " miss; exit }
        }
        if (arows != erows) report("row count: got " arows ", expected " erows)
        rows = arows < erows ? arows : erows
        for (r = 1; r <= rows; r++) {
            for (k = 1; k <= nc; k++) {
                c = C[k]; j = ahdr[c]
                av = (j <= alen[r]) ? A[r, j] : "<none>"
                ev = ((r, c) in E) ? E[r, c] : "<none>"
                if (isnum(av) && isnum(ev)) {
                    d = av - ev; if (d < 0) d = -d
                    if (d > tol)
                        report(sprintf("line %d, %s: got %s, expected %s (diff %.3g > %g)",
                                       r + 1, c, av, ev, d, tol))
                } else if (av != ev)
                    report(sprintf("line %d, %s: got \"%s\", expected \"%s\"", r + 1, c, av, ev))
            }
        }
        if (nd > max) print "... and " nd - max " more difference(s)"
    }' "$1" "$2"
}

# point_counts CSV: "graph symbol=N" lines, sorted
point_counts() {
    awk "$AWK_CSV"'
    FNR == 1 { n = csvsplit($0, h); for (i = 1; i <= n; i++) col[h[i]] = i; next }
    /^\r?$/ { next }
    { csvsplit($0, f); count[f[col["graph"]] " " f[col["symbol"]]]++ }
    END { for (k in count) print k "=" count[k] }' "$1" | LC_ALL=C sort
}

# -- running the program ----------------------------------------------------------

# run_program: run the current case; its CSV ends up in $TMP/result (empty
# when there are no points).  Returns 1, with the reason in $TMP/why, when
# the exit status, a message or the output file is wrong.
run_program() {
    local out= status want text
    local cmd
    rm -rf "$TMP/o" "$TMP/m" "$TMP/result" "$TMP/meta_result" "$TMP/why"
    cmd=("$PYTHON" "$PROGRAM" "$DATA/$c_pdf" ${c_args[@]+"${c_args[@]}"})
    if [ -n "$c_out" ]; then
        mkdir "$TMP/o"
        out=$TMP/o/$c_out
        cmd+=(-o "$out")
    fi
    if [ -n "$c_meta" ]; then
        mkdir "$TMP/m"
        cmd+=(-meta "$TMP/m/meta.csv")
    fi
    $TIMEOUT "${cmd[@]}" >"$TMP/stdout" 2>"$TMP/stderr"
    status=$?
    want=${c_exit:-0}
    if [ "$status" -ne "$want" ]; then
        { echo "pdfgraph2csv.py exit status $status, expected $want:"; cat "$TMP/stderr"; } >"$TMP/why"
        return 1
    fi
    while IFS= read -r text; do
        [ -z "$text" ] && continue
        if ! grep -qF -- "$text" "$TMP/stderr"; then
            { echo "message '$text' missing from stderr:"; cat "$TMP/stderr"; } >"$TMP/why"
            return 1
        fi
    done <<EOF
$c_stderr
EOF
    if [ -n "$c_out" ]; then
        if [ -s "$TMP/stdout" ]; then
            echo "output on stdout although -o was given" >"$TMP/why"
            return 1
        fi
        if [ -e "$out" ]; then
            if [ ! -s "$out" ]; then
                echo "an empty output file was created" >"$TMP/why"
                return 1
            fi
            cp "$out" "$TMP/result"
        else
            : >"$TMP/result"
        fi
    else
        cp "$TMP/stdout" "$TMP/result"
    fi
    if [ -n "$c_meta" ]; then
        if [ -e "$TMP/m/meta.csv" ]; then
            if [ "$c_meta" = "-" ]; then
                { echo "a meta file was created:"; head -5 "$TMP/m/meta.csv"; } >"$TMP/why"
                return 1
            fi
            cp "$TMP/m/meta.csv" "$TMP/meta_result"
        else
            : >"$TMP/meta_result"
        fi
    fi
    return 0
}

# check: run the current case and compare (points, then meta file); prints
# the differences to $TMP/why and returns 1 on failure
check() {
    run_program || return 1
    check_points || return 1
    if [ -n "$c_meta" ] && [ "$c_meta" != "-" ]; then
        if [ ! -f "$DATA/$c_meta" ]; then
            echo "missing expected file $c_meta (run with --update)" >"$TMP/why"
            return 1
        fi
        compare_csv "$TMP/meta_result" "$DATA/$c_meta" "$c_tol" "" | sed 's/^/meta: /' >"$TMP/why"
        [ ! -s "$TMP/why" ] || return 1
    fi
    return 0
}

# check_points: compare the points written (after run_program)
check_points() {
    if [ -n "$c_counts" ]; then
        point_counts "$TMP/result" >"$TMP/got"
        printf '%s\n' "$c_counts" | tr '|' '\n' | LC_ALL=C sort >"$TMP/want"
        if ! cmp -s "$TMP/got" "$TMP/want"; then
            { echo "points per graph and symbol differ (< got, > expected):"
              diff "$TMP/got" "$TMP/want" | grep '^[<>]'; } >"$TMP/why"
            return 1
        fi
        return 0
    fi
    if [ -z "$c_expect" ]; then
        if [ -s "$TMP/result" ]; then
            { echo "output is not empty:"; head -5 "$TMP/result"; } >"$TMP/why"
            return 1
        fi
        return 0
    fi
    if [ ! -f "$DATA/$c_expect" ]; then
        echo "missing expected file $c_expect (run with --update)" >"$TMP/why"
        return 1
    fi
    compare_csv "$TMP/result" "$DATA/$c_expect" "$c_tol" "$c_cols" >"$TMP/why"
    [ ! -s "$TMP/why" ]
}

# update: rewrite the current case's expected CSV (and meta CSV) from the
# program's output
update_expected() {
    if [ -z "$c_expect" ] && { [ -z "$c_meta" ] || [ "$c_meta" = "-" ]; }; then
        return
    fi
    if [ -n "$c_keep" ]; then
        echo "kept      ${c_expect:-$c_meta} (hand-made reference)"
        return
    fi
    if ! run_program; then
        echo "FAILED    ${c_expect:-$c_meta}: $(head -1 "$TMP/why")"
        failed=$((failed + 1))
        return
    fi
    [ -n "$c_expect" ] && write_expected "$TMP/result" "$c_expect"
    if [ -n "$c_meta" ] && [ "$c_meta" != "-" ]; then
        write_expected "$TMP/meta_result" "$c_meta"
    fi
}

# write_expected NEW NAME: replace tests/data/NAME, saying what changed
write_expected() {
    local path=$DATA/$2 state rows
    if [ ! -e "$path" ]; then state="created  "
    elif cmp -s "$1" "$path"; then state="unchanged"
    else state="UPDATED  "
    fi
    cp "$1" "$path"
    rows=$(awk 'NF' "$path" | wc -l)
    [ "$rows" -gt 0 ] && rows=$((rows - 1))
    echo "$state $2 ($rows rows)"
}

# t NAME --pdf FILE [options] [-- program arguments]: one case
t() {
    c_name=$1; shift
    c_pdf= c_expect= c_tol=1e-6 c_cols= c_keep= c_exit= c_stderr= c_out= c_counts= c_meta=
    c_args=()
    while [ $# -gt 0 ]; do
        case $1 in
            --pdf) c_pdf=$2; shift ;;
            --expect) c_expect=$2; shift ;;
            --tol) c_tol=$2; shift ;;
            --cols) c_cols=$2; shift ;;
            --keep) c_keep=1 ;;
            --exit) c_exit=$2; shift ;;
            --stderr) c_stderr="$c_stderr$2
"; shift ;;
            --out) c_out=$2; shift ;;
            --counts) c_counts=$2; shift ;;
            --meta) c_meta=$2; shift ;;
            --) shift; c_args=("$@"); break ;;
            *) echo "case '$c_name': unknown option $1" >&2; exit 2 ;;
        esac
        shift
    done
    if [ -n "$filter" ] && ! printf '%s\n' "$c_name" | grep -qiF -- "$filter"; then
        return
    fi
    if [ "$update" -eq 1 ]; then
        update_expected
        return
    fi
    local start=$SECONDS
    if check; then
        passed=$((passed + 1))
        [ "$verbose" -eq 1 ] && printf 'ok    %4ds  %s\n' $((SECONDS - start)) "$c_name"
    else
        failed=$((failed + 1))
        failed_names="$failed_names  $c_name
"
        printf 'FAIL  %4ds  %s\n' $((SECONDS - start)) "$c_name"
        sed 's/^/      /' "$TMP/why"
    fi
}

# summary: called after the last case
summary() {
    if [ "$update" -eq 1 ]; then
        [ "$failed" -eq 0 ]
        exit $?
    fi
    if [ $((passed + failed)) -eq 0 ]; then
        echo "no cases selected"
        exit 1
    fi
    echo
    echo "$((passed + failed)) cases: $passed passed, $failed failed  (${SECONDS}s)"
    if [ "$failed" -gt 0 ]; then
        echo "failed:"
        printf '%s' "$failed_names"
        exit 1
    fi
    exit 0
}

# -- the cases (PDFs and expected CSVs are in tests/data) ---------------------------

t 'schumpeter-001 matches the supplied reference CSV' \
  --pdf schumpeter-001.pdf \
  --expect schumpeter-001.reference.csv \
  --tol 0.001 \
  --cols page,graph,symbol,x_coord,y_coord,color,color_hex \
  --keep

t 'schumpeter-001 default output' \
  --pdf schumpeter-001.pdf \
  --expect schumpeter-001.csv

t 'schumpeter-001 inside the axes only (legend keys dropped)' \
  --pdf schumpeter-001.pdf \
  --expect schumpeter-001.inside-only.csv \
  -- --inside-only

t 'rofpc-19: four log-log graphs in one stream, ZapfDingbats circles' \
  --pdf rofpc-19.pdf \
  --expect rofpc-19.csv

t 'matplotlib: two panels, log y axis, marker XObjects' \
  --pdf mpl-two-panels-log.pdf \
  --expect mpl-two-panels-log.csv

t 'matplotlib: multi-page, open circles, diamonds, x, vector minus signs' \
  --pdf mpl-multipage-markers.pdf \
  --expect mpl-multipage-markers.csv

t 'matplotlib: multi-page with page selection' \
  --pdf mpl-multipage-markers.pdf \
  --expect mpl-multipage-markers.page2-internal.csv \
  -- --pages 2 --internal

t 'effort-fig2: three Excel scatter plots, diamonds from four lines, inward ticks, packed TJ labels, sub-caption titles' \
  --pdf effort-fig2-excel-diamonds.pdf \
  --expect effort-fig2-excel-diamonds.csv

t 'swed-bank: 9-page paper, 4 Excel scatter plots on page 6 (fill+outline diamonds) and bar charts with category axes (High/Medium/Low) on page 4' \
  --pdf swed-bank.pdf \
  --expect swed-bank.csv

t 'swed-bank: page selection (--pages 6) gives the page-6 scatter plots only' \
  --pdf swed-bank.pdf \
  --expect swed-bank-p6.csv \
  -- --pages 6

t 'Schalken p57: two R graphs, mixed markers (Dingbats circle a71 + cross a27), legend series' \
  --pdf Schalken_PhD-057.pdf \
  --expect Schalken_PhD-057.csv

t 'Schalken p57: --exclude-legend drops the legend keys' \
  --pdf Schalken_PhD-057.pdf \
  --expect Schalken_PhD-057.no-legend.csv \
  -- --exclude-legend

t 'synthetic: line-drawn pluses (all verticals first), duplicates, legend - exact known values' \
  --pdf synthetic-line-plus.pdf \
  --expect synthetic-line-plus.csv

t 'King p214: graph turned 90 deg clockwise, no tick marks (grid lines), Times-Roman labels in one TJ' \
  --pdf King_PhD-214.pdf \
  --expect King_PhD-214.csv \
  -- --rotation

t 'synthetic: same graph turned clockwise gives identical values' \
  --pdf synthetic-rotated-cw.pdf \
  --expect synthetic-line-plus.csv \
  --keep

t 'synthetic: same graph turned counter-clockwise gives identical values' \
  --pdf synthetic-rotated-ccw.pdf \
  --expect synthetic-line-plus.csv \
  --keep

t 'ssrn-4204819 p16: filled grey circles, graph turned 90 deg anticlockwise, log-log, all text and strokes outlined' \
  --pdf ssrn-4204819-016.pdf \
  --expect ssrn-4204819-016.csv \
  -- --rotation

t 'arXiv 2304.10304 p5: matplotlib markers as Form XObject /M0 (8-Bezier filled circle), log-log, 10^n labels, minor ticks' \
  --pdf 2304_10304v3-005.pdf \
  --expect 2304_10304v3-005.csv

t 'computer depreciation p189: two scatter plots, every marker outline written twice (Distiller), coincident points, clipped markers' \
  --pdf Estimatingcomputerdepreciationauctiondata-001.pdf \
  --expect Estimatingcomputerdepreciationauctiondata-001.csv

t 'broken-axes: four Excel graphs with axis breaks (wiggle lines) on x and y; labels edited by white boxes; all points mapped piecewise' \
  --pdf broken-axes.pdf \
  --expect broken-axes.csv

t 'grid-line-axes: six graphs, axes from grid lines, all labels drawn as outlines (incl. '"'"'%'"'"'), x-axis breaks with one label beyond the wiggle, figure legend with unreadable names' \
  --pdf grid-line-axes.pdf \
  --expect grid-line-axes.csv

t 'symbols-on-axes: three graphs, '"'"'+'"'"' markers sitting on the axes, colour-swatch legend' \
  --pdf symbols-on-axes.pdf \
  --expect symbols-on-axes.csv

t 'log-inset: two graphs, log y axis with unlabelled minor ticks and a x10^-9 multiplier, two inset graphs' \
  --pdf log-inset.pdf \
  --expect log-inset.csv

t 'nominal-axis: category x axis (outlined, unreadable names numbered #1..#35)' \
  --pdf nominal-axis.pdf \
  --expect nominal-axis.csv

t 'short-years: '"'"'95-style year labels, log axis, nominal feature-size axis' \
  --pdf short-years.pdf \
  --expect short-years.csv

t 'lattice-panels: 216 panels on one page, merged tick labels '"'"'510 20'"'"', figure legend' \
  --pdf lattice-panels.pdf \
  --expect lattice-panels.csv

t 'month-axis: month names at ticks with years below (year + month/12), dashed line series' \
  --pdf month-axis.pdf \
  --expect month-axis.csv

t 'histogram: 16 small histograms, short bars that look like squares' \
  --pdf histogram.pdf \
  --expect histogram.csv

t 'frame-corner-axes: two graphs, '"'"'+'"'"' markers, body text beside the plot is no legend' \
  --pdf frame-corner-axes.pdf \
  --expect frame-corner-axes.csv

t 'plus-symbols-log-axes: six panels of '"'"'+'"'"' markers, log y axis, numbered colour legend (1..8); markers beyond the axis ranges (clipped out of view) are reported, assigned to the graph they were clipped to' \
  --pdf plus-symbols-log-axes.pdf \
  --expect plus-symbols-log-axes.csv

t 'log-clipped-markers: circles flattened into fragments and clipped; rebuilt with stacking counts' \
  --pdf log-clipped-markers.pdf \
  --expect log-clipped-markers.csv \
  --stderr 'circles rebuilt from their outlines'

t 'encrypted: AES-128, empty user password' \
  --pdf encrypted.pdf \
  --expect schumpeter-001.csv \
  --keep

t 'encrypted-password: needs --password secret' \
  --pdf encrypted-password.pdf \
  --expect schumpeter-001.csv \
  --keep \
  -- --password secret

t 'encrypted-password: without the password the file is refused' \
  --pdf encrypted-password.pdf \
  --exit 1 \
  --stderr 'needs a password'

t 'synthetic encryption rc4-40 gives the unencrypted output' \
  --pdf enc-rc4-40.pdf \
  --expect enc-plain.csv

t 'synthetic encryption aes256 gives the unencrypted output' \
  --pdf enc-aes256.pdf \
  --expect enc-plain.csv \
  --keep

t 'synthetic encryption aes256-r5 gives the unencrypted output' \
  --pdf enc-aes256-r5.pdf \
  --expect enc-plain.csv \
  --keep

t 'synthetic encryption rc4-user gives the unencrypted output' \
  --pdf enc-rc4-user.pdf \
  --expect enc-plain.csv \
  --keep \
  -- --password secret

t 'bad-stream: a corrupt Ascii85 stream is skipped with a warning' \
  --pdf bad-stream.pdf \
  --expect schumpeter-001.csv \
  --keep \
  --stderr 'corrupt ASCII85Decode stream was skipped'

t 'damaged: rejected with an error' \
  --pdf damaged.pdf \
  --exit 1 \
  --stderr 'damaged beyond repair'

t 'not-a-pdf: rejected with an error' \
  --pdf not-a-pdf.pdf \
  --exit 1 \
  --stderr 'not a PDF file'

t 'no-graph: no graph with numbered axes' \
  --pdf no-graph.pdf \
  --stderr 'No vector graphics found'

t 'many-shapes: no graph with numbered axes' \
  --pdf many-shapes.pdf \
  --stderr 'No vector graphics found'

t 'zero-width-glyph: no graph with numbered axes' \
  --pdf zero-width-glyph.pdf \
  --stderr 'No vector graphics found'

t 'doubtful-axes: no graph with numbered axes' \
  --pdf doubtful-axes.pdf \
  --stderr 'No vector graphics found'

t 'synthetic-date-axis: date tick labels ('"'"'Jan 2010'"'"', python-dateutil) and glyph names in /Differences incl. the /fi ligature (fontTools); exact known values' \
  --pdf synthetic-date-axis.pdf \
  --expect synthetic-date-axis.reference.csv \
  --tol 0.001 \
  --keep

t 'synthetic-date-axis: the title, read through glyph names with the /fi ligature (fontTools), is found (--debug; titles are not output)' \
  --pdf synthetic-date-axis.pdf \
  --expect synthetic-date-axis.reference.csv \
  --tol 0.001 \
  --keep \
  --stderr 'graph 1 title: '"'"'Profits by month'"'"'' \
  -- --debug

t 'no-graph with -o: no output file is created' \
  --pdf no-graph.pdf \
  --stderr 'No vector graphics found' \
  --out points.csv

t 'histogram with -o: the output file holds the points' \
  --pdf histogram.pdf \
  --expect histogram.csv \
  --keep \
  --out points.csv

t '1209.1411v2-013: four log-log graphs, outlined labels whose exponent minus signs are separate dashes, points beyond the axis values (clipped out of view) reported, in-graph legend with unreadable names' \
  --pdf 1209.1411v2-013.pdf \
  --expect 1209.1411v2-013.csv

t '2001.10488v4-56: a 69 MB content stream drawing 200 000 circle markers (2.9 million operators) must finish (about a minute) with every marker' \
  --pdf 2001.10488v4-56.pdf \
  --stderr 'MB of drawing instructions' \
  --counts '2 filled-circle=100000|3 filled-circle=99989|1 line=335'

t 'overflow-exponent: body text '"'"'10^602'"'"' (a superscript) is no number - no crash, no graph' \
  --pdf overflow-exponent.pdf \
  --stderr 'No vector graphics found'

t '2001.10488v4-121: two 3-D cube plots (not processed) and a degenerate box 3x10^9 points across - must finish quickly with no graph' \
  --pdf 2001.10488v4-121.pdf \
  --stderr 'No vector graphics found'

t 'S1383762124002030 page 9: box plots with 472 000 outlier circles in a 92 MB Form XObject (2.3 million operators) - must finish in well under a minute without exhausting memory; only the point counts are checked' \
  --pdf S1383762124002030.pdf \
  --stderr 'MB of drawing instructions' \
  --counts '1 open-circle=240614|2 open-circle=218658|3 open-circle=13121|3 filled-circle=4|1 filled-polygon=2|1 filled-circle=2|2 filled-circle=1|3 filled-square=1|3 open-square=1|3 filled-polygon=1' \
  -- --pages 9

t 'meta file: figure numbers and captions set apart from their label ("Figure 1."), category and numeric axes, several pages' \
  --pdf swed-bank.pdf \
  --expect swed-bank.csv \
  --meta swed-bank.meta.csv

t 'meta file: four graphs stacked two by two share the caption below the figure' \
  --pdf rofpc-19.pdf \
  --expect rofpc-19.csv \
  --meta rofpc-19.meta.csv

t 'meta file: a double-spaced caption, untitled graphs, log axes' \
  --pdf 1209.1411v2-013.pdf \
  --expect 1209.1411v2-013.csv \
  --meta 1209.1411v2-013.meta.csv

t 'meta file: x10^-9 axis multiplier applied to the tick values, inset graphs, numbered section figure (3.2)' \
  --pdf log-inset.pdf \
  --expect log-inset.csv \
  --meta log-inset.meta.csv

t 'meta file: date axis ticks, title and no caption' \
  --pdf synthetic-date-axis.pdf \
  --counts '1 filled-square=8' \
  --meta synthetic-date-axis.meta.csv

t 'S1383762124002030 pages 6-7, with meta file: two-column journal pages, captions with monospaced words, category axes' \
  --pdf S1383762124002030.pdf \
  --expect S1383762124002030-p6-7.csv \
  --meta S1383762124002030-p6-7.meta.csv \
  -- --pages 6,7

t 'meta file: not created when no graph is found' \
  --pdf no-graph.pdf \
  --meta - \
  --stderr 'No vector graphics found'

t 'random circle: 1000 uniform points, filled circles of four Bezier curves; within the 3-decimal precision of the PDF' \
  --pdf random-circle.pdf \
  --expect random-circle.reference.csv \
  --cols symbol,x_coord,y_coord \
  --tol 1.3e-4 \
  --keep \
  -- --digits 10

t 'random open-circle: 1000 uniform points, stroked circles of four Bezier curves; within the 3-decimal precision of the PDF' \
  --pdf random-open-circle.pdf \
  --expect random-open-circle.reference.csv \
  --cols symbol,x_coord,y_coord \
  --tol 1.3e-4 \
  --keep \
  -- --digits 10

t 'random circle8: 1000 uniform points, circles of eight Bezier curves in a Form XObject (matplotlib); within the 3-decimal precision of the PDF' \
  --pdf random-circle8.pdf \
  --expect random-circle8.reference.csv \
  --cols symbol,x_coord,y_coord \
  --tol 1.3e-4 \
  --keep \
  -- --digits 10

t 'random dingbat-circle: 1000 uniform points, ZapfDingbats a71 circles (R pdf()); within the 3-decimal precision of the PDF' \
  --pdf random-dingbat-circle.pdf \
  --expect random-dingbat-circle.reference.csv \
  --cols symbol,x_coord,y_coord \
  --tol 1.3e-4 \
  --keep \
  -- --digits 10

t 'random diamond: 1000 uniform points, stroked diamonds of four lines; within the 3-decimal precision of the PDF' \
  --pdf random-diamond.pdf \
  --expect random-diamond.reference.csv \
  --cols symbol,x_coord,y_coord \
  --tol 1.3e-4 \
  --keep \
  -- --digits 10

t 'random filled-diamond: 1000 uniform points, filled diamonds; within the 3-decimal precision of the PDF' \
  --pdf random-filled-diamond.pdf \
  --expect random-filled-diamond.reference.csv \
  --cols symbol,x_coord,y_coord \
  --tol 1.3e-4 \
  --keep \
  -- --digits 10

t 'random fill-outline-diamond: 1000 uniform points, diamonds filled then stroked (Excel); within the 3-decimal precision of the PDF' \
  --pdf random-fill-outline-diamond.pdf \
  --expect random-fill-outline-diamond.reference.csv \
  --cols symbol,x_coord,y_coord \
  --tol 1.3e-4 \
  --keep \
  -- --digits 10

t 'random square: 1000 uniform points, filled squares (re); within the 3-decimal precision of the PDF' \
  --pdf random-square.pdf \
  --expect random-square.reference.csv \
  --cols symbol,x_coord,y_coord \
  --tol 1.3e-4 \
  --keep \
  -- --digits 10

t 'random open-square: 1000 uniform points, stroked squares (re); within the 3-decimal precision of the PDF' \
  --pdf random-open-square.pdf \
  --expect random-open-square.reference.csv \
  --cols symbol,x_coord,y_coord \
  --tol 1.3e-4 \
  --keep \
  -- --digits 10

t 'random triangle: 1000 uniform points, R equilateral triangles, point at the centroid; within the 3-decimal precision of the PDF' \
  --pdf random-triangle.pdf \
  --expect random-triangle.reference.csv \
  --cols symbol,x_coord,y_coord \
  --tol 1.3e-4 \
  --keep \
  -- --digits 10

t 'random down-triangle: 1000 uniform points, R downward equilateral triangles; within the 3-decimal precision of the PDF' \
  --pdf random-down-triangle.pdf \
  --expect random-down-triangle.reference.csv \
  --cols symbol,x_coord,y_coord \
  --tol 1.3e-4 \
  --keep \
  -- --digits 10

t 'random mpl-triangle: 1000 uniform points, matplotlib triangles filling a square box, point at the box centre; within the 3-decimal precision of the PDF' \
  --pdf random-mpl-triangle.pdf \
  --expect random-mpl-triangle.reference.csv \
  --cols symbol,x_coord,y_coord \
  --tol 1.3e-4 \
  --keep \
  -- --digits 10

t 'random pentagon: 1000 uniform points, regular pentagons, point at the centre (not the box middle); within the 3-decimal precision of the PDF' \
  --pdf random-pentagon.pdf \
  --expect random-pentagon.reference.csv \
  --cols symbol,x_coord,y_coord \
  --tol 1.3e-4 \
  --keep \
  -- --digits 10

t 'random hexagon: 1000 uniform points, regular hexagons; within the 3-decimal precision of the PDF' \
  --pdf random-hexagon.pdf \
  --expect random-hexagon.reference.csv \
  --cols symbol,x_coord,y_coord \
  --tol 1.3e-4 \
  --keep \
  -- --digits 10

t 'random star: 1000 uniform points, five-pointed stars, point at the centre; within the 3-decimal precision of the PDF' \
  --pdf random-star.pdf \
  --expect random-star.reference.csv \
  --cols symbol,x_coord,y_coord \
  --tol 1.3e-4 \
  --keep \
  -- --digits 10

t 'random plus: 1000 uniform points, plus signs, all vertical strokes first (R); within the 3-decimal precision of the PDF' \
  --pdf random-plus.pdf \
  --expect random-plus.reference.csv \
  --cols symbol,x_coord,y_coord \
  --tol 1.3e-4 \
  --keep \
  -- --digits 10

t 'random cross: 1000 uniform points, x crosses of two strokes; within the 3-decimal precision of the PDF' \
  --pdf random-cross.pdf \
  --expect random-cross.reference.csv \
  --cols symbol,x_coord,y_coord \
  --tol 1.3e-4 \
  --keep \
  -- --digits 10

t 'random asterisk: 1000 uniform points, R asterisks: four separate strokes of equal length; within the 3-decimal precision of the PDF' \
  --pdf random-asterisk.pdf \
  --expect random-asterisk.reference.csv \
  --cols symbol,x_coord,y_coord \
  --tol 1.3e-4 \
  --keep \
  -- --digits 10

t 'random asterisk-unequal: 1000 uniform points, asterisks whose diagonal rays are longer (a plus and a cross joined); within the 3-decimal precision of the PDF' \
  --pdf random-asterisk-unequal.pdf \
  --expect random-asterisk-unequal.reference.csv \
  --cols symbol,x_coord,y_coord \
  --tol 1.3e-4 \
  --keep \
  -- --digits 10

summary

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
#     colour, ...) identical, numeric columns equal within a tolerance
#     (rows are in increasing x within a graph, so rows a few lines apart
#     whose values all agree within the tolerance may be in either order);
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
# The Python interpreter is taken from $PYTHON (default python3).  To test
# another build of the program, set $PDFGRAPH2CSV to its path; it is run
# instead of pdfgraph2csv.py.  Needs only bash (3.2 or later) and the
# standard tools awk, grep, sort, diff, cmp.
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
#   --no-stderr TEXT a message stderr must not contain (may be repeated)
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
    function same(r, s,    k, c, j, av, ev, d) {     # actual row r = expected row s?
        for (k = 1; k <= nc; k++) {
            c = C[k]; j = ahdr[c]
            av = (j <= alen[r]) ? A[r, j] : "<none>"
            ev = ((s, c) in E) ? E[s, c] : "<none>"
            if (isnum(av) && isnum(ev)) { d = av - ev; if (d < 0) d = -d; if (d > tol) return 0 }
            else if (av != ev) return 0
        }
        return 1
    }
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
            # a row may match an expected row a few lines away when every
            # value agrees within the tolerance: rows come in increasing x,
            # and rows whose x agree within the tolerance in either order
            if (!used[r] && same(r, r)) { used[r] = 1; continue }
            found = 0
            for (s = r - 5; s <= r + 5 && !found; s++)
                if (s >= 1 && s <= erows && s != r && !used[s] && same(r, s)) { used[s] = 1; found = 1 }
            if (found) continue
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
    if [ -n "$PDFGRAPH2CSV" ]; then
        cmd=("$PDFGRAPH2CSV" "$DATA/$c_pdf" ${c_args[@]+"${c_args[@]}"})
    else
        cmd=("$PYTHON" "$PROGRAM" "$DATA/$c_pdf" ${c_args[@]+"${c_args[@]}"})
    fi
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
    while IFS= read -r text; do
        [ -z "$text" ] && continue
        if grep -qF -- "$text" "$TMP/stderr"; then
            { echo "message '$text' should not be on stderr:"; cat "$TMP/stderr"; } >"$TMP/why"
            return 1
        fi
    done <<EOF
$c_nostderr
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
    c_pdf= c_expect= c_tol=1e-6 c_cols= c_keep= c_exit= c_stderr= c_nostderr= c_out= c_counts= c_meta=
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
            --no-stderr) c_nostderr="$c_nostderr$2
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

# t_help: the --help text must be the usage text README.md gives
t_help() {
    local name='--help: the same text as the usage block of README.md'
    if [ -n "$filter" ] && ! printf '%s\n' "$name" | grep -qiF -- "$filter"; then
        return
    fi
    [ "$update" -eq 1 ] && return
    # (the indented block from "usage:" to the first line not indented)
    awk '/^    usage:/ { on = 1 } on && !/^    / && !/^$/ { exit } on' \
        "$(dirname "$PROGRAM")/README.md" | sed 's/^    //' | sed -e :a -e '/^\n*$/{$d;N;ba' -e '}' >"$TMP/help_readme"
    "$PYTHON" -I "$PROGRAM" --help >"$TMP/help_now" 2>&1
    if diff "$TMP/help_readme" "$TMP/help_now" >"$TMP/why"; then
        passed=$((passed + 1))
        [ "$verbose" -eq 1 ] && printf 'ok    %4ds  %s\n' 0 "$name"
    else
        failed=$((failed + 1))
        failed_names="$failed_names  $name
"
        printf 'FAIL  %4ds  %s\n' 0 "$name"
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

t 'matplotlib error bars (--errbars): asymmetric x/y errors, caps, stacked bars, log y; known values' \
  --pdf mpl-errorbars.pdf \
  --expect mpl-errorbars.truth.csv \
  --tol 0.000001 \
  --cols page,graph,x_coord,y_coord,x_low,x_high,y_low,y_high \
  -- --errbars

t 'matplotlib error bars: full output with --errbars' \
  --pdf mpl-errorbars.pdf \
  --expect mpl-errorbars.csv \
  -- --errbars

t 'matplotlib error bars: without --errbars no low/high columns; "3x10^1" log labels' \
  --pdf mpl-errorbars.pdf \
  --expect mpl-errorbars.noerrbars.csv

t 'matplotlib line error bars (--errbars): capped bars on the vertices of two lines without markers, one zero, drop lines ending at the caps (no bars); uncapped bars in a second panel are not reported; known values' \
  --pdf mpl-line-errorbars.pdf \
  --expect mpl-line-errorbars.truth.csv \
  --tol 0.000001 \
  --cols page,graph,x_coord,y_coord,y_low,y_high \
  -- --errbars

t 'matplotlib line error bars: full output with --errbars; two side-by-side panels whose white backgrounds are nearly square are no markers' \
  --pdf mpl-line-errorbars.pdf \
  --expect mpl-line-errorbars.csv \
  -- --errbars

t '2204.07073-010 with --errbars: capped bars on the vertices of both polarisation lines' \
  --pdf 2204.07073-010.pdf \
  --expect 2204.07073-010.errbars.csv \
  -- --errbars

t 'shared x axis: two stacked GraphPad Prism graphs, x labels under the lower one only; circles of two Bezier arcs' \
  --pdf number-sense-across-the-lifespan-004.pdf \
  --expect number-sense-across-the-lifespan-004.csv

t 'shared x axis with --errbars: interdecile bars of both stacked graphs' \
  --pdf number-sense-across-the-lifespan-004.pdf \
  --expect number-sense-across-the-lifespan-004.errbars.csv \
  -- --errbars

t 'matplotlib shared axes: stacked (sharex), side by side (sharey); a panel with other unlabelled ticks takes no scale' \
  --pdf mpl-shared-axes.pdf \
  --expect mpl-shared-axes.csv

t 'two y scales: SRAM on the left, CGP and M1 pitch on the right (named by the axis titles); InDesign ticks as tiny outlined boxes, end labels at the frame corners, small-caps caption' \
  --pdf 2017_End-of-Moores-Law-004.pdf \
  --expect 2017_End-of-Moores-Law-004.csv \
  --meta 2017_End-of-Moores-Law-004.meta.csv

t 'matplotlib twinx: scale chosen by axis title, by legend "(right axis)", by tick label colour' \
  --pdf mpl-twin-axes.pdf \
  --expect mpl-twin-axes.csv \
  --meta mpl-twin-axes.meta.csv

t 'no tick marks or axis lines: white grid lines on a grey background (seaborn darkgrid) give the ticks; thin diamonds; caption not a title' \
  --pdf 2205.01842-004.pdf \
  --expect 2205.01842-004.csv \
  --meta 2205.01842-004.meta.csv

t 'background grids: seaborn darkgrid with thin diamonds; grey blocks tiled with white gaps and nothing else; known values' \
  --pdf mpl-background-grid.pdf \
  --expect mpl-background-grid.csv \
  --tol 0.000001

t 'ggplot2 theme_minimal: only major and minor grid lines (no ticks, no axis lines); log axes; kB/MB and 1.5x labels; bars from 1x, some below; upright category labels; running header not a title' \
  --pdf 3759548.3763370-007.pdf \
  --expect 3759548.3763370-007.csv \
  --meta 3759548.3763370-007.meta.csv

t 'R curves drawn as 441 000 one-segment strokes of 0.01 pt beside long axes (the stroke grid once scanned 10^8 cells per long stroke: hours); 9 999 tiny circles per graph' \
  --pdf 61676858-74.pdf \
  --expect 61676858-74.csv \
  --meta 61676858-74.meta.csv

t 'TrueType (Type 42) text: the reference for the two damaged copies below' \
  --pdf mpl-font-type42.pdf \
  --expect mpl-font-type42.csv

t 'font without any map to Unicode (no ToUnicode, no cmap; glyph numbers as codes): read from glyph names' \
  --pdf mpl-font-no-unicode.pdf \
  --expect mpl-font-type42.csv

t 'the same, Type 0 font without /Subtype: strings read as byte pairs (once gave control characters as coordinates)' \
  --pdf mpl-font-no-subtype.pdf \
  --expect mpl-font-type42.csv

t 'Type 3 copies of Arial (matplotlib 3.3.3 output, pages 7 and 13 of 2305.15675v1) whose glyph names spell glyph numbers (uni00000013 for code 48, "0"): read by code, not as control characters' \
  --pdf 2305.15675v1-p7-13.pdf \
  --expect 2305.15675v1-p7-13.csv \
  --meta 2305.15675v1-p7-13.meta.csv

t 'six matplotlib panels on light blue backgrounds, grid lines for ticks running through three panels in a row; panel titles below ("(a) GCC"), not the x-axis title of the panel above; a centred one-line caption above two-column text' \
  --pdf 2308.04748-008.pdf \
  --expect 2308.04748-008.csv \
  --meta 2308.04748-008.meta.csv

t 'two ggplot2 panels side by side sharing project-name categories, a light grey block for the positive side (a background, not ticks), grid lines only; means drawn over the per-generator markers (open circles not highlight boxes); legend labels in small capitals with two words ("FULL higher"); keys drawn once per layer' \
  --pdf 2610.20068v1-009.pdf \
  --expect 2610.20068v1-009.csv \
  --meta 2610.20068v1-009.meta.csv

t 'MSR23_Anisha-003: two R box plots inside Form XObjects (PDFTron): text in Type 0 fonts with an embedded one-byte Identity CMap, y labels written vertically (0e+00 ... 1e+05); every outlier circle is output, those clipped far above the plot included; 20 boxes per graph (five rows each), a whisker clipped above the plot included' \
  --pdf MSR23_Anisha-003.pdf \
  --expect MSR23_Anisha-003.csv

t 'MSR23_Anisha-003: all 22463 + 11288 ZapfDingbats outliers, two legend boxes per graph, no circle hidden off the plot taken for a legend key' \
  --pdf MSR23_Anisha-003.pdf \
  --counts '1 box-max=20|1 box-median=20|1 box-min=20|1 box-q1=20|1 box-q3=20|1 filled-rectangle=2|1 open-circle=22463|2 box-max=20|2 box-median=20|2 box-min=20|2 box-q1=20|2 box-q3=20|2 filled-rectangle=2|2 open-circle=11288'

t 'matplotlib axes crossing inside the plot, tick labels in its body: spines through the origin (four quadrants), log axes crossing at 1 with grid lines at the y ends and a frame round the figure; known values (tolerance 1e-6)' \
  --pdf mpl-crossing-axes.pdf \
  --expect mpl-crossing-axes.csv \
  --tol 0.000001

t 'three Excel scatter plots with log axes (0.1, 1, 10) crossing at 1 in the middle of the plot, grid lines at 0.1 and 10, a frame round each chart' \
  --pdf 3276496-020.pdf \
  --expect 3276496-020.csv \
  --meta 3276496-020.meta.csv

t 'no tick marks: the x labels 1, 101, ... 1001 alone mark their positions; log y axis with grid lines at 1 and 10 only; a box round the chart with body text above it (no title); known values within the precision of label positions' \
  --pdf mpl-label-ticks.pdf \
  --expect mpl-label-ticks.csv

t 'Excel line chart: category x axis without ticks labelled 1, 101, ... 1001 (1061 loops); log y axis from two grid lines (1 and 10); markers every 20 points; body text above the chart box is no title' \
  --pdf 3276496-014.pdf \
  --expect 3276496-014.csv \
  --meta 3276496-014.meta.csv

t 'no tick marks on any axis: label centres give the positions (0.00 ... 1.00; 4, 8, 12 on a 1..15 axis); a facet without labels shares the y axis of its left neighbour, not of the panel to its right whose labels stand between them; dots hidden in a line as wide as they are dropped; known values (y within 0.001: the labels are the only scale)' \
  --pdf mpl-no-ticks.pdf \
  --expect mpl-no-ticks.csv

t 'five ggplot2 panels without tick marks (labels at the positions, 0.00 ... 1.00, 4 / 8 / 12); three facets sharing one y axis inside grey frames; markers flattened with semi-transparent error bars into pieces of blended colours (one marker each, not stacks); y label "0.50" set close to the sideways axis title; outline rings and dots hidden in model curves dropped; panel label "(c)" is no title' \
  --pdf cheyette2024limited-008.pdf \
  --expect cheyette2024limited-008.csv \
  --meta cheyette2024limited-008.meta.csv \
  --no-stderr 'flattened into fragments'

t 'Excel error bars (--errbars): halves from the marker centre, slightly slanted, dense stacks, log-log' \
  --pdf Rescaling_reliability_bounds_new_opprof-002.pdf \
  --expect Rescaling_reliability_bounds_new_opprof-002.errbars.csv \
  -- --errbars

t 'MollickMooresLawIEEE-009: two Excel scatter plots (x 1978-1996 and 1965-2000), filled diamonds with corners on a coarse grid, outlines stroked as separate edges, a fitted curve of filled slivers through some diamonds, a wrong y label (0.4 for 0.2), ticks crossing at the axes corner' \
  --pdf MollickMooresLawIEEE-009.pdf \
  --expect MollickMooresLawIEEE-009.csv

t 'MollickMooresLawIEEE-009: every diamond (47 and 13, duplicates included), no + or x from crossing outline edges or corner ticks' \
  --pdf MollickMooresLawIEEE-009.pdf \
  --counts '1 filled-diamond=47|2 filled-diamond=13'

t 'LogicProbPragSyllogistic_Reasoning-013: three ggplot2 facets traced from a bitmap (31 000 staircase slivers of error bars and dotted lines, all labels drawn as outlines); x axes 0 and 1 under each facet, y axis 0 and 1 on the left only; panel borders as filled outlines; points drawn as a coloured disc and a black ring' \
  --pdf LogicProbPragSyllogistic_Reasoning-013.pdf \
  --expect LogicProbPragSyllogistic_Reasoning-013.csv

t 'horowitz2014-004: eight graphs on a page: y labels with SI units (10 mW ... 1 W, 22 nm ... 1.5 um, 10 MHz ... 5 GHz with the units drawn as outlines: the prefix step read from the fall 500 -> 1), an inset (Vdd 1-5 V over 1985-2015) inside a plot whose grid line must not take its labels, Helvetica+T42 glyphs named s0..s9 read by their outlines, 1x 2x 5x ... at equal spacing (a log axis fitted to its decades), legend keys of distinct shapes naming points coloured along a colour bar, a range dash in an unembedded Identity font' \
  --pdf horowitz2014-004.pdf \
  --expect horowitz2014-004.csv

t '0307278v2-003: two log-log panels whose left y ticks are repeated on the right axis (one scale, not two: the body text beside panel B is no label); each circle drawn as a white fill, a pattern fill and a black outline (one point); top-right corner where the mirrored minor ticks cross is no plus; panel B = L/(N(N-1)) of panel A' \
  --pdf 0307278v2-003.pdf \
  --expect 0307278v2-003.csv

t '3368089.3409714-004: ggplot2 scatter of 14 subjects drawn as big discs, squares and pentagons (13 pt, over the usual size limit; accepted as their shapes and colours are the legend keys), each with its subject id inside: ids of touching markers run together into one line and are split; the points match the paper table (years of programming)' \
  --pdf 3368089.3409714-004.pdf \
  --expect 3368089.3409714-004.csv

t '2609.00744v2-025: log y axis labelled 10^-9, 10^-7 ... 10^3 (exponents in steps of 2) whose TeX minus signs come from a symbol font, apart from their digits; three marked points with data labels (two-line "FlashAttention, paged KV")' \
  --pdf 2609.00744v2-025.pdf \
  --expect 2609.00744v2-025.csv

t '2014_JPL-State_of_SW_Jun-29-031: Excel for Mac line chart whose markers are images (gradient-filled diamond, square, triangle with soft masks, each over a faint black shadow image): shapes read from the masks, series from the colour of the line through each marker; data labels 55% ... 26% in the label column; Calibri subset whose ToUnicode maps the space to "$" and the "ti" ligature to "8"; figure "3-6"' \
  --pdf 2014_JPL-State_of_SW_Jun-29-031.pdf \
  --expect 2014_JPL-State_of_SW_Jun-29-031.csv \
  --meta 2014_JPL-State_of_SW_Jun-29-031.meta.csv

t '120875-008: R line chart without tick marks under a translucent watermark image (it hides no labels): the y label centres (50 ... 200, drawn as outlines) stand in for ticks, with y_coord_low/y_coord_high; three categories (outlined, unreadable, one on two lines) numbered #1 ... #3 at their centres; the ranges hold the paper table means 60, 43, 39, 146' \
  --pdf 120875-008.pdf \
  --expect 120875-008.csv

t 'ITRS_2011ExecSum-028: Excel chart with notes in bordered boxes (three yellow, two blue) inside and beside the plot: the boxed text is not counted as running text; DRAM, Flash and MPU 17 points each' \
  --pdf ITRS_2011ExecSum-028.pdf \
  --expect ITRS_2011ExecSum-028.csv

t 'ITRS_2011ExecSum-031: log-scale frequency chart crowded with notes in yellow boxes with dashed borders: the boxed text is not counted (the graph is kept), and the dashes of the borders, drawn as small squares, are no points' \
  --pdf ITRS_2011ExecSum-031.pdf \
  --expect ITRS_2011ExecSum-031.csv

t 'prob-book-057: two binomial probability functions on a page of text: open circles drawn as stroked 20-gons, filled circles as fans of thin triangles; the sample markers in the caption, the dots of "X1 + ... + Xn" and a full stop drawn as a shape are no points; the values are Binomial(20, 1/2) and Binomial(20, 1/5) to 0.0005' \
  --pdf prob-book-057.pdf \
  --expect prob-book-057.csv

t '2206.11102v2-018: beeswarm plot, categories journal / conference / workshop on y (points spread around each line to be seen), circles squashed into ellipses by unequal x and y scaling, --integer x (participant counts drawn with jitter); the paper gives the workshop median 26 and mean 33.1, and the shares of student-only samples (19/41, 25/45, 7/9)' \
  --pdf 2206.11102v2-018.pdf \
  --expect 2206.11102v2-018.csv \
  -- --integer x

t '2610.30307v1-011: log y axis of durations labelled 1 s, 15 s, 1 min ... 64 h (values in seconds), vertical error bars not given (points read the same), a blue dot highlighted by a white circle with a blue outline (one point, its own series); a category y axis of model names with horizontal error bars' \
  --pdf 2610.30307v1-011.pdf \
  --expect 2610.30307v1-011.csv

t '2204.07073-010: x axis 1939, 1949, 1965, 1977, 1991; stacked bars (cognitive under physical, labelled 87% ... 77% inside the bars) under node-link diagrams of tens of thousands of tiny markers (reported, read through the axes of the bars: squares turned by the angle of each network; the 1949 nodes, a little off the legend colours, named by the nearest swatch); two line graphs over grey bands (not bars), one with an inset of density curves whose coloured legend samples are no axis' \
  --pdf 2204.07073-010.pdf \
  --expect 2204.07073-010.csv

t '2610.30307v1-003: a log y axis labelled 1 min, 1 hour, 1 day (values in minutes, the smallest unit; "1 day" stands at 8 hours, a day of work), six small multiples and a line chart' \
  --pdf 2610.30307v1-003.pdf \
  --expect 2610.30307v1-003.csv

t '2610.30307v1-011: with --errbars, the bars in seconds and in index units' \
  --pdf 2610.30307v1-011.pdf \
  --expect 2610.30307v1-011.errbars.csv \
  -- --errbars

t 'song2025rigorous-002: with --sizesymbol, the marker sizes (circles 1.36 and 1.43 pt across, triangles 1.8 pt); stippled drawings of a hare and a lynx (hundreds of dots of all sizes, clipped to the whole figure) over plot a are no data; plot d stacks two panels with y axis lines of their own over one x axis; the phase plot (c, observed pattern) gives the 21 corners of its path, not its arrowheads, and the drawings of panel e beside it do not count as its markers' \
  --pdf song2025rigorous-002.pdf \
  --expect song2025rigorous-002.sizesymbol.csv \
  -- --sizesymbol

t '2017_End-of-Moores-Law-002: log y axis labelled 1E-21 ... 1E-03 (programming notation) without tick marks, the label centres standing in for them, with x_coord_low ... y_coord_high giving the range of each value; legend keys filled white with coloured outlines name open and outlined markers' \
  --pdf 2017_End-of-Moores-Law-002.pdf \
  --expect 2017_End-of-Moores-Law-002.csv

t 'mpl-no-ticks: x_coord_low ... y_coord_high where label centres stand in for ticks (checked once to hold the known values)' \
  --pdf mpl-no-ticks.pdf \
  --expect mpl-no-ticks.ranges.csv \
  --cols x_coord_low,x_coord_high,y_coord_low,y_coord_high

t 'LogicProbPragSyllogistic_Reasoning-013: 576 points per facet (no slivers read as "1" or as markers, no disc taken for the dot of an i), five legend keys' \
  --pdf LogicProbPragSyllogistic_Reasoning-013.pdf \
  --counts '1 filled-circle=576|2 filled-circle=576|3 filled-circle=581'

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

t 'State_IT_Project_Management_in_UK-056: no graph, one large ruled table of numbers (24 rules across its width, column rules cut cell by cell); no row of it is taken for a plot, no meta file' \
  --pdf State_IT_Project_Management_in_UK-056.pdf \
  --meta - \
  --stderr 'No vector graphics found'

t 'ThomasBockPhD-073, with meta file: four pdfLaTeX scatter plots of plus markers (26 MB of drawing instructions, 153 329 markers, 49 032 of them on one spot, each with its own horizontal stroke); the stacked copies are looked at once for legend keys (it took many minutes); a stray point beside the annotation "RMSE: 2.14" is no legend key' \
  --pdf ThomasBockPhD-073.pdf \
  --meta ThomasBockPhD-073.meta.csv \
  --counts '1 plus=134915|2 plus=12848|3 plus=2783|4 plus=2783'

t 'Memory_systems_cacheDRAMdisk-051, with meta file: InDesign page of three bar charts whose x ticks are labelled twice: bandwidths 0.8 ... 25.6 (numbers that fit no scale: categories) and, for each group of bars, its channel configuration in the x_group column (slanted under the GCC and BZIP charts, set last letter first; slanted above the PERL bars, whose axis has no ticks and whose 12.8 and 25.6 come as one string); stacked bars of five segments, the black ones thick strokes, the grey ones 0.17 pt thin; BZIP legend inside its plot with a white swatch drawn as an outline only; GCC named by the page colours, PERL (one colour) not' \
  --pdf Memory_systems_cacheDRAMdisk-051.pdf \
  --expect Memory_systems_cacheDRAMdisk-051.csv \
  --meta Memory_systems_cacheDRAMdisk-051.meta.csv

t 'cheyette2024limited-011, with meta file: four ggplot panels, all text outlined, no tick marks anywhere: axis positions from the labels (the y axis of panel (a) from two labels at the plot corner; the minus signs in panel (c) are no ticks; the labels of panel (d) not kept by error-bar caps read as ticks); markers of (c) and (d) drawn in layers, their pale faces dropped; the translucent rings of panel (b), flattened into pieces, rebuilt from their white faces (300 rings), its dotted diagonal (one path of 107 dots) no markers; two-key line legends with unreadable names flagged as keys' \
  --pdf cheyette2024limited-011.pdf \
  --expect cheyette2024limited-011.csv \
  --meta cheyette2024limited-011.meta.csv

t 'ArianeWuerbach-Phd-064, with meta file: two R lattice panels side by side (Female, Male) sharing one frame; the x axis of the left panel at the bottom and of the right panel at the top, each line across both panels, cut at the panel border; the right panel borrows the y scale of the left (its unlabelled ticks on the right edge); about ten open circles per observation' \
  --pdf ArianeWuerbach-Phd-064.pdf \
  --meta ArianeWuerbach-Phd-064.meta.csv \
  --counts '1 open-circle=41455|2 open-circle=45058'

t 'Maj-Petr_PhD-077, with meta file: four ggplot heat maps (geom_bin2d): a point per tile, its value read off the log colour bar (an inline image) beside it, the bar ticks no minus signs; titles under the axis title of the graph above; a two-label log x axis (10, 1000)' \
  --pdf Maj-Petr_PhD-077.pdf \
  --meta Maj-Petr_PhD-077.meta.csv \
  --counts '1 tile=3017|2 tile=3705|3 tile=3137|4 tile=4526'

t '10.5445IR1000121285-038, with meta file: six matplotlib panels of transfer curves (log y axes from 10^-11 to 10^-3), each with a legend of seven V_DS values in two columns: the numbers name the series (0.01 ... 1) and are no right y axis (no scale on both sides), the heading V_DS names no key, panel (f) is not split by its 10^-11 grid line; a grey square of the next figure under the caption is no legend key' \
  --pdf 10.5445IR1000121285-038.pdf \
  --expect 10.5445IR1000121285-038.csv \
  --meta 10.5445IR1000121285-038.meta.csv \
  --no-stderr 'scale on both sides'

t '2305.15675v1-015, with meta file: 85 MB of drawing (34 000 dashes no longer compared pair by pair for minus signs: 30 s, was over 5 minutes); a horizontal box plot of 10 features, boxes as short as 0.25 pt; three histograms, the middle one log-log (labels 10^1, 10^3 and 10^2, 10^4 alone make log axes; its bars, clipped at the plot bottom, stand there and no longer hide the x labels under the plot)' \
  --pdf 2305.15675v1-015.pdf \
  --expect 2305.15675v1-015.csv \
  --meta 2305.15675v1-015.meta.csv

t 'unified-noise-bayes-019, with meta file: six MATLAB scatter panels whose markers are flattened into fragments, 510 circles rebuilt (each with a confidence) and no warning about it; log axes 0 (at the place of 1), 10, 100, 250' \
  --pdf unified-noise-bayes-019.pdf \
  --expect unified-noise-bayes-019.csv \
  --meta unified-noise-bayes-019.meta.csv \
  --no-stderr 'flattened into fragments'

t 'log-clipped-markers: circles flattened into fragments and clipped; rebuilt with stacking counts and a confidence for each, no warning about it' \
  --pdf log-clipped-markers.pdf \
  --expect log-clipped-markers.csv \
  --no-stderr 'flattened into fragments'

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

t '3297663.3310314-005: four ruled tables (column headings, row names, shaded cells, a number in each cell) are no graphs' \
  --pdf 3297663.3310314-005.pdf \
  --stderr 'No vector graphics found'

t 'Main_causes_of_missing_errors_testing-006: a 3 x 3 table of percentages whose rules pass for axes, a column of it for y labels and words of its caption for categories; a grid of numbers is no graph' \
  --pdf Main_causes_of_missing_errors_testing-006.pdf \
  --stderr 'No vector graphics found'

t '564-010: a table of numbers ruled with thin filled rectangles (0.5 pt squares at the joints, row names t14 ... t28, numbers split by thin spaces) is no graph' \
  --pdf 564-010.pdf \
  --stderr 'No vector graphics found'

t 'prob-book-038: a page of mathematics (shaded definition boxes ruled above and below, bracket glyphs drawn as outlines, numbers in the prose) is no graph' \
  --pdf prob-book-038.pdf \
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

t 'S1383762124002030 page 9: box plots with 472 000 outlier circles in a 92 MB Form XObject (2.3 million operators) - must finish in well under a minute without exhausting memory; only the point counts are checked; 21 boxes in graphs 2 and 3 (a box filled and outlined across a rounding edge is one box), none in graph 1 where they are squashed flat' \
  --pdf S1383762124002030.pdf \
  --stderr 'MB of drawing instructions' \
  --counts '1 open-circle=240613|2 box-max=21|2 box-median=21|2 box-min=21|2 box-q1=21|2 box-q3=21|2 open-circle=218658|3 box-max=21|3 box-median=21|3 box-min=21|3 box-q1=21|3 box-q3=21|3 open-circle=13121' \
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

t 'cumulative-evol-hollywood-film-crews-007, with meta file: three log-scale panels whose outlined axes and tick labels are drawn up to four times over in the same place (repeated glyphs are one glyph); 1910 to 2010 and 3 to 3000 read in all three' \
  --pdf cumulative-evol-hollywood-film-crews-007.pdf \
  --expect cumulative-evol-hollywood-film-crews-007.csv \
  --meta cumulative-evol-hollywood-film-crews-007.meta.csv

t '2401.16279-023, with meta file: two log y axes labelled only 10^2, scaled by their minor ticks (2 to 9 times each power of ten); x labels 10^-2 and 10^-1 whose minus signs are drawn bars; error bars of a log bar chart clipped off the page do not hide those bars' \
  --pdf 2401.16279-023.pdf \
  --expect 2401.16279-023.csv \
  --meta 2401.16279-023.meta.csv

t 'sarroRE15-008, with meta file: eight R box plots (pdfTeX): boxes filled and outlined, dashed whiskers with caps, boxes of no height (just a median line), boxes without whiskers; outliers in a re-encoded ZapfDingbats subset (the circle as code 33), drawn as outlines' \
  --pdf sarroRE15-008.pdf \
  --expect sarroRE15-008.csv \
  --meta sarroRE15-008.meta.csv

t '2308.04785-006, with meta file: two seaborn correlation matrices with category axes both ways; each cell a coloured square with its coefficient printed in it (a label per square, values in neighbouring cells run together are split, a value just after a y label is not lost with it); the grid of numbers is no table; the colour bar is an image (indexed colours): each cell a heat-map tile whose colour-bar value agrees with its printed coefficient' \
  --pdf 2308.04785-006.pdf \
  --expect 2308.04785-006.csv \
  --meta 2308.04785-006.meta.csv

t '3485513-020, with meta file: three Google Sheets charts without frames or x ticks; a dot chart of 30 benchmarks whose names, slanted 60 degrees, mark the categories with their ends (2mm read as a word, not a length); two bar charts with rounded bars and soft shadows, the tallest rising above the top grid line, whose bar edges must not split the grid; the right chart averages the middle one' \
  --pdf 3485513-020.pdf \
  --expect 3485513-020.csv \
  --meta 3485513-020.meta.csv

t 'Korotayev_Doomsday_preprint-005, with meta file: Excel scatter plot with decimal commas (x axis 4,0 ... 0,0 falling to the right, log y axis 1,E-10 ... 1,E-01 on the right)' \
  --pdf Korotayev_Doomsday_preprint-005.pdf \
  --expect Korotayev_Doomsday_preprint-005.csv \
  --meta Korotayev_Doomsday_preprint-005.meta.csv

t 'Statistical_Test_Coverage_for_Linux, with meta file: 14-page IEEE paper; page 10 left: outlined R labels in e-notation (1e+00 ... 1e+06, 5e-04 ... 5e-01) on log axes, 238 open circles; pages 6 and 11: line charts whose curves are no longer hidden by circles of a diagram in the other column; page 8: horizontal interval boxes without whiskers (estimate and 95 percent interval per estimator)' \
  --pdf Statistical_Test_Coverage_for_Linux.pdf \
  --expect Statistical_Test_Coverage_for_Linux.csv \
  --meta Statistical_Test_Coverage_for_Linux.meta.csv

t 'w21074-042, with meta file: Excel line chart whose y labels 0% to 100% are repeated on the right side, 0.2 pt higher, with no tick marks of their own: one scale, no warning' \
  --pdf w21074-042.pdf \
  --expect w21074-042.csv \
  --meta w21074-042.meta.csv

t 'wp_21_1036-019, with meta file: ggplot2 scatter of three series, each of 17 points drawn 175 to 525 times over (duplicates reported); squares with a plus (pch 12) are one marker, not box plots; the line samples on the grey legend key squares and the names beside them are no second scale' \
  --pdf wp_21_1036-019.pdf \
  --meta wp_21_1036-019.meta.csv \
  --counts '1 filled-square=4029|1 open-square-plus=3851|1 open-triangle=3676'

t 'Seongmin-PhD-044, with --rotation and meta file: a thesis page set sideways (content turned 90 degrees anticlockwise, page not rotated) holding four ggplot figures of two box-plot panels each; the page is read turned; panel ticks with no axis lines run together across panels and are split into even runs; turned y labels end at their ticks; a two-label time axis (1000, 2000) running past zero is log; legend key medians are no ticks; panels without a legend named by the page colours; flat ORBS boxes named by their dodge slot; outliers named by their box and filled by a dot glyph' \
  --pdf Seongmin-PhD-044.pdf \
  --expect Seongmin-PhD-044.rotation.csv \
  --meta Seongmin-PhD-044.meta.csv \
  -- --rotation

t 'Teaching-disciplined-softdev-008, with --errbars and meta file: three Statistica plots of means with 0.95 confidence bars; Fig. 4 category labels Exercise 2 ... 10 staggered over two rows, alternate ticks on each (Exercice 3 is spelt so in the PDF); markers are 10 x 9 pixel images of blue discs on white, no mask, with the dotted grid through them' \
  --pdf Teaching-disciplined-softdev-008.pdf \
  --expect Teaching-disciplined-softdev-008.errbars.csv \
  --meta Teaching-disciplined-softdev-008.meta.csv \
  -- --errbars

t '3576042-018, with meta file: six matplotlib line charts, all text outlined; tick marks filled as single segments (no glyphs); x labels 1 to 10 read upright though 6 and 9 read as well upside down; each framed legend below its x axis goes whole to the graph above; the I of HINDBR bridges its word, so the H is no marker' \
  --pdf 3576042-018.pdf \
  --expect 3576042-018.csv \
  --meta 3576042-018.meta.csv

t 'logpaper5Rediscoveries-007, with --errbars and meta file: Excel via PScript5 and Distiller; left, 37 dash markers (thin filled rectangles, a set of one size) with error bars on a log y axis, dotted fitted curve drawn as small turned pieces (no markers); right, line chart named by its own legend (Year 1, Year 2), not the left one' \
  --pdf logpaper5Rediscoveries-007.pdf \
  --expect logpaper5Rediscoveries-007.errbars.csv \
  --meta logpaper5Rediscoveries-007.meta.csv \
  -- --errbars

t 'jordan-teh-026: four stem plots of Dirichlet process draws (one point per atom at the top of its stem; atoms of no mass drawn as strokes of no length or as dots on the axis); stems standing on the x axis like tick marks do not make axes' \
  --pdf jordan-teh-026.pdf \
  --expect jordan-teh-026.csv

t 'S1383762124002030 pages 6-7, with meta file: two-column journal pages, captions with monospaced words, category axes; autocorrelation stem plots (stems up and down from the 0 line, every lag)' \
  --pdf S1383762124002030.pdf \
  --expect S1383762124002030-p6-7.csv \
  --meta S1383762124002030-p6-7.meta.csv \
  -- --pages 6,7

t 'meta file: tool from the document information of a PDF that is itself a plot (as R writes it)' \
  --pdf synthetic-line-plus.pdf \
  --counts '1 filled-circle=7|1 plus=7' \
  --meta synthetic-line-plus.meta.csv

t 'meta file: no tool when the embedded graphic names only a printer driver and Distiller' \
  --pdf broken-axes.pdf \
  --expect broken-axes.csv \
  --meta broken-axes.meta.csv

t 'meta file: tool guessed from the drawing style - matplotlib 2.2.2 histograms (graphics states A1.., tab10 blue)' \
  --pdf histogram.pdf \
  --expect histogram.csv \
  --meta histogram.meta.csv

t 'meta file: tool guessed from the drawing style - Excel 2003 charts (navy diamonds), no tool recorded' \
  --pdf effort-fig2-excel-diamonds.pdf \
  --expect effort-fig2-excel-diamonds.csv \
  --meta effort-fig2-excel-diamonds.meta.csv

t '2510.19281v2-013: SPSS scatter plot converted by Inkscape - every shape followed by an empty subpath, all text outlined (labels with Bezier 0s, letters o and full stops that look like markers), legend key beside a line sample converted to a thin filled rectangle' \
  --pdf 2510.19281v2-013.pdf \
  --expect 2510.19281v2-013.csv \
  --meta 2510.19281v2-013.meta.csv

t 'meta file only: --meta-only writes the meta file and no data points (nothing on stdout)' \
  --pdf 3576042-018.pdf \
  --meta 3576042-018.meta.csv \
  -- --meta-only

t 'meta file: not created when no graph is found' \
  --pdf no-graph.pdf \
  --meta - \
  --stderr 'No vector graphics found'

t 'random circle: 1000 uniform points, filled circles of four Bezier curves; coordinates with 3 decimals, every point within their precision' \
  --pdf random-circle.pdf \
  --expect random-circle.reference.csv \
  --cols symbol,x_coord,y_coord \
  --tol 1.3e-4 \
  --keep

t 'random open-circle: 1000 uniform points, stroked circles of four Bezier curves; coordinates with 3 decimals, every point within their precision' \
  --pdf random-open-circle.pdf \
  --expect random-open-circle.reference.csv \
  --cols symbol,x_coord,y_coord \
  --tol 1.3e-4 \
  --keep

t 'random circle8: 1000 uniform points, circles of eight Bezier curves in a Form XObject (matplotlib); coordinates with 3 decimals, every point within their precision' \
  --pdf random-circle8.pdf \
  --expect random-circle8.reference.csv \
  --cols symbol,x_coord,y_coord \
  --tol 1.3e-4 \
  --keep

t 'random dingbat-circle: 1000 uniform points, ZapfDingbats a71 circles (R pdf()); coordinates with 3 decimals, every point within their precision' \
  --pdf random-dingbat-circle.pdf \
  --expect random-dingbat-circle.reference.csv \
  --cols symbol,x_coord,y_coord \
  --tol 1.3e-4 \
  --keep

t 'random diamond: 1000 uniform points, stroked diamonds of four lines; coordinates with 3 decimals, every point within their precision' \
  --pdf random-diamond.pdf \
  --expect random-diamond.reference.csv \
  --cols symbol,x_coord,y_coord \
  --tol 1.3e-4 \
  --keep

t 'random filled-diamond: 1000 uniform points, filled diamonds; coordinates with 3 decimals, every point within their precision' \
  --pdf random-filled-diamond.pdf \
  --expect random-filled-diamond.reference.csv \
  --cols symbol,x_coord,y_coord \
  --tol 1.3e-4 \
  --keep

t 'random fill-outline-diamond: 1000 uniform points, diamonds filled then stroked (Excel); coordinates with 3 decimals, every point within their precision' \
  --pdf random-fill-outline-diamond.pdf \
  --expect random-fill-outline-diamond.reference.csv \
  --cols symbol,x_coord,y_coord \
  --tol 1.3e-4 \
  --keep

t 'random square: 1000 uniform points, filled squares (re); coordinates with 3 decimals, every point within their precision' \
  --pdf random-square.pdf \
  --expect random-square.reference.csv \
  --cols symbol,x_coord,y_coord \
  --tol 1.3e-4 \
  --keep

t 'random open-square: 1000 uniform points, stroked squares (re); coordinates with 3 decimals, every point within their precision' \
  --pdf random-open-square.pdf \
  --expect random-open-square.reference.csv \
  --cols symbol,x_coord,y_coord \
  --tol 1.3e-4 \
  --keep

t 'random triangle: 1000 uniform points, R equilateral triangles, point at the centroid; coordinates with 3 decimals, every point within their precision' \
  --pdf random-triangle.pdf \
  --expect random-triangle.reference.csv \
  --cols symbol,x_coord,y_coord \
  --tol 1.3e-4 \
  --keep

t 'random down-triangle: 1000 uniform points, R downward equilateral triangles; coordinates with 3 decimals, every point within their precision' \
  --pdf random-down-triangle.pdf \
  --expect random-down-triangle.reference.csv \
  --cols symbol,x_coord,y_coord \
  --tol 1.3e-4 \
  --keep

t 'random mpl-triangle: 1000 uniform points, matplotlib triangles filling a square box, point at the box centre; coordinates with 3 decimals, every point within their precision' \
  --pdf random-mpl-triangle.pdf \
  --expect random-mpl-triangle.reference.csv \
  --cols symbol,x_coord,y_coord \
  --tol 1.3e-4 \
  --keep

t 'random pentagon: 1000 uniform points, regular pentagons, point at the centre (not the box middle); coordinates with 3 decimals, every point within their precision' \
  --pdf random-pentagon.pdf \
  --expect random-pentagon.reference.csv \
  --cols symbol,x_coord,y_coord \
  --tol 1.3e-4 \
  --keep

t 'random hexagon: 1000 uniform points, regular hexagons; coordinates with 3 decimals, every point within their precision' \
  --pdf random-hexagon.pdf \
  --expect random-hexagon.reference.csv \
  --cols symbol,x_coord,y_coord \
  --tol 1.3e-4 \
  --keep

t 'random star: 1000 uniform points, five-pointed stars, point at the centre; coordinates with 3 decimals, every point within their precision' \
  --pdf random-star.pdf \
  --expect random-star.reference.csv \
  --cols symbol,x_coord,y_coord \
  --tol 1.3e-4 \
  --keep

t 'random plus: 1000 uniform points, plus signs, all vertical strokes first (R); coordinates with 3 decimals, every point within their precision' \
  --pdf random-plus.pdf \
  --expect random-plus.reference.csv \
  --cols symbol,x_coord,y_coord \
  --tol 1.3e-4 \
  --keep

t 'random cross: 1000 uniform points, x crosses of two strokes; coordinates with 3 decimals, every point within their precision' \
  --pdf random-cross.pdf \
  --expect random-cross.reference.csv \
  --cols symbol,x_coord,y_coord \
  --tol 1.3e-4 \
  --keep

t 'random asterisk: 1000 uniform points, R asterisks: four separate strokes of equal length; coordinates with 3 decimals, every point within their precision' \
  --pdf random-asterisk.pdf \
  --expect random-asterisk.reference.csv \
  --cols symbol,x_coord,y_coord \
  --tol 1.3e-4 \
  --keep

t 'random asterisk-unequal: 1000 uniform points, asterisks whose diagonal rays are longer (a plus and a cross joined); coordinates with 3 decimals, every point within their precision' \
  --pdf random-asterisk-unequal.pdf \
  --expect random-asterisk-unequal.reference.csv \
  --cols symbol,x_coord,y_coord \
  --tol 1.3e-4 \
  --keep

t 'random10 circle: the same points with 10-digit coordinates (filled circles of four Bezier curves); every point within their precision (1.25e-8)' \
  --pdf random10-circle.pdf \
  --expect random-circle.reference.csv \
  --cols symbol,x_coord,y_coord \
  --tol 1.3e-8 \
  --keep

t 'random10 open-circle: the same points with 10-digit coordinates (stroked circles of four Bezier curves); every point within their precision (1.25e-8)' \
  --pdf random10-open-circle.pdf \
  --expect random-open-circle.reference.csv \
  --cols symbol,x_coord,y_coord \
  --tol 1.3e-8 \
  --keep

t 'random10 circle8: the same points with 10-digit coordinates (circles of eight Bezier curves in a Form XObject (matplotlib)); every point within their precision (1.25e-8)' \
  --pdf random10-circle8.pdf \
  --expect random-circle8.reference.csv \
  --cols symbol,x_coord,y_coord \
  --tol 1.3e-8 \
  --keep

t 'random10 dingbat-circle: the same points with 10-digit coordinates (ZapfDingbats a71 circles (R pdf())); every point within their precision (1.25e-8)' \
  --pdf random10-dingbat-circle.pdf \
  --expect random-dingbat-circle.reference.csv \
  --cols symbol,x_coord,y_coord \
  --tol 1.3e-8 \
  --keep

t 'random10 diamond: the same points with 10-digit coordinates (stroked diamonds of four lines); every point within their precision (1.25e-8)' \
  --pdf random10-diamond.pdf \
  --expect random-diamond.reference.csv \
  --cols symbol,x_coord,y_coord \
  --tol 1.3e-8 \
  --keep

t 'random10 filled-diamond: the same points with 10-digit coordinates (filled diamonds); every point within their precision (1.25e-8)' \
  --pdf random10-filled-diamond.pdf \
  --expect random-filled-diamond.reference.csv \
  --cols symbol,x_coord,y_coord \
  --tol 1.3e-8 \
  --keep

t 'random10 fill-outline-diamond: the same points with 10-digit coordinates (diamonds filled then stroked (Excel)); every point within their precision (1.25e-8)' \
  --pdf random10-fill-outline-diamond.pdf \
  --expect random-fill-outline-diamond.reference.csv \
  --cols symbol,x_coord,y_coord \
  --tol 1.3e-8 \
  --keep

t 'random10 square: the same points with 10-digit coordinates (filled squares (re)); every point within their precision (1.25e-8)' \
  --pdf random10-square.pdf \
  --expect random-square.reference.csv \
  --cols symbol,x_coord,y_coord \
  --tol 1.3e-8 \
  --keep

t 'random10 open-square: the same points with 10-digit coordinates (stroked squares (re)); every point within their precision (1.25e-8)' \
  --pdf random10-open-square.pdf \
  --expect random-open-square.reference.csv \
  --cols symbol,x_coord,y_coord \
  --tol 1.3e-8 \
  --keep

t 'random10 triangle: the same points with 10-digit coordinates (R equilateral triangles, point at the centroid); every point within their precision (1.25e-8)' \
  --pdf random10-triangle.pdf \
  --expect random-triangle.reference.csv \
  --cols symbol,x_coord,y_coord \
  --tol 1.3e-8 \
  --keep

t 'random10 down-triangle: the same points with 10-digit coordinates (R downward equilateral triangles); every point within their precision (1.25e-8)' \
  --pdf random10-down-triangle.pdf \
  --expect random-down-triangle.reference.csv \
  --cols symbol,x_coord,y_coord \
  --tol 1.3e-8 \
  --keep

t 'random10 mpl-triangle: the same points with 10-digit coordinates (matplotlib triangles filling a square box, point at the box centre); every point within their precision (1.25e-8)' \
  --pdf random10-mpl-triangle.pdf \
  --expect random-mpl-triangle.reference.csv \
  --cols symbol,x_coord,y_coord \
  --tol 1.3e-8 \
  --keep

t 'random10 pentagon: the same points with 10-digit coordinates (regular pentagons, point at the centre (not the box middle)); every point within their precision (1.25e-8)' \
  --pdf random10-pentagon.pdf \
  --expect random-pentagon.reference.csv \
  --cols symbol,x_coord,y_coord \
  --tol 1.3e-8 \
  --keep

t 'random10 hexagon: the same points with 10-digit coordinates (regular hexagons); every point within their precision (1.25e-8)' \
  --pdf random10-hexagon.pdf \
  --expect random-hexagon.reference.csv \
  --cols symbol,x_coord,y_coord \
  --tol 1.3e-8 \
  --keep

t 'random10 star: the same points with 10-digit coordinates (five-pointed stars, point at the centre); every point within their precision (1.25e-8)' \
  --pdf random10-star.pdf \
  --expect random-star.reference.csv \
  --cols symbol,x_coord,y_coord \
  --tol 1.3e-8 \
  --keep

t 'random10 plus: the same points with 10-digit coordinates (plus signs, all vertical strokes first (R)); every point within their precision (1.25e-8)' \
  --pdf random10-plus.pdf \
  --expect random-plus.reference.csv \
  --cols symbol,x_coord,y_coord \
  --tol 1.3e-8 \
  --keep

t 'random10 cross: the same points with 10-digit coordinates (x crosses of two strokes); every point within their precision (1.25e-8)' \
  --pdf random10-cross.pdf \
  --expect random-cross.reference.csv \
  --cols symbol,x_coord,y_coord \
  --tol 1.3e-8 \
  --keep

t 'random10 asterisk: the same points with 10-digit coordinates (R asterisks: four separate strokes of equal length); every point within their precision (1.25e-8)' \
  --pdf random10-asterisk.pdf \
  --expect random-asterisk.reference.csv \
  --cols symbol,x_coord,y_coord \
  --tol 1.3e-8 \
  --keep

t 'random10 asterisk-unequal: the same points with 10-digit coordinates (asterisks whose diagonal rays are longer (a plus and a cross joined)); every point within their precision (1.25e-8)' \
  --pdf random10-asterisk-unequal.pdf \
  --expect random-asterisk-unequal.reference.csv \
  --cols symbol,x_coord,y_coord \
  --tol 1.3e-8 \
  --keep

t_help

summary

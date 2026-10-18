#!/usr/bin/env python3
"""
Regression test suite for pdfgraph2csv.py.

Every case in cases.json runs pdfgraph2csv.py (as a separate process, exactly
as a user would) on a PDF in tests/data and compares the CSV it writes with
the expected CSV stored next to it:

  * the same number of rows, in the same order;
  * text columns (page, graph, symbol, color, ...) identical;
  * numeric columns equal within the case's tolerance.

A case may also give "output_file" (the CSV is then written with -o to a
temporary file of that name, which must not be created when there are no
points), "exit_code" (default 0) and "stderr_contains" (texts
the warnings / error message must include); a case whose "expected" is null
checks only those and that nothing is written to stdout (e.g. a damaged
file that must be rejected cleanly, or a file without graphs) - or, with
"expected_counts", the number of points per "graph symbol" (for files whose
output is too big to keep).

Usage
-----
    python3 tests/run_tests.py              # run all cases
    python3 tests/run_tests.py -v           # verbose (one line per case)
    python3 tests/run_tests.py -k rofpc     # only cases whose name contains "rofpc"
    python3 tests/run_tests.py --update     # re-generate the expected CSVs
                                            # (after an intended change; review
                                            #  the differences with git diff)

Exit status is 0 when every case passes, 1 otherwise.
"""

import argparse
import csv
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
PROGRAM = os.path.join(os.path.dirname(HERE), "pdfgraph2csv.py")
MAX_REPORTED = 10  # differences listed per failing case


def load_cases():
    with open(os.path.join(HERE, "cases.json")) as f:
        return json.load(f)["cases"]


def run_program(case):
    """Run the program on the case's PDF; returns the CSV it wrote (to
    stdout, or with "output_file" to a file given with -o, which must only
    exist when there are data points)."""
    cmd = [sys.executable, PROGRAM, os.path.join(DATA, case["pdf"])] + case.get("args", [])
    if case.get("output_file"):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, case["output_file"])
            stdout = _run(case, cmd + ["-o", path])
            if stdout:
                raise AssertionError("output on stdout although -o was given")
            if not os.path.exists(path):
                return ""
            with open(path, newline="") as f:
                text = f.read()
            if not text:
                raise AssertionError("an empty output file was created")
            return text
    return _run(case, cmd)


def _run(case, cmd):
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    want = case.get("exit_code", 0)
    if proc.returncode != want:
        raise AssertionError("pdfgraph2csv.py exit status %d, expected %d:\n%s"
                             % (proc.returncode, want, proc.stderr))
    for text in case.get("stderr_contains", []):
        if text not in proc.stderr:
            raise AssertionError("message %r missing from stderr:\n%s" % (text, proc.stderr))
    return proc.stdout


def read_csv(text):
    return list(csv.DictReader(io.StringIO(text)))


def as_number(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def compare(actual_rows, expected_rows, columns, tol):
    """Return a list of human readable differences (empty = pass)."""
    diffs = []
    if actual_rows and expected_rows:
        missing = [c for c in columns if c not in actual_rows[0]]
        if missing:
            return ["output lacks column(s): %s" % ", ".join(missing)]
    if len(actual_rows) != len(expected_rows):
        diffs.append("row count: got %d, expected %d" % (len(actual_rows), len(expected_rows)))
    worst = {}
    for i, (a, e) in enumerate(zip(actual_rows, expected_rows), start=2):  # line numbers
        for c in columns:
            av, ev = a.get(c), e.get(c)
            an, en = as_number(av), as_number(ev)
            if an is not None and en is not None:
                d = abs(an - en)
                worst[c] = max(worst.get(c, 0.0), d)
                if d > tol:
                    diffs.append("line %d, %s: got %s, expected %s (diff %.3g > %g)" % (i, c, av, ev, d, tol))
            elif av != ev:
                diffs.append("line %d, %s: got %r, expected %r" % (i, c, av, ev))
    return diffs


class RegressionTests(unittest.TestCase):
    maxDiff = None


def make_test(case):
    def test(self):
        if case.get("expected") is None:
            out = run_program(case)
            if "expected_counts" in case:
                # big outputs: only the number of points per graph and symbol
                counts = {}
                for r in read_csv(out):
                    k = "%s %s" % (r["graph"], r["symbol"])
                    counts[k] = counts.get(k, 0) + 1
                self.assertEqual(counts, case["expected_counts"], case["name"])
                return
            # exit status and messages only; no points means no output at
            # all (not even the CSV header)
            self.assertEqual(out, "", "%s\noutput is not empty" % case["name"])
            return
        expected_path = os.path.join(DATA, case["expected"])
        self.assertTrue(os.path.exists(expected_path),
                        "missing expected file %s (run with --update)" % case["expected"])
        with open(expected_path, newline="") as f:
            expected = read_csv(f.read())
        actual = read_csv(run_program(case))
        columns = case.get("columns") or (list(expected[0].keys()) if expected else [])
        diffs = compare(actual, expected, columns, case.get("tolerance", 1e-6))
        if diffs:
            more = len(diffs) - MAX_REPORTED
            msg = "\n".join(diffs[:MAX_REPORTED])
            if more > 0:
                msg += "\n... and %d more difference(s)" % more
            self.fail("%s\n%s" % (case["name"], msg))
    test.__doc__ = case["name"]
    return test


def update_expected(cases, selected):
    for case in cases:
        if not selected(case):
            continue
        if case.get("expected") is None:
            continue
        if case.get("update", True) is False:
            print("kept      %s (hand-made reference)" % case["expected"])
            continue
        out = run_program(case)
        path = os.path.join(DATA, case["expected"])
        old = open(path).read() if os.path.exists(path) else None
        with open(path, "w", newline="") as f:
            f.write(out)
        state = "created  " if old is None else ("unchanged" if old == out else "UPDATED  ")
        print("%s %s (%d rows)" % (state, case["expected"], max(0, out.count("\n") - 1)))


def main():
    ap = argparse.ArgumentParser(description="pdfgraph2csv.py regression tests")
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("-k", metavar="TEXT", help="only run cases whose name contains TEXT")
    ap.add_argument("--update", action="store_true",
                    help="regenerate the expected CSV files from the current program")
    args = ap.parse_args()

    cases = load_cases()

    def selected(c):
        return not args.k or args.k.lower() in c["name"].lower()

    if args.update:
        update_expected(cases, selected)
        return 0

    suite = unittest.TestSuite()
    for n, case in enumerate(cases, 1):
        if selected(case):
            name = "test_%02d" % n
            setattr(RegressionTests, name, make_test(case))
            suite.addTest(RegressionTests(name))
    if suite.countTestCases() == 0:
        print("no cases selected")
        return 1
    result = unittest.TextTestRunner(verbosity=2 if args.verbose else 1).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())

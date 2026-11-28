"""The symbol filter chain as a list of named rules, with a trace.

Most of what decides whether a shape is reported as a data point is a
chain of small steps - find the marker shapes, put broken markers back
together, drop what is painted over, drop highlight boxes, specks, letters,
dashes of patterns, crowds outside the plot ... - each written for the PDF
that needed it (named in its docstring).  Run as a list of `Rule`s, each
step has a name, and the chain can say which step dropped or added which
shape:

  --debug                   one line per step that changed the symbols:
                            how many it dropped, added and changed (a
                            symbol kept with another shape, fill, place,
                            size, colour or legend frame)
  PDFPOINTS_TRACE=x,y[,r]   every symbol within r pt (default 3) of the
                            page point (x, y) that a step drops, adds or
                            changes,
                            with the step's name: "why is this point
                            missing?" (page coordinates are those written
                            by --internal)
  PDFPOINTS_RULE_STATS=FILE append "page<TAB>step<TAB>dropped<TAB>added<TAB>changed"
                            for every step of every page to FILE: summed
                            over the regression suite, the steps that never
                            change anything are those no test exercises

A rule is a function (symbols, ctx) -> symbols, where ctx carries what the
steps read (the page model, the interpreter's drawing, the graphs, the
page's text, ...).  The order of a list is the order the steps run in.
"""

import os
import re
import sys


class Rule:
    """One step of a filter chain: `run(symbols, ctx)` returns the symbols
    it keeps (and any it adds); `why` says what it does: the first sentence
    of `why` (given, or the function's docstring)."""

    __slots__ = ("name", "run", "why")

    def __init__(self, name, run, why=None):
        self.name = name
        self.run = run
        text = " ".join((why if why is not None else getattr(run, "__doc__", None) or "").split())
        # (the first sentence)
        m = re.search(r"(?<!\.)\.(?!\.)\s", text)
        self.why = text[:m.start() + 1] if m else text

    def __repr__(self):
        return "Rule(%r)" % self.name


class Context:
    """What the steps of a chain read: set as attributes by the caller
    (page, it, paths, graphs, texts, ...)."""

    def __init__(self, **kw):
        self.__dict__.update(kw)


_TRACE_RADIUS_PT = 3.0  # PDFPOINTS_TRACE's default radius


def _trace_point():
    spec = os.environ.get("PDFPOINTS_TRACE")
    if not spec:
        return None
    try:
        v = [float(x) for x in spec.split(",")]
        return (v[0], v[1], v[2] if len(v) > 2 else _TRACE_RADIUS_PT)
    except (ValueError, IndexError):
        print("warning: PDFPOINTS_TRACE should be x,y or x,y,r (page points)", file=sys.stderr)
        return None


class Tracer:
    """Watches a chain run (see the module's docstring)."""

    def __init__(self, page_no, debug=False):
        self.page_no = page_no
        self.debug = debug
        self.point = _trace_point()
        self.stats = os.environ.get("PDFPOINTS_RULE_STATS")
        self.active = bool(debug or self.point or self.stats)

    def note(self, rule, before, signatures, after):
        before_ids = {id(s): s for s in before}
        after_ids = {id(s): s for s in after}
        dropped = [s for k, s in before_ids.items() if k not in after_ids]
        added = [s for k, s in after_ids.items() if k not in before_ids]
        changed = [s for k, s in after_ids.items() if k in signatures and signature(s) != signatures[k]]
        if self.stats:
            with open(self.stats, "a") as f:
                f.write("%d\t%s\t%d\t%d\t%d\n"
                        % (self.page_no, rule.name, len(dropped), len(added), len(changed)))
        if self.debug and (dropped or added or changed):
            print("[debug] page %d rule %s: dropped %d, added %d, changed %d (%d symbols)"
                  % (self.page_no, rule.name, len(dropped), len(added), len(changed), len(after)),
                  file=sys.stderr)
        if self.point:
            x, y, r = self.point
            for what, group in (("dropped", dropped), ("added", added), ("changed", changed)):
                for s in group:
                    if abs(s.get("cx", 1e18) - x) <= r and abs(s.get("cy", 1e18) - y) <= r:
                        print("[trace] page %d rule %s %s %s at (%.3f, %.3f) size %.3g, drawing step %s"
                              % (self.page_no, rule.name, what, s.get("shape"), s["cx"], s["cy"],
                                 s.get("size", 0.0), s.get("idx")), file=sys.stderr)


def _note_drawing(self, step, before, after):
    """note() for a normaliser (normalise.py): the paths, raw texts and
    words it removed and added."""
    counts = []
    for b, a in zip(before, after):
        bi, ai = {id(x) for x in b}, {id(x) for x in a}
        counts.append((len(bi - ai), len(ai - bi)))
    (pd, pa), (td, ta), (wd, wa) = counts
    if self.stats:
        with open(self.stats, "a") as f:
            f.write("%d\tnormalise:%s\t%d\t%d\t%d\n" % (self.page_no, step.name, pd + td + wd, pa + ta + wa, 0))
    if self.debug and any(n for c in counts for n in c):
        print("[debug] page %d normaliser %s: paths -%d +%d, texts -%d +%d, words -%d +%d"
              % (self.page_no, step.name, pd, pa, td, ta, wd, wa), file=sys.stderr)


Tracer.note_drawing = _note_drawing


def signature(s):
    """What a step may change in a symbol it keeps."""
    return (s.get("shape"), s.get("filled"), s.get("cx"), s.get("cy"), s.get("size"),
            s.get("rgb"), "frame" in s)


def run_rules(rules, symbols, ctx, tracer=None):
    """Run the rules in order on `symbols`; returns the symbols kept."""
    if tracer is None or not tracer.active:
        for rule in rules:
            symbols = rule.run(symbols, ctx)
        return symbols
    for rule in rules:
        before = list(symbols)
        signatures = {id(s): signature(s) for s in before}
        symbols = rule.run(symbols, ctx)
        tracer.note(rule, before, signatures, symbols)
    return symbols


def describe(rules):
    """The rules of a chain, one line each: name and what it does."""
    return "\n".join("%-28s %s" % (r.name, r.why) for r in rules)

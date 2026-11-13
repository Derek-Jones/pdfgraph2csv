#!/usr/bin/env python3
"""Re-create the matplotlib test PDFs in tests/data (needs matplotlib).

The data points plotted here are the ground truth that the expected CSVs
mpl-*.csv contain, so these cases test true values, not just snapshots.
Only needed if the files are lost; the committed PDFs are the test inputs.
"""
import os
import matplotlib
matplotlib.use("pdf")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

# two panels side by side, linear axes left, log y axis right; uncompressed
plt.rcParams["pdf.compression"] = 0
fig, axs = plt.subplots(1, 2, figsize=(8, 3))
axs[0].plot([1, 2, 3, 3], [10, 20, 15, 15], "o", color="red")      # incl. a duplicate point
axs[0].plot([1.5, 2.5], [12, 18], "s", color="blue")
axs[1].scatter([0.5, 1.5], [100, 1000], marker="^", color="green")
axs[1].set_yscale("log")
axs[1].plot([1], [300], "+", ms=10, color="k")
fig.savefig(os.path.join(DATA, "mpl-two-panels-log.pdf"))
plt.close(fig)

# two pages, compressed streams, negative tick labels, a non-marker line
plt.rcParams["pdf.compression"] = 6
with PdfPages(os.path.join(DATA, "mpl-multipage-markers.pdf")) as pp:
    for k in range(2):
        fig, ax = plt.subplots(figsize=(5, 4))
        ax.plot([-5, 0, 5], [k, -1, 2], "o", mfc="none", color="purple")
        ax.plot([1, 2], [0.5, 0.5], "D", color="orange")
        ax.plot([-2], [1.5], "x", ms=8, color="k")
        ax.plot([-4, 4], [-1, 2], "-", color="gray")
        pp.savefig(fig)
        plt.close(fig)

# error bars (--errbars): asymmetric x and y errors, caps, a log y panel;
# the truth is written to mpl-errorbars.truth.csv
plt.rcParams["pdf.compression"] = 6
EB = [  # x, y, x-, x+, y-, y+ (linear panel); log panel uses y*10
    (1.0, 4.0, 0.2, 0.3, 0.5, 1.0),
    (2.0, 6.5, 0.0, 0.0, 1.5, 0.75),
    (3.0, 3.25, 0.4, 0.1, 0.25, 2.0),
    (4.0, 8.0, 0.25, 0.25, 0.0, 0.0),
    (5.0, 5.5, 0.15, 0.6, 1.25, 1.25),
    (5.0, 7.5, 0.0, 0.0, 0.5, 0.5),           # same x, bars stacked
]
fig, axs = plt.subplots(1, 2, figsize=(8, 3.5))
xs, ys = [r[0] for r in EB], [r[1] for r in EB]
axs[0].errorbar(xs, ys, xerr=[[r[2] for r in EB], [r[3] for r in EB]],
                yerr=[[r[4] for r in EB], [r[5] for r in EB]],
                fmt="o", color="navy", capsize=3)
axs[1].errorbar(xs, [10 * y for y in ys], yerr=[[10 * r[4] for r in EB], [10 * r[5] for r in EB]],
                fmt="s", color="darkred", capsize=2)
axs[1].set_yscale("log")
fig.savefig(os.path.join(DATA, "mpl-errorbars.pdf"))
plt.close(fig)
def _pair(v, minus, plus):
    """low, high cells: empty when there is no bar on either side."""
    return ("", "") if minus == plus == 0 else (repr(v - minus), repr(v + plus))


with open(os.path.join(DATA, "mpl-errorbars.truth.csv"), "w") as f:
    f.write("page,graph,x_coord,y_coord,x_low,x_high,y_low,y_high\n")
    for g, scale, xerr in ((1, 1, True), (2, 10, False)):
        for x, y, xm, xp, ym, yp in EB:
            xl, xh = _pair(x, xm, xp) if xerr else ("", "")
            yl, yh = _pair(scale * y, scale * ym, scale * yp)
            f.write(f"1,{g},{x!r},{scale * y!r},{xl},{xh},{yl},{yh}\n")
# shared axes: stacked panels with the x labels under the bottom one only,
# side-by-side panels with the y labels left of the first one only, and
# stacked panels whose top one has other (unlabelled) ticks: it must not
# take the bottom panel's scale
plt.rcParams["pdf.compression"] = 6
with PdfPages(os.path.join(DATA, "mpl-shared-axes.pdf")) as pp:
    fig, (a1, a2) = plt.subplots(2, 1, sharex=True, figsize=(4, 5))
    a1.plot([10, 20, 30], [1, 3, 2], "o", color="k")
    a2.plot([15, 25, 35], [100, 300, 200], "s", color="b")
    pp.savefig(fig)
    plt.close(fig)
    fig, (a1, a2) = plt.subplots(1, 2, sharey=True, figsize=(6, 3))
    a1.plot([1, 2, 3], [5, 15, 10], "o", color="k")
    a2.plot([100, 200, 300], [7, 12, 18], "s", color="b")
    pp.savefig(fig)
    plt.close(fig)
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(4, 5))
    a1.plot([0.1, 0.5, 0.9], [1, 3, 2], "o", color="k")
    a1.set_xlim(0, 1)
    a1.set_xticks([0, 0.25, 0.5, 0.75, 1.0])
    a1.set_xticklabels([])
    a2.plot([15, 25, 35], [100, 300, 200], "s", color="b")
    a2.set_xlim(10, 40)
    a2.set_xticks([10, 20, 30, 40])
    pp.savefig(fig)
    plt.close(fig)
# two scales: a right-hand y axis (twinx); which series uses it is told by
# the axis titles, by the legend ("(right axis)"), or by colour
plt.rcParams["pdf.compression"] = 6
with PdfPages(os.path.join(DATA, "mpl-twin-axes.pdf")) as pp:
    yrs = [2000, 2004, 2008, 2012, 2016]
    fig, ax = plt.subplots(figsize=(5, 3.5))
    ax2 = ax.twinx()
    ax.plot(yrs, [10, 30, 20, 50, 40], "o", color="tab:blue", label="Density")
    ax2.plot(yrs, [0.5, 0.4, 0.3, 0.2, 0.1], "s", color="tab:red", label="Pitch")
    ax2.plot(yrs, [0.45, 0.35, 0.25, 0.15, 0.12], "^", color="tab:green", label="Gate")
    ax.set_ylabel("Density (per mm)")
    ax2.set_ylabel("Pitch and Gate length (um)")
    fig.legend(loc="upper center")
    fig.tight_layout()
    pp.savefig(fig)
    plt.close(fig)
    fig, ax = plt.subplots(figsize=(5, 3.5))
    ax2 = ax.twinx()
    ax.plot([1, 2, 3, 4], [100, 300, 200, 400], "D", color="k", label="Cost (left axis)")
    ax2.plot([1, 2, 3, 4], [5, 7, 6, 8], "o", color="tab:orange", label="Speed (right axis)")
    ax.set_ylabel("value")
    ax2.set_ylabel("value")
    fig.legend(loc="upper center")
    fig.tight_layout()
    pp.savefig(fig)
    plt.close(fig)
    fig, ax = plt.subplots(figsize=(5, 3.5))
    ax2 = ax.twinx()
    ax.plot([0, 10, 20, 30], [1, 4, 2, 3], "o", color="tab:blue")
    ax2.plot([0, 10, 20, 30], [-50, 0, 50, 25], "s", color="tab:red")
    ax.tick_params(axis="y", colors="tab:blue")
    ax2.tick_params(axis="y", colors="tab:red")
    fig.tight_layout()
    pp.savefig(fig)
    plt.close(fig)
# no tick marks or axis lines: the grid on a grey background gives the tick
# positions (seaborn's darkgrid), or the white gaps between grey blocks
# tiling the plot area do
with PdfPages(os.path.join(DATA, "mpl-background-grid.pdf")) as pp:
    with plt.style.context("seaborn-v0_8-darkgrid"):
        fig, ax = plt.subplots(figsize=(4.5, 3.5))
        ax.plot([0.15, 0.25, 0.35, 0.45, 0.55], [0.1, 0.3, 0.5, 0.7, 0.9], "d", label="thin")
        ax.plot([0.12, 0.22, 0.32, 0.42, 0.52], [0.9, 0.6, 0.4, 0.2, 0.05], "o", label="round")
        ax.set_xlim(0.05, 0.65)
        ax.set_ylim(-0.05, 1.05)
        ax.legend(loc="center right")
        pp.savefig(fig)
        plt.close(fig)
    fig = plt.figure(figsize=(4.5, 3.5))
    ax = fig.add_axes([0.15, 0.15, 0.8, 0.8])
    ax.set_xlim(0, 5)
    ax.set_ylim(0, 40)
    ax.axis("off")
    from matplotlib.patches import Rectangle
    g = 0.04                               # half the gap, in data units (x)
    gy = g * 8                             # the same gap in y units
    for i in range(5):
        for j in range(4):
            ax.add_patch(Rectangle((i + (g if i else 0), 10 * j + (gy if j else 0)),
                                   1 - (g if i else 0) - (g if i < 4 else 0),
                                   10 - (gy if j else 0) - (gy if j < 3 else 0),
                                   facecolor="#e5e5e5", edgecolor="none"))
    for i in range(1, 5):
        ax.text(i, -1.5, str(i), ha="center", va="top", fontsize=9)
    for j in range(1, 4):
        ax.text(-0.08, 10 * j, str(10 * j), ha="right", va="center", fontsize=9)
    ax.plot([0.5, 1.5, 2.5, 3.5, 4.5], [5, 12, 18, 27, 35], "s", color="k", clip_on=False)
    pp.savefig(fig)
    plt.close(fig)
# axes crossing inside the plot, the tick labels in its body: spines through
# the origin (points in all four quadrants), and log axes crossing at 1 with
# a frame round the figure and grid lines at the ends of the y axis (as
# Excel draws them) - lines that are not axes
def crossing_axes():
    fig, axs = plt.subplots(1, 2, figsize=(8, 3.5))
    ax = axs[0]
    for side in ("left", "bottom"):
        ax.spines[side].set_position("zero")
    for side in ("right", "top"):
        ax.spines[side].set_visible(False)
    ax.set_xlim(-4, 4)
    ax.set_ylim(-3, 3)
    ax.set_xticks([-4, -2, 2, 4])
    ax.set_yticks([-3, -2, -1, 1, 2, 3])
    ax.plot([-3, -1, 1.5, 3, 2.5], [2, -2.5, 1, -1, 2.5], "o", color="tab:green")
    ax = axs[1]
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlim(0.1, 10)
    ax.set_ylim(0.1, 10)
    for side in ("left", "bottom"):
        ax.spines[side].set_position(("data", 1))
    for side in ("right", "top"):
        ax.spines[side].set_visible(False)
    ax.minorticks_off()
    ax.set_xticks([0.1, 1, 10], ["0.1", "1", "10"])
    ax.set_yticks([0.1, 1, 10], ["0.1", "1", "10"])
    ax.axhline(0.1, color="0.5", lw=0.6)
    ax.axhline(10, color="0.5", lw=0.6)
    ax.plot([0.5, 2, 4, 0.8, 1.5], [0.3, 3, 0.5, 2, 1.2], "o", color="k", ms=4)
    fig.patches.append(plt.Rectangle((0.01, 0.01), 0.98, 0.98, transform=fig.transFigure,
                                     fill=False, edgecolor="k", lw=0.8))
    fig.savefig(os.path.join(DATA, "mpl-crossing-axes.pdf"))
    plt.close(fig)


crossing_axes()
# no tick marks: the x labels alone mark their positions (Excel's category
# axis of a line chart: 1, 101, 201, ...), the y axis a log scale with only
# two grid lines (1 and 10); a box round the chart, with a line of body
# text centred above it that is no title
def label_ticks():
    fig = plt.figure(figsize=(6, 3.4))
    ax = fig.add_axes([0.12, 0.15, 0.82, 0.58])
    ax.set_yscale("log")
    ax.set_xlim(1, 1061)
    ax.set_ylim(1, 20)
    ax.minorticks_off()
    ax.set_xticks(range(1, 1062, 100))
    ax.set_yticks([1, 10], ["1", "10"])
    ax.tick_params(length=0)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.spines["left"].set_color("0.55")
    ax.spines["bottom"].set_color("0.55")
    ax.axhline(10, color="0.55", lw=0.8)
    ax.plot([1, 201, 401, 601, 801, 1001, 1061], [1, 1.2, 1.5, 2, 3, 7, 15], "s-", color="k",
            ms=3, lw=0.6)
    fig.patches.append(plt.Rectangle((0.02, 0.03), 0.96, 0.8, transform=fig.transFigure,
                                     fill=False, edgecolor="0.55", lw=0.8))
    fig.text(0.5, 0.9, "the plot clearly shows the difference between the compilers",
             ha="center", fontsize=10)
    fig.savefig(os.path.join(DATA, "mpl-label-ticks.pdf"))
    plt.close(fig)


label_ticks()
# no tick marks on any axis (ggplot2 with axis.ticks blank): the labels
# beside the axis lines mark their positions - 0.00 ... 1.00, and only
# 4, 8, 12 on a 1..15 axis; two facets in grey frames share the y labels of
# the left one; a line through dots no wider than it (model points)
def no_ticks():
    fig = plt.figure(figsize=(8, 2.8))
    axs = [fig.add_axes([0.08, 0.15, 0.25, 0.75]), fig.add_axes([0.35, 0.15, 0.25, 0.75]),
           fig.add_axes([0.72, 0.15, 0.25, 0.75])]
    for k, ax in enumerate(axs[:2]):
        ax.set_xlim(-0.05, 1.05)
        ax.set_ylim(-0.05, 1.05)
        ax.set_xticks([0, 0.25, 0.5, 0.75, 1.0], ["0.00", "0.25", "0.50", "0.75", "1.00"])
        ax.set_yticks([0, 0.25, 0.5, 0.75, 1.0], ["0.00", "0.25", "0.50", "0.75", "1.00"])
        ax.tick_params(length=0, labelleft=(k == 0))
        for sp in ax.spines.values():
            sp.set_color("0.5")
        xs = [0.1, 0.3, 0.5, 0.7, 0.9]
        for lab in ax.get_yticklabels():
            lab.set_verticalalignment("center")
        ax.plot(xs, [x * (0.9 + 0.2 * k) for x in xs], "o", color="blue" if k == 0 else "red")
    ax = axs[2]
    ax.set_xlim(0.3, 15.7)
    ax.set_ylim(0.1, 1.05)
    ax.set_xticks([4, 8, 12])
    ax.tick_params(length=0, labelleft=True)
    ax.set_yticks([0.25, 0.5, 0.75, 1.0], ["0.25", "0.50", "0.75", "1.00"])
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for lab in ax.get_yticklabels():
        lab.set_verticalalignment("center")
    n = list(range(1, 16))
    ax.plot(n, [0.2 + 0.7 * 0.8 ** (i - 1) for i in n], "-o", color="tab:orange", lw=1.5, ms=1.6)
    ax.plot([2, 5, 9, 14], [0.8, 0.55, 0.3, 0.25], "o", color="k", ms=4)
    fig.savefig(os.path.join(DATA, "mpl-no-ticks.pdf"))
    plt.close(fig)


no_ticks()
# text in a font with no map to Unicode: TrueType (Type 42) fonts, then the
# strings re-encoded as glyph numbers (CIDToGIDMap /Identity, as cairo
# writes them), /ToUnicode and the program's cmap table removed (only glyph
# names are left); one copy keeps the Type 0 font, one loses its /Subtype
# (so the strings must be read as byte pairs).  Both must read as the
# original: mpl-font-type42.pdf.
def _font_variants():
    import io
    import pikepdf
    from fontTools.ttLib import TTFont
    with plt.rc_context({"pdf.fonttype": 42}):
        fig, ax = plt.subplots(figsize=(4, 3))
        ax.bar([1, 2, 3, 4], [12000, 30000, 25000, 60000], color="#4878d0")
        ax.plot([1, 2, 3, 4], [10000, 20000, 15000, 40000], "o", color="k")
        base = os.path.join(DATA, "mpl-font-type42.pdf")
        fig.savefig(base)
        plt.close(fig)
    for name, keep_subtype in (("mpl-font-no-unicode.pdf", True),
                               ("mpl-font-no-subtype.pdf", False)):
        pdf = pikepdf.open(base)
        cid2gid = {}
        for obj in pdf.objects:
            if isinstance(obj, pikepdf.Dictionary) and obj.get("/Subtype") == "/CIDFontType2":
                raw = obj.CIDToGIDMap.read_bytes()
                cid2gid = {k // 2: (raw[k] << 8) | raw[k + 1] for k in range(0, len(raw) - 1, 2)}
                obj.CIDToGIDMap = pikepdf.Name("/Identity")
                widths, w, k = {}, obj.W, 0
                while k < len(w):
                    first, nxt = int(w[k]), w[k + 1]
                    if isinstance(nxt, pikepdf.Array):
                        for j, v in enumerate(nxt):
                            widths[first + j] = float(v)
                        k += 2
                    else:
                        for c in range(first, int(nxt) + 1):
                            widths[c] = float(w[k + 2])
                        k += 3
                arr = []
                for cid, wd in sorted(widths.items()):
                    if cid2gid.get(cid):
                        arr += [cid2gid[cid], pikepdf.Array([wd])]
                obj.W = pikepdf.Array(arr)
                ff = obj.FontDescriptor.FontFile2
                tt = TTFont(io.BytesIO(ff.read_bytes()))
                if "cmap" in tt:
                    del tt["cmap"]
                out = io.BytesIO()
                tt.save(out)
                ff.write(out.getvalue())
        for obj in pdf.objects:
            if isinstance(obj, pikepdf.Dictionary) and obj.get("/Subtype") == "/Type0":
                del obj["/ToUnicode"]
                if not keep_subtype:
                    del obj["/Subtype"]

        def conv(b):
            b = bytes(b)
            return pikepdf.String(b"".join(
                cid2gid.get((b[i] << 8) | b[i + 1], 0).to_bytes(2, "big")
                for i in range(0, len(b) - 1, 2)))
        for page in pdf.pages:
            new = []
            for operands, op in pikepdf.parse_content_stream(page):
                if str(op) == "Tj":
                    operands = [conv(operands[0])]
                elif str(op) == "TJ":
                    operands = [pikepdf.Array([conv(x) if isinstance(x, pikepdf.String) else x
                                               for x in operands[0]])]
                new.append((operands, op))
            page.Contents = pdf.make_stream(pikepdf.unparse_content_stream(new))
        pdf.save(os.path.join(DATA, name))


_font_variants()
print("written to", DATA)

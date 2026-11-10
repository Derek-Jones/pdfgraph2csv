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
print("written to", DATA)

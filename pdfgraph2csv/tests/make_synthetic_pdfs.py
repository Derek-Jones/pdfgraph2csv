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
print("written to", DATA)

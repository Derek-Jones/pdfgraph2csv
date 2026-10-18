# Packages that could replace hand-written code

## Packages now used

| Package | What it replaced |
|---|---|
| **pikepdf** (qpdf) | the PDF object parser, xref scanning and repair, stream filters (Flate, LZW, ASCII85, ASCIIHex, PNG predictors), the RC4 / AES-128 / AES-256 decryption, the content-stream tokenizer for content with inline images (`pdfobjects.py`, `filters.py`, `crypto.py`, most of `document.py`) |
| **pdfminer.six** | the operator handling, CTM and q/Q handling, text-state operators, resources, font loading, ToUnicode/CMap parsing, CID fonts, the standard-14 width tables |
| **fontTools** | the hand-made glyph-name table (`fontTools.agl.toUnicode` covers the whole Adobe Glyph List, `uniXXXX`, `uXXXXX` and ligature names such as `f_i`) |
| **python-dateutil** | the month-name table; it also adds date tick labels ("Mar 2010", "2010-03-15", "15 March 2010", Excel's "Jan-10") |

The package shrank from about 5,350 to 4,550 lines.  Nearly all of the
saving is in opening the file: about 830 lines became 120.  The interpreter
did not get shorter, because it still has to override many of
pdfminer.six's operators, but it no longer parses PDF syntax, fonts or
CMaps itself.

What was kept on purpose: pdfminer.six ignores clipping paths and fill
opacity, starts a Form XObject with a fresh graphics state, reduces colours
to its own colour-space objects and sends text to the device a whole string
at a time.  `interpreter.ContentInterpreter` therefore overrides the
painting, clipping, colour, ExtGState, text-showing and XObject operators.
The extraction heuristics depend on those details: drawing order, clipping
boxes, opacity, glyph-by-glyph positions and the inherited state of Form
XObjects.

## Further candidates

The parts below are still hand-written; these packages could take them over.

## Geometry, spatial search and grouping (geometry, grouping, occlusion, symbols, fragments, axes)

| Package | What it would replace |
|---|---|
| **NumPy** | Most loops over points: box computations, distances and least-squares fits (`numpy.linalg.lstsq` in `scales.fit_axis`). |
| **SciPy** | `scipy.spatial.cKDTree` replaces the ad-hoc spatial grids (cover index, cross-stroke matching, word grouping, stacked-marker counting). `scipy.sparse.csgraph.connected_components` replaces `DisjointSets`. `scipy.optimize.linear_sum_assignment` gives an optimal one-to-one tick↔label matching instead of the greedy "best pairs first" in `labels.assign_labels`. |
| **Shapely** | Polygons from flattened subpaths, point-in-polygon, areas, holes, rectangle tests and `STRtree` spatial indexes (`occlusion`, `symbols`, `fragments`). |
| **bezier** or **svgpathtools** | Bézier evaluation and flattening (`geometry.flatten_subpath`, `geometry.bezier_point`). |
| **scikit-image** | `skimage.measure.CircleModel` with `ransac` for the circle fits when rebuilding fragmented markers (`fragments.py`). |
| **scikit-learn** | `DBSCAN` for clustering circle centres and markers; `RANSACRegressor` / `HuberRegressor` for axis fits that ignore misread labels. That second use replaces the "drop the worst label and refit" loop in `fit_axis`. |
| **pwlf** or **ruptures** | Piecewise-linear fitting / change-point detection for broken axes (`scales.piecewise_axis`). |

## Reading text drawn as outlines (outlined_text, ≈450 lines)

| Package | What it would replace |
|---|---|
| **Tesseract** via **pytesseract** (or **EasyOCR**) | The 12×16 digit templates. Rasterise the word's outline (with PyMuPDF, or Pillow `ImageDraw.polygon`) and OCR it with a character whitelist such as `0123456789.-%`. It would also read the **letters** that the templates cannot, so category names (nominal-axis.pdf) and legend labels (grid-line-axes.pdf) would no longer be lost. This needs the Tesseract program installed. |
| **Pillow** / **matplotlib.path** | The hand-written polygon rasteriser (`_raster`). |

## Text and numbers (text, labels, colours)

| Package | What it would replace |
|---|---|
| **Babel** | Month names and number formats in other languages (`babel.dates`, `babel.numbers.parse_decimal`); python-dateutil (now used) knows English names only. |
| **webcolors** + **colour-science** (or **colormath**) | The CSS colour table and colour naming (`colours.py`). Perceptual colour distance (ΔE) would make matching marker colours to legend colours (`legend.SeriesNamer`) more reliable than the current per-channel threshold. |
| pdfminer.six layout analysis (`LAParams`) | Joining glyphs into words and lines (`text.merge_texts`, title line joining in `titles.py`). |

## Output, command line and tests

| Package | What it would replace |
|---|---|
| **pandas** | CSV writing and the per-graph bookkeeping. Returning a DataFrame from `extract()` would suit users who analyse the points in Python. |
| **pytest** + **pytest-regressions** | The shell runner `tests/run_tests.sh`. `dataframe_regression` compares CSV-like results with per-column tolerances, and `--force-regen` replaces `--update`. |
| **click** or **typer** | `argparse` in `cli.py` (a matter of taste; argparse is fine). |

## Suggested order

1. **NumPy + SciPy** for fitting, spatial search and grouping. This simplifies many loops without changing any heuristics.
2. **Tesseract OCR** for outlined text, which adds the ability to read words as well as digits.
3. **pytest-regressions** for the test suite.

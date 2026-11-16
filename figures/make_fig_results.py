#!/usr/bin/env python3
"""Figure 2: held-out results (accuracy by condition, what repair did, the main difference across analyses).

  python figures/make_fig_results.py        (needs matplotlib)

Numbers come from Tables 10, 12, 14 and 16 of the article and the released mechanism analysis (one repair round).
Writes fig_results_overview.pdf at the text width (392 pt) and a PNG preview.

Visual rules (dataviz skill): one accent on marks only, text in ink tokens, solid hairline grid, 2 px surface ring on
markers, gaps between cells, labels only on the few marks the text discusses.
"""
import math
import os

import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

HERE = os.path.dirname(os.path.abspath(__file__))
SURFACE = "#ffffff"
INK, INK2, MUTED = "#1b1b1a", "#5c5b57", "#93928c"
GRID = "#e8e7e3"
ACCENT = "#2a78d6"                       # reference palette slot 1
NEUTRAL = "#4a4945"                      # marks that are not the accent
SOFT, FAINT = "#c9c8c2", "#efeeea"
N = 125

mpl.rcParams.update({
    "font.family": "sans-serif", "font.sans-serif": ["Arial", "Helvetica"],
    "font.size": 6.5, "axes.labelsize": 6.2, "xtick.labelsize": 6.0, "ytick.labelsize": 6.5,
    "axes.edgecolor": GRID, "axes.linewidth": 0.6, "xtick.color": MUTED, "ytick.color": INK,
    "xtick.major.size": 0, "ytick.major.size": 0, "xtick.major.pad": 2.5, "axes.labelcolor": INK2,
    "pdf.fonttype": 42, "savefig.dpi": 300, "text.color": INK,
})

CONDS = [  # name, Qwen3-8B correct of 125, gpt-oss-20b correct or None (Table 10)
    ("Gene repair", 59, 81), ("Generic repair", 54, 81), ("Forced review", 54, None),
    ("Gene trigger, generic text", 54, None), ("Direct", 49, 80), ("Specification with contract", 48, 88),
    ("Spec. first + generic repair", 47, None), ("Specification first", 46, 69), ("Rules in prompt", 42, None),
    ("Advice prompt", 35, 69),
]
REPAIR = [("Generic repair", 37, 5), ("Gene trigger, generic text", 49, 5), ("Forced review", 76, 5), ("Gene repair", 49, 10)]
GROUPS = [  # group, rows: name, diff, lo, hi (Tables 14 and 16)
    ("Registered", [("Main analysis", 4.0, 0.8, 8.0), ("Original references", 4.8, 1.6, 8.8),
                    ("Full ComplexLP, ambiguous kept", 4.2, 1.9, 7.0), ("Well-specified subset", 4.2, 0.8, 8.4),
                    ("Tolerance 10$^{-6}$", 4.0, 0.8, 8.0), ("Tolerance 10$^{-2}$", 4.0, 0.0, 8.0),
                    ("One repair round", 4.0, 0.8, 8.0), ("Temperature 0.7, three repeats", 5.2, 2.0, 9.1),
                    ("Same 84 problems, temperature 0", 3.6, 0.0, 8.3)]),
    ("Post hoc", [("Without 8 adjudication-gap problems", 4.3, 0.9, 8.6), ("Viewed problems added", 3.9, 0.8, 7.7),
                  ("Full release, viewed added", 4.0, 1.8, 6.7)]),
    ("Expert check", [("Corrected for measurement error", 3.8, 0.8, 7.2)]),
    ("Second model", [("gpt-oss-20b", 0.0, 0.0, 0.0), ("gpt-oss-20b, complete case", 0.0, 0.0, 0.0)]),
]


def wilson(k, n, z=1.96):
    p = k / n; d = 1 + z * z / n; c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return 100 * (c - h), 100 * (c + h)


def bare(ax, grid_x=()):
    for s in ax.spines.values():
        s.set_visible(False)
    for x in grid_x:
        ax.axvline(x, color=GRID, lw=0.6, zorder=0)


def heading(fig, x, y, letter, text):
    fig.text(x, y, letter, fontsize=7.4, fontweight="bold", va="baseline", ha="left", color=INK)
    fig.text(x + 0.022, y, text, fontsize=7.0, va="baseline", ha="left", color=INK)


fig = plt.figure(figsize=(392 / 72, 5.6))

# (a) accuracy, dumbbell per condition
ax = fig.add_axes([0.255, 0.60, 0.255, 0.32])
ys = list(range(len(CONDS)))[::-1]
bare(ax, grid_x=[30, 40, 50, 60, 70])
for y, (name, q, g) in zip(ys, CONDS):
    gene = name == "Gene repair"
    qa = 100 * q / N
    lo, hi = wilson(q, N)
    ax.plot([lo, hi], [y, y], color=ACCENT if gene else SOFT, lw=1.6, solid_capstyle="round", zorder=1,
            alpha=0.4 if gene else 1)
    if g is not None:
        ga = 100 * g / N
        ax.plot(ga, y, "o", ms=4.8, mfc=SURFACE, mec=MUTED, mew=1.0, zorder=3)
    ax.plot(qa, y, "o", ms=5.6, color=ACCENT if gene else NEUTRAL, mec=SURFACE, mew=1.2, zorder=4)
    if name in ("Gene repair", "Direct"):
        ax.text(lo - 1.2, y, f"{qa:.1f}", ha="right", va="center", fontsize=5.8, color=INK)
ax.set_yticks(ys)
ax.set_yticklabels([c[0] for c in CONDS])
ax.set_xlim(20, 74)
ax.set_xticks([30, 40, 50, 60, 70])
ax.set_ylim(-0.7, len(CONDS) - 0.2)
ax.set_xlabel("Accuracy on 125 held-out problems (%)", labelpad=3)
ax.tick_params(axis="y", pad=4)
heading(fig, 0.02, 0.968, "a", "Accuracy by condition")
lx, ly = 0.025, 0.945
fig.lines.append(mpl.lines.Line2D([lx], [ly], marker="o", ms=4.6, color=NEUTRAL, mec=SURFACE, mew=1.0,
                                   transform=fig.transFigure))
fig.text(lx + 0.012, ly, "Qwen3-8B, with 95% interval", fontsize=5.7, color=INK2, va="center")
fig.lines.append(mpl.lines.Line2D([lx + 0.235], [ly], marker="o", ms=4.2, mfc=SURFACE, mec=MUTED, mew=1.0,
                                   transform=fig.transFigure))
fig.text(lx + 0.247, ly, "gpt-oss-20b", fontsize=5.7, color=INK2, va="center")

# (b) unit chart: the 76 wrong first programs, one cell each
ax = fig.add_axes([0.725, 0.665, 0.25, 0.255])
bare(ax)
cols, rows_per = 19, 4
cell, gap = 1.0, 0.26
block_h = rows_per * (cell + gap)
for k, (name, sent, fixed) in enumerate(REPAIR[::-1]):
    y0 = k * (block_h + 1.6)
    gene = name == "Gene repair"
    for idx in range(76):
        c, r = idx % cols, idx // cols
        color = NEUTRAL if idx < 5 else (ACCENT if idx < fixed else (SOFT if idx < sent else FAINT))
        ax.add_patch(FancyBboxPatch((c * (cell + gap), y0 + (rows_per - 1 - r) * (cell + gap)), cell, cell,
                                    boxstyle="round,pad=0,rounding_size=0.2", lw=0, fc=color))
    mid = y0 + block_h / 2 - gap / 2
    ax.text(-0.9, mid, name, ha="right", va="center", fontsize=6.5, color=INK)
    ax.text(cols * (cell + gap) + 0.4, mid, f"{fixed}/{sent}", ha="left", va="center", fontsize=6.0,
            color=INK if gene else INK2, fontweight="bold" if gene else "normal")
ax.set_xlim(0, cols * (cell + gap) + 3.6)
ax.set_ylim(-0.3, 4 * (block_h + 1.6) - 1.3)
ax.set_xticks([]); ax.set_yticks([])
heading(fig, 0.555, 0.968, "b", "Repair of the 76 wrong first programs")
fig.text(0.557, 0.945, "One cell per program; repaired / sent to repair at right", fontsize=5.7, color=INK2,
         va="center")
key = [(NEUTRAL, "repaired by every condition"), (ACCENT, "repaired by gene repair only"),
       (SOFT, "sent to repair, still wrong"), (FAINT, "not sent to repair")]
for i, (c, t) in enumerate(key):
    xx = 0.557 + (i % 2) * 0.215
    yy = 0.632 - (i // 2) * 0.022
    fig.patches.append(FancyBboxPatch((xx, yy - 0.0045), 0.0105, 0.009, boxstyle="round,pad=0,rounding_size=0.0015",
                                      transform=fig.transFigure, fc=c, lw=0, figure=fig))
    fig.text(xx + 0.016, yy, t, fontsize=5.7, color=INK2, va="center")
fig.text(0.557, 0.578, "Of the five gene-only repairs, four came from the tuple-key\n"
         "indexing rule and one from the logical-indicator rule.\nNo condition broke a correct program.",
         fontsize=5.7, color=INK2, va="top", linespacing=1.4)

# (c) the main difference across analyses, grouped
ax = fig.add_axes([0.35, 0.07, 0.55, 0.395])
bare(ax, grid_x=[-4, 0, 4, 8])
ax.axvspan(-5, 5, color=FAINT, lw=0, zorder=0)
ax.axvline(0, color=SOFT, lw=0.7, zorder=0.5)
y = 0.0
ticks, labels, faded_labels, group_marks = [], [], set(), []
for gname, rows in GROUPS[::-1]:
    for name, d, lo, hi in rows[::-1]:
        main = name == "Main analysis"
        faded = gname in ("Post hoc", "Second model")
        col = ACCENT if main else (MUTED if faded else NEUTRAL)
        if hi > lo:
            ax.plot([lo, hi], [y, y], color=col, lw=1.7 if main else 1.2, solid_capstyle="round", zorder=2)
        if gname == "Expert check":
            ax.plot(d, y, "D", ms=4.4, mfc=SURFACE, mec=NEUTRAL, mew=1.1, zorder=3)
            ax.text(hi + 0.35, y, "+3.8 [0.8, 7.2]", va="center", fontsize=5.9, color=INK2)
        else:
            ax.plot(d, y, "o", ms=6.0 if main else 4.8, color=col, mec=SURFACE, mew=1.2, zorder=3)
        if main:
            ax.text(hi + 0.35, y, "+4.0 [0.8, 8.0], p = 0.0625", va="center", fontsize=5.9, color=INK)
        ticks.append(y); labels.append(name)
        if faded:
            faded_labels.add(name)
        y += 1
    group_marks.append((gname, y - 1))
    y += 1.55
ax.set_yticks(ticks)
ax.set_yticklabels(labels)
for t, lab in zip(ax.get_yticklabels(), labels):
    if lab in faded_labels:
        t.set_color(INK2)
for gname, ytop in group_marks:
    ax.text(-0.59, ytop + 0.78, gname, transform=ax.get_yaxis_transform(), fontsize=6.1, fontweight="bold",
            color=INK, ha="left", va="bottom")
ax.set_xlim(-5.6, 13.6)
ax.set_xticks([-4, 0, 4, 8])
ax.set_xticklabels(["−4", "0", "+4", "+8"])
ax.set_ylim(-0.8, y - 0.2)
ax.text(-4.85, y - 0.75, "equivalence margin ±5", ha="left", va="bottom", fontsize=5.6, color=MUTED)
ax.set_xlabel("Gene repair minus generic repair (percentage points, 95% interval)", labelpad=3)
ax.tick_params(axis="y", pad=4)
heading(fig, 0.02, 0.51, "c", "The main difference across analyses")

for ext in ("pdf", "png"):
    fig.savefig(os.path.join(HERE, f"fig_results_overview.{ext}"), facecolor=SURFACE)
print("wrote", os.path.join(HERE, "fig_results_overview.pdf"))

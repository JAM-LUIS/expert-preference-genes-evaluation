#!/usr/bin/env python3
"""Forest plot of one comparison across sensitivity settings, as vector PDF and SVG (E20a; todo A1-28).

  .venv-tools/bin/python analysis/r1/forest.py --spec forest_spec.json --out forest   (writes forest.<LABEL>.svg/.pdf/.json)

Needs matplotlib (.venv-tools). The spec lists the rows to draw, each taken from a paired.py output:
  {"title": "C3L@2 vs C3E@2", "margin": null | 0.05,
   "rows": [{"setting": "main", "file": "paired.main.DEV.json", "a": "C3L@2", "b": "C3E@2",
             "model": "qwen3:8b", "scope": "pooled"[, "outcome": "correct"]}, ...]}
Every row must be found exactly once in its file and all files must carry the same data label; the label is
printed in the title and in the file names. x = A - B in accuracy points with the bootstrap CI; a dashed line at 0
and, when a margin is given, dotted lines at +-margin (the TOST bounds). The drawing is deterministic (fixed SVG
hash salt, no dates in the metadata), so the same inputs give byte-identical files.
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from common import AnalysisError, dumps, rel, write_text  # noqa: E402

SCHEMA = "orgene.r1.forest.v1"


def collect(spec, base_dir=None):
    rows, labels = [], set()
    cache = {}
    for i, s in enumerate(spec.get("rows") or []):
        path = s["file"] if os.path.isabs(s["file"]) else os.path.join(base_dir or os.getcwd(), s["file"])
        doc = cache.setdefault(path, json.load(open(path, encoding="utf-8")))
        labels.add(doc["data"])
        hits = [r for r in doc["results"] if r["a"] == s["a"] and r["b"] == s["b"] and r["model"] == s["model"]
                and r["scope"] == s["scope"] and r.get("outcome", "correct") == s.get("outcome", r.get("outcome", "correct"))]
        if len(hits) != 1:
            raise AnalysisError(f"row {i} ({s['setting']}): {len(hits)} matching results in {os.path.basename(path)}")
        h = hits[0]
        rows.append({"setting": s["setting"], "effect": h["diff"], "lo": h["ci"][0], "hi": h["ci"][1], "n": h["n"],
                     "source": os.path.basename(path)})
    if not rows:
        raise AnalysisError("the spec lists no rows")
    if len(labels) != 1:
        raise AnalysisError(f"rows from several data labels {sorted(labels)}")
    return rows, labels.pop()


def draw(rows, label, title, out_stem, margin=None):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    matplotlib.rcParams["svg.hashsalt"] = "orgene-r1-forest"
    matplotlib.rcParams["svg.fonttype"] = "none"
    matplotlib.rcParams["pdf.fonttype"] = 42
    n = len(rows)
    fig, ax = plt.subplots(figsize=(6.4, 0.45 * n + 1.4))
    ys = list(range(n, 0, -1))
    for y, r in zip(ys, rows):
        ax.plot([100 * r["lo"], 100 * r["hi"]], [y, y], color="black", linewidth=1.2)
        ax.plot([100 * r["effect"]], [y], marker="s", color="black", markersize=5)
    ax.axvline(0.0, color="grey", linestyle="--", linewidth=0.8)
    if margin:
        for x in (-100 * margin, 100 * margin):
            ax.axvline(x, color="grey", linestyle=":", linewidth=0.8)
    ax.set_ylim(0.4, n + 0.6)
    ax.set_yticks(ys)
    ax.set_yticklabels([f"{r['setting']} (n={r['n']})" for r in rows])
    ax.set_xlabel("difference A − B (accuracy points), bootstrap 95% CI")
    ax.set_title(f"[{label}] {title}", fontsize=10)
    fig.tight_layout()
    svg, pdf = f"{out_stem}.{label}.svg", f"{out_stem}.{label}.pdf"
    os.makedirs(os.path.dirname(os.path.abspath(svg)), exist_ok=True)
    fig.savefig(svg, format="svg", metadata={"Date": None, "Creator": None})
    fig.savefig(pdf, format="pdf", metadata={"CreationDate": None, "ModDate": None, "Creator": None, "Producer": None})
    plt.close(fig)
    return svg, pdf


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--spec", required=True)
    ap.add_argument("--out", required=True, help="output stem; .<LABEL>.svg/.pdf/.json are appended")
    a = ap.parse_args(argv)
    try:
        spec = json.load(open(a.spec, encoding="utf-8"))
        rows, label = collect(spec, os.path.dirname(os.path.abspath(a.spec)))
    except AnalysisError as x:
        print(f"[forest] REFUSED: {x}", file=sys.stderr)
        return 2
    svg, pdf = draw(rows, label, spec.get("title", ""), a.out, spec.get("margin"))
    write_text(f"{a.out}.{label}.json", dumps({"schema": SCHEMA, "data": label, "generated_by": "analysis/r1/forest.py",
                                               "title": spec.get("title"), "margin": spec.get("margin"), "rows": rows}))
    print(f"[forest] {label}: {len(rows)} rows -> {rel(svg)}, {rel(pdf)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

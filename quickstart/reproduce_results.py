#!/usr/bin/env python3
"""Recompute the headline results of the article from the released raw outputs.

    python quickstart/reproduce_results.py

Standard library only. Reads the scored result files inside the two test archives
(outputs/test-main-20261006/*.tar.gz), takes the main analysis set from the frozen
definitions, recomputes accuracies, paired wins and losses and the exact McNemar
p-value, and compares them with the values printed in the article and with the
released analysis files. Exits with status 1 on any difference.
"""
import json
import math
import os
import sys
import tarfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.dont_write_bytecode = True
sys.path.insert(0, os.path.join(ROOT, "frozen_tree", "runtime"))
from orgene import analysis_sets  # noqa: E402  (frozen code of the evaluation)

RUN = os.path.join(ROOT, "outputs", "test-main-20261006")
STAGES = ("mamo-test", "industryor-test")
MODEL = "qwen3-8b.main"
NAMES = {"C0": "Direct generation", "C3E": "Generic repair", "C3L": "Gene repair"}
# Values printed in the article (abstract and Section 6).
ARTICLE = {"n": 125, "acc": {"C3L": 47.2, "C3E": 43.2, "C0": 39.2},
           "C3L_vs_C3E": {"wins": 5, "losses": 0, "p": 0.0625},
           "C3L_vs_C0": {"wins": 10, "losses": 0}}


def main_set():
    return set(analysis_sets.analysis_set("main", root=os.path.join(ROOT, "frozen_tree"), strict=True)["ids"])


def read_results(cond):
    rows = {}
    for stage in STAGES:
        with tarfile.open(os.path.join(RUN, stage + ".tar.gz")) as tf:
            f = tf.extractfile(f"{stage}/by-model/{MODEL}/results.{cond}.jsonl")
            for line in f.read().decode("utf-8").splitlines():
                if line.strip():
                    r = json.loads(line)
                    rows[r["case_id"]] = bool(r["correct"])
    return rows


def mcnemar_exact(wins, losses):
    n, k = wins + losses, min(wins, losses)
    if n == 0:
        return 1.0
    return min(1.0, 2 * sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n)


def main():
    ids = main_set()
    res = {c: read_results(c) for c in NAMES}
    bad = []

    def check(label, got, want):
        ok = abs(got - want) < 5e-4 if isinstance(want, float) else got == want
        if not ok:
            bad.append(label)
        return "ok" if ok else "DIFFERENT"

    print(f"Main analysis set: {len(ids)} held-out problems   [{check('n', len(ids), ARTICLE['n'])}]")
    print()
    print(f"{'Condition':<20}{'correct':>9}{'accuracy':>10}{'article':>9}")
    for c in ("C3L", "C3E", "C0"):
        k = sum(res[c][i] for i in ids)
        acc = round(100 * k / len(ids), 1)
        print(f"{NAMES[c]:<20}{k:>5}/{len(ids):<3}{acc:>9.1f}%{ARTICLE['acc'][c]:>8.1f}%   [{check('acc ' + c, acc, ARTICLE['acc'][c])}]")
    print()
    for a, b in (("C3L", "C3E"), ("C3L", "C0")):
        wins = sum(res[a][i] and not res[b][i] for i in ids)
        losses = sum(res[b][i] and not res[a][i] for i in ids)
        p = mcnemar_exact(wins, losses)
        art = ARTICLE[f"{a}_vs_{b}"]
        marks = [check(f"{a} vs {b} wins", wins, art["wins"]), check(f"{a} vs {b} losses", losses, art["losses"])]
        if "p" in art:
            marks.append(check(f"{a} vs {b} p", round(p, 4), art["p"]))
        rel = json.load(open(os.path.join(ROOT, "analysis", f"paired.{a}@2_vs_{b}@2.TEST.json" if b != "C0" else f"paired.{a}@2_vs_{b}.TEST.json")))
        r = max(rel["results"], key=lambda row: row["n"])  # the pooled row; the others are per benchmark
        marks.append(check(f"{a} vs {b} released analysis", (len(ids), wins, losses), (r["n"], r["wins"], r["losses"])))
        print(f"{NAMES[a]} vs {NAMES[b].lower()}: {wins} gained, {losses} lost, "
              f"difference {100 * (wins - losses) / len(ids):+.1f} points, exact McNemar p = {p:.4f}"
              f"{'' if 'p' in art else ' before the Holm adjustment of the article'}   [{', '.join(marks)}]")
    print()
    if bad:
        print("DIFFERENCES: " + "; ".join(bad))
        return 1
    print("All values match the article and the released analysis files.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Recompute the numbers quoted in UNSAID.md from the released raw outputs.

    python quickstart/beyond_the_paper.py

Standard library only. Everything here is read from the held-out test
(outputs/test-main-20261006/) on the main analysis set of 125 problems. The
article reports some of these numbers and not others; the comparisons marked
"post hoc" were not registered before the test and are not adjusted for
multiple testing. They are descriptions of this one run.
"""
import collections
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
SMALL, LARGE = "qwen3-8b.main", "gptoss-20b.main.server_refused"  # the larger model: refused units count as wrong
NAMES = {"C0": "Direct generation", "C1": "Advice prompt", "C2": "Specification first",
         "C3": "Specification with contract", "C3E": "Generic repair", "C3L": "Gene repair",
         "C3T": "Gene trigger, generic text", "C3A": "Forced review", "C2E": "Spec. first + generic repair",
         "C0R-E": "Rules in prompt + generic repair"}
# Rules that only say "the program did not run" or "it did not report a status"; generic repair uses them too.
RUN_RULES = {"orgene.execution.runs", "orgene.solution.status_optimal_or_justified", "orgene.artifact.code_present",
             "orgene.boundary.solve_before_report", "orgene.boundary.status_reported"}


def read(tars, model, name, ids):
    rows = {}
    for stage, tf in tars.items():
        try:
            f = tf.extractfile(f"{stage}/by-model/{model}/{name}")
        except KeyError:
            continue
        for line in f.read().decode("utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                if r["case_id"] in ids:
                    rows[r["case_id"]] = r
    return rows


def mcnemar(a, b, ids):
    """(problems only a solves, problems only b solves, exact two-sided p)."""
    w = sum(a[i] and not b[i] for i in ids)
    l = sum(b[i] and not a[i] for i in ids)
    n, k = w + l, min(w, l)
    p = 1.0 if n == 0 else min(1.0, 2 * sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n)
    return w, l, p


def main():
    ids = sorted(analysis_sets.analysis_set("main", root=os.path.join(ROOT, "frozen_tree"), strict=True)["ids"])
    n = len(ids)
    tars = {s: tarfile.open(os.path.join(RUN, s + ".tar.gz")) for s in STAGES}
    res = {c: read(tars, SMALL, f"results.{c}.jsonl", ids) for c in NAMES}
    ok = {c: {i: bool(res[c][i]["correct"]) for i in ids} for c in NAMES}
    big_res = {c: read(tars, LARGE, f"results.{c}.jsonl", ids) for c in ("C0", "C1", "C2", "C3", "C3E", "C3L")}
    big = {c: {i: bool(big_res[c].get(i, {}).get("correct")) for i in ids} for c in big_res}
    first = read(tars, SMALL, "validated.C3L.round0.jsonl", ids)  # the checks on the first program
    pct = lambda k: f"{100 * k / n:.1f}%"  # noqa: E731
    cmp = lambda a, b: "{} gained, {} lost, exact p = {:.3f}".format(*mcnemar(a, b, ids))  # noqa: E731

    print(f"Main analysis set: {n} held-out problems. Small model: Qwen3-8B. Large model: gpt-oss-20b.\n")

    wrong = [i for i in ids if not ok["C0"][i]]
    ran = [i for i in wrong if res["C0"][i].get("exec_ok")]
    optimal = [i for i in wrong if res["C0"][i].get("status") == "Optimal"]
    print("1. 'Optimal' is not 'correct'")
    print(f"   wrong first programs: {len(wrong)}; ran without error: {len(ran)}; printed STATUS: Optimal: {len(optimal)}\n")

    flagged = [i for i in ids if first[i]["hard_failed_genes"]]
    beyond = [i for i in flagged if set(first[i]["hard_failed_genes"]) - RUN_RULES]
    silent = [i for i in beyond if res["C0"][i].get("exec_ok")]
    print("2. The rules as a detector, on the first program")
    print(f"   flagged: {len(flagged)}; of them wrong: {sum(not ok['C0'][i] for i in flagged)}; "
          f"correct programs flagged: {sum(ok['C0'][i] for i in flagged)} of {n - len(wrong)}")
    print(f"   wrong programs no rule flagged: {sum(1 for i in wrong if i not in flagged)}")
    print(f"   flagged by a modeling or code rule: {len(beyond)}, all wrong: {all(not ok['C0'][i] for i in beyond)}; "
          f"of them ran without error: {len(silent)}; of those solved after gene repair: {sum(ok['C3L'][i] for i in silent)}")
    fired, solved, checked = collections.Counter(), collections.Counter(), collections.Counter()
    warned = collections.Counter(g for v in first.values() for g in v["soft_failed_genes"])
    for i in ids:
        for issue in first[i]["issues"]:
            checked[issue["geneId"]] += issue.get("ok") is not None
        for g in first[i]["hard_failed_genes"]:
            fired[g] += 1
            solved[g] += ok["C3L"][i]
    print(f"   {'rule':<42}{'checked':>8}{'fired':>7}{'solved after repair':>21}")
    for g in sorted(checked, key=lambda g: (-fired[g], g)):
        note = f"   (warned {warned[g]} times)" if warned[g] else ""
        print(f"   {g.replace('orgene.', ''):<42}{checked[g]:>8}{fired[g]:>7}{solved[g]:>21}{note}")
    print()

    print("3. Telling the model beforehand, against checking afterwards (small model)")
    for c in ("C0", "C1", "C0R-E", "C3E", "C3L"):
        print(f"   {NAMES[c]:<34}{pct(sum(ok[c].values())):>7}")
    print(f"   advice prompt vs direct generation (post hoc): {cmp(ok['C1'], ok['C0'])}")
    print(f"   rules in prompt + generic repair vs generic repair alone (post hoc): {cmp(ok['C0R-E'], ok['C3E'])}")
    print(f"   gene repair vs rules in prompt + generic repair: {cmp(ok['C3L'], ok['C0R-E'])}")
    print(f"   large model, advice prompt vs direct generation (post hoc): {cmp(big['C1'], big['C0'])}\n")

    rounds = collections.Counter(res["C3L"][i].get("repair_rounds_used") for i in ids if ok["C3L"][i] and not ok["C0"][i])
    print("4. When the repairs landed")
    print(f"   programs gene repair fixed, by number of repair rounds used: {dict(sorted(rounds.items()))}\n")

    print("5. The larger model")
    for c in big:
        print(f"   {NAMES[c]:<34}{pct(sum(big[c].values())):>7}")
    print(f"   large model direct vs small model with gene repair (post hoc): {cmp(big['C0'], ok['C3L'])}")
    print(f"   large model, specification with contract vs direct (post hoc): {cmp(big['C3'], big['C0'])}\n")

    tok = {c: sum((res[c][i].get("in_tokens") or 0) + (res[c][i].get("out_tokens") or 0) for i in ids) / n for c in NAMES}
    print("6. What it costs (small model, mean tokens per problem, input + output)")
    for c in ("C0", "C3E", "C3L"):
        print(f"   {NAMES[c]:<34}{tok[c]:>7.0f}   {tok[c] / tok['C0']:.1f}x direct generation")
    print()

    wall = [i for i in ids if not any(ok[c][i] for c in ok) and not any(big[c][i] for c in big)]
    print(f"7. The wall: {len(wall)} problems that no condition of either model solved")
    print("   " + ", ".join(wall))


if __name__ == "__main__":
    main()

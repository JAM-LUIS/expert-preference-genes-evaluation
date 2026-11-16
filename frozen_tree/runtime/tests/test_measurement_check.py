"""Measurement check (analysis/r1/measurement_check.py, E20b) on toy data: program identity, display normalization,
allocation and selection, the bounds and rates of the plan's worked examples (prereg/MEASUREMENT_CHECK_PLAN.md 9.4),
and the analysis on a toy key. Toy ids and self-made programs only."""
import ast
import os
import random
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "runtime"))
sys.path.insert(0, os.path.join(ROOT, "analysis", "r1"))

import measurement_check as MC  # noqa: E402

PROG = '''"""Module docstring naming C3L."""
import pulp  # solver

def build(n):
    """Build the model."""
    prob = pulp.LpProblem("C3L_round2_model", pulp.LpMinimize)   # name with run metadata
    x = pulp.LpVariable("x", lowBound=0)


    prob += 3 * x
    prob += x >= n, "demand"
    return prob

def helper():
    """Only a docstring."""

print("objective", pulp.value(build(4).objective))
'''


def test_identity_ignores_comments_docstrings_and_layout():
    k, how = MC.program_identity(PROG)
    assert how == "tokens"
    relaid = PROG.replace("# solver", "").replace("\n\n\n", "\n").replace('"""Build the model."""', "")
    assert MC.program_identity(relaid)[0] == k
    assert MC.program_identity(PROG.replace("3 * x", "4 * x"))[0] != k
    assert MC.program_identity(None) == (MC.NO_PROGRAM, "none")
    assert MC.program_identity("def f(:\n  (")[1] == "fallback"


def test_display_removes_comments_and_docstrings_masks_metadata_and_keeps_the_ast():
    text, flags = MC.display_program(PROG)
    assert flags == []
    assert "#" not in text and "docstring" not in text and "Build the model" not in text
    assert "C3L" not in text and MC.MASK in text and '"demand"' in text and '"x"' in text
    assert "def helper():\n    pass" in text and "\n\n\n" not in text
    assert MC.canon_dump(text) == MC.canon_dump(PROG)
    # a program that does not parse only loses its comments
    bad, fl = MC.display_program("x = (1,  # open\ny = 2\n")
    assert fl == ["unparsable"] and "# open" not in bad


def test_allocation_largest_remainder_and_census():
    assert MC.allocate([("a", 10), ("b", 0), ("c", 5), ("d", 1)], 6) == {"a": 3, "c": 2, "d": 1}
    assert MC.allocate([("a", 3), ("b", 2)], 10) == {"a": 3, "b": 2}
    al = MC.allocate([(k, n) for k, n in zip("abcdef", (20, 7, 11, 3, 15, 10))], 24)
    assert sum(al.values()) == 24 and all(v >= 1 for v in al.values())
    ids = [f"toy-{i:04d}" for i in range(30)]
    assert MC.select(ids, 5) == MC.select(list(reversed(ids)), 5) == sorted(ids, key=lambda c: MC.h(f"20261008:{c}"))[:5]


def _frame(n=60, seed=3):
    rng = random.Random(seed)
    fr = {}
    for i in range(n):
        c = f"toy-{i:04d}"
        same = rng.random() < 0.6
        S = {"C0": rng.random() < 0.5, "C3E": rng.random() < 0.6, "C3L": rng.random() < 0.65}
        if same:
            S["C3E"] = S["C3L"]
        fr[c] = {"benchmark": MC.BENCH_ORDER[i % 2], "S": S, "X": {k: True for k in S},
                 "id": {"C0": f"p0-{i}", "C3E": f"p0-{i}" if same else f"pe-{i}", "C3L": f"p0-{i}" if same else f"pl-{i}"}}
    return fr


def test_draw_sample_two_parts_weights_and_codes():
    fr = _frame()
    s = MC.draw_sample(fr)
    nd = sum(1 for v in fr.values() if v["id"]["C3L"] != v["id"]["C3E"])
    assert s["N_D"] == nd and s["census_D"] == (nd <= 24)
    p1 = [r for r in s["selected"] if r["part"] == 1]
    p2 = [r for r in s["selected"] if r["part"] == 2]
    assert len(p1) == min(24, nd) and len(p2) == 10
    for st in s["strata"]:
        if st["n_h"]:
            assert st["weight"] == pytest.approx(st["N_h"] / st["n_h"])
    assert [r["problem_id"] for r in s["selected"]] == [f"P{i:02d}" for i in range(1, len(s["selected"]) + 1)]
    assert MC.draw_sample(fr)["digest"] == s["digest"]
    small = {c: v for c, v in list(fr.items())[:30]}
    assert MC.draw_sample(small)["census_D"]


def test_hypergeometric_limits_of_the_worked_examples():
    assert MC.k_upper(1, 66, 22) == 13 and MC.k_upper(2, 66, 22) == 17          # (a)
    assert MC.k_upper(1, 66, 30) == 9 and MC.k_upper(3, 66, 30) == 14           # (b)
    assert MC.k_upper(1, 66, 24) == 11 and MC.k_upper(2, 66, 24) == 15          # (c)
    assert MC.k_upper(0, 66, 24) == 7
    assert MC.hyper_cdf(1, 66, 11, 24) == pytest.approx(0.0369, abs=5e-4)


def test_bounds_sample_and_census_examples():
    judged = [(2.75, -1), (2.75, 1), (2.75, 1)] + [(2.75, 0)] * 21                # (c)
    b = MC.sample_bounds(0.08, 150, 66, judged)
    assert (b["K_minus"], b["K_plus"]) == (11, 15)
    assert 100 * b["point"] == pytest.approx(9.83, abs=0.01)
    assert round(100 * b["L"], 1) == 0.7 and round(100 * b["U"], 1) == 18.0
    c = MC.census_bounds(0.08, 150, [(1, 1, 1), (1, 1, 1), (-1, -1, -1), (None, -1, 0)] + [(0, 0, 0)] * 18)  # (d)
    assert round(100 * c["point"], 1) == 8.7 and round(100 * c["L"], 1) == 8.0 and round(100 * c["U"], 1) == 8.7


def test_weighted_false_positive_rate_example():
    pytest.importorskip("scipy")
    units = [(2.75, True)] + [(2.75, False)] * 12 + [(8.4, False)] * 6
    r = MC.weighted_rate(units)
    assert round(100 * r["rate"], 1) == 3.2 and round(r["n_eff"], 1) == 14.2
    assert round(100 * r["ci"][0], 1) == 0.0 and round(100 * r["ci"][1], 0) == 28


def test_kappa():
    pairs = [("correct", "correct")] * 6 + [("incorrect", "incorrect")] * 3 + [("correct", "incorrect")]
    assert MC.cohen_kappa(pairs, MC.JUDGMENTS) == pytest.approx((0.9 - (0.7 * 0.6 + 0.3 * 0.4)) / (1 - 0.54))


def _toy_key():
    probs = []
    # P01 in D: C3L counted correct but judged wrong (d = -1); P02 in D: C3E counted correct, judged wrong (d = +1)
    # P03 outside D: one program for all, counted and judged correct
    spec = [("P01", True, {"C0": ("A", False), "C3E": ("A", False), "C3L": ("B", True)}),
            ("P02", True, {"C0": ("A", True), "C3E": ("A", True), "C3L": ("B", False)}),
            ("P03", False, {"C0": ("A", True), "C3E": ("A", True), "C3L": ("A", True)})]
    for pid, inD, cm in spec:
        progs = sorted({v[0] for v in cm.values()})
        probs.append({"problem_id": pid, "case_id": f"toy-{pid}", "benchmark": "industryor", "part": 1 if inD else 2,
                      "stratum": "s1" if inD else "s2", "weight": 1.0 if inD else 5.0, "in_D": inD,
                      "programs": [{"program_id": f"{pid}-{x}", "conditions": [c for c in cm if cm[c][0] == x]}
                                   for x in progs],
                      "conditions": {c: {"program_id": f"{pid}-{cm[c][0]}", "S": cm[c][1], "X": True} for c in cm}})
    return {"data": "DEV", "N": 20, "N_D": 2, "census_D": True, "strata": [], "problems": probs,
            "accuracy": {"C0": 0.5, "C3E": 0.55, "C3L": 0.6}, "delta_C3L_C3E": 0.05, "delta_C3L_C0": 0.1,
            "delta_C3E_C0": 0.05}


def _j(overall, cat=None):
    return {"variables": "correct", "objective": "correct", "constraints": "correct" if overall == "correct" else
            "incorrect", "data_use": "correct", "overall": overall, "error_category": cat, "notes": ""}


def test_analyze_toy_key_census():
    pytest.importorskip("scipy")
    key = _toy_key()
    j = {"P01-A": _j("incorrect", "other"), "P01-B": _j("incorrect", "missing_constraint"),
         "P02-A": _j("incorrect", "big_m"), "P02-B": _j("incorrect", "other"), "P03-A": _j("correct")}
    j2 = dict(j, **{"P02-A": _j("correct")})
    dis = MC.disagreements(j, j2)
    assert dis == [("P02-A", "overall_differs")]
    doc = MC.analyze(key, j, j2, {"P02-A": ("incorrect", "big_m")}, n_boot=200)
    m = doc["main_effect_bounds"]
    assert m["design"] == "census" and m["n_NA"] == 0
    assert m["point"] == pytest.approx(0.05 + (-1 + 1) / 20) and m["L"] == m["U"] == m["point"]
    fp = doc["rates"]["by_condition"]["C3L"]["weighted"]["FP"]
    assert fp["rate"] == pytest.approx(1 / (1 + 5))                 # P01 (w 1) false positive, P03 (w 5) right
    assert doc["resolution"]["listed"] == 1 and doc["resolution"]["NA"] == 0
    # an unresolved C3L program in D widens the census bounds
    doc = MC.analyze(key, j, j2, {"P02-A": ("unresolved", None)}, n_boot=50)
    assert doc["resolution"]["NA"] == 1
    m = doc["main_effect_bounds"]
    assert m["n_NA"] == 1 and m["L"] < m["U"]

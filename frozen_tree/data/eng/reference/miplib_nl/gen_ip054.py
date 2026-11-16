"""gen-ip054: translation of the instance's solve.py (non-negative integer quantities; resource upper limits and
performance lower targets from headerless CSV files)."""
import csv
import os

import pulp


def _rows(path):
    with open(path, encoding="utf-8", newline="") as f:
        return [r for r in csv.reader(f) if r]


def build(instance_dir):
    d = os.path.join(instance_dir, "data")
    obj = {}
    names = []
    for r in _rows(os.path.join(d, "C1.csv")):
        obj[r[0]] = float(r[1])
        names.append(r[0])
    res_limits = [(r[0], float(r[1])) for r in _rows(os.path.join(d, "C3.csv"))]
    res_matrix = {r[0]: [float(x) for x in r[1:]] for r in _rows(os.path.join(d, "C2.csv"))}
    perf_targets = [(r[0], float(r[1])) for r in _rows(os.path.join(d, "C5.csv"))]
    perf_matrix = {r[0]: [float(x) for x in r[1:]] for r in _rows(os.path.join(d, "C4.csv"))}
    prob = pulp.LpProblem("gen_ip054", pulp.LpMinimize)
    v = {n: pulp.LpVariable(n, lowBound=0, cat=pulp.LpInteger) for n in names}
    prob += pulp.lpSum(obj[n] * v[n] for n in names)
    for j, (rid, lim) in enumerate(res_limits):
        prob += pulp.lpSum(res_matrix[n][j] * v[n] for n in names) <= lim, f"Resource_{rid}"
    for k, (pid, tgt) in enumerate(perf_targets):
        prob += pulp.lpSum(perf_matrix[n][k] * v[n] for n in names) >= tgt, f"Performance_{pid}"
    return prob

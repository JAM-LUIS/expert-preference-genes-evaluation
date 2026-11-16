"""neos-5140963-mincio: translation of the instance's solve.py (asymmetric TSP with MTZ subtour elimination)."""
import csv
import os

import pulp

from . import read_rows


def build(instance_dir):
    d = os.path.join(instance_dir, "data")
    nodes = [int(r["location_id"]) for r in read_rows(os.path.join(d, "locations.csv"))]
    N = len(nodes)
    with open(os.path.join(d, "cost_matrix.csv"), encoding="utf-8", newline="") as f:
        rd = csv.reader(f)
        header = next(rd)
        cols = [int(h) for h in header[1:]]
        mat = {int(r[0]): dict(zip(cols, (float(v) for v in r[1:]))) for r in rd}
    cost = {(i, j): mat[i][j] for i in nodes for j in nodes if i != j}
    prob = pulp.LpProblem("neos_5140963_mincio", pulp.LpMinimize)
    x = {k: pulp.LpVariable(f"x_{k[0]}_{k[1]}", cat=pulp.LpBinary) for k in cost}
    u_nodes = nodes[1:]
    u = {i: pulp.LpVariable(f"u_{i}", lowBound=1, upBound=N - 1) for i in u_nodes}
    prob += pulp.lpSum(cost[k] * x[k] for k in cost)
    for i in nodes:
        prob += pulp.lpSum(x[i, j] for j in nodes if i != j) == 1, f"Leave_{i}"
    for j in nodes:
        prob += pulp.lpSum(x[i, j] for i in nodes if i != j) == 1, f"Enter_{j}"
    for i in u_nodes:
        for j in u_nodes:
            if i != j:
                prob += u[i] - u[j] + N * x[i, j] <= N - 1, f"MTZ_{i}_{j}"
    return prob

"""wachplan: translation of the instance's solve.py (cyclic watch schedule; maximise the common number of shifts Z)."""
import pulp

from . import load_instance


def build(instance_dir):
    p = load_instance(instance_dir)["parameters"]
    nc, ns = p["n_crew"], p["n_slots"]
    prob = pulp.LpProblem("wachplan", pulp.LpMaximize)
    x = {(i, t): pulp.LpVariable(f"x_{i}_{t}", cat=pulp.LpBinary) for i in range(nc) for t in range(ns)}
    Z = pulp.LpVariable("Z", lowBound=0, cat=pulp.LpInteger)  # gurobipy addVar: lower bound 0 by default
    prob += Z
    for t in range(ns):
        prob += pulp.lpSum(x[i, t] for i in range(nc)) >= p["min_on_duty"], f"min_duty_{t}"
        prob += pulp.lpSum(x[i, t] for i in range(nc)) <= p["max_on_duty"], f"max_duty_{t}"
    for i in range(nc):
        for t in range(ns):
            prob += x[i, t] + x[i, (t + 1) % ns] <= 1, f"no_consecutive_{i}_{t}"
    for i in range(nc):
        for t in range(ns):
            prob += pulp.lpSum(x[i, (t + k) % ns] for k in range(p["window_size"])) <= p["max_shifts_in_window"], f"window_{i}_{t}"
    for i in range(nc):
        prob += pulp.lpSum(x[i, t] for t in range(ns)) == Z, f"fairness_{i}"
    for i in range(nc):
        for j in range(i + 1, nc):
            zp = [pulp.LpVariable(f"z_{i}_{j}_{t}", cat=pulp.LpBinary) for t in range(ns)]
            for t in range(ns):
                prob += zp[t] <= x[i, t], f"zi_{i}_{j}_{t}"
                prob += zp[t] <= x[j, t], f"zj_{i}_{j}_{t}"
                prob += zp[t] >= x[i, t] + x[j, t] - 1, f"zij_{i}_{j}_{t}"
            prob += pulp.lpSum(zp) >= 1, f"social_{i}_{j}"
    for k, (i, t) in enumerate([(0, 0), (1, 0), (2, 0), (3, 1), (4, 1)]):
        prob += x[i, t] == 1, f"pre_{k}"
    return prob

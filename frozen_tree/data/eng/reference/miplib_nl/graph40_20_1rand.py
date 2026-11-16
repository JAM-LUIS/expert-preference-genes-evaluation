"""graph40-20-1rand: translation of the instance's solve.py (maximum number of edge-disjoint cuts, one binary
partition per potential cut)."""
import pulp

from . import data_path, load_instance, read_rows


def build(instance_dir):
    inst = load_instance(instance_dir)
    n = inst["parameters"]["n"]
    m = inst["parameters"]["m"]
    edges = [(int(r["id1"]), int(r["id2"])) for r in read_rows(data_path(instance_dir, inst, "network_topology"))]
    if len(edges) != m:  # solve.py warns and uses the file count
        m = len(edges)
    K = range(m)
    prob = pulp.LpProblem("graph40_20_1rand", pulp.LpMaximize)
    z = {k: pulp.LpVariable(f"z_{k}", cat=pulp.LpBinary) for k in K}
    x = {(v, k): pulp.LpVariable(f"x_{v}_{k}", cat=pulp.LpBinary) for v in range(n) for k in K}
    y = {(e, k): pulp.LpVariable(f"y_{e}_{k}", cat=pulp.LpBinary) for e in range(len(edges)) for k in K}
    prob += pulp.lpSum(z.values())
    for e in range(len(edges)):
        prob += pulp.lpSum(y[e, k] for k in K) <= 1, f"EdgeDisjoint_{e}"
    for k in K:
        for e, (u, v) in enumerate(edges):
            prob += y[e, k] >= x[u, k] - x[v, k], f"CutDef1_{e}_{k}"
            prob += y[e, k] >= x[v, k] - x[u, k], f"CutDef2_{e}_{k}"
    for k in K:
        prob += x[0, k] == 0, f"FixNode0_{k}"
        for v in range(n):
            prob += x[v, k] <= z[k], f"InactiveZero_{v}_{k}"
        prob += pulp.lpSum(x[v, k] for v in range(n)) >= z[k], f"NonTrivial_{k}"
    for k in range(m - 1):
        prob += z[k] >= z[k + 1], f"Symmetry_{k}"
    return prob

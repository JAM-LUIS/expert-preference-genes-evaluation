"""p2m2p1m1p0n100: translation of the instance's solve.py (0-1 knapsack: total weight at least W, minimised)."""
import csv

import pulp

from . import data_path, load_instance


def build(instance_dir):
    inst = load_instance(instance_dir)
    I = inst["parameters"]["I"]
    W = inst["parameters"]["W"]
    key = next(iter(inst["files"]))  # the single weight file
    with open(data_path(instance_dir, inst, key), encoding="utf-8", newline="") as f:
        rows = list(csv.reader(f))[1:]  # solve.py renames the two columns to item_id, weight
    weights = [float(r[1]) for r in rows]
    prob = pulp.LpProblem("p2m2p1m1p0n100", pulp.LpMinimize)
    x = [pulp.LpVariable(f"x_{i}", cat=pulp.LpBinary) for i in range(I)]
    prob += pulp.lpSum(weights[i] * x[i] for i in range(I))
    prob += pulp.lpSum(weights[i] * x[i] for i in range(I)) >= W, "weight_lower_bound"
    return prob

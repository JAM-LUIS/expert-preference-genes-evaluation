"""gt2: translation of the instance's solve.py (integer vehicle assignment; supply limits, capacity-weighted demand)."""
import csv
import os

import pulp

from . import read_rows


def _matrix(path):
    with open(path, encoding="utf-8", newline="") as f:
        rd = csv.reader(f)
        header = next(rd)
        dests = header[1:]
        return dests, {int(r[0]): dict(zip(dests, (float(v) for v in r[1:]))) for r in rd}


def build(instance_dir):
    d = os.path.join(instance_dir, "data")
    c1 = read_rows(os.path.join(d, "C1.csv"))
    vehicles = [int(r["VehicleID"]) for r in c1]
    supply = {int(r["VehicleID"]): float(r["Quantity"]) for r in c1}
    dests, costs = _matrix(os.path.join(d, "C2.csv"))
    _, caps = _matrix(os.path.join(d, "C3.csv"))
    demand = {str(int(float(r["LocationID"]))): float(r["RequiredQuantity"]) for r in read_rows(os.path.join(d, "C4.csv"))}
    prob = pulp.LpProblem("gt2", pulp.LpMinimize)
    x = {(i, j): pulp.LpVariable(f"x_{i}_{j}", lowBound=0, cat=pulp.LpInteger) for i in vehicles for j in dests}
    prob += pulp.lpSum(costs[i][j] * x[i, j] for i in vehicles for j in dests)
    for i in vehicles:
        prob += pulp.lpSum(x[i, j] for j in dests) <= supply[i], f"Supply_{i}"
    for j in dests:
        prob += pulp.lpSum(caps[i][j] * x[i, j] for i in vehicles) >= demand[j], f"Demand_{j}"
    return prob

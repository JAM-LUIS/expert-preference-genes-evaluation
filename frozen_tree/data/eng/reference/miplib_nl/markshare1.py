"""markshare1: translation of the instance's solve.py (select bundles; shortfall u per market; minimise the
penalised shortfall)."""
import os

import pulp

from . import load_instance, read_rows


def build(instance_dir):
    inst = load_instance(instance_dir)
    penalty = float(inst.get("parameters", {}).get("penalty_per_unit", 1.0))
    d = os.path.join(instance_dir, "data")
    markets = read_rows(os.path.join(d, "markets.csv"))
    packages = read_rows(os.path.join(d, "packages.csv"))
    prob = pulp.LpProblem("markshare1", pulp.LpMinimize)
    x = {r["package_id"]: pulp.LpVariable(f"x_{r['package_id']}", cat=pulp.LpBinary) for r in packages}
    u = {r["market_id"]: pulp.LpVariable(f"u_{r['market_id']}", lowBound=0) for r in markets}
    prob += pulp.lpSum(penalty * u[m] for m in u)
    for m in markets:
        col = f"market_{m['market_id']}"
        if col not in packages[0]:
            raise ValueError(f"column {col} missing")
        terms = [(x[p["package_id"]], float(p[col])) for p in packages if float(p[col]) > 0]
        prob += pulp.LpAffineExpression(terms) + u[m["market_id"]] == float(m["target_units"]), f"balance_{m['market_id']}"
    return prob

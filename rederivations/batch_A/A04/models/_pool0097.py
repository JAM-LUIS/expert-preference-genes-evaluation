# Pooling problem: raw A, B, D -> one mixing tank (single pool quality p) -> blended with raw C into products A and B.
# For a fixed pool sulfur level p the model is an LP; the bilinear term (pool sulfur x pool-to-product flow)
# is handled by scanning p over [1, 3] (pool sulfur must lie between 1% and 3%) and solving an LP at each p.
import numpy as np
from scipy.optimize import linprog, minimize_scalar

SUL = {"A": 3.0, "B": 1.0, "C": 2.0, "D": 1.0}
COST = {"A": 6.0, "B": 16.0, "C": 10.0, "D": 15.0}
LIM = {"PA": 2.5, "PB": 1.5}
DEM = {"PA": 100.0, "PB": 200.0}
D_MAX = 50.0

def lp_at(p, price, demand_equal=False):
    # vars: xA, xB, xD (raw into pool), yA, yB (pool -> product A, B), zA, zB (raw C -> product A, B)
    c = -np.array([-COST["A"], -COST["B"], -COST["D"], price["PA"], price["PB"],
                   price["PA"] - COST["C"], price["PB"] - COST["C"]])
    A_eq = [[1, 1, 1, -1, -1, 0, 0],
            [SUL["A"], SUL["B"], SUL["D"], -p, -p, 0, 0]]
    b_eq = [0, 0]
    A_ub = [[0, 0, 0, p - LIM["PA"], 0, SUL["C"] - LIM["PA"], 0],
            [0, 0, 0, 0, p - LIM["PB"], 0, SUL["C"] - LIM["PB"]]]
    b_ub = [0, 0]
    dem_rows = [[0, 0, 0, 1, 0, 1, 0], [0, 0, 0, 0, 1, 0, 1]]
    dem_rhs = [DEM["PA"], DEM["PB"]]
    if demand_equal:
        A_eq += dem_rows; b_eq += dem_rhs
    else:
        A_ub += dem_rows; b_ub += dem_rhs
    bounds = [(0, None), (0, None), (0, D_MAX), (0, None), (0, None), (0, None), (0, None)]
    r = linprog(c, A_ub=A_ub, b_ub=b_ub, A_eq=A_eq, b_eq=b_eq, bounds=bounds, method="highs")
    if r.status != 0:
        return None, None
    return -r.fun, r.x

def solve(price, demand_equal=False):
    grid = np.unique(np.concatenate([np.linspace(1.0, 3.0, 4001), [1.0, 1.5, 2.0, 2.5, 3.0]]))
    best, bp, bx = None, None, None
    for p in grid:
        v, x = lp_at(p, price, demand_equal)
        if v is not None and (best is None or v > best + 1e-9):
            best, bp, bx = v, p, x
    if best is None:
        return None, None, None
    lo, hi = max(1.0, bp - 0.001), min(3.0, bp + 0.001)
    def neg(p):
        v, _ = lp_at(p, price, demand_equal)
        return 1e9 if v is None else -v
    r = minimize_scalar(neg, bounds=(lo, hi), method="bounded", options={"xatol": 1e-10})
    if -r.fun > best + 1e-7:
        best, bp = -r.fun, r.x
        _, bx = lp_at(bp, price, demand_equal)
    return best, bp, bx

def main(price, demand_equal=False):
    best, bp, bx = solve(price, demand_equal)
    if best is None:
        print("STATUS: Infeasible"); print("FINAL_OBJECTIVE: None"); return
    print("STATUS: Optimal")
    print("FINAL_OBJECTIVE:", round(best, 6))
    print("  pool sulfur %:", round(bp, 6))
    for n, v in zip(["rawA_to_pool", "rawB_to_pool", "rawD_to_pool", "pool_to_prodA", "pool_to_prodB", "rawC_to_prodA", "rawC_to_prodB"], bx):
        print(f"  {n} = {round(v, 4)}")

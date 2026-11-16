#!/usr/bin/env python3
# industryor-0097 r2 (both selling prices literally 9.15): one-pool pooling problem (bilinear). Pool gets raw A,B,D; pool output and raw C
# blended into products PA (<=2.5% S, demand<=100) and PB (<=1.5% S, demand<=200).
# Method: pool sulfur s is the only complicating variable; for fixed s the problem is an LP
# (solved with scipy linprog/HiGHS). Scan s on a grid over [1,3] (%), then refine with bounded 1-D search.
import numpy as np
from scipy.optimize import linprog, minimize_scalar
PRICE_PA, PRICE_PB = 9.15, 9.15
cost = {'A': 6, 'B': 16, 'C': 10, 'D': 15}
S = {'A': 3, 'B': 1, 'C': 2, 'D': 1}
# variables: a, b, d, pA, pB, cA, cB
def lp(s):
    c = -np.array([-cost['A'], -cost['B'], -cost['D'], PRICE_PA, PRICE_PB,
                   PRICE_PA - cost['C'], PRICE_PB - cost['C']], dtype=float)
    Aeq = [[S['A'] - s, S['B'] - s, S['D'] - s, 0, 0, 0, 0],   # pool sulfur balance
           [1, 1, 1, -1, -1, 0, 0]]                            # pool mass balance
    beq = [0, 0]
    Aub = [[0, 0, 0, s - 2.5, 0, S['C'] - 2.5, 0],
           [0, 0, 0, 0, s - 1.5, 0, S['C'] - 1.5],
           [0, 0, 0, 1, 0, 1, 0],
           [0, 0, 0, 0, 1, 0, 1]]
    bub = [0, 0, 100, 200]
    bounds = [(0, None), (0, None), (0, 50), (0, None), (0, None), (0, None), (0, None)]
    r = linprog(c, A_ub=Aub, b_ub=bub, A_eq=Aeq, b_eq=beq, bounds=bounds, method="highs")
    return (-r.fun, r.x) if r.status == 0 else (-np.inf, None)
grid = np.linspace(1.0, 3.0, 4001)
vals = [lp(s)[0] for s in grid]
k = int(np.argmax(vals))
best_s, best_v = grid[k], vals[k]
lo, hi = grid[max(k-1, 0)], grid[min(k+1, len(grid)-1)]
res = minimize_scalar(lambda s: -lp(s)[0], bounds=(lo, hi), method="bounded", options={"xatol": 1e-10})
if -res.fun > best_v:
    best_s, best_v = res.x, -res.fun
v, x = lp(best_s)
print("STATUS: LocallyOptimal")
print("FINAL_OBJECTIVE:", round(v, 6))
print("  pool_sulfur_pct =", best_s)
for nme, val in zip(["a", "b", "d", "pool_to_PA", "pool_to_PB", "C_to_PA", "C_to_PB"], x):
    print(f"  {nme} = {val:.6f}")

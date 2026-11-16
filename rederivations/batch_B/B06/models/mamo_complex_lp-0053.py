# Transshipment between 5 regions: flows f[i,j] >= 0; final stock of each region >= need.
import sys, os; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pulp
from _common import solve_report, relax_and_solve
stock = {1: 410, 2: 266, 3: 132, 4: 6, 5: 485}
need = {1: 274, 2: 331, 3: 232, 4: 359, 5: 74}
cost = {(1, 2): 24, (1, 3): 3, (1, 4): 27, (1, 5): 31,
        (2, 1): 24, (2, 3): 11, (2, 4): 7, (2, 5): 37,
        (3, 1): 30, (3, 2): 1, (3, 4): 38, (3, 5): 22,
        (4, 1): 36, (4, 2): 18, (4, 3): 17, (4, 5): 35,
        (5, 1): 41, (5, 2): 35, (5, 3): 33, (5, 4): 33}
R = list(stock)
m = pulp.LpProblem("mamo0053", pulp.LpMinimize)
f = {a: pulp.LpVariable(f"f_{a[0]}_{a[1]}", lowBound=0, cat="Integer") for a in cost}
m += pulp.lpSum(cost[a]*f[a] for a in cost)
for r in R:
    m += stock[r] + pulp.lpSum(f[i, j] for (i, j) in cost if j == r) - pulp.lpSum(f[i, j] for (i, j) in cost if i == r) >= need[r]
solve_report(m)
relax_and_solve(m)

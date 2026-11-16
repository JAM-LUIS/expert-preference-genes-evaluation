# Reading 2: all-units pricing - the whole sales volume earns the unit profit of the range it falls in. MILP.
import sys, os; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pulp
from _common import solve_report, relax_and_solve
M = 1000  # any product volume is <= 400 by the material constraint
rng = {"A": [(0, 40, 10), (40, 100, 9), (100, 150, 8), (150, M, 7)],
       "B": [(0, 50, 6), (50, 100, 4), (100, M, 3)],
       "C": [(0, 100, 5), (100, M, 4)]}
m = pulp.LpProblem("io0045_r2", pulp.LpMaximize)
q, obj = {}, []
for p, rs in rng.items():
    parts = []
    z = [pulp.LpVariable(f"z_{p}_{i}", cat="Binary") for i in range(len(rs))]
    for i, (lo, hi, pr) in enumerate(rs):
        v = pulp.LpVariable(f"q_{p}_{i}", lowBound=0)
        m += v >= lo*z[i]; m += v <= hi*z[i]
        parts.append(v); obj.append(pr*v)
    m += pulp.lpSum(z) == 1
    q[p] = pulp.LpVariable(f"{p}", lowBound=0, cat="Integer")
    m += q[p] == pulp.lpSum(parts)
m += pulp.lpSum(obj)
m += q["A"] + 2*q["B"] + q["C"] <= 100
m += 10*q["A"] + 4*q["B"] + 5*q["C"] <= 700
m += 3*q["A"] + 2*q["B"] + q["C"] <= 400
solve_report(m)
relax_and_solve(m)

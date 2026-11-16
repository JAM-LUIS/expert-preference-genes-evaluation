import sys, os; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pulp
from _common import solve_report, relax_and_solve
P = ["I", "II", "III"]; T = [1, 2, 3, 4]
d = {"I": [1500, 1000, 2000, 1200], "II": [1500, 1500, 1200, 1500], "III": [1000, 2000, 1500, 2500]}
hrs = {"I": 2, "II": 4, "III": 3}
pen = {"I": 20, "II": 20, "III": 10}
m = pulp.LpProblem("io0006", pulp.LpMinimize)
x = {(p, t): pulp.LpVariable(f"x_{p}_{t}", lowBound=0, cat="Integer") for p in P for t in T}
I = {(p, t): pulp.LpVariable(f"inv_{p}_{t}", lowBound=0) for p in P for t in T}
B = {(p, t): pulp.LpVariable(f"back_{p}_{t}", lowBound=0) for p in P for t in T}
m += pulp.lpSum(5 * I[p, t] + pen[p] * B[p, t] for p in P for t in T)
for p in P:
    for t in T:
        prev = (I[p, t-1] - B[p, t-1]) if t > 1 else 0
        m += I[p, t] - B[p, t] == prev + x[p, t] - d[p][t-1]
    m += I[p, 4] == 150
    m += B[p, 4] == 0
for t in T:
    m += pulp.lpSum(hrs[p] * x[p, t] for p in P) <= 15000
m += x["I", 2] == 0
solve_report(m)
relax_and_solve(m)

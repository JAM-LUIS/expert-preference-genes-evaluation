import sys, os; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pulp
from _common import solve_report, relax_and_solve
toys = ["robot", "car", "blocks", "doll"]
profit = {"robot": 15, "car": 8, "blocks": 12, "doll": 5}
plastic = {"robot": 30, "car": 10, "blocks": 20, "doll": 15}
elec = {"robot": 8, "car": 5, "blocks": 3, "doll": 2}
U = {t: 1200 // plastic[t] for t in toys}  # upper bound from plastic
m = pulp.LpProblem("io0020", pulp.LpMaximize)
x = {t: pulp.LpVariable(f"x_{t}", lowBound=0, cat="Integer") for t in toys}
y = {t: pulp.LpVariable(f"y_{t}", cat="Binary") for t in toys}
m += pulp.lpSum(profit[t]*x[t] for t in toys)
m += pulp.lpSum(plastic[t]*x[t] for t in toys) <= 1200
m += pulp.lpSum(elec[t]*x[t] for t in toys) <= 800
for t in toys:
    m += x[t] <= U[t]*y[t]
    m += x[t] >= y[t]
m += y["robot"] + y["doll"] <= 1          # robots -> no dolls
m += y["car"] <= y["blocks"]              # cars -> blocks
m += x["doll"] <= x["car"]
solve_report(m)
print("number of toy types produced:", sum(1 for t in toys if x[t].varValue > 0.5))
relax_and_solve(m)

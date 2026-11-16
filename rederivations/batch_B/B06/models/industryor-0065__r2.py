# Reading 2: as main GP but workshop B available time (150 h) is a hard cap (no overtime in B).
# x1 microwave ovens, x2 water heaters (integer units). Reported objective = sum of deviations at last level.
import sys, os; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pulp
from _common import solve_report
m = pulp.LpProblem("io0065", pulp.LpMinimize)
x1 = pulp.LpVariable("x1_microwave", lowBound=0, cat="Integer"); x2 = pulp.LpVariable("x2_heater", lowBound=0, cat="Integer")
dv = {k: (pulp.LpVariable(f"d{k}m", lowBound=0), pulp.LpVariable(f"d{k}p", lowBound=0)) for k in ["1", "2", "3A", "3B", "4", "5"]}
m += 30*x1 + 50*x2 + dv["1"][0] - dv["1"][1] == 5500
m += x1 + dv["2"][0] - dv["2"][1] == 80
m += 2*x1 + x2 + dv["3A"][0] - dv["3A"][1] == 250
m += x1 + 3*x2 + dv["3B"][0] - dv["3B"][1] == 150
m += dv["3A"][1] + dv["4"][0] - dv["4"][1] == 20       # overtime in A <= 20
m += x2 + dv["5"][0] - dv["5"][1] == 50
m += x1 + 3*x2 <= 150   # r2: hard cap in workshop B
goals = [lambda: dv["1"][1], lambda: dv["2"][0], lambda: dv["3A"][0] + dv["3B"][0],
         lambda: dv["4"][1], lambda: dv["5"][0]]
for k, g in enumerate(goals[:-1]):
    m.setObjective(g()); m.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=600))
    val = pulp.value(m.objective); print(f"level {k+1}: {pulp.LpStatus[m.status]} deviation = {val}")
    m += g() <= val, f"fix_{k+1}"
m.setObjective(goals[-1]())
solve_report(m)
tot = sum(pulp.value(g()) for g in goals)
print("total unwanted deviation over all levels:", tot)
print("plan: x1 =", x1.varValue, " x2 =", x2.varValue)

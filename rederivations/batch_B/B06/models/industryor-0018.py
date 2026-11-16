# Lexicographic goal programming. x1 = curtain hours, x2 = clothing hours (1000 m/h each).
import sys, os; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pulp
from _common import solve_report
m = pulp.LpProblem("io0018", pulp.LpMinimize)
x1 = pulp.LpVariable("x_curtain_h", lowBound=0); x2 = pulp.LpVariable("x_cloth_h", lowBound=0)
d1m = pulp.LpVariable("d1m", lowBound=0); d1p = pulp.LpVariable("d1p_overtime", lowBound=0)
d2m = pulp.LpVariable("d2m", lowBound=0); d2p = pulp.LpVariable("d2p", lowBound=0)
d3m = pulp.LpVariable("d3m", lowBound=0); d3p = pulp.LpVariable("d3p", lowBound=0)
d4m = pulp.LpVariable("d4m", lowBound=0); d4p = pulp.LpVariable("d4p", lowBound=0)
m += x1 + x2 + d1m - d1p == 110            # p1 regular time
m += d1p + d2m - d2p == 10                 # p2 overtime <= 10
m += 1000*x1 + d3m - d3p == 70000          # p3 curtain sales
m += 1000*x2 + d4m - d4p == 45000          # p3 clothing sales
goals = [lambda: d1m, lambda: d2p, lambda: 2.5*d3m + 1.5*d4m, lambda: d1p]
for k, g in enumerate(goals[:-1]):
    m.setObjective(g())
    m.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=600))
    val = pulp.value(m.objective)
    print(f"level p{k+1}: {pulp.LpStatus[m.status]} deviation = {val}")
    m += g() <= val, f"fix_p{k+1}"
m.setObjective(goals[-1]())   # p4: minimize overtime (final level, reported objective)
solve_report(m)
print("profit of plan (yuan):", 2.5*1000*x1.varValue + 1.5*1000*x2.varValue)

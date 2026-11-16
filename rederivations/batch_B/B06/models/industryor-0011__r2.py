# Lexicographic goal programming, continuous (problem says "linear programming model").
import sys, os; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pulp
from _common import solve_report
INT = True
cat = "Integer" if INT else "Continuous"
pA = 650 - (20*12 + 5*8 + 3*10)
pB = 725 - (0*12 + 7*8 + 6*10)
def build():
    m = pulp.LpProblem("io0011", pulp.LpMinimize)
    x1 = pulp.LpVariable("x1", lowBound=0, cat=cat); x2 = pulp.LpVariable("x2", lowBound=0, cat=cat)
    d1m = pulp.LpVariable("d1m", lowBound=0); d1p = pulp.LpVariable("d1p", lowBound=0)
    d2m = pulp.LpVariable("d2m", lowBound=0); d2p = pulp.LpVariable("d2p", lowBound=0)
    idle = [pulp.LpVariable(f"idle{j}", lowBound=0) for j in range(3)]
    m += pA*x1 + pB*x2 + d1m - d1p == 3000
    m += x1 + d2m - d2p == 5
    m += 20*x1 + idle[0] == 120   # no overtime: usage + idle = capacity
    m += 5*x1 + 7*x2 + idle[1] == 80
    m += 3*x1 + 6*x2 + idle[2] == 40
    return m, x1, x2, d1m, d2m, idle
levels = []
m, x1, x2, d1m, d2m, idle = build()
goals = [lambda: d1m, lambda: d2m, lambda: 12*idle[0] + 8*idle[1] + 10*idle[2]]
for k, g in enumerate(goals):
    m.setObjective(g())
    m.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=600))
    val = pulp.value(m.objective)
    print(f"level p{k+1}: {pulp.LpStatus[m.status]} deviation = {val}")
    m += g() <= val + 1e-6, f"fix_p{k+1}"
# final: report profit of the GP plan
m.setObjective(-(pA*x1 + pB*x2)); m.sense = pulp.LpMinimize
m2 = pulp.LpProblem("final", pulp.LpMaximize)
m2 += pA*x1 + pB*x2
for name, c in m.constraints.items():
    m2 += c, name
solve_report(m2)
print("profit per unit A, B:", pA, pB)

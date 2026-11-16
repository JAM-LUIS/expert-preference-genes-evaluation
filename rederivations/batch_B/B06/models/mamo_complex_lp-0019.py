# Diet problem. Main model: integer number of each food item; continuous version reported on INTEGERS_RELAXED line.
import sys, os; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pulp
from _common import solve_report
F = {"steak": (1, 3, 210, 6), "apples": (7, 22, 96, 1), "eggs": (6, 18, 189, 1),
     "chicken": (20, 6, 132, 3), "tofu": (8, 4, 75, 1)}
def build(cat):
    m = pulp.LpProblem("mamo0019", pulp.LpMinimize)
    x = {f: pulp.LpVariable(f"x_{f}", lowBound=0, cat=cat) for f in F}
    m += pulp.lpSum(F[f][3]*x[f] for f in F)
    m += pulp.lpSum(F[f][0]*x[f] for f in F) >= 87
    m += pulp.lpSum(F[f][1]*x[f] for f in F) >= 135
    m += pulp.lpSum(F[f][2]*x[f] for f in F) >= 1926
    return m
m = build("Integer")
solve_report(m)
mc = build("Continuous"); mc.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=600))
print("INTEGERS_RELAXED:", pulp.LpStatus[mc.status], pulp.value(mc.objective))
for v in mc.variables():
    if v.varValue: print(f"  {v.name} = {v.varValue}")

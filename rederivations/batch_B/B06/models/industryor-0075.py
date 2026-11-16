import sys, os; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pulp
from _common import solve_report
m = pulp.LpProblem("io0075", pulp.LpMaximize)
xA = pulp.LpVariable("xA", lowBound=0); xB = pulp.LpVariable("xB", lowBound=0)
cs = pulp.LpVariable("C_sold", lowBound=0, upBound=5); cd = pulp.LpVariable("C_disposed", lowBound=0)
m += 4*xA + 10*xB + 3*cs - 2*cd
m += 2*xA + 3*xB <= 16
m += 3*xA + 4*xB <= 24
m += cs + cd == 2*xB
solve_report(m)
# integer check
for v in (xA, xB, cd): v.cat = pulp.LpInteger
cs.cat = pulp.LpInteger
m.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=600))
print("INTEGER_VERSION:", pulp.LpStatus[m.status], pulp.value(m.objective), xA.varValue, xB.varValue)

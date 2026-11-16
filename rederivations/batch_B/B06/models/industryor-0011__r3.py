# Reading 3: maximize profit with p1, p2 and capacity (no overtime) as hard constraints; integer units.
import sys, os; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pulp
from _common import solve_report, relax_and_solve
pA = 650 - (20*12 + 5*8 + 3*10); pB = 725 - (7*8 + 6*10)
m = pulp.LpProblem("io0011_r3", pulp.LpMaximize)
x1 = pulp.LpVariable("x1", lowBound=0, cat="Integer"); x2 = pulp.LpVariable("x2", lowBound=0, cat="Integer")
m += pA*x1 + pB*x2
m += pA*x1 + pB*x2 >= 3000
m += x1 >= 5
m += 20*x1 <= 120
m += 5*x1 + 7*x2 <= 80
m += 3*x1 + 6*x2 <= 40
solve_report(m)
relax_and_solve(m)

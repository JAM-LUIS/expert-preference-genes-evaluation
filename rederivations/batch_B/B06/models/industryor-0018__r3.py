# Reading 3: maximize weekly profit with p1-p3 as hard constraints (>=110 h, overtime <=10 h, sales minimums).
import sys, os; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pulp
from _common import solve_report
m = pulp.LpProblem("io0018_r3", pulp.LpMaximize)
x1 = pulp.LpVariable("x_curtain_h", lowBound=0); x2 = pulp.LpVariable("x_cloth_h", lowBound=0)
m += 2500*x1 + 1500*x2
m += x1 + x2 >= 110
m += x1 + x2 <= 120
m += 1000*x1 >= 70000
m += 1000*x2 >= 45000
solve_report(m)

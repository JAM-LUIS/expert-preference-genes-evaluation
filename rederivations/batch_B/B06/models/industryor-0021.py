import sys, os; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pulp
from _common import solve_report
m = pulp.LpProblem("io0021", pulp.LpMinimize)
nA = pulp.LpVariable("orders_A", lowBound=0, cat="Integer")
nB = pulp.LpVariable("orders_B", lowBound=0, cat="Integer")
nC = pulp.LpVariable("orders_C", lowBound=0, cat="Integer")
yA = pulp.LpVariable("use_A", cat="Binary"); yB = pulp.LpVariable("use_B", cat="Binary")
tA, tB, tC = 20*nA, 15*nB, 15*nC
m += 120*tA + 110*tB + 100*tC
m += tA + tB + tC >= 150
m += tA + tB + tC <= 600
m += nA <= 30*yA          # 600/20 = 30 max orders from A
m += nB <= 40*yB          # 600/15 = 40 max orders from B
m += tB >= 30*yA          # A used -> at least 30 tables from B
m += nC >= yB             # B used -> order from C
solve_report(m)

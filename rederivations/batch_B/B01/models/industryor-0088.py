# Lots (fractional allowed). Ending inventory = 30 + xL - 75 + 90 + xS - 95, demand must be met.
import pulp
from _common import solve_report
m = pulp.LpProblem("ior0088", pulp.LpMaximize)
xL = pulp.LpVariable("liquid", lowBound=0); xS = pulp.LpVariable("solid", lowBound=0)
m += (30 + xL - 75) + (90 + xS - 95)
m += 50*xL + 24*xS <= 40*60
m += 30*xL + 33*xS <= 35*60
m += 30 + xL >= 75
m += 90 + xS >= 95
solve_report(m)

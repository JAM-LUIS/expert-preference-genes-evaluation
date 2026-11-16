# Diet LP; food quantities treated as continuous servings (main); integer servings reported as relaxed check.
import sys
import pulp
from _common import solve_report
INT = len(sys.argv) > 1 and sys.argv[1] == "int"
F = ["Chicken","Rice","Eggs","Broccoli","Lentils","Apples"]
prot = dict(zip(F,[18,14,18,7,15,8])); carb = dict(zip(F,[5,13,4,15,17,13]))
cal = dict(zip(F,[202,234,220,247,88,77])); price = dict(zip(F,[1,7,4,3,1,2]))
m = pulp.LpProblem("mamo0025", pulp.LpMinimize)
x = pulp.LpVariable.dicts("qty", F, lowBound=0, cat="Integer" if INT else "Continuous")
m += pulp.lpSum(price[f]*x[f] for f in F)
m += pulp.lpSum(prot[f]*x[f] for f in F) >= 70
m += pulp.lpSum(carb[f]*x[f] for f in F) >= 187
m += pulp.lpSum(cal[f]*x[f] for f in F) >= 2181
solve_report(m)

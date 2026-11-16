import pulp
from _common import solve_report
T = range(1,7)
dem = dict(zip(T, [500,550,700,900,400,300]))
c = dict(zip(T, [5,8,10,12,16,18]))
F = 1200
M = sum(dem.values())
m = pulp.LpProblem("ior0012", pulp.LpMinimize)
x = pulp.LpVariable.dicts("prod", T, lowBound=0, cat="Integer")
y = pulp.LpVariable.dicts("open", T, cat="Binary")
s = pulp.LpVariable.dicts("use", [(i,j) for i in T for j in T if i >= j], lowBound=0, cat="Integer")
m += pulp.lpSum(c[i]*x[i] + F*y[i] for i in T)
for i in T:
    m += pulp.lpSum(s[i,j] for j in T if j <= i) <= x[i]
    m += x[i] <= M * y[i]
for j in T:
    m += pulp.lpSum(s[i,j] for i in T if i >= j) >= dem[j]
solve_report(m, relax=True)

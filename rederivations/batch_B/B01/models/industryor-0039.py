# Main reading: at most two of the three methods may be used.
import sys
import pulp
from _common import solve_report
EXACT = len(sys.argv) > 1 and sys.argv[1] == "exact"
V = ["moto","small","large"]
pol = dict(zip(V,[40,70,100])); cap = dict(zip(V,[10,20,50]))
m = pulp.LpProblem("ior0039", pulp.LpMinimize)
n = pulp.LpVariable.dicts("trips", V, lowBound=0, cat="Integer")
u = pulp.LpVariable.dicts("use", V, cat="Binary")
m += pulp.lpSum(pol[v]*n[v] for v in V)
if EXACT:
    m += pulp.lpSum(u.values()) == 2
    for v in V: m += n[v] >= u[v]
else:
    m += pulp.lpSum(u.values()) <= 2
for v in V: m += n[v] <= 20*u[v]
m += n["moto"] <= 8
m += pulp.lpSum(cap[v]*n[v] for v in V) >= 300
m += pulp.lpSum(n.values()) <= 20
solve_report(m, relax=True)

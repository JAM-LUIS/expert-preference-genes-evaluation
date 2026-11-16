import pulp
from _common import solve_report
V = ["truck","van","moto","ev"]
pol = dict(zip(V,[100,50,10,0])); cap = dict(zip(V,[100,80,40,60]))
m = pulp.LpProblem("ior0024", pulp.LpMinimize)
n = pulp.LpVariable.dicts("trips", V, lowBound=0, cat="Integer")
uv = pulp.LpVariable("use_van", cat="Binary"); ue = pulp.LpVariable("use_ev", cat="Binary")
M = 1800  # upper bound on trips (each trip carries >= 40 units would suffice; generous bound)
m += pulp.lpSum(pol[v]*n[v] for v in V)
m += uv + ue <= 1
m += n["van"] <= M*uv
m += n["ev"] <= M*ue
m += pulp.lpSum(pol[v]*n[v] for v in V) <= 2000
m += n["truck"] >= 10
m += pulp.lpSum(cap[v]*n[v] for v in V) >= 1800
solve_report(m, relax=True)

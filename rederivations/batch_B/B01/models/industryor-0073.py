import pulp
from _common import solve_report
K = ["Alice","Bob","Charlie","Diana","Ella"]
cost = dict(zip(K,[1000,900,600,500,700]))
m = pulp.LpProblem("ior0073", pulp.LpMinimize)
t = pulp.LpVariable.dicts("take", K, cat="Binary")
m += pulp.lpSum(cost[k]*t[k] for k in K)
m += pulp.lpSum(t.values()) <= 3
m += t["Bob"] == 1
m += t["Alice"] + t["Diana"] <= 1
m += t["Bob"] + t["Charlie"] <= 1
m += t["Charlie"] <= t["Diana"]
m += t["Diana"] <= t["Ella"]
m += pulp.lpSum(t.values()) >= 2
solve_report(m)

import pulp
from _common import solve_report
C = [1,2,3,4]; S = [1,2,3,4,5,6]
fixed = dict(zip(C,[151000,192000,114000,171000]))
tc = {1:[5,5,2,3,3,3],2:[5,4,3,5,2,4],3:[2,4,5,1,4,2],4:[5,4,1,1,3,3]}
dem = dict(zip(S,[910,875,589,962,966,643]))
capa = dict(zip(C,[1631,1954,1446,820]))
m = pulp.LpProblem("mamo0154", pulp.LpMinimize)
y = pulp.LpVariable.dicts("open", C, cat="Binary")
x = pulp.LpVariable.dicts("ship", [(i,j) for i in C for j in S], lowBound=0)
m += pulp.lpSum(fixed[i]*y[i] for i in C) + pulp.lpSum(tc[i][j-1]*x[i,j] for i in C for j in S)
for j in S: m += pulp.lpSum(x[i,j] for i in C) >= dem[j]
for i in C: m += pulp.lpSum(x[i,j] for j in S) <= capa[i]*y[i]
solve_report(m)

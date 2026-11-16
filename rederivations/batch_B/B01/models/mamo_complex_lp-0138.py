import pulp
from _common import solve_report
rows = {
0:[0,9,7,18,0,0,7,0,2],
1:[15,0,11,5,20,15,18,9,15],
2:[3,8,0,10,16,18,8,0,20],
3:[13,3,7,0,20,13,16,6,20],
4:[7,20,2,4,0,9,3,14,2],
5:[17,10,5,1,4,0,4,3,20],
6:[0,20,10,10,15,5,0,1,10],
7:[10,3,9,4,3,13,18,0,20],
8:[2,12,10,5,15,14,0,10,0]}
E = [(i,j) for i in rows for j in range(9) if i != j and rows[i][j] > 0]
m = pulp.LpProblem("mamo0138", pulp.LpMaximize)
f = pulp.LpVariable.dicts("f", E, lowBound=0)
for (i,j) in E: f[i,j].upBound = rows[i][j]
m += pulp.lpSum(f[0,j] for (i,j) in E if i==0) - pulp.lpSum(f[i,0] for (i,j) in E if j==0)
for n in range(1,8):
    m += pulp.lpSum(f[i,j] for (i,j) in E if j==n) == pulp.lpSum(f[i,j] for (i,j) in E if i==n)
solve_report(m, show=False)

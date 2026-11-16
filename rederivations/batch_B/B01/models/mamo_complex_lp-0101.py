import pulp
from _common import solve_report
cap = {
0:{1:15,2:1,3:9,4:18,5:12,6:18,7:6,8:17},
1:{0:14,2:13,3:11,4:14,5:10,6:15,7:4,8:15},
2:{0:3,3:2,4:14,5:16,6:7,7:12,8:4},
3:{0:5,1:20,4:9,5:1,6:12,7:1,8:20},
4:{0:11,1:18,2:12,3:3,5:4,6:16,7:15,8:2},
5:{0:13,1:8,2:8,3:6,4:4,6:8,7:10,8:11},
6:{0:12,1:1,2:3,3:4,4:11,5:8,7:10,8:19},
7:{0:18,1:3,2:9,3:5,4:9,5:17,6:10,8:13},
8:{0:9,1:8,2:12,3:2,4:5,5:2,6:16,7:5}}
E = [(i,j) for i in cap for j in cap[i] if cap[i][j] > 0]
m = pulp.LpProblem("mamo0101", pulp.LpMaximize)
f = pulp.LpVariable.dicts("f", E, lowBound=0)
for (i,j) in E: f[i,j].upBound = cap[i][j]
val = pulp.lpSum(f[0,j] for (i,j) in E if i==0) - pulp.lpSum(f[i,0] for (i,j) in E if j==0)
m += val
for n in range(1,8):
    m += pulp.lpSum(f[i,j] for (i,j) in E if j==n) == pulp.lpSum(f[i,j] for (i,j) in E if i==n)
solve_report(m, show=False)

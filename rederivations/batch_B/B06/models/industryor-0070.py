# Asymmetric TSP on 4 cities (visit every city exactly once), MTZ subtour elimination.
import sys, os; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pulp
from _common import solve_report
D = [[0, 10, 20, 12], [10, 0, 5, 10], [20, 5, 0, 8], [15, 12, 8, 0]]
n = 4; N = range(n)
m = pulp.LpProblem("io0070", pulp.LpMinimize)
x = {(i, j): pulp.LpVariable(f"x_{i+1}_{j+1}", cat="Binary") for i in N for j in N if i != j}
u = {i: pulp.LpVariable(f"u_{i+1}", lowBound=1, upBound=n-1) for i in N if i != 0}
m += pulp.lpSum(D[i][j]*x[i, j] for (i, j) in x)
for i in N:
    m += pulp.lpSum(x[i, j] for j in N if j != i) == 1
    m += pulp.lpSum(x[j, i] for j in N if j != i) == 1
for i in N:
    for j in N:
        if i != j and i != 0 and j != 0:
            m += u[i] - u[j] + (n-1)*x[i, j] <= n-2
solve_report(m)

# Reading 2: table column k read as the profit earned by the k-th store of that type (incremental).
# Total profit of type i with n stores = n * p_i(n); rent = 20% of total. Exact linearization by
# choosing the number of stores with binaries z[i,n] (enumeration over the bounded integer count).
import sys, os; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pulp
from _common import solve_report
area = {1: 250, 2: 350, 3: 800, 4: 400, 5: 500}
mn = {1: 1, 2: 1, 3: 1, 4: 0, 5: 1}
mx = {1: 3, 2: 2, 3: 3, 4: 2, 5: 3}
prof = {1: [9, 8, 7], 2: [10, 9], 3: [27, 21, 20], 4: [16, 10], 5: [17, 15, 12]}  # ten-thousand yuan
m = pulp.LpProblem("io0082", pulp.LpMaximize)
z = {(i, n): pulp.LpVariable(f"z_{i}_{n}", cat="Binary") for i in area for n in range(mn[i], mx[i]+1)}
val = lambda i, n: sum(prof[i][:n])  # r2: column k = profit of the k-th store (marginal)
for i in area:
    m += pulp.lpSum(z[i, n] for n in range(mn[i], mx[i]+1)) == 1
m += pulp.lpSum(0.2 * val(i, n) * z[i, n] for (i, n) in z)
m += pulp.lpSum(area[i] * n * z[i, n] for (i, n) in z) <= 5000
solve_report(m)
for (i, n), v in z.items():
    if v.varValue > 0.5: print(f"type {i}: {n} stores")

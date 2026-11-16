#!/usr/bin/env python3
import pulp
cap = {
 0: {1: 6, 2: 16, 3: 5, 4: 6, 5: 11, 6: 6, 7: 4},
 1: {2: 8, 3: 10, 4: 6, 5: 3, 6: 6, 7: 14},
 2: {1: 6, 3: 20, 4: 7, 5: 16, 6: 13, 7: 14},
 3: {1: 11, 2: 19, 4: 18, 5: 5, 7: 8},
 4: {1: 1, 2: 14, 3: 18, 5: 12, 6: 4, 7: 7},
 5: {1: 16, 2: 3, 3: 20, 4: 7, 6: 15, 7: 6},
 6: {1: 11, 2: 4, 3: 19, 4: 7, 5: 6, 7: 17},
 7: {1: 5, 2: 8, 3: 17, 4: 2, 5: 5, 6: 4},
}
arcs = [(i, j) for i in cap for j in cap[i]]
m = pulp.LpProblem("m0122", pulp.LpMaximize)
f = {a: pulp.LpVariable(f"f_{a[0]}_{a[1]}", lowBound=0, upBound=cap[a[0]][a[1]]) for a in arcs}
inflow = lambda n: pulp.lpSum(f[a] for a in arcs if a[1] == n)
outflow = lambda n: pulp.lpSum(f[a] for a in arcs if a[0] == n)
m += inflow(7) - outflow(7)
for n in range(1, 7):
    m += inflow(n) == outflow(n)

m.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=600))
status = pulp.LpStatus[m.status]
sol_status = pulp.LpSolution[m.sol_status]
print("STATUS:", status)
print("SOLUTION_STATUS:", sol_status)
if status == "Optimal" and sol_status == "Optimal Solution Found":
    print("FINAL_OBJECTIVE:", pulp.value(m.objective))
    for v in m.variables():
        if v.varValue:
            print(f"  {v.name} = {v.varValue}")
else:
    print("FINAL_OBJECTIVE: None")

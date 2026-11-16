#!/usr/bin/env python3
import pulp
cap = {
    0: {1: 15, 2: 1, 3: 9, 4: 18, 5: 12, 6: 18, 7: 6, 8: 17},
    1: {0: 14, 2: 13, 3: 11, 4: 14, 5: 10, 6: 15, 7: 4, 8: 15},
    2: {0: 3, 3: 2, 4: 14, 5: 16, 6: 7, 7: 12, 8: 4},
    3: {0: 5, 1: 20, 4: 9, 5: 1, 6: 12, 7: 1, 8: 20},
    4: {0: 11, 1: 18, 2: 12, 3: 3, 5: 4, 6: 16, 7: 15, 8: 2},
    5: {0: 13, 1: 8, 2: 8, 3: 6, 4: 4, 6: 8, 7: 10, 8: 11},
    6: {0: 12, 1: 1, 2: 3, 3: 4, 4: 11, 5: 8, 7: 10, 8: 19},
    7: {0: 18, 1: 3, 2: 9, 3: 5, 4: 9, 5: 17, 6: 10, 8: 13},
    8: {0: 9, 1: 8, 2: 12, 3: 2, 4: 5, 5: 2, 6: 16, 7: 5},
}
S, T = 0, 8
arcs = [(i, j) for i in cap for j in cap[i]]
m = pulp.LpProblem("maxflow", pulp.LpMaximize)
f = {a: pulp.LpVariable(f"f_{a[0]}_{a[1]}", lowBound=0, upBound=cap[a[0]][a[1]]) for a in arcs}
m += pulp.lpSum(f[a] for a in arcs if a[0] == S) - pulp.lpSum(f[a] for a in arcs if a[1] == S)
for n in cap:
    if n not in (S, T):
        m += pulp.lpSum(f[a] for a in arcs if a[1] == n) == pulp.lpSum(f[a] for a in arcs if a[0] == n), f"cons_{n}"

m.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=600))
status = pulp.LpStatus[m.status]
sol_status = pulp.LpSolution[m.sol_status]
print("STATUS:", status)
print("SOLUTION_STATUS:", sol_status)
if status == "Optimal" and sol_status == "Optimal Solution Found":
    print("FINAL_OBJECTIVE:", pulp.value(m.objective))
    for v in m.variables():
        if v.varValue and abs(v.varValue) > 1e-9:
            print(f"  {v.name} = {v.varValue}")
else:
    print("FINAL_OBJECTIVE: None")

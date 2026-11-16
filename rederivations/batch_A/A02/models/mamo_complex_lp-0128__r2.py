#!/usr/bin/env python3
import pulp
# Reading 2: the "From Node 8" line is taken as capacities INTO node 8 from nodes 0..6, overriding the
# values given earlier for those arcs (7->8 keeps its earlier value 6); node 8 has no outgoing arcs.
cap = {
    0: {1: 13, 2: 19, 3: 17, 4: 7, 5: 7, 6: 11, 7: 7, 8: 7},
    1: {0: 9, 2: 19, 3: 20, 4: 10, 5: 19, 6: 20, 7: 19, 8: 15},
    2: {0: 0, 1: 16, 3: 0, 4: 10, 5: 2, 6: 14, 7: 9, 8: 14},
    3: {0: 6, 1: 0, 2: 5, 4: 7, 5: 18, 6: 15, 7: 20, 8: 18},
    4: {0: 18, 1: 19, 2: 12, 3: 0, 5: 16, 6: 20, 7: 10, 8: 18},
    5: {0: 3, 1: 4, 2: 8, 3: 9, 4: 20, 6: 7, 7: 8, 8: 11},
    6: {0: 3, 1: 14, 2: 14, 3: 16, 4: 1, 5: 12, 7: 10, 8: 18},
    7: {0: 9, 1: 20, 2: 19, 3: 4, 4: 9, 5: 16, 6: 1, 8: 6},
    8: {},
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

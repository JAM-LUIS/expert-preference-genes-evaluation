#!/usr/bin/env python3
import pulp
# Set covering: choose areas for stores so every area has a store within 800 m.
within = {
    "A": ["A", "C", "E", "G", "H", "I"],
    "B": ["B", "H", "I"],
    "C": ["A", "C", "G", "H", "I"],
    "D": ["D", "J"],
    "E": ["A", "E", "G"],
    "F": ["F", "J", "K"],
    "G": ["A", "C", "E", "G"],
    "H": ["A", "B", "C", "H", "I"],
    "I": ["A", "B", "C", "H", "I"],
    "J": ["D", "F", "J", "K", "L"],
    "K": ["F", "J", "K", "L"],
    "L": ["J", "K", "L"],
}
m = pulp.LpProblem("set_cover", pulp.LpMinimize)
y = pulp.LpVariable.dicts("store", list(within), cat="Binary")
m += pulp.lpSum(y.values())
for a, nb in within.items():
    m += pulp.lpSum(y[b] for b in nb) >= 1, f"cover_{a}"

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

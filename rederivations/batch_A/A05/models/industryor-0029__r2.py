#!/usr/bin/env python3
# Preemptive goal programme solved lexicographically (P1 >> P2 >> P3).
# Reading 2: EXACT=False (True: staff placed in each post equals demand minus shortfall, no over-hiring;
#                       False: posts may receive more people than demanded, up to all 9000 applicants).
import pulp
EXACT = False
cities = ["Donghai", "Nanjiang"]
dem = {("Donghai", 1): 1000, ("Donghai", 2): 2000, ("Donghai", 3): 1500,
       ("Nanjiang", 1): 2000, ("Nanjiang", 2): 1000, ("Nanjiang", 3): 1000}
num = {i: 1500 for i in range(1, 7)}
suit = {1: [1, 2], 2: [2, 3], 3: [1, 3], 4: [1, 3], 5: [2, 3], 6: [3]}
prefS = {1: 1, 2: 2, 3: 1, 4: 3, 5: 3, 6: 3}
prefC = {1: "Donghai", 2: "Donghai", 3: "Nanjiang", 4: "Nanjiang", 5: "Donghai", 6: "Nanjiang"}
m = pulp.LpProblem("p0029", pulp.LpMinimize)
x = {(i, s, c): pulp.LpVariable(f"x_{i}_{s}_{c}", lowBound=0, cat="Integer") for i in suit for s in suit[i] for c in cities}
short = {k: pulp.LpVariable(f"short_{k[0]}_{k[1]}", lowBound=0, cat="Integer") for k in dem}
d2m = pulp.LpVariable("d2_minus", lowBound=0, cat="Integer"); d2p = pulp.LpVariable("d2_plus", lowBound=0, cat="Integer")
d3m = pulp.LpVariable("d3_minus", lowBound=0, cat="Integer"); d3p = pulp.LpVariable("d3_plus", lowBound=0, cat="Integer")
for i in suit:
    m += pulp.lpSum(x[i, s, c] for s in suit[i] for c in cities) <= num[i]
for (c, s), D in dem.items():
    lhs = pulp.lpSum(x[i, s, c] for i in suit if s in suit[i]) + short[c, s]
    m += (lhs == D) if EXACT else (lhs >= D)
m += pulp.lpSum(v for (i, s, c), v in x.items() if s == prefS[i]) + d2m - d2p == 8000
m += pulp.lpSum(v for (i, s, c), v in x.items() if c == prefC[i]) + d3m - d3p == 8000
solver = lambda: m.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=600))
P1 = pulp.lpSum(short.values())
m.setObjective(P1); solver(); v1 = pulp.value(P1); print("P1 total shortfall:", pulp.LpStatus[m.status], v1)
m += P1 <= v1
m.setObjective(d2m + 0); solver(); v2 = pulp.value(d2m); print("P2 d2_minus:", pulp.LpStatus[m.status], v2)
m += d2m <= v2
m.setObjective(d3m + 0); solver()
status = pulp.LpStatus[m.status]; sol = pulp.LpSolution[m.sol_status]
print("STATUS:", status); print("SOLUTION_STATUS:", sol)
if status == "Optimal" and sol == "Optimal Solution Found":
    print("FINAL_OBJECTIVE:", pulp.value(m.objective))
    for v in m.variables():
        if v.varValue and abs(v.varValue) > 1e-9: print(f"  {v.name} = {v.varValue}")
else:
    print("FINAL_OBJECTIVE: None")

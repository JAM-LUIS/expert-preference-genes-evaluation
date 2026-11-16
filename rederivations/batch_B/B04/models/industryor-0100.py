#!/usr/bin/env python3
# Max-bottleneck simple path A -> ... -> E visiting C; directed arcs row->column with bandwidth>0.
# Binary arc selection, flow conservation, MTZ to forbid subtours, z <= bw_ij + M(1-x_ij). Cross-checked by enumeration.
import pulp, itertools
N = ["A","B","C","D","E"]
bw = {"A":[0,90,85,0,65],"B":[95,0,70,65,34],"C":[60,0,0,88,80],"D":[67,30,25,0,84],"E":[0,51,0,56,0]}
arcs = {(i,N[j]): bw[i][j] for i in N for j in range(5) if bw[i][j] > 0 and i != N[j]}
M = max(arcs.values())
m = pulp.LpProblem("ior0100", pulp.LpMaximize)
x = {a: pulp.LpVariable(f"x_{a[0]}_{a[1]}", cat="Binary") for a in arcs}
u = {n: pulp.LpVariable(f"u_{n}", lowBound=0, upBound=len(N)-1) for n in N}
z = pulp.LpVariable("z", lowBound=0, upBound=M)
m += z
out = lambda n: pulp.lpSum(x[a] for a in arcs if a[0] == n)
inn = lambda n: pulp.lpSum(x[a] for a in arcs if a[1] == n)
m += out("A") == 1; m += inn("A") == 0
m += inn("E") == 1; m += out("E") == 0
for n in ["B","C","D"]:
    m += inn(n) == out(n); m += inn(n) <= 1
m += inn("C") == 1
for (i,j) in arcs:
    m += u[j] >= u[i] + 1 - len(N)*(1 - x[i,j])
    m += z <= arcs[i,j] + M*(1 - x[i,j])
m.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=600))
s = pulp.LpStatus[m.status]; ss = pulp.LpSolution[m.sol_status]
print("STATUS:", s); print("SOLUTION_STATUS:", ss)
if s == "Optimal" and ss == "Optimal Solution Found":
    print("FINAL_OBJECTIVE:", pulp.value(m.objective))
    print("  arcs:", [a for a in arcs if x[a].varValue > 0.5])
else: print("FINAL_OBJECTIVE: None")
best = (-1, None)
for r in range(0, 3):
    for mid in itertools.permutations(["B","C","D"], r+1):
        if "C" not in mid: continue
        p = ["A", *mid, "E"]
        if all((p[k],p[k+1]) in arcs for k in range(len(p)-1)):
            v = min(arcs[p[k],p[k+1]] for k in range(len(p)-1))
            if v > best[0]: best = (v, p)
print("ENUMERATION_CHECK:", best)

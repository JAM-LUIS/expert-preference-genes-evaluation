#!/usr/bin/env python3
import pulp

def report(m, relax=False):
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
    if relax:
        to_relax = [v for v in m.variables()
                    if v.cat == pulp.LpInteger and not (v.lowBound == 0 and v.upBound == 1)]
        for v in to_relax:
            v.cat = pulp.LpContinuous
        m.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=600))
        print("INTEGERS_RELAXED:", pulp.LpStatus[m.status], pulp.value(m.objective),
              f"({len(to_relax)} general-integer variables made continuous; binaries kept)")
        for v in to_relax:
            v.cat = pulp.LpInteger

START_ONLY_MONTH1 = False
EXACT = True
# x[i,j]: units of 100 m2 rented under a contract starting at month i with length j (integer).
# u[i,j]=1 if that contract is signed; w[j]=1 if some contract of length j is signed.
need = {1: 15, 2: 10, 3: 20, 4: 12}          # in units of 100 m2
fee = {1: 4000, 2: 7500, 3: 10500, 4: 13000}  # per 100 m2
starts = [1] if START_ONLY_MONTH1 else [1, 2, 3, 4]
keys = [(i, j) for i in starts for j in fee if i + j - 1 <= 4]
BIG = max(need.values()) if EXACT else 2 * max(need.values())
m = pulp.LpProblem("p0049", pulp.LpMinimize)
x = {k: pulp.LpVariable(f"x_{k[0]}_{k[1]}", lowBound=0, upBound=BIG, cat="Integer") for k in keys}
u = {k: pulp.LpVariable(f"u_{k[0]}_{k[1]}", cat="Binary") for k in keys}
w = {j: pulp.LpVariable(f"w_{j}", cat="Binary") for j in fee}
m += pulp.lpSum(fee[j] * x[i, j] for (i, j) in keys)
for t in need:
    cover = pulp.lpSum(x[i, j] for (i, j) in keys if i <= t <= i + j - 1)
    m += (cover == need[t]) if EXACT else (cover >= need[t])
for k in keys:
    m += x[k] <= BIG * u[k]
    m += x[k] >= u[k]
    m += u[k] <= w[k[1]]
for j in fee:
    m += w[j] <= pulp.lpSum(u[k] for k in keys if k[1] == j)
m += pulp.lpSum(w.values()) >= 2          # rule 2: at least two different lengths
# rule 3 dropped in this diagnostic reading
# rule 4 dropped in this diagnostic reading
report(m)

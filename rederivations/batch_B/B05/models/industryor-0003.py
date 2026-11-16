#!/usr/bin/env python3
import pulp

def report(m, relax=True):
    m.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=600))
    status = pulp.LpStatus[m.status]
    sol_status = pulp.LpSolution[m.sol_status]
    print("STATUS:", status)
    print("SOLUTION_STATUS:", sol_status)
    if status == "Optimal" and sol_status == "Optimal Solution Found":
        print("FINAL_OBJECTIVE:", pulp.value(m.objective))
        for v in m.variables():
            if v.varValue is not None and abs(v.varValue) > 1e-9:
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

# Six-month production / workforce plan, maximize net profit.
T = range(1, 7)
D = {1: 20000, 2: 40000, 3: 42000, 4: 35000, 5: 19000, 6: 18500}
m = pulp.LpProblem("ind0003", pulp.LpMaximize)
W = pulp.LpVariable.dicts("W", T, lowBound=0, cat="Integer")   # workers in month t
H = pulp.LpVariable.dicts("H", T, lowBound=0, cat="Integer")
F = pulp.LpVariable.dicts("F", T, lowBound=0, cat="Integer")
P = pulp.LpVariable.dicts("P", T, lowBound=0, cat="Integer")   # in-house units
C = pulp.LpVariable.dicts("C", T, lowBound=0, cat="Integer")   # outsourced units
O = pulp.LpVariable.dicts("O", T, lowBound=0)                  # overtime hours
I = pulp.LpVariable.dicts("I", T, lowBound=0, cat="Integer")   # end inventory
B = pulp.LpVariable.dicts("B", T, lowBound=0, cat="Integer")   # end backorder
S = pulp.LpVariable.dicts("S", T, lowBound=0, cat="Integer")   # units sold (delivered) in month t
revenue = pulp.lpSum(300 * S[t] for t in T)
cost = pulp.lpSum(90 * P[t] + 200 * C[t] + 15 * I[t] + 35 * B[t] + 30 * 160 * W[t] + 40 * O[t]
                  + 5000 * H[t] + 8000 * F[t] for t in T)
m += revenue - cost
for t in T:
    Wp = 1000 if t == 1 else W[t - 1]
    Ip = 15000 if t == 1 else I[t - 1]
    Bp = 0 if t == 1 else B[t - 1]
    m += W[t] == Wp + H[t] - F[t]
    m += 5 * P[t] <= 160 * W[t] + O[t]
    m += O[t] <= 20 * W[t]
    m += Ip + P[t] + C[t] - S[t] == I[t]          # inventory balance
    m += Bp + D[t] - S[t] == B[t]                 # backorder balance (sales serve backlog + current demand)
m += I[6] >= 10000
m += B[6] == 0
report(m)

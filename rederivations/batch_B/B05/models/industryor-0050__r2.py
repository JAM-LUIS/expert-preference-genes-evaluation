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

# Reading 2: goods sold in month t come only from stock held before that month's purchase
# (purchased goods are for later months); stock after purchase <= 500.
buy = [28, 24, 25, 27, 23, 23]
sell = [29, 24, 26, 28, 22, 25]
m = pulp.LpProblem("ind0050r2", pulp.LpMaximize)
x = [pulp.LpVariable(f"buy{t}", lowBound=0) for t in range(6)]
y = [pulp.LpVariable(f"sell{t}", lowBound=0) for t in range(6)]
I = [pulp.LpVariable(f"inv{t}", lowBound=0) for t in range(6)]
m += pulp.lpSum(sell[t] * y[t] - buy[t] * x[t] for t in range(6))
for t in range(6):
    Ip = 200 if t == 0 else I[t - 1]
    m += Ip + x[t] <= 500
    m += y[t] <= Ip
    m += I[t] == Ip + x[t] - y[t]
report(m, relax=False)

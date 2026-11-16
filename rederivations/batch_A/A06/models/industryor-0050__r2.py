#!/usr/bin/env python3
# industryor-0050: buy x_t at the start of month t, sell y_t during month t; stock after buying <= 500.
# MODE "buyfirst": goods bought this month can be sold this month. MODE "sellfirst": sales only from opening stock,
# and stock after selling and buying <= 500.
import pulp

def report(m, extra=None):
    status = pulp.LpStatus[m.status]; sol = pulp.LpSolution[m.sol_status]
    print("STATUS:", status); print("SOLUTION_STATUS:", sol)
    if status == "Optimal" and sol == "Optimal Solution Found":
        print("FINAL_OBJECTIVE:", pulp.value(m.objective) if extra is None else extra)
        for v in m.variables():
            if v.varValue and abs(v.varValue) > 1e-9: print(f"  {v.name} = {v.varValue}")
    else:
        print("FINAL_OBJECTIVE: None")
SOLVER = lambda: pulp.PULP_CBC_CMD(msg=False, timeLimit=600)
def relax_and_report(m):
    to_relax = [v for v in m.variables() if v.cat == pulp.LpInteger and not (v.lowBound == 0 and v.upBound == 1)]
    for v in to_relax: v.cat = pulp.LpContinuous
    m.solve(SOLVER())
    print("INTEGERS_RELAXED:", pulp.LpStatus[m.status], pulp.value(m.objective), f"({len(to_relax)} general-integer variables made continuous; binaries kept)")
    for v in to_relax: v.cat = pulp.LpInteger

MODE = "sellfirst"
buy = [28, 24, 25, 27, 23, 23]; sell = [29, 24, 26, 28, 22, 25]
m = pulp.LpProblem("p", pulp.LpMaximize)
x = [pulp.LpVariable(f"buy{t+7}", lowBound=0) for t in range(6)]
y = [pulp.LpVariable(f"sell{t+7}", lowBound=0) for t in range(6)]
m += pulp.lpSum(sell[t] * y[t] - buy[t] * x[t] for t in range(6))
s = 200
for t in range(6):
    if MODE == "buyfirst":
        m += s + x[t] <= 500
        m += y[t] <= s + x[t]
    else:
        m += y[t] <= s
        m += s - y[t] + x[t] <= 500
    s = s + x[t] - y[t]
m.solve(SOLVER())
report(m)

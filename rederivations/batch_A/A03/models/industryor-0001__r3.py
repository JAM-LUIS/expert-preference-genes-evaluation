#!/usr/bin/env python3
# industryor-0001: workforce training / production plan over 8 weeks. TERMINAL_ZERO=False
import pulp

def report(m, relax=False):
    m.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=600))
    status = pulp.LpStatus[m.status]; sol = pulp.LpSolution[m.sol_status]
    print("STATUS:", status); print("SOLUTION_STATUS:", sol)
    if status == "Optimal" and sol == "Optimal Solution Found":
        print("FINAL_OBJECTIVE:", pulp.value(m.objective))
        for v in m.variables():
            if v.varValue and abs(v.varValue) > 1e-9: print(f"  {v.name} = {v.varValue}")
    else:
        print("FINAL_OBJECTIVE: None")
    if relax:
        tr = [v for v in m.variables() if v.cat == pulp.LpInteger and not (v.lowBound == 0 and v.upBound == 1)]
        for v in tr: v.cat = pulp.LpContinuous
        m.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=600))
        print("INTEGERS_RELAXED:", pulp.LpStatus[m.status], pulp.value(m.objective), f"({len(tr)} general-integer variables made continuous; binaries kept)")
        for v in tr: v.cat = pulp.LpInteger

TERMINAL_ZERO = False   # True: all booked food must be delivered by end of week 8
T = range(1, 9)
dI = dict(zip(T, [10000, 10000, 12000, 12000, 16000, 16000, 20000, 20000]))
dII = dict(zip(T, [6000, 7200, 8400, 10800, 10800, 12000, 12000, 12000]))
m = pulp.LpProblem("io0001", pulp.LpMinimize)
I = "Integer"
a1 = pulp.LpVariable.dicts("norm_I", T, 0, cat=I)     # skilled, 40h, food I
a2 = pulp.LpVariable.dicts("norm_II", T, 0, cat=I)
o1 = pulp.LpVariable.dicts("over_I", T, 0, cat=I)     # skilled, 60h, food I
o2 = pulp.LpVariable.dicts("over_II", T, 0, cat=I)
w = pulp.LpVariable.dicts("trainers_start", range(1, 8), 0, cat=I)   # training occupies weeks t, t+1
n = pulp.LpVariable.dicts("trainees_start", range(1, 8), 0, cat=I)
b1 = pulp.LpVariable.dicts("new_I", T, 0, cat=I)      # trained new workers on food I
b2 = pulp.LpVariable.dicts("new_II", T, 0, cat=I)
B1 = pulp.LpVariable.dicts("backlog_I", T, 0)
B2 = pulp.LpVariable.dicts("backlog_II", T, 0)
S1 = pulp.LpVariable.dicts("stock_I", T, 0, 0)  # no production ahead of demand
S2 = pulp.LpVariable.dicts("stock_II", T, 0, 0)
def N(t):  # new workers that have finished training before week t
    return pulp.lpSum(n[s] for s in range(1, 8) if s + 2 <= t)
def intrain(t):
    return pulp.lpSum(n[s] for s in range(1, 8) if s in (t, t - 1))
for t in T:
    m += a1[t] + a2[t] + o1[t] + o2[t] + pulp.lpSum(w[s] for s in (t, t - 1) if 1 <= s <= 7) <= 50, f"skilled_{t}"
    m += b1[t] + b2[t] <= N(t), f"new_{t}"
    prodI = 10 * 40 * (a1[t] + b1[t]) + 10 * 60 * o1[t]
    prodII = 6 * 40 * (a2[t] + b2[t]) + 6 * 60 * o2[t]
    pI = (S1[t - 1] - B1[t - 1]) if t > 1 else 0
    pII = (S2[t - 1] - B2[t - 1]) if t > 1 else 0
    m += S1[t] - B1[t] == pI + prodI - dI[t], f"balI_{t}"
    m += S2[t] - B2[t] == pII + prodII - dII[t], f"balII_{t}"
for s in range(1, 8):
    m += n[s] <= 3 * w[s], f"ratio_{s}"
m += pulp.lpSum(n[s] for s in range(1, 8)) == 50, "train50"
if TERMINAL_ZERO:
    m += B1[8] == 0; m += B2[8] == 0
m += (360 * 50 * 8 + (540 - 360) * pulp.lpSum(o1[t] + o2[t] for t in T)
      + 120 * pulp.lpSum(intrain(t) for t in T) + 240 * pulp.lpSum(N(t) for t in T)
      + 0.5 * pulp.lpSum(B1[t] for t in T) + 0.6 * pulp.lpSum(B2[t] for t in T)), "total_cost"
report(m, relax=True)

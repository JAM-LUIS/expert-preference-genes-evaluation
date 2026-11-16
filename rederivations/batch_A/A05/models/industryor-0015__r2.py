#!/usr/bin/env python3
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

# Tool purchase / repair (caterer problem). Tools sent to repair at end of stage j are usable in stage j + duration + LAG.
# Reading 2: LAG = 1
LAG = 1
n = 10; r = [3, 5, 2, 4, 6, 5, 4, 3, 2, 1]; a = 10; b = 1; c = 3; p = 3; q = 1
J = range(1, n + 1)
m = pulp.LpProblem("p0015", pulp.LpMinimize)
buy = pulp.LpVariable.dicts("buy", J, lowBound=0, cat="Integer")
slow = pulp.LpVariable.dicts("slow", J, lowBound=0, cat="Integer")
fast = pulp.LpVariable.dicts("fast", J, lowBound=0, cat="Integer")
clean = pulp.LpVariable.dicts("clean", J, lowBound=0, cat="Integer")   # unused clean tools carried after stage j
dirty = pulp.LpVariable.dicts("dirty", J, lowBound=0, cat="Integer")   # used tools not (yet) sent to repair after stage j
m += pulp.lpSum(a * buy[j] + b * slow[j] + c * fast[j] for j in J)
for j in J:
    arr = 0
    if j - p - LAG >= 1: arr += slow[j - p - LAG]
    if j - q - LAG >= 1: arr += fast[j - q - LAG]
    m += (clean[j-1] if j > 1 else 0) + buy[j] + arr == r[j-1] + clean[j]
    m += (dirty[j-1] if j > 1 else 0) + r[j-1] == slow[j] + fast[j] + dirty[j]
report(m)

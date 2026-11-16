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
            if v.varValue:
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

import sys
sys.argv = [sys.argv[0]] + ['trim']   # fixed variant of industryor-0069
import sys
MODE = sys.argv[1] if len(sys.argv) > 1 else "main"
# all cutting patterns (i pieces of 3 m, j pieces of 4 m) from a 10 m bar
pats = [(i, j) for i in range(4) for j in range(3) if 3 * i + 4 * j <= 10 and i + j > 0]
m = pulp.LpProblem("p", pulp.LpMinimize)
n = {p: pulp.LpVariable(f"n_{p[0]}_{p[1]}", lowBound=0, cat="Integer") for p in pats}
if MODE == "main":
    # exact demand; waste = everything that is not a required piece = 10*bars - (90*3 + 60*4)
    m += pulp.lpSum((10 - 3 * p[0] - 4 * p[1]) * n[p] for p in pats)
    m += pulp.lpSum(p[0] * n[p] for p in pats) == 90
    m += pulp.lpSum(p[1] * n[p] for p in pats) == 60
elif MODE == "trim":
    # demand may be exceeded, only trim loss counted (surplus pieces not counted as waste)
    m += pulp.lpSum((10 - 3 * p[0] - 4 * p[1]) * n[p] for p in pats)
    m += pulp.lpSum(p[0] * n[p] for p in pats) >= 90
    m += pulp.lpSum(p[1] * n[p] for p in pats) >= 60
report(m, relax=True)
print("  bars used (last solve) =", sum(v.varValue for v in n.values()))

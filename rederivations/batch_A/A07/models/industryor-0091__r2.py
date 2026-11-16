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
sys.argv = [sys.argv[0]] + ['batch']   # fixed variant of industryor-0091
import sys
MODE = sys.argv[1] if len(sys.argv) > 1 else "ratio"
m = pulp.LpProblem("p", pulp.LpMaximize)
a = pulp.LpVariable("A", lowBound=0, cat="Integer")
b = pulp.LpVariable("B", lowBound=0, cat="Integer")
m += 3 * a + 5 * b
m += 12 * a + 25 * b <= 30 * 60
if MODE == "ratio":
    m += 5 * b >= 2 * a
else:   # per complete batch of five A: B >= 2*floor(A/5)
    k = pulp.LpVariable("k", lowBound=0, cat="Integer")
    m += a <= 5 * k + 4
    m += b >= 2 * k
report(m, relax=(MODE == "ratio"))

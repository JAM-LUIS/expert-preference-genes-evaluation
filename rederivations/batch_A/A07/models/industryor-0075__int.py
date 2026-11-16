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
sys.argv = [sys.argv[0]] + ['int']   # fixed variant of industryor-0075
import sys
INT = len(sys.argv) > 1 and sys.argv[1] == "int"
cat = "Integer" if INT else "Continuous"
m = pulp.LpProblem("p", pulp.LpMaximize)
a = pulp.LpVariable("A", lowBound=0, cat=cat)
b = pulp.LpVariable("B", lowBound=0, cat=cat)
cs = pulp.LpVariable("C_sold", lowBound=0, upBound=5)
cd = pulp.LpVariable("C_disposed", lowBound=0)
m += 4 * a + 10 * b + 3 * cs - 2 * cd
m += 2 * a + 3 * b <= 16
m += 3 * a + 4 * b <= 24
m += cs + cd == 2 * b
report(m)

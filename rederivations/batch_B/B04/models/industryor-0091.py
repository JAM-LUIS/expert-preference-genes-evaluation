#!/usr/bin/env python3
# Max 3A + 5B; 12A + 25B <= 1800 min; 5B >= 2A. Units integer (main).
import pulp
m = pulp.LpProblem("ior0091", pulp.LpMaximize)
A = pulp.LpVariable("A", lowBound=0, cat="Integer"); B = pulp.LpVariable("B", lowBound=0, cat="Integer")
m += 3*A + 5*B
m += 12*A + 25*B <= 30*60
m += 5*B >= 2*A
m.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=600))
s = pulp.LpStatus[m.status]; ss = pulp.LpSolution[m.sol_status]
print("STATUS:", s); print("SOLUTION_STATUS:", ss)
if s == "Optimal" and ss == "Optimal Solution Found":
    print("FINAL_OBJECTIVE:", pulp.value(m.objective))
    for v in m.variables(): print(" ", v.name, v.varValue)
else: print("FINAL_OBJECTIVE: None")
to_relax = [v for v in m.variables() if v.cat == pulp.LpInteger and not (v.lowBound == 0 and v.upBound == 1)]
for v in to_relax: v.cat = pulp.LpContinuous
m.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=600))
print("INTEGERS_RELAXED:", pulp.LpStatus[m.status], pulp.value(m.objective), [ (v.name, v.varValue) for v in m.variables()])

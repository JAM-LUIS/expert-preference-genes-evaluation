#!/usr/bin/env python3
# mamo_complex_lp-0021: diet LP (continuous servings); integer version printed via INTEGER_VERSION line.
import pulp
F = {'Chicken':(16,22,292,5), 'Cheese':(10,4,82,9), 'Rice':(12,21,207,2), 'Beans':(13,14,81,1)}
req = (94, 191, 2271)
def build(cat):
    m = pulp.LpProblem("diet", pulp.LpMinimize)
    x = {f: pulp.LpVariable(f"x_{f}", lowBound=0, cat=cat) for f in F}
    m += pulp.lpSum(F[f][3]*x[f] for f in F)
    for k in range(3):
        m += pulp.lpSum(F[f][k]*x[f] for f in F) >= req[k]
    return m
mi = build("Integer"); mi.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=600))
print("INTEGER_VERSION:", pulp.LpStatus[mi.status], pulp.value(mi.objective))
m = build("Continuous")
m.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=600))
status = pulp.LpStatus[m.status]
sol_status = pulp.LpSolution[m.sol_status]
print("STATUS:", status)
print("SOLUTION_STATUS:", sol_status)
if status == "Optimal" and sol_status == "Optimal Solution Found":
    print("FINAL_OBJECTIVE:", pulp.value(m.objective))
    for v in m.variables():
        print(f"  {v.name} = {v.varValue}")
else:
    print("FINAL_OBJECTIVE: None")

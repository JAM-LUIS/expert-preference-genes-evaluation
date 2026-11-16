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
# mamo_complex_lp-0207: Sailco production planning
d = [40,60,75,25]
m = pulp.LpProblem("mamo0207", pulp.LpMinimize)
r = [pulp.LpVariable(f"regular{q+1}", lowBound=0, upBound=40, cat="Integer") for q in range(4)]
o = [pulp.LpVariable(f"overtime{q+1}", lowBound=0, cat="Integer") for q in range(4)]
I = [pulp.LpVariable(f"inv_end{q+1}", lowBound=0, cat="Integer") for q in range(4)]
for q in range(4):
    prev = 10 if q == 0 else I[q-1]
    m += prev + r[q] + o[q] - d[q] == I[q]
m += pulp.lpSum(400*r[q] + 450*o[q] + 20*I[q] for q in range(4))
report(m, relax=True)

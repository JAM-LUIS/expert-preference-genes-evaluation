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

# industryor-0072: buy properties 1..4 (binary)
inc = [12500, 35000, 23000, 100000]
cost = [1.5e6, 2.1e6, 2.3e6, 4.2e6]
m = pulp.LpProblem("io0072", pulp.LpMaximize)
y = [pulp.LpVariable(f"buy{i+1}", cat="Binary") for i in range(4)]
m += pulp.lpSum(inc[i]*y[i] for i in range(4))
m += pulp.lpSum(cost[i]*y[i] for i in range(4)) <= 7e6
m += y[3] + y[2] <= 1
report(m)

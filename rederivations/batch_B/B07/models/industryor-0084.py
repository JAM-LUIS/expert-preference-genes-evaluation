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

# industryor-0084: hire candidates A..E (binary)
c = ["A","B","C","D","E"]
sal = dict(A=8100,B=20000,C=21000,D=3000,E=8000)
exp_ = dict(A=3,B=10,C=4,D=3,E=7)
m = pulp.LpProblem("io0084", pulp.LpMinimize)
y = {k: pulp.LpVariable(f"hire_{k}", cat="Binary") for k in c}
m += pulp.lpSum(sal[k]*y[k] for k in c)
m += pulp.lpSum(y.values()) <= 3
m += pulp.lpSum(sal[k]*y[k] for k in c) <= 35000
m += y["B"] + y["C"] >= 1
m += pulp.lpSum(exp_[k]*y[k] for k in c) >= 12
m += y["A"] + y["E"] <= 1
m += pulp.lpSum(y.values()) >= 2
report(m)

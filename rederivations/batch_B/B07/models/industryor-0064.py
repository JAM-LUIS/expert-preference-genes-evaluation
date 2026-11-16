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

# industryor-0064: hire candidates F,G,H,I,J (binary)
c = ["F","G","H","I","J"]
sal = dict(F=12000,G=15000,H=18000,I=5000,J=10000)
skl = dict(F=2,G=3,H=4,I=1,J=2)
exp_ = dict(F=1,G=2,H=2,I=5,J=4)
m = pulp.LpProblem("io0064", pulp.LpMinimize)
y = {k: pulp.LpVariable(f"hire_{k}", cat="Binary") for k in c}
m += pulp.lpSum(sal[k]*y[k] for k in c)
m += pulp.lpSum(sal[k]*y[k] for k in c) <= 40000
m += pulp.lpSum(y.values()) <= 4
m += pulp.lpSum(skl[k]*y[k] for k in c) >= 8
m += pulp.lpSum(exp_[k]*y[k] for k in c) >= 8
m += y["G"] + y["J"] <= 1
report(m)

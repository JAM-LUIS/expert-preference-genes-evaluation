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
# industryor-0047: farm plan
m = pulp.LpProblem("io0047", pulp.LpMaximize)
s = pulp.LpVariable("soy_ha", lowBound=0)
c = pulp.LpVariable("corn_ha", lowBound=0)
w = pulp.LpVariable("wheat_ha", lowBound=0)
cow = pulp.LpVariable("cows", lowBound=0, upBound=32, cat="Integer")
hen = pulp.LpVariable("chickens", lowBound=0, upBound=3000, cat="Integer")
eaw = pulp.LpVariable("ext_days_aw", lowBound=0, cat="Integer")
ess = pulp.LpVariable("ext_days_ss", lowBound=0, cat="Integer")
m += 175*s + 300*c + 120*w + 400*cow + 2*hen + 1.8*eaw + 2.1*ess
m += s + c + w + 1.5*cow <= 100
m += 400*cow + 3*hen <= 15000
m += 20*s + 35*c + 10*w + 100*cow + 0.6*hen + eaw <= 3500
m += 50*s + 75*c + 40*w + 50*cow + 0.3*hen + ess <= 4000
report(m, relax=True)

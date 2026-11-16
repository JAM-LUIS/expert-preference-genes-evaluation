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
# industryor-0080: method choice per task; integer workers/groups; group hours = sum of members' hours
SK, LB = 42, 36
m = pulp.LpProblem("io0080", pulp.LpMinimize)
y1B = pulp.LpVariable("t1_methodB", cat="Binary")   # 0 -> method A
y2B = pulp.LpVariable("t2_methodB", cat="Binary")
y3B = pulp.LpVariable("t3_methodB", cat="Binary")
s1A = pulp.LpVariable("t1A_skilled", lowBound=0, cat="Integer")
g1B = pulp.LpVariable("t1B_groups", lowBound=0, cat="Integer")
s2A = pulp.LpVariable("t2A_skilled", lowBound=0, cat="Integer")
l2B = pulp.LpVariable("t2B_laborers", lowBound=0, cat="Integer")
g3A = pulp.LpVariable("t3A_groups5L", lowBound=0, cat="Integer")
g3B = pulp.LpVariable("t3B_groups1S3L", lowBound=0, cat="Integer")
MS, ML = 400, 800
# hours requirements
m += SK*s1A + (SK+2*LB)*g1B >= 8400
m += SK*s2A + LB*l2B >= 10800
m += 5*LB*g3A + (SK+3*LB)*g3B >= 18000
# only chosen method used (big-M from worker limits)
m += s1A <= MS*(1-y1B)
m += g1B <= MS*y1B
m += s2A <= MS*(1-y2B)
m += l2B <= ML*y2B
m += 5*g3A <= ML*(1-y3B)
m += g3B <= MS*y3B
skilled = s1A + g1B + s2A + g3B
labor = 2*g1B + l2B + 5*g3A + 3*g3B
m += skilled <= MS
m += labor <= ML
m += y1B <= y3B                       # task1 B => task3 not A
m += g3B >= 20*y3B                    # min 20 skilled if task3 B
m += skilled <= 0.6*labor
m += 100*skilled + 80*labor + 500*y1B
report(m, relax=True)

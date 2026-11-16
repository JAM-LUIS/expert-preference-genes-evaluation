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
# mamo_complex_lp-0036: diet problem, integer servings (main), relaxed reported
foods = {1:(6,3,73,6), 2:(16,3,181,2), 3:(12,17,231,10), 4:(9,28,160,6), 5:(12,17,209,4), 6:(12,14,184,1), 7:(13,20,118,9)}
m = pulp.LpProblem("mamo0036", pulp.LpMinimize)
x = {f: pulp.LpVariable(f"n_food{f}", lowBound=0, cat="Integer") for f in foods}
m += pulp.lpSum(foods[f][3]*x[f] for f in foods)
m += pulp.lpSum(foods[f][0]*x[f] for f in foods) >= 59
m += pulp.lpSum(foods[f][1]*x[f] for f in foods) >= 179
m += pulp.lpSum(foods[f][2]*x[f] for f in foods) >= 2414
report(m, relax=True)

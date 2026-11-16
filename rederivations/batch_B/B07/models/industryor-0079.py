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

# industryor-0079: tables t, chairs c, bookshelves b (integer)
m = pulp.LpProblem("io0079", pulp.LpMaximize)
t = pulp.LpVariable("tables", lowBound=0, cat="Integer")
c = pulp.LpVariable("chairs", lowBound=0, cat="Integer")
b = pulp.LpVariable("bookshelves", lowBound=0, cat="Integer")
m += (200-120)*t + (50-20)*c + (150-90)*b
m += 5*t + 2*c + 3*b <= 500
m += t >= 10
m += b >= 20
m += t + c + b <= 200
report(m, relax=True)

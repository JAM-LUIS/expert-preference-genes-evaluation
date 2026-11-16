import pulp
m = pulp.LpProblem("farm", pulp.LpMaximize)
c = pulp.LpVariable("cows", lowBound=10, cat="Integer")
s = pulp.LpVariable("sheep", lowBound=20, cat="Integer")
h = pulp.LpVariable("chickens", lowBound=0, upBound=50, cat="Integer")
m += (500-100)*c + (200-80)*s + (8-5)*h
m += 10*c + 5*s + 3*h <= 800, "manure"
m += c + s + h <= 100, "total"

m.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=600))
status = pulp.LpStatus[m.status]
sol_status = pulp.LpSolution[m.sol_status]
print("STATUS:", status)
print("SOLUTION_STATUS:", sol_status)
if status == "Optimal" and sol_status == "Optimal Solution Found":
    print("FINAL_OBJECTIVE:", pulp.value(m.objective))
    for v in m.variables():
        if v.varValue and abs(v.varValue) > 1e-9:
            print(f"  {v.name} = {v.varValue}")
else:
    print("FINAL_OBJECTIVE: None")


to_relax = [v for v in m.variables() if v.cat == pulp.LpInteger and not (v.lowBound == 0 and v.upBound == 1)]
for v in to_relax:
    v.cat = pulp.LpContinuous
m.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=600))
print("INTEGERS_RELAXED:", pulp.LpStatus[m.status], pulp.value(m.objective), f"({len(to_relax)} general-integer variables made continuous; binaries kept)")


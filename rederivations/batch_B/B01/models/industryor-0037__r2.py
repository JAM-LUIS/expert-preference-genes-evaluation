# Reading 2: lexicographic goal programming with deviation variables (p1 profit, p2 contracts, p3 process times),
# then maximize profit among goal-optimal plans. Process I capacity 150 treated as soft goal only (overtime only in II).
import pulp
m = pulp.LpProblem("ior0037_r2", pulp.LpMinimize)
A = pulp.LpVariable("A", lowBound=0, cat="Integer"); B = pulp.LpVariable("B", lowBound=0, cat="Integer")
dv = {n: pulp.LpVariable(n, lowBound=0) for n in ["d1m","d1p","d2am","d2ap","d2bm","d2bp","d3m","d3p","d4m","d4p"]}
m += 300*A + 450*B + dv["d1m"] - dv["d1p"] == 10000
m += A + dv["d2am"] - dv["d2ap"] == 10
m += B + dv["d2bm"] - dv["d2bp"] == 15
m += 4*A + 6*B + dv["d3m"] - dv["d3p"] == 150
m += 3*A + 2*B + dv["d4m"] - dv["d4p"] == 70
goals = [dv["d1m"], dv["d2am"]+dv["d2bm"], dv["d3m"]+dv["d3p"]+dv["d4m"]]
for g in goals:
    m.setObjective(g); m.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=600))
    gv = pulp.value(m.objective); print("goal value", gv)
    m += g <= gv + 1e-6
m.sense = pulp.LpMaximize
m.setObjective(300*A + 450*B); m.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=600))
status = pulp.LpStatus[m.status]; ss = pulp.LpSolution[m.sol_status]
print("STATUS:", status); print("SOLUTION_STATUS:", ss)
print("FINAL_OBJECTIVE:", pulp.value(m.objective) if status=="Optimal" and ss=="Optimal Solution Found" else None)
print("A", A.varValue, "B", B.varValue)

#!/usr/bin/env python3
# Project LP: start times; precedence; T >= finish of all; cost = 1000*T (project duration, start at time 0)
# + 5000*(finish_B - start_A) machine rental.
import pulp, sys
WORK = "activity_days"
dur = {"A":4,"B":3,"C":5,"D":2,"E":10,"F":10,"G":1}
prec = [("A","G"),("A","D"),("E","F"),("G","F"),("D","C"),("F","C"),("F","B")]
m = pulp.LpProblem("ior0074", pulp.LpMinimize)
st = {a: pulp.LpVariable(f"s_{a}", lowBound=0) for a in dur}
T = pulp.LpVariable("T", lowBound=0)
work = 1000*T if WORK == "duration" else 1000*sum(dur.values())
m += work + 5000*(st["B"] + dur["B"] - st["A"])
for i,j in prec: m += st[j] >= st[i] + dur[i]
for a in dur: m += T >= st[a] + dur[a]
m.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=600))
s = pulp.LpStatus[m.status]; ss = pulp.LpSolution[m.sol_status]
print("STATUS:", s); print("SOLUTION_STATUS:", ss)
if s == "Optimal" and ss == "Optimal Solution Found":
    print("FINAL_OBJECTIVE:", pulp.value(m.objective))
    for v in m.variables(): print(" ", v.name, v.varValue)
else: print("FINAL_OBJECTIVE: None")

#!/usr/bin/env python3
# industryor-0074: start times s_k >= 0; T = project completion; machine rented from start of A to end of B.
# MODE "duration": cost = 1000*T + 5000*(end_B - start_A).
# MODE "activitydays": cost = 1000*(sum of activity durations) + 5000*(end_B - start_A).
import pulp

def report(m, extra=None):
    status = pulp.LpStatus[m.status]; sol = pulp.LpSolution[m.sol_status]
    print("STATUS:", status); print("SOLUTION_STATUS:", sol)
    if status == "Optimal" and sol == "Optimal Solution Found":
        print("FINAL_OBJECTIVE:", pulp.value(m.objective) if extra is None else extra)
        for v in m.variables():
            if v.varValue and abs(v.varValue) > 1e-9: print(f"  {v.name} = {v.varValue}")
    else:
        print("FINAL_OBJECTIVE: None")
SOLVER = lambda: pulp.PULP_CBC_CMD(msg=False, timeLimit=600)
def relax_and_report(m):
    to_relax = [v for v in m.variables() if v.cat == pulp.LpInteger and not (v.lowBound == 0 and v.upBound == 1)]
    for v in to_relax: v.cat = pulp.LpContinuous
    m.solve(SOLVER())
    print("INTEGERS_RELAXED:", pulp.LpStatus[m.status], pulp.value(m.objective), f"({len(to_relax)} general-integer variables made continuous; binaries kept)")
    for v in to_relax: v.cat = pulp.LpInteger

MODE = "duration"
dur = {"A": 4, "B": 3, "C": 5, "D": 2, "E": 10, "F": 10, "G": 1}
prec = [("A", "G"), ("A", "D"), ("E", "F"), ("G", "F"), ("D", "C"), ("F", "C"), ("F", "B")]
m = pulp.LpProblem("p", pulp.LpMinimize)
s = {k: pulp.LpVariable("s_" + k, lowBound=0) for k in dur}
T = pulp.LpVariable("T", lowBound=0)
for a, b in prec: m += s[b] >= s[a] + dur[a]
for k in dur: m += T >= s[k] + dur[k]
rent = 5000 * (s["B"] + dur["B"] - s["A"])
m += (1000 * T if MODE == "duration" else 1000 * sum(dur.values())) + rent
m.solve(SOLVER())
report(m)

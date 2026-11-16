#!/usr/bin/env python3
# Preemptive (lexicographic) goal programme; the five numbered plan constraints are taken as goals
# in priority order 1..5. Reported objective = sum of the unwanted deviations over all priority levels.
import pulp

def build():
    m = pulp.LpProblem("goal_programme", pulp.LpMinimize)
    x1 = pulp.LpVariable("microwaves", lowBound=0, cat="Integer")
    x2 = pulp.LpVariable("water_heaters", lowBound=0, cat="Integer")
    d = {k: pulp.LpVariable("dev_" + k, lowBound=0) for k in
         ["cost_over", "mw_short", "A_idle", "A_over", "B_idle", "B_over", "A_ot_over20", "wh_short"]}
    m += 30 * x1 + 50 * x2 - d["cost_over"] <= 5500                      # goal 1
    m += x1 + d["mw_short"] >= 80                                        # goal 2
    m += 2 * x1 + 1 * x2 + d["A_idle"] - d["A_over"] == 250              # workshop A hours
    m += 1 * x1 + 3 * x2 + d["B_idle"] - d["B_over"] == 150              # workshop B hours
    m += d["A_over"] - d["A_ot_over20"] <= 20                            # goal 4
    m += x2 + d["wh_short"] >= 50                                        # goal 5
    levels = [d["cost_over"], d["mw_short"], d["A_idle"] + d["B_idle"], d["A_ot_over20"], d["wh_short"]]
    return m, levels, (x1, x2), d

m, levels, xs, d = build()
ok, vals = True, []
for k, expr in enumerate(levels):
    m.setObjective(expr)
    m.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=600))
    if not (pulp.LpStatus[m.status] == "Optimal" and pulp.LpSolution[m.sol_status] == "Optimal Solution Found"):
        ok = False
        break
    v = pulp.value(expr)
    vals.append(v)
    m += expr <= v + 1e-7, f"fix_level_{k+1}"
print("STATUS:", pulp.LpStatus[m.status])
print("SOLUTION_STATUS:", pulp.LpSolution[m.sol_status])
if ok:
    print("FINAL_OBJECTIVE:", float(sum(vals)))
    print("  level values:", vals)
    for v in m.variables():
        print(f"  {v.name} = {v.varValue}")
else:
    print("FINAL_OBJECTIVE: None")

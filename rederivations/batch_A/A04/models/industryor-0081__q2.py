#!/usr/bin/env python3
# Second question of the statement: one side may hold at most 30 m of cars.
import os, sys, importlib.util
here = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("base", os.path.join(here, "industryor-0081.py"))
base = importlib.util.module_from_spec(spec); spec.loader.exec_module(base)
import pulp
m = base.build(30)
m.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=600))
status = pulp.LpStatus[m.status]; sol = pulp.LpSolution[m.sol_status]
print("STATUS:", status); print("SOLUTION_STATUS:", sol)
if status == "Optimal" and sol == "Optimal Solution Found":
    print("FINAL_OBJECTIVE:", round(pulp.value(m.objective), 6))
else:
    print("FINAL_OBJECTIVE: None")

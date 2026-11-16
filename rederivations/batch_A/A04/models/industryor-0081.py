#!/usr/bin/env python3
# Park 15 cars on two sides of the street; minimise the occupied street length = max(side lengths).
# Lengths are in tenths of a metre (integers) to keep the arithmetic exact; objective is printed in metres.
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pulp
lam = [4, 4.5, 5, 4.1, 2.4, 5.2, 3.7, 3.5, 3.2, 4.5, 2.3, 3.3, 3.8, 4.6, 3]
n = len(lam)
SIDE_LIMIT = None  # second question: 30 (see __q2 script)
def build(limit):
    m = pulp.LpProblem("ior0081", pulp.LpMinimize)
    x = pulp.LpVariable.dicts("left", range(n), cat="Binary")
    z = pulp.LpVariable("z", lowBound=0)
    m += z
    left = pulp.lpSum(lam[i] * x[i] for i in range(n))
    right = pulp.lpSum(lam[i] * (1 - x[i]) for i in range(n))
    m += z >= left
    m += z >= right
    if limit is not None:
        m += left <= limit
    return m
if __name__ == "__main__":
    m = build(SIDE_LIMIT)
    m.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=600))
    status = pulp.LpStatus[m.status]; sol = pulp.LpSolution[m.sol_status]
    print("STATUS:", status); print("SOLUTION_STATUS:", sol)
    if status == "Optimal" and sol == "Optimal Solution Found":
        print("FINAL_OBJECTIVE:", round(pulp.value(m.objective), 6))
        for v in m.variables():
            print(f"  {v.name} = {v.varValue}")
    else:
        print("FINAL_OBJECTIVE: None")

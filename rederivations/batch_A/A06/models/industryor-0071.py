#!/usr/bin/env python3
# industryor-0071: x[i,p]=1 if factory i is at location p.
# MODE "qap": min sum d_ij c_pq x_ip x_jq over all i,j,p,q (products linearised with binary w).
# MODE "qap_offdiag": same but only i != j.  MODE "linear": min sum d_ip*c_ip*x_ip (table headers read literally).
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

MODE = "qap"
d = {(1, 1): 10, (1, 2): 20, (2, 1): 30, (2, 2): 40}
c = {(1, 1): 5, (1, 2): 8, (2, 1): 6, (2, 2): 7}
N = (1, 2)
m = pulp.LpProblem("p", pulp.LpMinimize)
x = {(i, p): pulp.LpVariable(f"x_{i}_{p}", cat="Binary") for i in N for p in N}
for i in N: m += pulp.lpSum(x[i, p] for p in N) == 1
for p in N: m += pulp.lpSum(x[i, p] for i in N) == 1
if MODE == "linear":
    m += pulp.lpSum(d[i, p] * c[i, p] * x[i, p] for i in N for p in N)
else:
    w = {}
    terms = []
    for i in N:
        for j in N:
            if MODE == "qap_offdiag" and i == j: continue
            for p in N:
                for q in N:
                    v = pulp.LpVariable(f"w_{i}_{p}_{j}_{q}", cat="Binary"); w[i, p, j, q] = v
                    m += v <= x[i, p]; m += v <= x[j, q]; m += v >= x[i, p] + x[j, q] - 1
                    terms.append(d[i, j] * c[p, q] * v)
    m += pulp.lpSum(terms)
m.solve(SOLVER())
report(m)

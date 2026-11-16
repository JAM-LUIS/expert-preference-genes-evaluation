#!/usr/bin/env python3
# Cutting stock with <= 4 patterns and rank-dependent extra cost.
# Reading 1 (main): extra cost is per raw pipe cut: each pipe cut with the k-th most used pattern costs
# an extra k/10 of a raw-pipe value. Costs expressed in units of one raw pipe's value.
# Patterns are enumerated exhaustively (<=5 pieces, total length <=1850, leftover <=100).
# Slots k=1..4 get extra cost k/10; minimization automatically assigns the most used pattern
# to the cheapest slot (rearrangement inequality), so this equals the rank-based rule exactly.
import itertools, sys
import pulp
L = 1850
lens = [290, 315, 350, 455]
dem = [15, 28, 21, 30]
pats = []
for r in itertools.product(*[range(0, 6) for _ in lens]):
    tot = sum(a * b for a, b in zip(r, lens))
    if sum(r) <= 5 and tot <= L and L - tot <= 100 and sum(r) > 0:
        pats.append(r)
PER_PIPE = not (len(sys.argv) > 1 and sys.argv[1] == "onetime")
K = range(1, 5)
Mbig = 100
m = pulp.LpProblem("ind0096", pulp.LpMinimize)
y = {(p, k): pulp.LpVariable(f"y_{p}_{k}", lowBound=0, upBound=Mbig, cat="Integer") for p in range(len(pats)) for k in K}
w = {(p, k): pulp.LpVariable(f"w_{p}_{k}", cat="Binary") for p in range(len(pats)) for k in K}
pipes = pulp.lpSum(y.values())
if PER_PIPE:
    extra = pulp.lpSum(k / 10 * y[p, k] for p in range(len(pats)) for k in K)
else:
    extra = pulp.lpSum(k / 10 * w[p, k] for p in range(len(pats)) for k in K)
    for k in K:
        if k > 1:  # slots filled in order so slot k used only if slot k-1 used (one-time costs 0.1,0.2,...)
            m += pulp.lpSum(w[p, k] for p in range(len(pats))) <= pulp.lpSum(w[p, k - 1] for p in range(len(pats)))
        # frequency ordering: usage in slot k >= usage in slot k+1
        if k < 4:
            m += pulp.lpSum(y[p, k] for p in range(len(pats))) >= pulp.lpSum(y[p, k + 1] for p in range(len(pats)))
m += pipes + extra
for k in K:
    m += pulp.lpSum(w[p, k] for p in range(len(pats))) <= 1
for p in range(len(pats)):
    m += pulp.lpSum(w[p, k] for k in K) <= 1
    for k in K:
        m += y[p, k] <= Mbig * w[p, k]
        m += y[p, k] >= w[p, k]      # a chosen pattern is actually used
for i in range(4):
    m += pulp.lpSum(pats[p][i] * y[p, k] for p in range(len(pats)) for k in K) >= dem[i]
m.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=600))
status = pulp.LpStatus[m.status]; sol_status = pulp.LpSolution[m.sol_status]
print("reading:", "per-pipe extra cost" if PER_PIPE else "one-time extra cost per pattern")
print("feasible patterns enumerated:", len(pats))
print("STATUS:", status)
print("SOLUTION_STATUS:", sol_status)
if status == "Optimal" and sol_status == "Optimal Solution Found":
    print("FINAL_OBJECTIVE:", pulp.value(m.objective))
    print("raw pipes:", pulp.value(pipes), " extra:", pulp.value(extra))
    for (p, k), v in y.items():
        if v.varValue and v.varValue > 0.5:
            print(f"  slot {k}: pattern {dict(zip(lens, pats[p]))} x {v.varValue}")
else:
    print("FINAL_OBJECTIVE: None")

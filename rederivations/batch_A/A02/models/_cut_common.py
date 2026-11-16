# Shared builder for industryor-0096 (kept inside models/). All data from the problem statement.
import itertools
import pulp

L = 1850
lengths = [290, 315, 350, 455]
demand = [15, 28, 21, 30]
MAX_PIECES, MAX_WASTE, MAX_PATTERNS = 5, 100, 4

def patterns():
    out = []
    for p in itertools.product(range(MAX_PIECES + 1), repeat=4):
        used = sum(a * l for a, l in zip(p, lengths))
        if 1 <= sum(p) <= MAX_PIECES and used <= L and L - used <= MAX_WASTE:
            out.append(p)
    return out

def build(per_pipe_surcharge):
    P = patterns()
    K = range(MAX_PATTERNS)                 # rank slots: slot 0 = most frequently used pattern
    UB = sum(demand)                        # never more raw pipes than pieces ordered
    m = pulp.LpProblem("cutting", pulp.LpMinimize)
    a = {(p, k): pulp.LpVariable(f"assign_{i}_{k}", cat="Binary") for i, p in enumerate(P) for k in K}
    x = {(p, k): pulp.LpVariable(f"pipes_{i}_{k}", lowBound=0, cat="Integer") for i, p in enumerate(P) for k in K}
    used = [pulp.LpVariable(f"slot_used_{k}", cat="Binary") for k in K]
    n = [pulp.lpSum(x[p, k] for p in P) for k in K]
    for k in K:
        m += pulp.lpSum(a[p, k] for p in P) == used[k]          # one pattern per used slot
        for p in P:
            m += x[p, k] <= UB * a[p, k]
        m += n[k] >= used[k]                                    # a used slot cuts at least one pipe
    for p in P:
        m += pulp.lpSum(a[p, k] for k in K) <= 1                # a pattern occupies at most one slot
    for k in range(MAX_PATTERNS - 1):
        m += n[k] >= n[k + 1]                                   # slots ordered by usage frequency
    for j in range(4):
        m += pulp.lpSum(p[j] * x[p, k] for p in P for k in K) >= demand[j], f"demand_{lengths[j]}"
    if per_pipe_surcharge:
        m += pulp.lpSum((1 + 0.1 * (k + 1)) * n[k] for k in K)
    else:
        m += pulp.lpSum(n) + pulp.lpSum(0.1 * (k + 1) * used[k] for k in K)
    return m, P, x

def run(per_pipe_surcharge):
    m, P, x = build(per_pipe_surcharge)
    m.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=600))
    status = pulp.LpStatus[m.status]; sol_status = pulp.LpSolution[m.sol_status]
    print("STATUS:", status); print("SOLUTION_STATUS:", sol_status)
    if status == "Optimal" and sol_status == "Optimal Solution Found":
        print("FINAL_OBJECTIVE:", pulp.value(m.objective))
        print("  feasible patterns:", len(P))
        tot = 0
        for (p, k), v in sorted(x.items(), key=lambda t: t[0][1]):
            if v.varValue and v.varValue > 0.5:
                tot += v.varValue
                print(f"  rank {k+1}: pattern {dict(zip(lengths, p))} x {v.varValue}")
        print("  raw pipes:", tot)
    else:
        print("FINAL_OBJECTIVE: None")

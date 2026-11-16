#!/usr/bin/env python3
# industryor-0099: spare-part allocation, complete enumeration of 6^3 combinations
import itertools
R = {1: [0.5, 0.6, 0.7, 0.8, 0.9, 1.0], 2: [0.6, 0.75, 0.95, 1.0, 1.0, 1.0], 3: [0.7, 0.9, 1.0, 1.0, 1.0, 1.0]}
price = {1: 20, 2: 30, 3: 40}; weight = {1: 2, 2: 4, 3: 6}
best = None
for n in itertools.product(range(6), repeat=3):
    if sum(price[i + 1] * n[i] for i in range(3)) > 150: continue
    if sum(weight[i + 1] * n[i] for i in range(3)) > 20: continue
    r = R[1][n[0]] * R[2][n[1]] * R[3][n[2]]
    if best is None or r > best[0] + 1e-12: best = (r, [n])
    elif abs(r - best[0]) <= 1e-12: best[1].append(n)
print("STATUS: Optimal")
print("FINAL_OBJECTIVE:", round(best[0], 10))
print("  spares (n1,n2,n3):", best[1])

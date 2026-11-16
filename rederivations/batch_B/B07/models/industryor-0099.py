# industryor-0099: full enumeration over spares k1,k2,k3 in 0..5 (exact global optimum)
import itertools
r = [[0.5,0.6,0.7,0.8,0.9,1.0],[0.6,0.75,0.95,1.0,1.0,1.0],[0.7,0.9,1.0,1.0,1.0,1.0]]
price = [20,30,40]; weight = [2,4,6]
best = None
for k in itertools.product(range(6), repeat=3):
    if sum(p*q for p,q in zip(price,k)) <= 150 and sum(p*q for p,q in zip(weight,k)) <= 20:
        val = r[0][k[0]]*r[1][k[1]]*r[2][k[2]]
        if best is None or val > best[0] + 1e-12:
            best = (val, k)
print("STATUS: Optimal")
print("FINAL_OBJECTIVE:", round(best[0], 10))
print("  spares =", best[1])
for k in itertools.product(range(6), repeat=3):
    if sum(p*q for p,q in zip(price,k)) <= 150 and sum(p*q for p,q in zip(weight,k)) <= 20:
        val = r[0][k[0]]*r[1][k[1]]*r[2][k[2]]
        if abs(val-best[0]) < 1e-12: print("  tie/opt:", k, val)

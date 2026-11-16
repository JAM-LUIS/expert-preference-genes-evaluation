TAKEOFF_LANDING = 100.0   # 100 L per trip covering takeoff and landing together
# Exhaustive enumeration over integer bomb allocations (heavy x_i, light y_i per key part).
# Success = at least two of the four parts destroyed; bombs act independently.
import itertools
import numpy as np
dist = [450, 480, 540, 600]
ph = [0.03, 0.10, 0.05, 0.05]
pl = [0.08, 0.11, 0.12, 0.09]
HMAX, LMAX, FUEL = 28, 12, 10000.0
fh = np.array([d/2 + d/4 + TAKEOFF_LANDING for d in dist])   # loaded out at 2 km/L, empty back at 4 km/L
fl = np.array([d/3 + d/4 + TAKEOFF_LANDING for d in dist])   # loaded out at 3 km/L

def comps(total):
    return np.array([c for c in itertools.product(range(total+1), repeat=4) if sum(c) <= total], dtype=np.int64)

X = comps(HMAX); Y = comps(LMAX)
fuelY = Y @ fl
logqY = Y @ np.log(1 - np.array(pl))          # log survive prob per part from light bombs: shape (nY,4) below
QY = np.exp(Y * np.log(1 - np.array(pl)))     # (nY,4)
best = (-1.0, None, None)
for x in X:
    rem = FUEL - float(x @ fh)
    if rem < -1e-9:
        continue
    ok = fuelY <= rem + 1e-9
    if not ok.any():
        continue
    q = QY[ok] * np.exp(x * np.log(1 - np.array(ph)))   # survival prob of each part
    p0 = q.prod(axis=1)
    p1 = np.zeros(len(q))
    for i in range(4):
        others = np.delete(q, i, axis=1).prod(axis=1)
        p1 += (1 - q[:, i]) * others
    succ = 1 - p0 - p1
    j = int(succ.argmax())
    if succ[j] > best[0] + 1e-15:
        best = (float(succ[j]), x.copy(), Y[ok][j].copy())
print("STATUS: Optimal")
print("FINAL_OBJECTIVE:", best[0])
print("  heavy per part:", best[1].tolist())
print("  light per part:", best[2].tolist())
print("  fuel used:", float(best[1] @ fh + best[2] @ fl))

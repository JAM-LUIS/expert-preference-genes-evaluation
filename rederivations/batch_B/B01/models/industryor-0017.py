# Full enumeration over integer bomb allocations (h_i heavy, l_i light to part i).
# Fuel per trip to part i: loaded leg d/2 (heavy) or d/3 (light), empty return d/4, plus 100 L takeoff+landing.
# Success = at least 2 of the 4 parts destroyed (independent parts, independent bombs).
import itertools
import numpy as np
dist = np.array([450,480,540,600], dtype=float)
ph = np.array([0.03,0.10,0.05,0.05])
pl = np.array([0.08,0.11,0.12,0.09])
fh = dist/2 + dist/4 + 100
fl = dist/3 + dist/4 + 100
FUEL = 10000.0
def vecs(maxsum):
    out = [v for v in itertools.product(range(maxsum+1), repeat=4) if sum(v) <= maxsum]
    return np.array(out, dtype=float)
H = vecs(28); L = vecs(12)
Hf = H @ fh; Lf = L @ fl
Hq = np.prod((1-ph)**H, axis=1, keepdims=False)  # not used directly
Hlog = np.log(1-ph) * H   # per-part log survival from heavy
Llog = np.log(1-pl) * L
best = -1.0; arg = None
for k in range(H.shape[0]):
    ok = Hf[k] + Lf <= FUEL + 1e-9
    if not ok.any(): continue
    q = np.exp(Hlog[k][None,:] + Llog[ok])     # survival prob per part
    pall = np.prod(q, axis=1)
    one = np.zeros(q.shape[0])
    for i in range(4):
        one += (1-q[:,i]) * np.prod(np.delete(q, i, axis=1), axis=1)
    succ = 1 - pall - one
    j = int(np.argmax(succ))
    if succ[j] > best + 1e-15:
        best = float(succ[j]); arg = (H[k].astype(int).tolist(), L[ok][j].astype(int).tolist(), float(Hf[k]+Lf[ok][j]))
print("STATUS: Optimal")
print("FINAL_OBJECTIVE:", best)
print("heavy per part:", arg[0], "light per part:", arg[1], "fuel used:", arg[2])
